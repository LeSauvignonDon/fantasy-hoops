import unittest

from fantasy_scraper.stats import (clean_statline, derive_games_played, normalize_header,
                                   parse_number, parse_pair, statline_from_cells,
                                   statline_from_yahoo_stats)


class StatsTests(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(parse_number("1,234"), 1234.0)
        self.assertEqual(parse_number(".475"), 0.475)
        self.assertIsNone(parse_number("-"))
        self.assertIsNone(parse_number("–"))
        self.assertIsNone(parse_number(""))
        self.assertEqual(parse_pair("41/88"), (41.0, 88.0))
        self.assertIsNone(parse_pair("-/-"))

    def test_header_normalization(self):
        self.assertEqual(normalize_header(" fgm/a* "), "FGM/A")
        self.assertEqual(normalize_header("GP*"), "GP")

    def test_cells_to_statline_nine_cats(self):
        headers = ["GP*", "FGM/A*", "FG%", "FTM/A*", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
        cells = ["5", "41/88", ".466", "20/25", ".800", "12", "114", "30", "22", "6", "3", "9"]
        line, found = statline_from_cells(headers, cells)
        self.assertEqual(line, {"gp": 5, "fgm": 41, "fga": 88, "ftm": 20, "fta": 25, "tpm": 12,
                                "pts": 114, "reb": 30, "ast": 22, "stl": 6, "blk": 3, "tov": 9})
        self.assertIn("gp", found)
        self.assertIn("tov", found)

    def test_unknown_and_missing_columns(self):
        line, found = statline_from_cells(["Rank", "% Ros", "PTS"], ["3", "99%", "-"])
        # "-" means "no games yet": the column exists, so it counts as found (= 0).
        self.assertEqual(found, {"pts"})
        self.assertEqual(line["pts"], 0)

    def test_yahoo_stat_ids(self):
        line, found = statline_from_yahoo_stats({"9004003": "41/88", "9007006": "20/25", "10": "12",
                                                 "12": "114", "15": "30", "16": "22", "17": "6",
                                                 "18": "3", "19": "9", "5": ".466"})
        self.assertEqual((line["fgm"], line["fga"], line["ftm"], line["fta"]), (41, 88, 20, 25))
        self.assertEqual(line["tov"], 9)
        self.assertNotIn("gp", found)

    def test_derive_games_played(self):
        totals = {"pts": 100, "reb": 40, "ast": 0}
        averages = {"pts": 20.0, "reb": 8.0, "ast": 0.0}
        self.assertEqual(derive_games_played(totals, averages), 5)
        self.assertIsNone(derive_games_played({"pts": 0}, {"pts": 0}))

    def test_clean_statline_types(self):
        out = clean_statline({"gp": 4.0, "fgm": 1 / 3, "pts": 10})
        self.assertIsInstance(out["gp"], int)
        self.assertEqual(out["fgm"], 0.333)
        self.assertEqual(sorted(out), sorted(["gp", "fgm", "fga", "ftm", "fta", "tpm", "pts",
                                              "reb", "ast", "stl", "blk", "tov"]))


if __name__ == "__main__":
    unittest.main()
