"""Parser tests on small synthetic HTML (shaped like Yahoo, all fake)."""

import unittest

from fantasy_scraper import parse
from fantasy_scraper.embedded import extract_embedded_json, players_from_state

from . import fake_site as fs

LID = fs.LID


def player_td(pid, name="Fakey Guy", team="AAA", pos="PG,SG"):
    return (f'<td><a href="https://sports.yahoo.com/nba/players/{pid}">{name}</a>'
            f'<span>{team} - {pos}</span></td>')


class HelperTests(unittest.TestCase):
    def test_ids_from_hrefs(self):
        self.assertEqual(parse.player_id_from_href("https://sports.yahoo.com/nba/players/6014/"), "6014")
        self.assertIsNone(parse.player_id_from_href("/nba/106518/players"))
        self.assertEqual(parse.team_id_from_href("/nba/106518/7", LID), 7)
        self.assertEqual(parse.team_id_from_href("https://basketball.fantasysports.yahoo.com/nba/106518/12/", LID), 12)
        self.assertIsNone(parse.team_id_from_href("/nba/106518/transactions", LID))
        self.assertIsNone(parse.team_id_from_href("/nba/999/3", LID))

    def test_login_detection(self):
        self.assertTrue(parse.is_login_page("https://login.yahoo.com/?done=x"))
        self.assertTrue(parse.is_login_page("https://example.com/", '<input id="login-username">'))
        self.assertFalse(parse.is_login_page("https://basketball.fantasysports.yahoo.com/nba/106518",
                                             fs.FakeYahoo().league_home()))


class PlayerTableTests(unittest.TestCase):
    def test_two_row_header_and_leading_action_cell(self):
        html = fs.FakeYahoo().players("A", 0, averages=False)
        rows = parse.parse_player_tables(html)
        self.assertEqual(len(rows), 25)
        first = rows[0]
        expected = fs.season(int(first.player_id))
        self.assertEqual(first.name, fs.player_name(int(first.player_id)))
        self.assertEqual(first.nba_team, fs.nba_team(int(first.player_id)))
        self.assertEqual(first.positions, fs.positions(int(first.player_id)).split(","))
        for k, v in expected.items():
            self.assertAlmostEqual(first.stats[k], v, msg=k)
        self.assertEqual(first.owner, "FA")

    def test_embedded_json_fills_missing_team_and_positions(self):
        html = ('<table><thead><tr><th>Player</th><th>PTS</th></tr></thead><tbody>'
                '<tr><td><a href="/nba/players/5555">Json Only</a></td><td>40</td></tr></tbody></table>'
                '<script>root.App.main = {"context": {"players": [{"player_id": "5555", '
                '"name": {"full": "Json Only"}, "editorial_team_abbr": "zzz", '
                '"display_position": "SF,PF"}, {"player_id": "1", "name": {"full": "Unrelated"}}]}};'
                '\n</script>')
        rows = parse.parse_player_tables(html)
        self.assertEqual([r.player_id for r in rows], ["5555"])  # unrelated JSON player ignored
        self.assertEqual(rows[0].nba_team, "ZZZ")
        self.assertEqual(rows[0].positions, ["SF", "PF"])
        self.assertEqual(rows[0].stats["pts"], 40)

    def test_embedded_extractors(self):
        html = ('<script type="application/json">{"a": 1}</script>'
                '<script id="__NEXT_DATA__" type="application/json">{"b": 2}</script>'
                '<script>window.__INITIAL_STATE__ = {"c": [1, 2]}; var x = 1;</script>'
                '<script>not json at all</script>')
        objs = extract_embedded_json(html)
        self.assertIn({"a": 1}, objs)
        self.assertIn({"c": [1, 2]}, objs)
        self.assertEqual(players_from_state([{"x": 1}]), {})

    def test_garbage_is_harmless(self):
        self.assertEqual(parse.parse_player_tables("<html><body>oops</body>"), [])
        self.assertEqual(parse.parse_player_tables(""), [])


class LeaguePageTests(unittest.TestCase):
    def setUp(self):
        self.site = fs.FakeYahoo()

    def test_league_home(self):
        home = self.site.league_home()
        self.assertTrue(parse.looks_like_league_page(home, LID))
        self.assertEqual(parse.parse_league_name(home), "Fake Hoops League")
        self.assertEqual(parse.detect_my_team_id(home, LID), 1)
        links = parse.parse_team_links(home, LID)
        self.assertEqual(sorted(links), list(range(1, 13)))
        self.assertEqual(links[1], "Cripples and Bastards")

    def test_standings(self):
        rows = parse.parse_standings(self.site.league_home(), LID)
        self.assertEqual(len(rows), 12)
        self.assertEqual((rows[0]["team_id"], rows[0]["rank"], rows[0]["wins"], rows[0]["losses"]), (1, 1, 11, 0))

    def test_teams_page_managers(self):
        teams = {t.team_id: t for t in parse.parse_teams_page(self.site.teams(), LID)}
        self.assertEqual(teams[1].manager, "Thomas")
        self.assertEqual(teams[12].name, "Fake Team 12")

    def test_scoreboard(self):
        b = parse.parse_scoreboard(self.site.scoreboard(1), LID, 2026)
        self.assertEqual(b.current_week, 1)
        self.assertIn((1, 1, 2), b.matchups)
        self.assertEqual(len(b.matchups), 6)
        self.assertEqual(sorted(b.week_ranges), [1, 2])

    def test_team_page(self):
        name, players = parse.parse_team_page(self.site.team(1), LID, 1)
        self.assertEqual(name, "Cripples and Bastards")
        ids = [p.player_id for p in players]
        self.assertIn("9160", ids)
        self.assertNotIn("9012", ids)
        self.assertEqual(len(ids), 13)

    def test_side_by_side_matchup(self):
        sides = parse.parse_matchup_page(self.site.matchup(1, 1, 2), 1, 2)
        self.assertEqual([p.player_id for p in sides[1]], [str(p) for p in fs.roster_at(1, 1)])
        self.assertEqual([p.player_id for p in sides[2]], [str(p) for p in fs.roster_at(2, 1)])
        p = sides[2][0]
        exp = fs.weekly(int(p.player_id), 1)
        self.assertEqual((p.stats["pts"], p.stats["fga"], p.stats["tov"]), (exp["pts"], exp["fga"], exp["tov"]))

    def test_two_table_matchup(self):
        t = ('<table><thead><tr><th>Player</th><th>PTS</th></tr></thead><tbody>'
             '<tr>{}<td>{}</td></tr></tbody></table>')
        html = t.format(player_td(1), 10) + t.format(player_td(2), 20)
        sides = parse.parse_matchup_page(html, 4, 9)
        self.assertEqual(sides[4][0].stats["pts"], 10)
        self.assertEqual(sides[9][0].player_id, "2")


class TransactionTests(unittest.TestCase):
    def test_fake_transactions_page(self):
        page = parse.parse_transactions(fs.FakeYahoo().transactions(1), LID,
                                        f"https://basketball.fantasysports.yahoo.com/nba/{LID}/transactions")
        got = [(m.team_id, m.kind, m.player.player_id) for m in page.moves]
        self.assertEqual(got, [(1, "add", "9160"), (1, "drop", "9012"), (7, "add", "9165"),
                               (5, "add", "9161"), (5, "drop", "9055")])
        self.assertEqual(len(page.skipped), 1)
        self.assertIn("trade", page.skipped[0])
        self.assertEqual(page.next_url,
                         f"https://basketball.fantasysports.yahoo.com/nba/{LID}/transactions?page=2")
        self.assertEqual(page.moves[0].group, page.moves[1].group)

    def test_padding_class_is_not_an_add(self):
        html = ('<table><tr><td><span class="Padding-s">x</span></td><td>'
                '<div><a href="/nba/players/7">Seven</a> <h6>Dropped</h6></div></td>'
                f'<td><a href="/nba/{LID}/3">T3</a> Oct 24, 10:23 am</td></tr></table>')
        page = parse.parse_transactions(html, LID)
        self.assertEqual([(m.kind, m.team_id) for m in page.moves], [("drop", 3)])

    def test_row_without_team_is_skipped(self):
        html = '<table><tr><td><span title="Added Player">+</span><a href="/nba/players/7">S</a></td></tr></table>'
        page = parse.parse_transactions(html, LID)
        self.assertEqual(page.moves, [])
        self.assertEqual(len(page.skipped), 1)


if __name__ == "__main__":
    unittest.main()
