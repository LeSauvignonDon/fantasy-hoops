//! Tiny hand-built leagues for unit tests. Compiled only under `cfg(test)`.

use crate::models::*;

/// A player with `pts` and `tov` per game over 10 games; other stats derive
/// from `pts` so better scorers are better at everything except TO.
pub fn player(key: &str, pts: f64, tov: f64) -> Player {
    let g = 10.0;
    Player {
        player_key: key.to_string(),
        name: format!("Fake {key}"),
        nba_team: "FAK".into(),
        positions: vec!["SF".into()],
        season: StatLine {
            gp: 10,
            fgm: pts * 0.4 * g,
            fga: pts * 0.8 * g,
            ftm: pts * 0.15 * g,
            fta: pts * 0.2 * g,
            tpm: pts * 0.1 * g,
            pts: pts * g,
            reb: pts * 0.3 * g,
            ast: pts * 0.2 * g,
            stl: pts * 0.05 * g,
            blk: pts * 0.03 * g,
            tov: tov * g,
        },
    }
}

/// Weekly stats equal to one game of a player's season average times `games`.
pub fn week_line(p: &Player, week: u32, games: u32) -> WeeklyPlayerStats {
    let pg = p.season.per_game();
    let g = f64::from(games);
    WeeklyPlayerStats {
        week,
        player_key: p.player_key.clone(),
        stats: StatLine {
            gp: games,
            fgm: pg.fgm * g,
            fga: pg.fga * g,
            ftm: pg.ftm * g,
            fta: pg.fta * g,
            tpm: pg.tpm * g,
            pts: pg.pts * g,
            reb: pg.reb * g,
            ast: pg.ast * g,
            stl: pg.stl * g,
            blk: pg.blk * g,
            tov: pg.tov * g,
        },
    }
}

/// Three teams, two players each, plus two free agents:
///
/// * t1 "Mine":  p1 (20 pts), p2 (10 pts)  — week 2: dropped p2, added fa1 (25 pts)
/// * t2 "Rival": p3 (30 pts), p4 (25 pts)
/// * t3 "Other": p5 (5 pts),  p6 (5 pts)
/// * free agents after week 2: p2, fa2 (8 pts)
pub fn tiny_league() -> LeagueData {
    let players = vec![
        player("p1", 20.0, 2.0),
        player("p2", 10.0, 1.0),
        player("p3", 30.0, 3.0),
        player("p4", 25.0, 3.0),
        player("p5", 5.0, 1.0),
        player("p6", 5.0, 1.0),
        player("fa1", 25.0, 2.0),
        player("fa2", 8.0, 1.0),
    ];
    let team = |k: &str, n: &str| Team {
        team_key: k.into(),
        name: n.into(),
        manager: "x".into(),
    };
    let roster = |week, t: &str, ps: &[&str]| RosterSnapshot {
        week,
        team_key: t.into(),
        player_keys: ps.iter().map(|s| s.to_string()).collect(),
    };
    let tx = |id, kind, p: &str| Transaction {
        id,
        week: 2,
        timestamp: "2026-10-28T10:00:00-07:00".into(),
        team_key: "t1".into(),
        kind,
        player_key: p.into(),
    };
    let weekly_stats = [1, 2]
        .into_iter()
        .flat_map(|w| players.iter().map(move |p| week_line(p, w, 3)))
        .collect();

    LeagueData {
        league: League {
            league_key: "fake.l.1".into(),
            name: "Tiny".into(),
            num_teams: 3,
            max_weekly_adds: 5,
            current_week: 2,
            my_team_key: "t1".into(),
        },
        teams: vec![team("t1", "Mine"), team("t2", "Rival"), team("t3", "Other")],
        rosters: vec![
            roster(1, "t1", &["p1", "p2"]),
            roster(1, "t2", &["p3", "p4"]),
            roster(1, "t3", &["p5", "p6"]),
            roster(2, "t1", &["p1", "fa1"]),
        ],
        transactions: vec![
            tx(1, TransactionKind::Drop, "p2"),
            tx(2, TransactionKind::Add, "fa1"),
        ],
        weekly_stats,
        matchups: vec![Matchup {
            week: 2,
            team_a: "t1".into(),
            team_b: "t2".into(),
        }],
        players,
    }
}
