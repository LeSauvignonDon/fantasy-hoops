"""Pure page parsers: HTML text in, plain Python data out.

Nothing here touches the network or a browser, so every function can be
unit-tested with a string (see ``tests/``).

**Selectors are best-effort.** They were written from memory of Yahoo
Fantasy's classic server-rendered pages, *not* verified against live pages
(we couldn't log in from the build machine). To stay robust they rely on
things Yahoo is unlikely to change, in this order:

1. JSON state in ``<script>`` tags (see ``embedded.py``), if any;
2. link *targets*: player links contain ``/nba/players/<id>``, team links
   are ``/nba/<league>/<team>``, matchup links carry ``week=&mid1=&mid2=``;
3. table *header text* ("FGM/A", "PTS", "TO"...), not column positions;
4. visible text patterns ("LAL - PG,SG", "Oct 24, 10:23 am").

CSS class names are only used as hints. If a parser returns nothing on a
real page, run ``snapshot --debug-dump``, open the saved HTML in
``data/debug/`` and adjust the function here; the tests show its contract.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .embedded import extract_embedded_json, players_from_state
from .stats import normalize_header, statline_from_cells
from .timeutil import parse_week_ranges

BASE_URL = "https://basketball.fantasysports.yahoo.com"

PLAYER_HREF_RE = re.compile(r"/nba/players/(\d+)")
# "LAL - PG,SG"  or  "LAL - SF"   (Yahoo shows "team - eligible positions")
TEAM_POS_RE = re.compile(r"\b([A-Z]{2,4})\s+[-\u2013]\s+((?:PG|SG|SF|PF|C|G|F)(?:\s*,\s*(?:PG|SG|SF|PF|C|G|F))*)\b")
_RECORD_RE = re.compile(r"\b(\d{1,3})-(\d{1,3})(?:-(\d{1,3}))?\b")


# ---------------------------------------------------------------------------
# Small data types (plain dataclasses, easy to print in a debugger)
# ---------------------------------------------------------------------------


@dataclass
class PlayerRow:
    """One player row from any table (players list, team roster, matchup)."""

    player_id: str
    name: str
    nba_team: str = ""
    positions: list[str] = field(default_factory=list)
    stats: dict | None = None          # StatLine dict, if the row had stat columns
    stat_fields: set[str] = field(default_factory=set)
    owner: str = ""                    # players page "Owner" column (FA / W / team)


@dataclass
class TeamInfo:
    team_id: int
    name: str
    manager: str = ""


@dataclass
class RawTransaction:
    """One half of a Yahoo transaction (an add OR a drop)."""

    kind: str                # "add" | "drop"
    player: PlayerRow
    team_id: int
    when_text: str
    group: int               # index of the Yahoo transaction row (keeps add+drop together)


@dataclass
class TransactionsPage:
    moves: list[RawTransaction]
    skipped: list[str]       # human-readable reasons (trades, unparseable rows)
    next_url: str | None


@dataclass
class ScoreboardPage:
    current_week: int | None
    matchups: list[tuple[int, int, int]]          # (week, team_id_a, team_id_b)
    week_ranges: dict                              # {week: (date, date)}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def soup_of(html: str) -> BeautifulSoup:
    # "html.parser" ships with Python: no lxml/C compiler needed on the Mac.
    return BeautifulSoup(html or "", "html.parser")


def text_of(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def player_id_from_href(href: str | None) -> str | None:
    m = PLAYER_HREF_RE.search(href or "")
    return m.group(1) if m else None


def team_id_from_href(href: str | None, league_id: str) -> int | None:
    """'/nba/106518/7' or 'https://.../nba/106518/7?x' -> 7. Sub-pages like
    '/nba/106518/7/team' also count; '/nba/106518/players' does not."""
    path = urlparse(href or "").path
    m = re.fullmatch(rf"/nba/{re.escape(str(league_id))}/(\d{{1,2}})(?:/[a-z]*)?/?", path)
    return int(m.group(1)) if m else None


def _expanded_cells(tr: Tag, tags=("th", "td")) -> list[Tag]:
    """Row cells with colspan expanded, so headers line up with body cells."""
    out: list[Tag] = []
    for cell in tr.find_all(tags, recursive=False):
        try:
            span = max(1, int(cell.get("colspan", 1)))
        except ValueError:
            span = 1
        out.extend([cell] * span)
    return out


def table_headers(table: Tag) -> list[str]:
    """Column labels. Yahoo uses two header rows (groups, then labels); we
    take the header row with the most cells, preferring the last one."""
    thead = table.find("thead")
    rows = thead.find_all("tr") if thead else [
        tr for tr in table.find_all("tr") if tr.find("th") and not tr.find("td")]
    best: list[str] = []
    for tr in rows:
        labels = [text_of(c) for c in _expanded_cells(tr)]
        if len(labels) >= len(best):
            best = labels
    return best


def body_rows(table: Tag) -> list[Tag]:
    """Data rows (``<tr>`` that contain ``<td>``), ignoring nested tables."""
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        if tr.find("td", recursive=False):
            rows.append(tr)
    return rows


def align_right(headers: list[str], cells: list[str]) -> tuple[list[str], list[str]]:
    """Pair headers with cells from the right-hand end.

    Stat columns are always on the right of Yahoo tables, while the left
    side (checkboxes, action buttons, slot labels) varies. Aligning from the
    right keeps 'PTS' over the points cell even when counts differ."""
    n = min(len(headers), len(cells))
    return headers[len(headers) - n:], cells[len(cells) - n:]


def _player_link(tr: Tag) -> Tag | None:
    """The <a> with the player's name (Yahoo also has icon links with no text)."""
    fallback = None
    for a in tr.find_all("a", href=True):
        if player_id_from_href(a["href"]):
            if text_of(a):
                return a
            fallback = fallback or a
    return fallback


def player_from_cell_context(node: Tag) -> PlayerRow | None:
    """Build a PlayerRow (no stats) from a row/cell containing a player link."""
    a = _player_link(node)
    pid = player_id_from_href(a["href"]) if a else None
    if not pid:
        # Some widgets only carry the id as data-ys-playerid="6583".
        holder = node.find(attrs={"data-ys-playerid": True})
        pid = holder["data-ys-playerid"] if holder and str(holder["data-ys-playerid"]).isdigit() else None
    if not pid:
        return None
    name = text_of(a) if a else ""
    row = PlayerRow(player_id=str(pid), name=name or f"Player {pid}")
    m = TEAM_POS_RE.search(text_of(node))
    if m:
        row.nba_team = m.group(1)
        row.positions = [p.strip() for p in m.group(2).split(",")]
    return row


def parse_player_tables(html: str) -> list[PlayerRow]:
    """Every player row in every table on the page, with stats if present.

    Works for the players list, a team's roster page and similar. The first
    occurrence of a player wins (pages sometimes repeat a player in a
    "spotlight" box).
    """
    soup = soup_of(html)
    rows: dict[str, PlayerRow] = {}
    for table in soup.find_all("table"):
        headers = table_headers(table)
        norm = [normalize_header(h) for h in headers]
        owner_idx = next((i for i, h in enumerate(norm) if h in ("OWNER", "STATUS")), None)
        for tr in body_rows(table):
            player = player_from_cell_context(tr)
            if not player or player.player_id in rows:
                continue
            cells = [text_of(c) for c in _expanded_cells(tr, ("td", "th"))]
            if headers:
                h, c = align_right(headers, cells)
                if owner_idx is not None:
                    # index into the right-aligned lists (rows may have extra leading cells)
                    shift = len(h) - len(headers)
                    if 0 <= owner_idx + shift < len(c):
                        player.owner = c[owner_idx + shift]
                line, found = statline_from_cells(h, c)
                if found:
                    player.stats, player.stat_fields = line, found
            rows[player.player_id] = player
    _merge_embedded(html, rows)
    return list(rows.values())


def _merge_embedded(html: str, rows: dict[str, PlayerRow]) -> None:
    """Fill gaps (team, positions, stats) from embedded JSON when available.

    Only players that are already in the visible table are enriched: the
    state blob may contain unrelated players (news, trending lists)."""
    state = players_from_state(extract_embedded_json(html))
    for pid, rec in state.items():
        row = rows.get(pid)
        if not row:
            continue
        row.nba_team = row.nba_team or rec.get("nba_team", "")
        row.positions = row.positions or rec.get("positions", [])
        if row.stats is None and rec.get("season"):
            row.stats, row.stat_fields = rec["season"], set(rec.get("season_fields", []))


# ---------------------------------------------------------------------------
# League-level pages
# ---------------------------------------------------------------------------


def page_title(html: str) -> str:
    soup = soup_of(html)
    return text_of(soup.find("title"))


def parse_league_name(html: str) -> str | None:
    """League name from the <title> ("My League | Fantasy Basketball | Yahoo")."""
    title = page_title(html)
    if not title:
        return None
    first = re.split(r"\s+[|\u2013\u2014-]\s+", title)[0].strip()
    return first or None


# Navigation link texts that point at a team page but aren't its name.
_GENERIC_TEAM_LINK_TEXT = {"my team", "team", "roster", "view team", "edit", "stats", "matchup",
                           "view", "more", "go"}


def parse_team_links(html: str, league_id: str) -> dict[int, str]:
    """{team_id: team name} from every team link with text on the page."""
    soup = soup_of(html)
    names: dict[int, Counter] = {}
    for a in soup.find_all("a", href=True):
        tid = team_id_from_href(a["href"], league_id)
        label = text_of(a)
        if (tid and label and not label.isdigit() and len(label) <= 60
                and label.lower() not in _GENERIC_TEAM_LINK_TEXT):
            names.setdefault(tid, Counter())[label] += 1
    # Most frequent label wins (logo links etc. are rarer than names).
    return {tid: c.most_common(1)[0][0] for tid, c in sorted(names.items())}


def parse_teams_page(html: str, league_id: str) -> list[TeamInfo]:
    """The league's "Teams" page: one row per team with the manager's name."""
    soup = soup_of(html)
    teams: dict[int, TeamInfo] = {}
    for table in soup.find_all("table"):
        norm = [normalize_header(h) for h in table_headers(table)]
        mgr_idx = next((i for i, h in enumerate(norm) if h.startswith("MANAGER")), None)
        for tr in body_rows(table):
            link = next((a for a in tr.find_all("a", href=True)
                         if team_id_from_href(a["href"], league_id) and text_of(a)), None)
            if not link:
                continue
            tid = team_id_from_href(link["href"], league_id)
            cells = [text_of(c) for c in _expanded_cells(tr, ("td", "th"))]
            manager = ""
            if mgr_idx is not None and mgr_idx < len(cells) and len(cells) == len(norm):
                manager = cells[mgr_idx]
            if not manager:
                hint = tr.find(class_=re.compile("manager|nickname", re.I))
                manager = text_of(hint)
            teams.setdefault(tid, TeamInfo(tid, text_of(link), manager))
    if not teams:  # no table: fall back to plain links
        teams = {tid: TeamInfo(tid, name) for tid, name in parse_team_links(html, league_id).items()}
    return [teams[k] for k in sorted(teams)]


def parse_standings(html: str, league_id: str) -> list[dict]:
    """Standings rows: ``{"team_id", "rank", "wins", "losses", "ties"}``.

    Looks for a table whose rows have a team link and a W-L-T record. The
    Rust model has no standings field; they are stored under ``_yahoo``
    in the snapshot for reference (serde ignores unknown keys)."""
    soup = soup_of(html)
    out: list[dict] = []
    seen: set[int] = set()
    for table in soup.find_all("table"):
        norm = [normalize_header(h) for h in table_headers(table)]
        for tr in body_rows(table):
            link = next((a for a in tr.find_all("a", href=True)
                         if team_id_from_href(a["href"], league_id)), None)
            if not link:
                continue
            tid = team_id_from_href(link["href"], league_id)
            cells = [text_of(c) for c in _expanded_cells(tr, ("td", "th"))]
            rec = None
            for i, cell in enumerate(cells):
                h = norm[i] if len(cells) == len(norm) else ""
                m = _RECORD_RE.fullmatch(cell.strip())
                if m and (h in ("W-L-T", "RECORD", "") or "W-L" in h):
                    rec = m
                    break
            if not rec or tid in seen:
                continue
            seen.add(tid)
            first = (cells[0] if cells else "").strip()
            rank = int(first.rstrip(".")) if re.fullmatch(r"\d{1,2}\.?", first) else len(out) + 1
            out.append({
                "team_id": tid,
                "rank": rank,
                "wins": int(rec.group(1)),
                "losses": int(rec.group(2)),
                "ties": int(rec.group(3) or 0),
            })
    return out


def detect_my_team_id(html: str, league_id: str) -> int | None:
    """Yahoo's nav has a "My Team" link pointing at the signed-in user's team."""
    soup = soup_of(html)
    for a in soup.find_all("a", href=True):
        tid = team_id_from_href(a["href"], league_id)
        if tid and re.fullmatch(r"my\s*team", text_of(a), re.I):
            return tid
    return None


def parse_scoreboard(html: str, league_id: str, start_year: int) -> ScoreboardPage:
    """Matchups from links like ``/nba/<lid>/matchup?week=3&mid1=1&mid2=7``.

    Also reads "Week N (Oct 27 - Nov 2)" ranges and the current week."""
    soup = soup_of(html)
    pairs: dict[tuple[int, int, int], None] = {}
    weeks_seen: Counter = Counter()
    for a in soup.find_all("a", href=True):
        url = urlparse(a["href"])
        if not url.path.rstrip("/").endswith(f"/nba/{league_id}/matchup"):
            continue
        q = parse_qs(url.query)
        try:
            week, m1, m2 = int(q["week"][0]), int(q["mid1"][0]), int(q["mid2"][0])
        except (KeyError, ValueError, IndexError):
            continue
        if m1 == m2:
            continue
        a_, b_ = sorted((m1, m2))
        pairs[(week, a_, b_)] = None
        weeks_seen[week] += 1
    current = None
    # A "selected"/"current" element that says "Week N" is the strongest hint.
    for node in soup.find_all(class_=re.compile(r"(selected|current|is-active|Selected)")):
        m = re.search(r"Week\s+(\d{1,2})", text_of(node))
        if m:
            current = int(m.group(1))
            break
    if current is None and weeks_seen:
        current = weeks_seen.most_common(1)[0][0]
    return ScoreboardPage(current, list(pairs), parse_week_ranges(text_of(soup), start_year))


# ---------------------------------------------------------------------------
# Team and matchup pages
# ---------------------------------------------------------------------------


def parse_team_page(html: str, league_id: str, team_id: int) -> tuple[str | None, list[PlayerRow]]:
    """A team's roster page: (team name if found, roster players).

    The team name is read from a link back to this team's own page (Yahoo's
    header shows it) and falls back to the <title>."""
    players = parse_player_tables(html)
    soup = soup_of(html)
    name = None
    for a in soup.find_all("a", href=True):
        if team_id_from_href(a["href"], league_id) == team_id and text_of(a) and \
                not re.fullmatch(r"(my\s*team|roster|team)", text_of(a), re.I):
            name = text_of(a)
            # Prefer links inside an obvious header element.
            if a.find_parent(["h1", "h2", "header"]) or "Navtarget" in " ".join(a.get("class", [])):
                break
    if not name:
        name = parse_league_name(html)  # title's first segment is usually the team name
    return name, players


def parse_matchup_page(html: str, mid1: int, mid2: int) -> dict[int, list[PlayerRow]]:
    """Weekly player stats for both teams of a matchup page.

    Handles two layouts:
    * two separate player tables -> first is ``mid1``, second ``mid2``;
    * one table with both teams side by side -> a row's left player belongs
      to ``mid1`` and right player to ``mid2``; stat headers are split where
      the stat columns start repeating.
    """
    soup = soup_of(html)
    tables = [t for t in soup.find_all("table") if any(
        player_id_from_href(a["href"]) for a in t.find_all("a", href=True))]
    result: dict[int, list[PlayerRow]] = {mid1: [], mid2: []}
    if len(tables) >= 2:
        for tid, table in zip((mid1, mid2), tables[:2]):
            result[tid] = parse_player_tables(str(table))
        return result
    if not tables:
        return result
    table = tables[0]
    headers = table_headers(table)
    norm = [normalize_header(h) for h in headers]
    split = _side_by_side_split(norm)
    for tr in body_rows(table):
        cells = _expanded_cells(tr, ("td", "th"))
        texts = [text_of(c) for c in cells]
        if split is None or len(cells) != len(headers):
            continue
        for tid, lo, hi in ((mid1, 0, split), (mid2, split, len(cells))):
            side = BeautifulSoup("<tr>" + "".join(str(c) for c in cells[lo:hi]) + "</tr>", "html.parser")
            player = player_from_cell_context(side)
            if not player:
                continue
            line, found = statline_from_cells(headers[lo:hi], texts[lo:hi])
            if found:
                player.stats, player.stat_fields = line, found
            result[tid].append(player)
    return result


def _side_by_side_split(norm: list[str]) -> int | None:
    """Column index where the right-hand team's half of a side-by-side
    matchup table begins, or None if stat headers don't repeat.

    Works whether the right half mirrors the left ("Player stats | Pos |
    stats Player") or repeats it ("Player stats | Pos | Player stats"): we
    split halfway between the end of the left stat block and the start of
    the right one, so each player-name cell lands on its own side."""
    from .stats import PAIR_HEADERS, SINGLE_HEADERS

    known = set(PAIR_HEADERS) | set(SINGLE_HEADERS) | {"FG%", "FT%"}
    firsts, seconds = [], []
    seen: set[str] = set()
    for i, h in enumerate(norm):
        if h not in known:
            continue
        (seconds if h in seen else firsts).append(i)
        seen.add(h)
    if not seconds:
        return None
    left_end = max(i for i in firsts if i < min(seconds))
    return (left_end + min(seconds) + 1) // 2


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

# Matched against whole class tokens ("F-positive", "Icon-add") and against
# title/aria-label words ("Added Player"). Whole tokens matter: a substring
# search for "add" would also match layout classes like "Padding".
_CLASS_KIND = [
    ("trade", re.compile(r"^(icon-)?trades?$|trade", re.I)),
    ("drop", re.compile(r"^(icon-)?(drop|dropped|minus|remove)$|negative", re.I)),
    ("add", re.compile(r"^(icon-)?(add|added|plus)$|positive", re.I)),
]
_LABEL_KIND = [
    ("trade", re.compile(r"\btrade[ds]?\b", re.I)),
    ("drop", re.compile(r"\bdrop(ped)?\b", re.I)),
    ("add", re.compile(r"\badd(ed)?\b", re.I)),
]


def _icon_kind(node: Tag) -> str | None:
    """'add' / 'drop' / 'trade' if this element looks like a move icon."""
    label = " ".join([node.get("title", ""), node.get("aria-label", ""), node.get("alt", "")])
    for kind, rx in _LABEL_KIND:
        if rx.search(label):
            return kind
    for token in node.get("class", []):
        for kind, rx in _CLASS_KIND:
            if rx.search(token):
                return kind
    return None


def parse_transactions(html: str, league_id: str, page_url: str | None = None) -> TransactionsPage:
    """League transactions page -> individual add/drop moves.

    Each Yahoo transaction row holds one or more players plus icons (+ for
    added, - for dropped) in the same order, the manager's team link and a
    time. Trades and commissioner moves are skipped and reported."""
    soup = soup_of(html)
    moves: list[RawTransaction] = []
    skipped: list[str] = []
    group = 0
    for table in soup.find_all("table"):
        for tr in body_rows(table):
            player_links = [a for a in tr.find_all("a", href=True)
                            if player_id_from_href(a["href"]) and text_of(a)]
            if not player_links:
                continue
            group += 1
            row_text = text_of(tr)
            icons = [k for k in (_icon_kind(n) for n in tr.find_all(["span", "i", "svg", "img"])) if k]
            if "trade" in icons or re.search(r"\btraded?\b", row_text, re.I):
                skipped.append(f"trade (row {group}): {row_text[:80]}")
                continue
            team_ids = [t for t in (team_id_from_href(a["href"], league_id)
                                    for a in tr.find_all("a", href=True)) if t]
            if not team_ids:
                skipped.append(f"no team link (row {group}): {row_text[:80]}")
                continue
            kinds = _pair_kinds(player_links, icons)
            if kinds is None:
                skipped.append(f"could not tell add from drop (row {group}): {row_text[:80]}")
                continue
            for a, kind in zip(player_links, kinds):
                cell = a.find_parent(["div", "td", "li"]) or a
                player = player_from_cell_context(cell) or PlayerRow(
                    player_id_from_href(a["href"]), text_of(a))
                moves.append(RawTransaction(kind, player, team_ids[-1], row_text, group))
    return TransactionsPage(moves, skipped, find_next_page_url(html, page_url))


def _pair_kinds(player_links: list[Tag], icons: list[str]) -> list[str] | None:
    """Decide add/drop for each player link in a row."""
    if len(icons) == len(player_links):
        return icons
    kinds = []
    for a in player_links:
        ctx = a.find_parent(["div", "li"]) or a.parent
        text = text_of(ctx).lower() if ctx else ""
        own = [k for k in (_icon_kind(n) for n in (ctx.find_all(True) if ctx else [])) if k]
        if own:
            kinds.append(own[0])
        elif "dropped" in text or "to waivers" in text or "to free agent" in text:
            kinds.append("drop")
        elif "added" in text or "from waivers" in text or "from free agent" in text:
            kinds.append("add")
        elif len(set(icons)) == 1:
            kinds.append(icons[0])
        else:
            return None
    return kinds


def find_next_page_url(html: str, page_url: str | None = None) -> str | None:
    """Absolute URL of a "Next" pagination link, if any (relative links are
    resolved against ``page_url``, the URL the HTML came from)."""
    soup = soup_of(html)
    link = soup.find("a", rel="next", href=True)
    if not link:
        link = next((a for a in soup.find_all("a", href=True)
                     if re.fullmatch(r"next(\s*(page|\d+))?\s*[\u203a>\u00bb]*", text_of(a), re.I)), None)
    if not link or link["href"].startswith(("#", "javascript")):
        return None
    return urljoin(page_url or BASE_URL + "/", link["href"])


# ---------------------------------------------------------------------------
# Session / login detection
# ---------------------------------------------------------------------------


def is_login_page(url: str, html: str = "") -> bool:
    """True if Yahoo bounced us to sign-in (session expired or never logged in)."""
    host = urlparse(url or "").netloc.lower()
    if host.startswith("login.") or "/login" in urlparse(url or "").path:
        return True
    soup = soup_of(html)
    return bool(soup.find("input", attrs={"id": "login-username"}) or
                soup.find("form", attrs={"id": "login-username-form"}))


def looks_like_league_page(html: str, league_id: str) -> bool:
    """A signed-in league page links to its team pages; a logged-out or
    "private league" page doesn't."""
    return len(parse_team_links(html, league_id)) >= 2
