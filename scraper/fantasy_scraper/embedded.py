"""Find JSON application state embedded in a page's <script> tags.

Modern web pages often ship their data as JSON inside the HTML, e.g.::

    <script id="__NEXT_DATA__" type="application/json">{...}</script>
    <script>root.App.main = {...};</script>
    <script>window.__INITIAL_STATE__ = {...};</script>

When present, that JSON is far more stable than CSS classes, so the parsers
try it first and fall back to the visible HTML tables. Yahoo Fantasy's
classic pages are mostly server-rendered tables, so on today's site this may
find nothing; that's fine. Run with ``--debug-dump`` and look in
``data/debug/*.state.json`` to see what (if anything) was found.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from bs4 import BeautifulSoup

from .stats import statline_from_yahoo_stats

# `<name> = {` assignments we know about. Add more if a dump shows another.
_ASSIGNMENT_RE = re.compile(
    r"(?:root\.App\.main|window\.__INITIAL_STATE__|window\.__PRELOADED_STATE__|"
    r"window\.__APOLLO_STATE__|window\.__DATA__|window\.App\.state)\s*=\s*",
)
_decoder = json.JSONDecoder()


def extract_embedded_json(html: str) -> list[Any]:
    """Return every JSON object we can find in script tags (may be empty)."""
    soup = BeautifulSoup(html or "", "html.parser")
    found: list[Any] = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        kind = (script.get("type") or "").lower()
        if kind in ("application/json", "application/ld+json") or script.get("id") == "__NEXT_DATA__":
            try:
                found.append(json.loads(text))
            except json.JSONDecodeError:
                pass
            continue
        for m in _ASSIGNMENT_RE.finditer(text):
            try:
                # raw_decode parses one JSON value and ignores the trailing `;...`
                obj, _ = _decoder.raw_decode(text, m.end())
                found.append(obj)
            except json.JSONDecodeError:
                pass
    return found


def walk(obj: Any) -> Iterator[dict]:
    """Yield every dict nested anywhere inside ``obj`` (depth-first)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _name_of(d: dict) -> str | None:
    name = d.get("name") or d.get("full_name") or d.get("displayName")
    if isinstance(name, dict):
        name = name.get("full") or " ".join(
            str(x) for x in (name.get("first"), name.get("last")) if x)
    return name if isinstance(name, str) and name.strip() else None


def _player_id_of(d: dict) -> str | None:
    for k in ("player_id", "playerId"):
        if str(d.get(k, "")).isdigit():
            return str(d[k])
    key = d.get("player_key") or d.get("playerKey")
    if isinstance(key, str):
        m = re.search(r"\.p\.(\d+)$", key)
        if m:
            return m.group(1)
    return None


def _stats_of(d: dict) -> dict[str, object] | None:
    """Yahoo API-ish stats: {"stats": [{"stat_id": "12", "value": "597"}]} or {"stats": {"12": "597"}}."""
    stats = d.get("stats")
    if isinstance(stats, dict) and "stats" in stats:  # player_stats: {stats: [...]}
        stats = stats["stats"]
    if isinstance(stats, dict):
        return {str(k): v for k, v in stats.items()}
    if isinstance(stats, list):
        out = {}
        for s in stats:
            s = s.get("stat", s) if isinstance(s, dict) else s
            if isinstance(s, dict) and "stat_id" in s:
                out[str(s["stat_id"])] = s.get("value")
        return out or None
    return None


def players_from_state(objs: list[Any]) -> dict[str, dict]:
    """Heuristically pull player records out of embedded state.

    Returns ``{yahoo_player_id: {"name", "nba_team", "positions", "season"?}}``.
    Only records that have both an id and a name are kept. ``season`` is set
    only if a stats block with at least one known stat id was found.
    """
    players: dict[str, dict] = {}
    for obj in objs:
        for d in walk(obj):
            pid, name = _player_id_of(d), _name_of(d)
            if not pid or not name:
                continue
            rec = players.setdefault(pid, {"name": name, "nba_team": "", "positions": []})
            team = d.get("editorial_team_abbr") or d.get("teamAbbr") or d.get("team_abbr")
            if isinstance(team, str) and team:
                rec["nba_team"] = team.upper()
            pos = d.get("eligible_positions") or d.get("display_position") or d.get("positions")
            if isinstance(pos, str):
                rec["positions"] = [p.strip() for p in pos.split(",") if p.strip()]
            elif isinstance(pos, list):
                rec["positions"] = [p.get("position", "") if isinstance(p, dict) else str(p) for p in pos]
            stats = _stats_of(d)
            if stats:
                line, found = statline_from_yahoo_stats(stats)
                if found:
                    rec["season"] = line
                    rec["season_fields"] = sorted(found)
    return players
