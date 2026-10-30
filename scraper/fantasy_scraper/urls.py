"""Every Yahoo URL the scraper visits, in one place.

If Yahoo changes a URL, this is the only file to edit. Paths are relative
to https://basketball.fantasysports.yahoo.com. Query parameters marked
"best-effort" come from memory of Yahoo's site and are unverified.
"""

from __future__ import annotations

from urllib.parse import urlencode

BASE = "https://basketball.fantasysports.yahoo.com"


def league_home(lid: str) -> str:
    return f"{BASE}/nba/{lid}"


def team_page(lid: str, team_id: int) -> str:
    return f"{BASE}/nba/{lid}/{team_id}"


def teams_page(lid: str) -> str:
    # The "Teams" tab: names + managers (best-effort path).
    return f"{BASE}/nba/{lid}/teams"


def standings_page(lid: str) -> str:
    # The "Standings" tab of league home (best-effort parameters).
    return f"{BASE}/nba/{lid}?lhst=stand"


def scoreboard_page(lid: str, week: int) -> str:
    # League home's matchups module for a given week (best-effort parameters).
    return f"{BASE}/nba/{lid}?" + urlencode({"matchup_week": week, "module": "matchups", "lhst": "matchups"})


def matchup_page(lid: str, week: int, mid1: int, mid2: int) -> str:
    return f"{BASE}/nba/{lid}/matchup?" + urlencode({"week": week, "mid1": mid1, "mid2": mid2})


def transactions_page(lid: str) -> str:
    return f"{BASE}/nba/{lid}/transactions"


def players_page(lid: str, status: str, season: int, offset: int, averages: bool = False) -> str:
    """Players list.

    * status: ``A`` = all available (FA + waivers), ``T`` = all taken.
    * stat1: ``S_S_<season>`` = season totals, ``S_AS_<season>`` = season averages.
    * sort ``AR`` = actual (season) rank; ``count`` is the row offset, 25 per page.
    """
    stat1 = f"S_AS_{season}" if averages else f"S_S_{season}"
    return f"{BASE}/nba/{lid}/players?" + urlencode({
        "status": status, "pos": "P", "cut_type": "33", "stat1": stat1,
        "myteam": "0", "sort": "AR", "sortdir": "1", "count": offset,
    })
