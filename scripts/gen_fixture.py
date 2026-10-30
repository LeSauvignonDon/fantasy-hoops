#!/usr/bin/env python3
"""Generate fixtures/sample_snapshot.json: CLEARLY FAKE example league data.

Every player name, stat line, and transaction is invented. Re-run with
`python3 scripts/gen_fixture.py` to regenerate (deterministic seed).
"""
import json
import random

random.seed(106518)

FIRST = ["Fakey", "Testy", "Mocky", "Sample", "Dummy", "Placeholder", "Example", "Stubby",
         "Fixture", "Lorem", "Ipsum", "Nobody", "Fictional", "Madeup", "Pretend"]
LAST = ["McFakerson", "Testington", "Mockworth", "Samplesson", "Dummington", "Stubbs",
        "Fixturez", "Loremsky", "Notreal", "Imaginary", "Synthetico", "Bogus", "Hypothetical"]
NBA = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]  # fake team codes
POS = [["PG"], ["SG"], ["SF"], ["PF"], ["C"], ["PG", "SG"], ["SG", "SF"], ["SF", "PF"], ["PF", "C"]]

TEAMS = [
    ("Cripples and Bastards", "Thomas"),
    ("Example Team 02", "Manager B"), ("Example Team 03", "Manager C"),
    ("Example Team 04", "Manager D"), ("Example Team 05", "Manager E"),
    ("Example Team 06", "Manager F"), ("Example Team 07", "Manager G"),
    ("Example Team 08", "Manager H"), ("Example Team 09", "Manager I"),
    ("Example Team 10", "Manager J"), ("Example Team 11", "Manager K"),
    ("Example Team 12", "Manager L"),
]
LEAGUE_KEY = "nba.l.106518"
ROSTER = 10
N_PLAYERS = 150


def r1(x):
    return round(x, 1)


def per_game(pos):
    big = "C" in pos or "PF" in pos
    guard = "PG" in pos or "SG" in pos
    tier = random.random()  # higher = better player
    fga = 6 + 14 * tier + random.uniform(-2, 2)
    fg_pct = (0.50 if big else 0.45) + random.uniform(-0.05, 0.05)
    fta = 1 + 6 * tier * random.uniform(0.5, 1.3)
    ft_pct = (0.70 if big else 0.82) + random.uniform(-0.08, 0.06)
    tpm = (0.3 if big else 1.5) + 2.0 * tier * random.random()
    fgm = fga * fg_pct
    ftm = fta * ft_pct
    pts = 2 * fgm + tpm + ftm
    reb = (6 if big else 3) + 6 * tier * random.random()
    ast = (5 if guard else 1.5) + 4 * tier * random.random()
    stl = 0.4 + 1.2 * random.random()
    blk = (0.8 if big else 0.2) + 1.5 * tier * random.random() * (1 if big else 0.4)
    tov = 0.8 + 0.12 * (ast + fga / 3) * random.uniform(0.6, 1.2)
    return dict(fgm=fgm, fga=fga, ftm=ftm, fta=fta, tpm=tpm, pts=pts, reb=reb,
                ast=ast, stl=stl, blk=blk, tov=tov), tier


def totals(pg, games, noise=0.0):
    """Season or weekly totals from per-game averages, with optional noise.

    Makes and attempts share one volume factor (plus a small shooting-luck
    factor on makes) so weekly percentages stay realistic.
    """
    def j(scale=1.0):
        return 1 + random.uniform(-noise, noise) * scale if noise else 1

    out = {"gp": games}
    fg_vol, ft_vol = j(), j()
    out["fga"] = r1(pg["fga"] * games * fg_vol)
    out["fgm"] = min(r1(pg["fgm"] * games * fg_vol * j(0.3)), out["fga"])
    out["fta"] = r1(pg["fta"] * games * ft_vol)
    out["ftm"] = min(r1(pg["ftm"] * games * ft_vol * j(0.3)), out["fta"])
    for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "tov"):
        out[k] = r1(pg[k] * games * j())
    return {k: out[k] for k in ("gp", "fgm", "fga", "ftm", "fta", "tpm", "pts",
                                "reb", "ast", "stl", "blk", "tov")}


players, pgs, value = [], {}, {}
used = set()
for i in range(N_PLAYERS):
    while True:
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        if name not in used:
            used.add(name)
            break
    pos = random.choice(POS)
    pg, tier = per_game(pos)
    key = f"fake.p.{1000 + i}"
    gp = random.randint(14, 20)
    players.append({"player_key": key, "name": name, "nba_team": random.choice(NBA),
                    "positions": pos, "season": totals(pg, gp)})
    pgs[key] = pg
    value[key] = tier

# Snake draft by "tier" so teams are roughly balanced; leftovers are free agents.
order = sorted(pgs, key=lambda k: -value[k])
team_keys = [f"{LEAGUE_KEY}.t.{i + 1}" for i in range(12)]
rosters = {t: [] for t in team_keys}
pick = 0
for rnd in range(ROSTER):
    seq = team_keys if rnd % 2 == 0 else list(reversed(team_keys))
    for t in seq:
        rosters[t].append(order[pick])
        pick += 1
free_agents = order[pick:]

transactions, snapshots, tx_id = [], [], 1
for week in (1, 2):
    # Each manager makes 0-3 add/drop pairs per week (league cap is 5 adds).
    for t in team_keys:
        n = 3 if t == team_keys[0] and week == 2 else random.randint(0, 2)
        added_this_week = set()
        for j in range(n):
            if not free_agents:
                break
            # Look at a handful of free agents and grab the best of them.
            add = max(random.sample(free_agents, min(5, len(free_agents))), key=lambda k: value[k])
            # Drop the weakest player who was not just picked up this week.
            drop = min((k for k in rosters[t] if k not in added_this_week), key=lambda k: value[k])
            added_this_week.add(add)
            ts = f"2026-10-{20 + week * 3 + j:02d}T1{j}:00:00-07:00"
            transactions.append({"id": tx_id, "week": week, "timestamp": ts, "team_key": t,
                                 "kind": "drop", "player_key": drop}); tx_id += 1
            transactions.append({"id": tx_id, "week": week, "timestamp": ts, "team_key": t,
                                 "kind": "add", "player_key": add}); tx_id += 1
            rosters[t].remove(drop)
            rosters[t].append(add)
            free_agents.remove(add)
            free_agents.append(drop)
    for t in team_keys:
        snapshots.append({"week": week, "team_key": t, "player_keys": sorted(rosters[t])})

weekly = []
for week in (1, 2):
    for p in players:
        games = random.randint(2, 4)
        weekly.append({"week": week, "player_key": p["player_key"],
                       "stats": totals(pgs[p["player_key"]], games, noise=0.35)})

matchups = []
for week in (1, 2):
    rot = team_keys[:1] + team_keys[1:][week:] + team_keys[1:][:week]  # circle method
    for i in range(6):
        matchups.append({"week": week, "team_a": rot[i], "team_b": rot[11 - i]})

snapshot = {
    "_comment": "FAKE EXAMPLE DATA generated by scripts/gen_fixture.py. No real players or stats.",
    "league": {"league_key": LEAGUE_KEY, "name": "Example League (fake fixture data)",
               "num_teams": 12, "max_weekly_adds": 5, "current_week": 2,
               "my_team_key": team_keys[0]},
    "teams": [{"team_key": k, "name": n, "manager": m} for k, (n, m) in zip(team_keys, TEAMS)],
    "players": players,
    "rosters": snapshots,
    "transactions": transactions,
    "weekly_stats": weekly,
    "matchups": matchups,
}
with open("fixtures/sample_snapshot.json", "w") as f:
    json.dump(snapshot, f, indent=1)
    f.write("\n")
print("wrote fixtures/sample_snapshot.json")
