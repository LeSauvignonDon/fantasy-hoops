//! How did this week's adds/drops change the weekly matchup?
//!
//! We compare two rosters for the same week:
//! * **actual** – the end-of-week roster snapshot;
//! * **without moves** – that roster with this week's transactions undone
//!   (walk them newest-first: un-add = remove, un-drop = put back).
//!
//! Each roster's weekly totals are the sum of its players' weekly stat lines,
//! and both are scored against the opponent's actual totals.
//!
//! Known simplification: weekly stats cover the whole week, so an added
//! player gets credit for games played *before* the add (and a dropped one
//! for games after the drop). Daily stats would fix this; see LEARNING.md.

use std::collections::BTreeSet;

use crate::error::{Error, Result};
use crate::models::{
    Category, CategoryMap, LeagueData, PlayerKey, StatLine, TeamKey, TransactionKind,
};

/// Result of one category comparison, from "our" point of view.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Outcome {
    Win,
    Loss,
    #[default]
    Tie,
}

/// Wins/losses/ties over the nine categories.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct CategoryRecord {
    pub wins: u32,
    pub losses: u32,
    pub ties: u32,
    pub per_category: CategoryMap<Outcome>,
}

impl CategoryRecord {
    /// Score `ours` against `theirs` in every category.
    pub fn compare(ours: &StatLine, theirs: &StatLine) -> Self {
        let mut rec = CategoryRecord::default();
        for cat in Category::ALL {
            let (a, b) = (ours.value(cat), theirs.value(cat));
            let outcome = if cat.beats(a, b) {
                rec.wins += 1;
                Outcome::Win
            } else if cat.beats(b, a) {
                rec.losses += 1;
                Outcome::Loss
            } else {
                rec.ties += 1;
                Outcome::Tie
            };
            rec.per_category[cat] = outcome;
        }
        rec
    }
}

/// Everything the `add-impact` command prints.
#[derive(Debug, Clone)]
pub struct AddDropImpact {
    pub team_key: TeamKey,
    pub week: u32,
    pub adds: Vec<PlayerKey>,
    pub drops: Vec<PlayerKey>,
    pub adds_limit: u32,
    pub actual: StatLine,
    pub without_moves: StatLine,
    pub opponent: Option<(TeamKey, StatLine)>,
}

impl AddDropImpact {
    /// Records vs the opponent: `(actual, without_moves)`, if there was a matchup.
    pub fn records(&self) -> Option<(CategoryRecord, CategoryRecord)> {
        self.opponent.as_ref().map(|(_, opp)| {
            (
                CategoryRecord::compare(&self.actual, opp),
                CategoryRecord::compare(&self.without_moves, opp),
            )
        })
    }
}

/// Sum weekly stat lines for a set of player keys. Missing stats count as zero.
pub fn weekly_totals<'a>(
    data: &LeagueData,
    week: u32,
    players: impl IntoIterator<Item = &'a PlayerKey>,
) -> StatLine {
    let index = data.weekly_stats_index(week);
    players
        .into_iter()
        .filter_map(|k| index.get(k.as_str()).copied().copied())
        .sum()
}

/// Analyse `team_key`'s transactions in `week`.
pub fn add_drop_impact(data: &LeagueData, team_key: &str, week: u32) -> Result<AddDropImpact> {
    if data.team(team_key).is_none() {
        return Err(Error::UnknownTeam(team_key.to_string()));
    }
    let roster = data.roster_at(team_key, week).ok_or_else(|| {
        Error::InvalidData(format!(
            "no roster snapshot for {team_key} at or before week {week}"
        ))
    })?;

    // This week's moves for the team, newest first.
    let mut moves: Vec<_> = data
        .transactions
        .iter()
        .filter(|t| t.team_key == team_key && t.week == week)
        .collect();
    moves.sort_by(|a, b| (&b.timestamp, b.id).cmp(&(&a.timestamp, a.id)));

    // BTreeSet: a sorted set, so output order is deterministic.
    let actual_set: BTreeSet<PlayerKey> = roster.player_keys.iter().cloned().collect();
    let mut undone = actual_set.clone();
    let (mut adds, mut drops) = (Vec::new(), Vec::new());
    for t in &moves {
        match t.kind {
            TransactionKind::Add => {
                undone.remove(&t.player_key);
                adds.push(t.player_key.clone());
            }
            TransactionKind::Drop => {
                undone.insert(t.player_key.clone());
                drops.push(t.player_key.clone());
            }
        }
    }
    // We collected newest-first; present them in chronological order.
    adds.reverse();
    drops.reverse();

    let opponent = data
        .matchups
        .iter()
        .filter(|m| m.week == week)
        .find_map(|m| m.opponent_of(team_key))
        .map(|opp| {
            let opp_roster = data
                .roster_at(opp, week)
                .map(|r| r.player_keys.as_slice())
                .unwrap_or_default();
            (opp.clone(), weekly_totals(data, week, opp_roster))
        });

    Ok(AddDropImpact {
        team_key: team_key.to_string(),
        week,
        adds,
        drops,
        adds_limit: data.league.max_weekly_adds,
        actual: weekly_totals(data, week, &actual_set),
        without_moves: weekly_totals(data, week, &undone),
        opponent,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::test_support::tiny_league;

    #[test]
    fn compare_counts_turnovers_correctly() {
        let ours = StatLine {
            gp: 1,
            pts: 100.0,
            tov: 5.0,
            ..Default::default()
        };
        let theirs = StatLine {
            gp: 1,
            pts: 90.0,
            tov: 10.0,
            ..Default::default()
        };
        let rec = CategoryRecord::compare(&ours, &theirs);
        assert_eq!(rec.per_category[Category::Pts], Outcome::Win);
        assert_eq!(
            rec.per_category[Category::To],
            Outcome::Win,
            "fewer TO wins"
        );
        assert_eq!(rec.wins + rec.losses + rec.ties, 9);
    }

    #[test]
    fn undoes_this_weeks_moves() {
        let data = tiny_league();
        let impact = add_drop_impact(&data, "t1", 2).unwrap();
        assert_eq!(impact.adds, vec!["fa1"]);
        assert_eq!(impact.drops, vec!["p2"]);
        // 3 games each: actual = (20 + 25) * 3, without = (20 + 10) * 3.
        assert!((impact.actual.pts - 135.0).abs() < 1e-9);
        assert!((impact.without_moves.pts - 90.0).abs() < 1e-9);
        let (opp, opp_totals) = impact.opponent.clone().unwrap();
        assert_eq!(opp, "t2");
        assert!((opp_totals.pts - 165.0).abs() < 1e-9);
    }

    #[test]
    fn week_without_moves_is_identical() {
        let impact = add_drop_impact(&tiny_league(), "t1", 1).unwrap();
        assert!(impact.adds.is_empty() && impact.drops.is_empty());
        assert_eq!(impact.actual, impact.without_moves);
        assert!(
            impact.opponent.is_none(),
            "no week-1 matchup in the tiny league"
        );
    }
}
