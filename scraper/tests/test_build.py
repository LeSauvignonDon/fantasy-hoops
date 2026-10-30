"""Schema mapping: ScrapeResult (Yahoo ids) -> snapshot JSON (Rust schema)."""

import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from fantasy_scraper.build import ScrapeResult, build_snapshot, validate_snapshot
from fantasy_scraper.parse import PlayerRow, RawTransaction, TeamInfo
from fantasy_scraper.timeutil import parse_week_ranges

PT = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 29, 21, 0, tzinfo=PT)
STAT_KEYS = ["gp", "fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov"]


def line(**kw):
    out = {k: 0.0 for k in STAT_KEYS}
    out.update(kw)
    return out


def small_result() -> ScrapeResult:
    r = ScrapeResult(league_id="106518", league_name="Synthetic League", current_week=2, my_team_id=None)
    r.teams = {1: TeamInfo(1, "Cripples and Bastards", "Thomas"), 2: TeamInfo(2, "Other Guys", "Pat")}
    r.week_ranges = parse_week_ranges("Week 1 (Oct 20 - Oct 26) Week 2 (Oct 27 - Nov 2)", 2026)
    rows = [PlayerRow("101", "Alpha One", "AAA", ["PG", "SG", "Util"], line(gp=4, pts=80.0, fgm=30, fga=60), {"gp", "pts"}),
            PlayerRow("102", "Beta Two", "BBB", ["C"], line(gp=3, reb=33.0), {"gp", "reb"}),
            PlayerRow("103", "Gamma Three", "CCC", ["SF"], line(gp=2, ast=9.0), {"gp", "ast"})]
    for p in rows:
        r.add_player(p)
    r.rosters = {(2, 1): ["101"], (2, 2): ["102"], (1, 1): ["101", "999"]}
    # 999 only appears on a roster and in a transaction: must become a placeholder player.
    r.add_player(PlayerRow("999", "Dropped Guy", "DDD", ["PF"]), prefer_stats=False)
    r.transactions = [
        (RawTransaction("add", PlayerRow("103", "Gamma Three"), 1, "Oct 28", 1), datetime(2026, 10, 28, 9, 15, tzinfo=PT)),
        (RawTransaction("drop", PlayerRow("999", "Dropped Guy"), 1, "Oct 28", 1), datetime(2026, 10, 28, 9, 15, tzinfo=PT)),
        (RawTransaction("add", PlayerRow("102", "Beta Two"), 2, "Oct 22", 2), datetime(2026, 10, 22, 12, 0, tzinfo=PT)),
        (RawTransaction("add", PlayerRow("101", "Alpha One"), 42, "Oct 22", 3), datetime(2026, 10, 22, 12, 0, tzinfo=PT)),
    ]
    r.weekly = {(1, "101"): line(pts=40.0), (2, "102"): line(reb=11.0)}
    r.matchups = {(1, 1, 2), (2, 2, 1)}
    r.standings = [{"team_id": 1, "rank": 1, "wins": 1, "losses": 0, "ties": 0}]
    return r


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(small_result(), NOW, "Cripples and Bastards")

    def test_valid_and_json_serializable(self):
        self.assertEqual(validate_snapshot(self.snap), [])
        json.loads(json.dumps(self.snap))

    def test_league_block(self):
        self.assertEqual(self.snap["league"], {
            "league_key": "nba.l.106518", "name": "Synthetic League", "num_teams": 2,
            "max_weekly_adds": 5, "current_week": 2, "my_team_key": "nba.l.106518.t.1"})

    def test_keys_and_positions(self):
        p = {x["player_key"]: x for x in self.snap["players"]}
        self.assertEqual(p["nba.p.101"]["positions"], ["PG", "SG"])  # Util dropped
        self.assertEqual(sorted(p["nba.p.101"]["season"]), sorted(STAT_KEYS))
        self.assertEqual(p["nba.p.101"]["season"]["gp"], 4)
        self.assertIsInstance(p["nba.p.101"]["season"]["gp"], int)
        self.assertEqual(p["nba.p.999"]["season"]["pts"], 0)  # placeholder with zeros
        self.assertTrue(any("no season stats" in w for w in self.snap["_yahoo"]["warnings"]))

    def test_transactions(self):
        tx = self.snap["transactions"]
        # oldest first, sequential ids, weeks from the date ranges, unknown team 42 skipped
        self.assertEqual([(t["id"], t["week"], t["kind"], t["player_key"]) for t in tx],
                         [(1, 1, "add", "nba.p.102"), (2, 2, "add", "nba.p.103"), (3, 2, "drop", "nba.p.999")])
        self.assertEqual(tx[1]["timestamp"], "2026-10-28T09:15:00-07:00")
        self.assertTrue(any("unknown team id 42" in w for w in self.snap["_yahoo"]["warnings"]))

    def test_rosters_weekly_matchups(self):
        self.assertEqual([(r["week"], r["team_key"]) for r in self.snap["rosters"]],
                         [(1, "nba.l.106518.t.1"), (2, "nba.l.106518.t.1"), (2, "nba.l.106518.t.2")])
        self.assertEqual(self.snap["weekly_stats"][0]["stats"]["pts"], 40)
        self.assertEqual(self.snap["matchups"][0], {"week": 1, "team_a": "nba.l.106518.t.1",
                                                    "team_b": "nba.l.106518.t.2"})
        self.assertEqual(self.snap["_yahoo"]["standings"][0]["team_key"], "nba.l.106518.t.1")

    def test_my_team_fallbacks(self):
        r = small_result()
        r.my_team_id = 2
        self.assertEqual(build_snapshot(r, NOW, None)["league"]["my_team_key"], "nba.l.106518.t.2")
        r.my_team_id = None
        snap = build_snapshot(r, NOW, "Nobody")
        self.assertEqual(snap["league"]["my_team_key"], "nba.l.106518.t.1")
        self.assertTrue(any("not found" in w for w in snap["_yahoo"]["warnings"]))

    def test_validator_catches_problems(self):
        bad = json.loads(json.dumps(self.snap))
        bad["players"].append(dict(bad["players"][0]))
        bad["league"]["my_team_key"] = "nba.l.106518.t.77"
        bad["rosters"][0]["player_keys"].append("nba.p.nope")
        errs = " | ".join(validate_snapshot(bad))
        for needle in ("duplicate player_key", "my_team_key", "unknown player"):
            self.assertIn(needle, errs)


if __name__ == "__main__":
    unittest.main()
