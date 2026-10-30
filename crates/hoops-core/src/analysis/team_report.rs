//! Rank teams category-by-category.
//!
//! A team's *strength* in a category is the sum of its rostered players'
//! season per-game averages: roughly "what this roster produces in an average
//! game slot". Percentages come from summed makes/attempts. Ranks use
//! "competition ranking" (1, 2, 2, 4) and respect TO being lower-is-better.

use crate::error::{Error, Result};
use crate::models::{Category, CategoryMap, LeagueData, StatLine, Team, TeamKey};

/// Where a team sits in one category, bucketed into thirds of the league.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Strength {
    Strong,
    Middle,
    Weak,
}

impl Strength {
    fn from_rank(rank: u32, num_teams: u32) -> Self {
        let third = (num_teams / 3).max(1);
        if rank <= third {
            Strength::Strong
        } else if rank > num_teams.saturating_sub(third) {
            Strength::Weak
        } else {
            Strength::Middle
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Strength::Strong => "strong",
            Strength::Middle => "-",
            Strength::Weak => "WEAK",
        }
    }
}

/// One team's per-game totals and ranks in every category.
#[derive(Debug, Clone)]
pub struct TeamStanding {
    pub team_key: TeamKey,
    pub totals: StatLine,
    pub ranks: CategoryMap<u32>,
}

/// One line of a team report.
#[derive(Debug, Clone)]
pub struct CategoryRow {
    pub category: Category,
    pub value: f64,
    pub rank: u32,
    pub league_avg: f64,
    pub league_best: f64,
    pub strength: Strength,
}

/// Category-by-category report for one team.
#[derive(Debug, Clone)]
pub struct TeamReport {
    pub team: Team,
    pub week: u32,
    pub num_teams: u32,
    pub rows: Vec<CategoryRow>,
    pub standings: Vec<TeamStanding>,
}

impl TeamReport {
    /// Categories where the team is in the bottom third.
    pub fn weak_categories(&self) -> Vec<Category> {
        self.rows
            .iter()
            .filter(|r| r.strength == Strength::Weak)
            .map(|r| r.category)
            .collect()
    }

    /// Mean rank across all nine categories (lower is better).
    pub fn average_rank(&self) -> f64 {
        self.rows.iter().map(|r| f64::from(r.rank)).sum::<f64>() / self.rows.len() as f64
    }
}

/// Sum of per-game season averages for a team's roster as of `week`.
pub fn roster_strength(data: &LeagueData, team_key: &str, week: u32) -> StatLine {
    data.roster_at(team_key, week)
        .into_iter()
        .flat_map(|r| &r.player_keys)
        .filter_map(|k| data.player(k))
        .map(|p| p.season.per_game())
        .sum()
}

/// Competition ranks: rank = 1 + number of values that strictly beat this one.
pub fn rank_values(values: &[f64], cat: Category) -> Vec<u32> {
    values
        .iter()
        .map(|&v| 1 + values.iter().filter(|&&o| cat.beats(o, v)).count() as u32)
        .collect()
}

/// Strength and ranks for every team in the league.
pub fn league_standings(data: &LeagueData, week: u32) -> Vec<TeamStanding> {
    let totals: Vec<StatLine> = data
        .teams
        .iter()
        .map(|t| roster_strength(data, &t.team_key, week))
        .collect();

    // For each category, rank all teams; then transpose into per-team maps.
    let ranks_by_cat = CategoryMap::from_fn(|cat| {
        let values: Vec<f64> = totals.iter().map(|s| s.value(cat)).collect();
        rank_values(&values, cat)
    });

    data.teams
        .iter()
        .zip(totals)
        .enumerate()
        .map(|(i, (team, totals))| TeamStanding {
            team_key: team.team_key.clone(),
            totals,
            ranks: CategoryMap::from_fn(|cat| ranks_by_cat[cat][i]),
        })
        .collect()
}

/// Build the report for `team_key` as of `week`.
pub fn team_report(data: &LeagueData, team_key: &str, week: u32) -> Result<TeamReport> {
    let team = data
        .team(team_key)
        .ok_or_else(|| Error::UnknownTeam(team_key.to_string()))?
        .clone();
    let standings = league_standings(data, week);
    let num_teams = standings.len() as u32;
    let mine = standings
        .iter()
        .find(|s| s.team_key == team_key)
        .expect("team exists, so it has a standing");

    let rows = Category::ALL
        .into_iter()
        .map(|cat| {
            let values: Vec<f64> = standings.iter().map(|s| s.totals.value(cat)).collect();
            let league_avg = values.iter().sum::<f64>() / values.len() as f64;
            let league_best = values
                .iter()
                .copied()
                .reduce(|a, b| if cat.beats(b, a) { b } else { a })
                .unwrap_or(0.0);
            let rank = mine.ranks[cat];
            CategoryRow {
                category: cat,
                value: mine.totals.value(cat),
                rank,
                league_avg,
                league_best,
                strength: Strength::from_rank(rank, num_teams),
            }
        })
        .collect();

    Ok(TeamReport {
        team,
        week,
        num_teams,
        rows,
        standings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::test_support::tiny_league;

    #[test]
    fn competition_ranking_handles_ties_and_turnovers() {
        assert_eq!(
            rank_values(&[10.0, 30.0, 20.0, 30.0], Category::Pts),
            vec![4, 1, 3, 1]
        );
        // Fewer turnovers rank higher.
        assert_eq!(rank_values(&[3.0, 1.0, 2.0], Category::To), vec![3, 1, 2]);
    }

    #[test]
    fn strength_buckets_for_twelve_teams() {
        assert_eq!(Strength::from_rank(1, 12), Strength::Strong);
        assert_eq!(Strength::from_rank(4, 12), Strength::Strong);
        assert_eq!(Strength::from_rank(5, 12), Strength::Middle);
        assert_eq!(Strength::from_rank(8, 12), Strength::Middle);
        assert_eq!(Strength::from_rank(9, 12), Strength::Weak);
    }

    #[test]
    fn report_ranks_my_team_against_league() {
        let data = tiny_league();
        // Week 2: Mine = p1 + fa1 = 45 pts/g, Rival = 55, Other = 10.
        let report = team_report(&data, "t1", 2).unwrap();
        let pts = report
            .rows
            .iter()
            .find(|r| r.category == Category::Pts)
            .unwrap();
        assert_eq!(pts.rank, 2);
        assert!((pts.value - 45.0).abs() < 1e-9);
        assert!((pts.league_best - 55.0).abs() < 1e-9);
        // Mine averages 4 TO/g vs Rival 6 and Other 2 -> rank 2 in TO.
        let to = report
            .rows
            .iter()
            .find(|r| r.category == Category::To)
            .unwrap();
        assert_eq!(to.rank, 2);
    }

    #[test]
    fn unknown_team_is_an_error() {
        assert!(matches!(
            team_report(&tiny_league(), "nope", 2),
            Err(Error::UnknownTeam(_))
        ));
    }
}
