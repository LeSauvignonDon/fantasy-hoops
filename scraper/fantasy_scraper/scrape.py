"""The crawl plan: which pages to visit, in which order, and what to keep.

This module never imports Playwright. It receives a ``fetch(url, label)``
function that returns page HTML, so the whole crawl can be tested offline
against fake pages (``tests/fake_site.py``) and run for real with the
browser fetcher from ``browser.py``. That separation ("dependency
injection") is the main design idea of the scraper.

Pages are fetched strictly one at a time; the fetcher sleeps between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import parse, urls
from .build import ScrapeResult
from .parse import TeamInfo
from .stats import derive_games_played
from .timeutil import now_in, parse_transaction_time, parse_week_spec, season_start_year

Fetch = Callable[[str, str], str]   # (url, label) -> html
Log = Callable[[str], None]


class SessionExpired(RuntimeError):
    """Yahoo redirected to sign-in: the saved browser session is gone."""


class ScrapeError(RuntimeError):
    """A page we cannot do without (league home) didn't parse."""


@dataclass
class ScrapeOptions:
    league_id: str = "106518"
    num_teams: int = 12
    fa_pages: int = 6            # x25 free agents (status=A)
    taken_pages: int = 10        # x25 rostered players (status=T) for season stats
    tx_pages: int = 4            # transaction pages to follow via "Next"
    stats_weeks: str = "last2"   # which weeks get per-player weekly stats (matchup pages)
    season: int | None = None    # Yahoo season year (2026 for 2026-27); default from today
    tz: str = "America/Los_Angeles"  # time zone Yahoo shows times in (your Yahoo setting)
    my_team_id: int | None = None
    my_team_name: str | None = "Cripples and Bastards"
    current_week: int | None = None
    max_weekly_adds: int = 5
    now: datetime | None = None  # injectable clock for tests


def run_scrape(fetch: Fetch, opts: ScrapeOptions, log: Log = print) -> ScrapeResult:
    lid = opts.league_id
    now = opts.now or now_in(opts.tz)
    start_year = opts.season or season_start_year(now.date())
    r = ScrapeResult(league_id=lid, max_weekly_adds=opts.max_weekly_adds)

    def get(url: str, label: str) -> str:
        r.source_pages += 1
        return fetch(url, label)

    def soft(label: str, fn: Callable[[], None]) -> None:
        """Run one step; a parse problem becomes a warning, not a crash."""
        try:
            fn()
        except SessionExpired:
            raise
        except Exception as e:  # noqa: BLE001 - deliberately broad: keep going
            r.warnings.append(f"{label}: {type(e).__name__}: {e}")
            log(f"  ! {label} failed: {e}")

    # 1. League home: proves we're signed in; gives name, my team, week -------
    log("league home")
    home = get(urls.league_home(lid), "league_home")
    if not parse.looks_like_league_page(home, lid):
        raise ScrapeError("league page has no team links: not signed in, wrong league id, "
                          "or Yahoo changed the page (re-run with --debug-dump)")
    r.league_name = parse.parse_league_name(home) or ""
    r.my_team_id = opts.my_team_id or parse.detect_my_team_id(home, lid)
    for tid, name in parse.parse_team_links(home, lid).items():
        if tid <= opts.num_teams:
            r.teams[tid] = TeamInfo(tid, name)
    board = parse.parse_scoreboard(home, lid, start_year)
    r.week_ranges.update(board.week_ranges)
    r.current_week = opts.current_week or board.current_week or 1
    if not (opts.current_week or board.current_week):
        r.warnings.append("current week not found on league page; using 1 (pass --current-week)")
    r.standings = parse.parse_standings(home, lid)
    log(f"  league {r.league_name!r}, current week {r.current_week}")

    # 2. Teams page (managers) and standings tab -----------------------------
    def teams_step() -> None:
        for t in parse.parse_teams_page(get(urls.teams_page(lid), "teams"), lid):
            if t.team_id <= opts.num_teams:
                old = r.teams.get(t.team_id)
                r.teams[t.team_id] = TeamInfo(t.team_id, t.name or (old.name if old else ""), t.manager)
    soft("teams page", teams_step)

    def standings_step() -> None:
        rows = parse.parse_standings(get(urls.standings_page(lid), "standings"), lid)
        if rows:
            r.standings = rows
    soft("standings", standings_step)

    # 3. Every team's roster (current week) ------------------------------------
    for tid in range(1, opts.num_teams + 1):
        def team_step(tid: int = tid) -> None:
            log(f"team {tid}/{opts.num_teams}")
            name, players = parse.parse_team_page(get(urls.team_page(lid, tid), f"team_{tid:02d}"), lid, tid)
            if tid not in r.teams or not r.teams[tid].name:
                r.teams[tid] = TeamInfo(tid, name or f"Team {tid}", r.teams.get(tid, TeamInfo(tid, "")).manager)
            r.rosters[(r.current_week, tid)] = [p.player_id for p in players]
            for p in players:
                # Team pages show *today's* or *this week's* stats by default,
                # not season totals, so don't use their numbers as season stats.
                r.add_player(p, prefer_stats=False)
            if not players:
                r.warnings.append(f"team {tid}: no players parsed (check data/debug/team_{tid:02d}.html)")
        soft(f"team {tid}", team_step)

    # 4. Scoreboards: who played whom each week --------------------------------
    r.matchups.update(m for m in board.matchups if m[0] == r.current_week)
    for week in range(1, r.current_week + 1):
        def board_step(week: int = week) -> None:
            log(f"scoreboard week {week}")
            b = parse.parse_scoreboard(get(urls.scoreboard_page(lid, week), f"scoreboard_w{week:02d}"),
                                       lid, start_year)
            r.matchups.update(m for m in b.matchups if m[0] == week)
            for w, rng in b.week_ranges.items():
                r.week_ranges.setdefault(w, rng)
        soft(f"scoreboard week {week}", board_step)

    # 5. Matchup pages: weekly player stats (+ rosters for past weeks) --------
    for week in parse_week_spec(opts.stats_weeks, r.current_week):
        for (_w, a, b) in sorted(m for m in r.matchups if m[0] == week):
            def matchup_step(week: int = week, a: int = a, b: int = b) -> None:
                log(f"matchup week {week}: {a} vs {b}")
                html = get(urls.matchup_page(lid, week, a, b), f"matchup_w{week:02d}_{a}v{b}")
                for tid, rows in parse.parse_matchup_page(html, a, b).items():
                    if week < r.current_week and rows:
                        r.rosters.setdefault((week, tid), [p.player_id for p in rows])
                    for p in rows:
                        r.add_player(p, prefer_stats=False)
                        if p.stats is not None:
                            r.weekly[(week, p.player_id)] = p.stats
            soft(f"matchup week {week} {a}v{b}", matchup_step)

    # 6. Transactions (newest first, follow "Next") -----------------------------
    def tx_step() -> None:
        url, page_no = urls.transactions_page(lid), 1
        group_offset = 0
        while url and page_no <= opts.tx_pages:
            log(f"transactions page {page_no}")
            page = parse.parse_transactions(get(url, f"transactions_{page_no}"), lid, url)
            for move in page.moves:
                move.group += group_offset  # keep groups unique across pages
                when = parse_transaction_time(move.when_text, now, start_year)
                r.transactions.append((move, when))
            group_offset += 10_000
            r.warnings.extend(f"transactions: skipped {s}" for s in page.skipped)
            url, page_no = page.next_url, page_no + 1
    soft("transactions", tx_step)

    # 7. Players lists: season totals for rostered (T) and available (A) -----
    fetched_offsets: dict[str, list[int]] = {}
    for status, max_pages in (("T", opts.taken_pages), ("A", opts.fa_pages)):
        def players_step(status: str = status, max_pages: int = max_pages) -> None:
            for page_no in range(max_pages):
                offset = page_no * 25
                log(f"players status={status} offset={offset}")
                rows = parse.parse_player_tables(get(urls.players_page(lid, status, start_year, offset),
                                                     f"players_{status}_{offset:04d}"))
                new = [p for p in rows if p.stats is not None]
                fetched_offsets.setdefault(status, []).append(offset)
                for p in new:
                    r.add_player(p, prefer_stats=True)
                if page_no == 0 and not new:
                    r.warnings.append(f"players status={status}: no stat rows parsed "
                                      f"(check data/debug/players_{status}_0000.html)")
                if len(new) < 25:   # short page = last page
                    break
        soft(f"players status={status}", players_step)

    # 8. GP fallback: if the totals table had no GP column, derive it ---------
    no_gp = [p for p in r.players.values() if p.stats is not None and "gp" not in p.stat_fields]
    if no_gp:
        log(f"{len(no_gp)} players without GP column; fetching season averages to derive GP")
        def gp_step() -> None:
            for status, offsets in fetched_offsets.items():
                for offset in offsets:
                    avg_rows = parse.parse_player_tables(get(
                        urls.players_page(lid, status, start_year, offset, averages=True),
                        f"players_{status}_{offset:04d}_avg"))
                    for a in avg_rows:
                        p = r.players.get(a.player_id)
                        if p and p.stats is not None and a.stats and "gp" not in p.stat_fields:
                            gp = derive_games_played(p.stats, a.stats)
                            if gp:
                                p.stats["gp"] = gp
                                p.stat_fields = set(p.stat_fields) | {"gp"}
        soft("gp fallback", gp_step)

    return r
