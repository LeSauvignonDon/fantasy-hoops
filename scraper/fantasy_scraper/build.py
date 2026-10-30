"""Assemble scraped pieces into the exact JSON the Rust app loads.

The target schema is the serde form of ``LeagueData`` in
``crates/hoops-core/src/models.rs`` (example: ``fixtures/sample_snapshot.json``)::

    {
      "league":  {"league_key", "name", "num_teams", "max_weekly_adds",
                  "current_week", "my_team_key"},
      "teams":   [{"team_key", "name", "manager"}],
      "players": [{"player_key", "name", "nba_team", "positions": [..],
                   "season": StatLine}],                 # season TOTALS
      "rosters": [{"week", "team_key", "player_keys": [..]}],
      "transactions": [{"id", "week", "timestamp", "team_key",
                        "kind": "add"|"drop", "player_key"}],
      "weekly_stats": [{"week", "player_key", "stats": StatLine}],
      "matchups": [{"week", "team_a", "team_b"}]
    }

Extra top-level keys starting with ``_`` (``_comment``, ``_yahoo``) are
ignored by serde, so we use them for provenance and standings.

``validate_snapshot`` mirrors ``LeagueData::validate`` in Rust so problems
show up in Python with a clear message before you ever run ``hoops``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from .parse import PlayerRow, RawTransaction, TeamInfo
from .stats import clean_statline, empty_statline
from .timeutil import rfc3339, week_for_date


def team_key(league_id: str, team_id: int) -> str:
    """Yahoo-style team key: ``nba.l.106518.t.7``."""
    return f"nba.l.{league_id}.t.{team_id}"


def player_key(player_id: str) -> str:
    """Player key from the numeric id in ``/nba/players/<id>`` links.

    Yahoo's API keys are ``<game_id>.p.<id>`` (game id changes per season);
    we use the stable ``nba.p.<id>`` form, matching the doc comment on
    ``PlayerKey`` in models.rs."""
    return f"nba.p.{player_id}"


@dataclass
class ScrapeResult:
    """Everything the crawl collected, still in "Yahoo ids" form."""

    league_id: str
    league_name: str = ""
    current_week: int = 1
    max_weekly_adds: int = 5
    my_team_id: int | None = None
    teams: dict[int, TeamInfo] = field(default_factory=dict)
    # Roster per (week, team_id); the current week comes from team pages,
    # earlier weeks from matchup pages.
    rosters: dict[tuple[int, int], list[str]] = field(default_factory=dict)
    # Season-total player rows by player id (players pages + team pages).
    players: dict[str, PlayerRow] = field(default_factory=dict)
    # Weekly stat lines by (week, player_id) from matchup pages.
    weekly: dict[tuple[int, str], dict] = field(default_factory=dict)
    matchups: set[tuple[int, int, int]] = field(default_factory=set)
    week_ranges: dict = field(default_factory=dict)
    # (move, parsed time or None)
    transactions: list[tuple[RawTransaction, datetime | None]] = field(default_factory=list)
    standings: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_pages: int = 0

    def add_player(self, row: PlayerRow, prefer_stats: bool = True) -> None:
        """Merge a player row into ``players``.

        ``prefer_stats=True`` means the row's numbers are *season totals*
        (players list pages); the first such line wins. Rows from team or
        matchup pages (``prefer_stats=False``) only contribute name, NBA team
        and positions, because their numbers are today's/weekly stats.
        The row object is copied, never mutated (callers still read it).
        """
        cur = self.players.get(row.player_id)
        if cur is None:
            cur = replace(row, positions=list(row.positions), stats=None, stat_fields=set())
            self.players[row.player_id] = cur
        if not cur.nba_team and row.nba_team:
            cur.nba_team = row.nba_team
        if not cur.positions and row.positions:
            cur.positions = list(row.positions)
        if (not cur.name or cur.name.startswith("Player ")) and row.name and not row.name.startswith("Player "):
            cur.name = row.name
        if prefer_stats and row.stats is not None and cur.stats is None:
            cur.stats, cur.stat_fields = dict(row.stats), set(row.stat_fields)


def _clean_positions(positions: list[str]) -> list[str]:
    keep = []
    for p in positions:
        p = p.strip().upper()
        if p and p not in ("UTIL", "BN", "IL", "IL+", "NA") and p not in keep:
            keep.append(p)
    return keep


def build_snapshot(r: ScrapeResult, generated_at: datetime, my_team_name: str | None = None) -> dict:
    """Turn a ScrapeResult into the snapshot dict (ready for json.dump)."""
    lid = r.league_id
    warnings = list(r.warnings)  # copy: calling build twice must not duplicate warnings

    # --- teams -------------------------------------------------------------
    teams = [{"team_key": team_key(lid, t.team_id), "name": t.name or f"Team {t.team_id}",
              "manager": t.manager or ""} for t in sorted(r.teams.values(), key=lambda t: t.team_id)]
    team_keys = {t["team_key"] for t in teams}

    my_id = r.my_team_id
    if my_team_name:
        by_name = [t for t in r.teams.values() if t.name.strip().lower() == my_team_name.strip().lower()]
        if by_name:
            my_id = by_name[0].team_id
        elif my_id is None:
            warnings.append(f"team named {my_team_name!r} not found; check --my-team-name")
    if my_id is None or team_key(lid, my_id) not in team_keys:
        my_id = min(r.teams) if r.teams else 1
        warnings.append(f"could not detect your team; defaulting to team {my_id} (use --my-team-id)")

    # --- transactions: give each half an id and a fantasy week ---------------
    transactions = []
    # Oldest first, so ids grow with time (Yahoo lists newest first).
    ordered = sorted(r.transactions, key=lambda mt: (mt[1] is None, mt[1] or generated_at, -mt[0].group))
    for move, when in ordered:
        week = week_for_date(when.date(), r.week_ranges) if when else None
        if week is None and when and 1 in r.week_ranges and when.date() < r.week_ranges[1][0]:
            week = 1  # pre-season pickups shape the week-1 roster, so count them there
        if week is None:
            week = r.current_week
            warnings.append(f"transaction {move.player.name}: unknown week, using current week {week}")
        if week > r.current_week:
            continue
        if team_key(lid, move.team_id) not in team_keys:
            warnings.append(f"transaction for unknown team id {move.team_id} skipped")
            continue
        transactions.append({
            "id": len(transactions) + 1,  # sequential over kept moves
            "week": week,
            "timestamp": rfc3339(when or generated_at),
            "team_key": team_key(lid, move.team_id),
            "kind": move.kind,
            "player_key": player_key(move.player.player_id),
        })

    # --- every player referenced anywhere must exist in `players` -----------
    referenced: dict[str, str] = {}
    for (_, _), pids in r.rosters.items():
        for pid in pids:
            referenced.setdefault(pid, "roster")
    for move, _ in r.transactions:
        referenced.setdefault(move.player.player_id, "transaction")
        r.add_player(move.player, prefer_stats=False)
    missing_stats = []
    players = []
    for pid, row in sorted(r.players.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        season = row.stats
        if season is None:
            season = empty_statline()
            if pid in referenced:
                missing_stats.append(row.name)
        players.append({
            "player_key": player_key(pid),
            "name": row.name,
            "nba_team": row.nba_team or "",
            "positions": _clean_positions(row.positions),
            "season": clean_statline(season),
        })
    if missing_stats:
        warnings.append(f"{len(missing_stats)} rostered/transacted players have no season stats "
                        f"(zeros used), e.g. {', '.join(missing_stats[:5])}")

    # --- rosters -------------------------------------------------------------
    rosters = []
    for (week, tid), pids in sorted(r.rosters.items()):
        if team_key(lid, tid) not in team_keys:
            warnings.append(f"roster for unknown team id {tid} skipped")
            continue
        unique = list(dict.fromkeys(pids))  # dedupe, keep order
        rosters.append({"week": week, "team_key": team_key(lid, tid),
                        "player_keys": [player_key(p) for p in unique]})

    # --- weekly stats & matchups ----------------------------------------------
    known_players = {p["player_key"] for p in players}
    weekly = []
    for (week, pid), line in sorted(r.weekly.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if player_key(pid) in known_players:
            weekly.append({"week": week, "player_key": player_key(pid), "stats": clean_statline(line)})
    matchups = [{"week": w, "team_a": team_key(lid, a), "team_b": team_key(lid, b)}
                for (w, a, b) in sorted(r.matchups)
                if team_key(lid, a) in team_keys and team_key(lid, b) in team_keys]

    return {
        "_comment": f"Scraped from Yahoo Fantasy league {lid} by scraper/ on "
                    f"{rfc3339(generated_at)}. Real league data: keep local (data/ is git-ignored).",
        "league": {
            "league_key": f"nba.l.{lid}",
            "name": r.league_name or f"Yahoo league {lid}",
            "num_teams": len(teams),
            "max_weekly_adds": r.max_weekly_adds,
            "current_week": r.current_week,
            "my_team_key": team_key(lid, my_id),
        },
        "teams": teams,
        "players": players,
        "rosters": rosters,
        "transactions": transactions,
        "weekly_stats": weekly,
        "matchups": matchups,
        "_yahoo": {
            "standings": [dict(s, team_key=team_key(lid, s["team_id"])) for s in r.standings],
            "week_ranges": {str(w): [a.isoformat(), b.isoformat()]
                            for w, (a, b) in sorted(r.week_ranges.items())},
            "pages_fetched": r.source_pages,
            "warnings": list(warnings),
        },
    }


def validate_snapshot(snap: dict) -> list[str]:
    """Return a list of problems (empty = OK). Mirrors Rust's
    ``LeagueData::validate`` plus basic type/shape checks."""
    errors: list[str] = []
    for key in ("league", "teams", "players", "rosters"):
        if key not in snap:
            errors.append(f"missing top-level key {key!r}")
    if errors:
        return errors
    league = snap["league"]
    for k, typ in (("league_key", str), ("name", str), ("num_teams", int), ("max_weekly_adds", int),
                   ("current_week", int), ("my_team_key", str)):
        if not isinstance(league.get(k), typ):
            errors.append(f"league.{k} must be {typ.__name__}")
    player_keys = [p.get("player_key") for p in snap["players"]]
    if len(set(player_keys)) != len(player_keys):
        errors.append("duplicate player_key")
    pk, tk = set(player_keys), {t.get("team_key") for t in snap["teams"]}
    if league.get("my_team_key") not in tk:
        errors.append(f"my_team_key {league.get('my_team_key')!r} is not a team in the league")
    stat_keys = set(empty_statline())
    for p in snap["players"]:
        if set(p.get("season", {})) != stat_keys or not isinstance(p["season"].get("gp"), int):
            errors.append(f"player {p.get('player_key')} has a malformed season StatLine")
        if not isinstance(p.get("positions"), list):
            errors.append(f"player {p.get('player_key')} positions must be a list")
    for r in snap["rosters"]:
        if r["team_key"] not in tk:
            errors.append(f"roster for unknown team {r['team_key']}")
        bad = [k for k in r["player_keys"] if k not in pk]
        if bad:
            errors.append(f"roster {r['team_key']} week {r['week']} lists unknown player {bad[0]}")
    for t in snap.get("transactions", []):
        if t["team_key"] not in tk or t["player_key"] not in pk:
            errors.append(f"transaction {t['id']} references unknown team or player")
        if t["kind"] not in ("add", "drop"):
            errors.append(f"transaction {t['id']} kind must be add/drop")
    for w in snap.get("weekly_stats", []):
        if set(w.get("stats", {})) != stat_keys:
            errors.append(f"weekly stats for {w.get('player_key')} malformed")
    return errors
