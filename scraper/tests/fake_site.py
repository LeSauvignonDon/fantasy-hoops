"""A tiny fake "Yahoo Fantasy" website for offline tests.

It generates HTML that imitates the *structure* of Yahoo's pages (two-row
table headers, player links to /nba/players/<id>, "LAL - PG,SG" spans, +/-
transaction icons, matchup links with week/mid1/mid2...) for a FAKE
12-team league. Every name and number is invented.

``FakeYahoo().fetch`` has the same signature as the real browser fetcher,
so ``run_scrape`` can crawl it end to end without a network or browser.
"""

from __future__ import annotations

from html import escape
from urllib.parse import parse_qs, urlparse

LID = "106518"
NUM_TEAMS = 12
ROSTER = 13
FIRST_ID = 9000
N_PLAYERS = 190
NBA = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
POS = ["PG", "SG", "SF", "PF", "C", "PG,SG", "SG,SF", "SF,PF", "PF,C"]
HEADERS = ["FGM/A*", "FG%", "FTM/A*", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]

# Week ranges and "now" used by the tests: Thursday of week 2.
WEEK_RANGES = {1: "Oct 20 - Oct 26", 2: "Oct 27 - Nov 2"}
CURRENT_WEEK = 2

# (team_id, kind, player_id, when) newest first, as Yahoo lists them.
MOVES = [
    # team 1 swaps 9012 -> 9160 on Oct 28 (week 2)
    [(1, "add", 9160, "Oct 28, 9:15 am"), (1, "drop", 9012, "Oct 28, 9:15 am")],
    # team 7 adds a free agent "yesterday" (Oct 28) without dropping (roster spot open)
    [(7, "add", 9165, "Yesterday, 8:05 pm")],
    # trade between 3 and 4 (must be skipped, not crash)
    "TRADE",
    # team 5 swaps 9055 -> 9161 on Oct 23 (week 1)
    [(5, "add", 9161, "Oct 23, 10:00 am"), (5, "drop", 9055, "Oct 23, 10:00 am")],
]
PAGE2_MOVES = [
    # pre-season pickup (before week 1) -> counted in week 1
    [(2, "drop", 9025, "Oct 18, 1:00 pm")],
]


def team_name(tid: int) -> str:
    return "Cripples and Bastards" if tid == 1 else f"Fake Team {tid:02d}"


def manager(tid: int) -> str:
    return "Thomas" if tid == 1 else f"Manager {chr(ord('A') + tid - 1)}"


def player_name(pid: int) -> str:
    return f"Fakey Player{pid}"


def nba_team(pid: int) -> str:
    return NBA[pid % len(NBA)]


def positions(pid: int) -> str:
    return POS[pid % len(POS)]


def season(pid: int) -> dict:
    """Deterministic fake season totals."""
    gp = 4 + pid % 4
    i = pid - FIRST_ID
    fga = gp * (6 + i % 9)
    fgm = fga * (40 + i % 15) // 100
    fta = gp * (1 + i % 5)
    ftm = fta * (60 + i % 30) // 100
    tpm = gp * (i % 4)
    return {"gp": gp, "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "tpm": tpm,
            "pts": 2 * fgm + ftm + tpm, "reb": gp * (2 + i % 9), "ast": gp * (1 + i % 7),
            "stl": gp * (i % 3), "blk": gp * (i % 2), "tov": gp * (1 + i % 3)}


def weekly(pid: int, week: int) -> dict:
    s = season(pid)
    f = 0.4 if week == 1 else 0.3
    return {k: (round(v * f) if k != "gp" else max(1, round(v * f))) for k, v in s.items()}


def roster_at(tid: int, week: int) -> list[int]:
    """Week-1 rosters: consecutive blocks; then apply moves by end of week."""
    base = list(range(FIRST_ID + (tid - 1) * ROSTER, FIRST_ID + tid * ROSTER))
    if tid == 2:
        base.remove(9025)  # pre-season drop
    if tid == 5:  # week-1 move, active from week 1 on
        base = [p for p in base if p != 9055] + [9161]
    if week >= 2 and tid == 1:
        base = [p for p in base if p != 9012] + [9160]
    if week >= 2 and tid == 7:
        base = base + [9165]
    return base


def rostered(week: int) -> set[int]:
    return {p for t in range(1, NUM_TEAMS + 1) for p in roster_at(t, week)}


def stat_cells(s: dict) -> list[str]:
    def pct(m, a):
        return f"{m / a:.3f}".lstrip("0") if a else "-"
    return [f"{s['fgm']}/{s['fga']}", pct(s["fgm"], s["fga"]), f"{s['ftm']}/{s['fta']}",
            pct(s["ftm"], s["fta"]), str(s["tpm"]), str(s["pts"]), str(s["reb"]), str(s["ast"]),
            str(s["stl"]), str(s["blk"]), str(s["tov"])]


def player_cell(pid: int) -> str:
    return (f'<td><div class="ysf-player-name Nowrap"><a class="Nowrap name F-link" '
            f'href="https://sports.yahoo.com/nba/players/{pid}">{escape(player_name(pid))}</a> '
            f'<span class="Fz-xxs">{nba_team(pid)} - {positions(pid)}</span></div>'
            f'<a class="playernote" href="#" data-ys-playerid="{pid}"></a></td>')


def page(title: str, body: str, nav_my_team: bool = True) -> str:
    nav = f'<a href="/nba/{LID}/1">My Team</a>' if nav_my_team else ""
    return (f"<!doctype html><html><head><title>{escape(title)}</title></head>"
            f"<body><nav><a href='/nba/{LID}'>League</a>{nav}"
            f"<a href='/nba/{LID}/players'>Players</a></nav>{body}</body></html>")


def two_row_thead(labels: list[str], group: str = "Stats") -> str:
    return (f'<thead><tr><th colspan="{len(labels) - len(HEADERS)}"></th>'
            f'<th colspan="{len(HEADERS)}">{group}</th></tr>'
            "<tr>" + "".join(f"<th><div>{escape(h)}</div></th>" for h in labels) + "</tr></thead>")


class FakeYahoo:
    def __init__(self, include_gp: bool = True, players_state_json: bool = False):
        self.include_gp = include_gp
        self.players_state_json = players_state_json
        self.requests: list[str] = []

    # -- the fetch() contract -------------------------------------------------
    def fetch(self, url: str, label: str) -> str:
        self.requests.append(label)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.rstrip("/")
        base = f"/nba/{LID}"
        if path == base and q.get("module") == "matchups":
            return self.scoreboard(int(q["matchup_week"]))
        if path == base and q.get("lhst") == "stand":
            return self.league_home()
        if path == base:
            return self.league_home()
        if path == f"{base}/teams":
            return self.teams()
        if path == f"{base}/transactions":
            return self.transactions(int(q.get("page", 1)))
        if path == f"{base}/players":
            return self.players(q["status"], int(q["count"]), q["stat1"].startswith("S_AS_"))
        if path == f"{base}/matchup":
            return self.matchup(int(q["week"]), int(q["mid1"]), int(q["mid2"]))
        tail = path[len(base) + 1:]
        if tail.isdigit():
            return self.team(int(tail))
        return page("Not found", "<p>404</p>")

    # -- pages ------------------------------------------------------------------
    def week_nav(self, selected: int) -> str:
        items = "".join(
            f'<li class="{"selected" if w == selected else ""}"><a href="#">Week {w}</a>'
            f'<span>Week {w} ({rng})</span></li>' for w, rng in WEEK_RANGES.items())
        return f'<ul class="weeknav">{items}</ul>'

    def pairs(self, week: int) -> list[tuple[int, int]]:
        if week == 1:
            return [(1, 2), (3, 12), (4, 11), (5, 10), (6, 9), (7, 8)]
        return [(1, 3), (2, 4), (5, 12), (6, 11), (7, 10), (8, 9)]

    def matchups_module(self, week: int) -> str:
        links = "".join(
            f'<li><a href="/nba/{LID}/matchup?week={week}&mid1={a}&mid2={b}">'
            f'{escape(team_name(a))} vs {escape(team_name(b))}</a></li>' for a, b in self.pairs(week))
        return f'<section id="matchups">{self.week_nav(week)}<ul>{links}</ul></section>'

    def league_home(self) -> str:
        rows = "".join(
            f'<tr><td>{rank}</td><td><a href="/nba/{LID}/{tid}">{escape(team_name(tid))}</a></td>'
            f"<td>{w}-{l}-0</td><td>.500</td></tr>"
            for rank, (tid, w, l) in enumerate([(t, 12 - t, t - 1) for t in range(1, NUM_TEAMS + 1)], 1))
        standings = ("<table id='standingstable'><thead><tr><th>Rank</th><th>Team</th>"
                     f"<th>W-L-T</th><th>Pct</th></tr></thead><tbody>{rows}</tbody></table>")
        return page("Fake Hoops League | Fantasy Basketball | Yahoo Sports",
                    self.matchups_module(CURRENT_WEEK) + standings)

    def scoreboard(self, week: int) -> str:
        return page("Fake Hoops League | Scoreboard", self.matchups_module(week))

    def teams(self) -> str:
        rows = "".join(f'<tr><td><a href="/nba/{LID}/{t}">{escape(team_name(t))}</a></td>'
                       f'<td><span class="manager">{escape(manager(t))}</span></td><td>{t * 3}</td></tr>'
                       for t in range(1, NUM_TEAMS + 1))
        return page("Teams | Fake Hoops League",
                    f"<table><thead><tr><th>Team</th><th>Manager(s)</th><th>Moves</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table>")

    def team(self, tid: int) -> str:
        labels = ["Pos", "Player", "Action", "Opp", *HEADERS]
        body = ""
        for i, pid in enumerate(roster_at(tid, CURRENT_WEEK)):
            today = {k: 1 for k in season(pid)}  # "today" stats: must NOT become season stats
            body += (f"<tr><td>{'BN' if i > 9 else 'Util'}</td>{player_cell(pid)}<td><a>Edit</a></td>"
                     "<td>@AAA</td>" + "".join(f"<td>{c}</td>" for c in stat_cells(today)) + "</tr>")
        header = (f'<h1><a class="Navtarget" href="/nba/{LID}/{tid}">{escape(team_name(tid))}</a></h1>'
                  f'<span class="manager">{escape(manager(tid))}</span>')
        return page(f"{team_name(tid)} | Fake Hoops League",
                    header + f'<table id="statTable0">{two_row_thead(labels)}<tbody>{body}</tbody></table>')

    def players(self, status: str, offset: int, averages: bool) -> str:
        taken = rostered(CURRENT_WEEK)
        pool = sorted(p for p in range(FIRST_ID, FIRST_ID + N_PLAYERS)
                      if (p in taken) == (status == "T"))
        chunk = pool[offset:offset + 25]
        labels = ["Player", "Owner", *(["GP*"] if self.include_gp else []), "% Ros", *HEADERS]
        body = ""
        for pid in chunk:
            s = season(pid)
            if averages:
                s = {k: (round(v / s["gp"], 1) if k != "gp" else 1) for k, v in s.items()}
            cells = stat_cells(s)
            owner = "Fake Team" if status == "T" else "FA"
            gp_cell = [str(season(pid)["gp"])] if self.include_gp else []
            # Leading action cell (add/drop buttons) has no header: tests right-alignment.
            body += (f'<tr><td class="Action"><a class="add" href="#">+</a></td>{player_cell(pid)}'
                     f"<td>{owner}</td>" + "".join(f"<td>{c}</td>" for c in gp_cell) + "<td>50%</td>"
                     + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        script = ""
        if self.players_state_json and chunk:
            import json
            state = {"players": [{"player_id": str(pid), "name": {"full": player_name(pid)},
                                  "editorial_team_abbr": nba_team(pid).lower(),
                                  "display_position": positions(pid)} for pid in chunk]}
            script = f"<script>root.App.main = {json.dumps(state)};\n</script>"
        nxt = f'<a href="?count={offset + 25}">Next 25</a>' if offset + 25 < len(pool) else ""
        return page("Players | Fake Hoops League",
                    f'<div id="players-table"><table>{two_row_thead(labels)}<tbody>{body}</tbody></table>'
                    f"{nxt}</div>{script}")

    def matchup(self, week: int, a: int, b: int) -> str:
        """Side-by-side layout: [Player A][stats A][Pos][stats B][Player B]."""
        labels = ["Player", *HEADERS, "Pos", *HEADERS, "Player"]
        ra, rb = roster_at(a, week), roster_at(b, week)
        body = ""
        for i in range(max(len(ra), len(rb))):
            left = (player_cell(ra[i]) + "".join(f"<td>{c}</td>" for c in stat_cells(weekly(ra[i], week)))
                    if i < len(ra) else "<td></td>" + "<td>-</td>" * len(HEADERS))
            right = ("".join(f"<td>{c}</td>" for c in stat_cells(weekly(rb[i], week))) + player_cell(rb[i])
                     if i < len(rb) else "<td>-</td>" * len(HEADERS) + "<td></td>")
            body += f"<tr>{left}<td>UTIL</td>{right}</tr>"
        thead = "<thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in labels) + "</tr></thead>"
        return page(f"Matchup week {week}", f"<table>{thead}<tbody>{body}</tbody></table>")

    def transactions(self, page_no: int) -> str:
        groups = MOVES if page_no == 1 else PAGE2_MOVES
        rows = ""
        for g in groups:
            if g == "TRADE":
                rows += (f'<tr><td><span class="Icon ys-trade" title="Trade"></span></td>'
                         f"<td><div>{player_cell(9030)[4:-5]} <h6>To {escape(team_name(4))}</h6></div>"
                         f"<div>{player_cell(9040)[4:-5]} <h6>To {escape(team_name(3))}</h6></div></td>"
                         f'<td><a href="/nba/{LID}/3">{escape(team_name(3))}</a>'
                         f'<a href="/nba/{LID}/4">{escape(team_name(4))}</a><span>Oct 25, 4:00 pm</span></td></tr>')
                continue
            icons = "".join(
                f'<span class="Icon F-{"positive" if k == "add" else "negative"}" '
                f'title="{"Added" if k == "add" else "Dropped"} Player">{"+" if k == "add" else "-"}</span>'
                for _, k, _, _ in g)
            players = "".join(
                f'<div class="Pbot-xs">{player_cell(pid)[4:-5]} '
                f'<h6 class="F-shade">{"Free Agent" if k == "add" else "To Waivers"}</h6></div>'
                for _, k, pid, _ in g)
            tid, when = g[0][0], g[0][3]
            rows += (f'<tr><td class="Ta-c">{icons}</td><td class="Pbot-xs">{players}</td>'
                     f'<td><a href="/nba/{LID}/{tid}">{escape(team_name(tid))}</a>'
                     f'<span class="Block">{when}</span></td></tr>')
        nxt = (f'<a rel="next" href="/nba/{LID}/transactions?page=2">Next</a>' if page_no == 1 else "")
        return page("Transactions | Fake Hoops League", f"<table><tbody>{rows}</tbody></table>{nxt}")
