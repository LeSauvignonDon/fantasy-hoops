//! Suggest free agents that help specific (usually weak) categories.

use crate::analysis::available::{available_players, AvailableFilter, SortBy};
use crate::analysis::valuation::Valuation;
use crate::models::{Category, CategoryMap, LeagueData, Player};

/// Weight given to non-target categories so we do not recommend a player who
/// helps blocks but tanks everything else. 0.0 = pure punt strategy.
pub const OTHER_CATEGORY_WEIGHT: f64 = 0.25;

/// A recommended pickup.
#[derive(Debug, Clone)]
pub struct Suggestion<'a> {
    pub player: &'a Player,
    /// Weighted score used for ordering.
    pub score: f64,
    /// Raw per-category z-scores, for display.
    pub z: CategoryMap<f64>,
}

/// Best free agents for `targets`, as of `week`.
pub fn suggest_free_agents<'a>(
    data: &'a LeagueData,
    week: u32,
    targets: &[Category],
    filter: &AvailableFilter,
    limit: usize,
) -> Vec<Suggestion<'a>> {
    let valuation = Valuation::compute(&data.players);
    let mut out: Vec<Suggestion<'a>> = available_players(data, week, filter, SortBy::Overall)
        .into_iter()
        .filter_map(|row| {
            let z = *valuation.z(&row.player.player_key)?;
            let score = Category::ALL
                .iter()
                .map(|&c| {
                    if targets.contains(&c) {
                        z[c]
                    } else {
                        OTHER_CATEGORY_WEIGHT * z[c]
                    }
                })
                .sum();
            Some(Suggestion {
                player: row.player,
                score,
                z,
            })
        })
        .collect();
    out.sort_by(|a, b| b.score.total_cmp(&a.score));
    out.truncate(limit);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::test_support::tiny_league;

    #[test]
    fn suggests_only_free_agents_best_first() {
        let data = tiny_league();
        let s = suggest_free_agents(&data, 2, &[Category::Pts], &AvailableFilter::default(), 10);
        let keys: Vec<_> = s.iter().map(|x| x.player.player_key.as_str()).collect();
        // p2 (10 pts) outscores fa2 (8 pts); rostered players never appear.
        assert_eq!(keys, vec!["p2", "fa2"]);
        assert!(s[0].score >= s[1].score);
    }

    #[test]
    fn respects_limit() {
        let data = tiny_league();
        assert_eq!(
            suggest_free_agents(&data, 2, &[], &AvailableFilter::default(), 1).len(),
            1
        );
    }
}
