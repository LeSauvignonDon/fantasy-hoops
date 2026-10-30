"""Convert Yahoo stat cells into the Rust ``StatLine`` JSON shape.

The Rust side (``crates/hoops-core/src/models.rs``) expects::

    {"gp": 20, "fgm": 205.9, "fga": 421.6, "ftm": .., "fta": .., "tpm": ..,
     "pts": .., "reb": .., "ast": .., "stl": .., "blk": .., "tov": ..}

``gp`` is an integer, everything else a float. Season lines are **totals**.

Yahoo shows the 9 categories as columns. FG% and FT% are derived from the
"FGM/A" and "FTM/A" columns ("205/421"), which is exactly what the Rust code
wants: it never stores percentages, only makes and attempts.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

# Order matches the Rust struct, so json.dumps output looks like the fixture.
STAT_FIELDS = ("fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov")

# Column header (normalised, see `normalize_header`) -> StatLine field.
SINGLE_HEADERS = {
    "GP": "gp",
    "G": "gp",
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
    "3PTM": "tpm",
    "3PM": "tpm",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",  # Yahoo labels steals "ST"
    "STL": "stl",
    "BLK": "blk",
    "TO": "tov",
    "TOV": "tov",
}

# Columns that hold "made/attempted" in one cell.
PAIR_HEADERS = {
    "FGM/A": ("fgm", "fga"),
    "FGM/FGA": ("fgm", "fga"),
    "FTM/A": ("ftm", "fta"),
    "FTM/FTA": ("ftm", "fta"),
}

# Yahoo's numeric stat ids for NBA (used by the official API and, often, by
# the JSON state embedded in pages). Best-effort; unknown ids are ignored.
YAHOO_STAT_IDS = {
    "0": "gp",
    "3": "fga",
    "4": "fgm",
    "6": "fta",
    "7": "ftm",
    "10": "tpm",
    "12": "pts",
    "15": "reb",
    "16": "ast",
    "17": "stl",
    "18": "blk",
    "19": "tov",
}
YAHOO_PAIR_STAT_IDS = {"9004003": ("fgm", "fga"), "9007006": ("ftm", "fta")}

_DASHES = {"", "-", "\u2013", "\u2014", "--", "N/A", "NA", "n/a"}


def empty_statline() -> dict:
    """A StatLine with every field zero (what Rust's `StatLine::default()` is)."""
    line: dict = {"gp": 0}
    for f in STAT_FIELDS:
        line[f] = 0.0
    return line


def normalize_header(text: str) -> str:
    """'  FGM/A* ' -> 'FGM/A'. Yahoo marks non-scoring stats with '*'."""
    text = re.sub(r"\s+", "", text or "")
    return text.replace("*", "").upper()


def parse_number(text: str | None) -> float | None:
    """'1,234' -> 1234.0, '.456' -> 0.456, '-' -> None (no games / no data)."""
    if text is None:
        return None
    t = text.strip().replace(",", "")
    if t in _DASHES:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_pair(text: str | None) -> tuple[float, float] | None:
    """'205/421' -> (205.0, 421.0); '5.3/11.2' works too; '-/-' -> None."""
    if not text or "/" not in text:
        return None
    left, _, right = text.partition("/")
    a, b = parse_number(left), parse_number(right)
    if a is None or b is None:
        return None
    return a, b


def statline_from_cells(headers: Iterable[str], cells: Iterable[str]) -> tuple[dict, set[str]]:
    """Map a table row to a StatLine.

    ``headers`` and ``cells`` are parallel lists of strings. Returns the stat
    line plus the set of fields that were actually present, so callers can
    tell "0 blocks" from "this table has no BLK column".
    """
    line = empty_statline()
    found: set[str] = set()
    for raw_header, cell in zip(headers, cells):
        h = normalize_header(raw_header)
        if h in PAIR_HEADERS:
            pair = parse_pair(cell)
            made_f, att_f = PAIR_HEADERS[h]
            found.update((made_f, att_f))
            if pair:
                line[made_f], line[att_f] = pair
        elif h in SINGLE_HEADERS:
            field = SINGLE_HEADERS[h]
            # Don't let a separate "FGM" column overwrite a pair we already read.
            if field in found and field in ("fgm", "fga", "ftm", "fta"):
                continue
            found.add(field)
            value = parse_number(cell)
            if value is not None:
                line[field] = int(round(value)) if field == "gp" else value
    return line, found


def statline_from_yahoo_stats(stats: Mapping[str, object]) -> tuple[dict, set[str]]:
    """Map ``{stat_id: value}`` (Yahoo API style) to a StatLine."""
    line = empty_statline()
    found: set[str] = set()
    for sid, value in stats.items():
        sid = str(sid)
        text = None if value is None else str(value)
        if sid in YAHOO_PAIR_STAT_IDS:
            pair = parse_pair(text)
            made_f, att_f = YAHOO_PAIR_STAT_IDS[sid]
            if pair:
                line[made_f], line[att_f] = pair
                found.update((made_f, att_f))
        elif sid in YAHOO_STAT_IDS:
            field = YAHOO_STAT_IDS[sid]
            if field in found:  # pair already gave us fgm/fga
                continue
            v = parse_number(text)
            if v is not None:
                line[field] = int(round(v)) if field == "gp" else v
                found.add(field)
    return line, found


def derive_games_played(totals: Mapping[str, float], averages: Mapping[str, float]) -> int | None:
    """Estimate GP from a totals line and a per-game line: GP = total / avg.

    Used only when Yahoo's table has no GP column. Tries the stats with the
    biggest numbers first (most precise after Yahoo rounds averages to 1 dp).
    """
    for field in ("pts", "fga", "reb", "ast", "fta"):
        total, avg = totals.get(field) or 0.0, averages.get(field) or 0.0
        if avg > 0 and total > 0:
            return max(1, int(round(total / avg)))
    return None


def has_any_stats(line: Mapping[str, float]) -> bool:
    return any((line.get(f) or 0) for f in STAT_FIELDS) or bool(line.get("gp"))


def clean_statline(line: Mapping[str, float]) -> dict:
    """Round floats (Yahoo averages produce 2.9999999...) and fix types."""
    out = {"gp": int(line.get("gp") or 0)}
    for f in STAT_FIELDS:
        out[f] = round(float(line.get(f) or 0.0), 3)
    return out
