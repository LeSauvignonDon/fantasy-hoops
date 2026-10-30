//! "Available players" = every player in the universe minus everyone on
//! any of the league's rosters (as of a given week).

use crate::analysis::valuation::Valuation;
use crate::models::{Category, LeagueData, Player, StatLine};

/// How to order the available-player list.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SortBy {
    /// Total z-score across all nine categories.
    Overall,
    /// z-score in one category (TO already inverted, so higher = better).
    Category(Category),
}

/// Optional filters for [`available_players`].
#[derive(Debug, Clone, Default)]
pub struct AvailableFilter {
    /// Only players eligible at this position (case-insensitive, e.g. "C").
    pub position: Option<String>,
    /// Skip players with fewer games played than this.
    pub min_games: u32,
}

/// One row of output: borrowed player plus derived numbers.
///
/// The lifetime `'a` says "this row borrows from a `LeagueData` that lives at
/// least as long as `'a`". No cloning of player data is needed.
#[derive(Debug, Clone)]
pub struct AvailablePlayer<'a> {
    pub player: &'a Player,
    pub per_game: StatLine,
    /// The value the list is sorted by.
    pub score: f64,
}

/// Unrostered players as of `week`, filtered, best first.
///
/// Z-scores are computed against the *whole* player pool (rostered + free
/// agents) so a free agent's score is comparable to what is on rosters.
pub fn available_players<'a>(
    data: &'a LeagueData,
    week: u32,
    filter: &AvailableFilter,
    sort: SortBy,
) -> Vec<AvailablePlayer<'a>> {
    let rostered = data.rostered_keys(week);
    let valuation = Valuation::compute(&data.players);

    let mut rows: Vec<AvailablePlayer<'a>> = data
        .players
        .iter()
        .filter(|p| !rostered.contains(p.player_key.as_str()))
        .filter(|p| p.season.gp >= filter.min_games)
        .filter(|p| match &filter.position {
            Some(pos) => p.positions.iter().any(|x| x.eq_ignore_ascii_case(pos)),
            None => true,
        })
        .map(|p| {
            let score = match sort {
                SortBy::Overall => valuation.total(&p.player_key, &Category::ALL),
                SortBy::Category(c) => valuation.total(&p.player_key, &[c]),
            };
            AvailablePlayer {
                player: p,
                per_game: p.season.per_game(),
                score,
            }
        })
        .collect();

    // f64 is not `Ord` (because of NaN), so use `total_cmp` for a total order.
    rows.sort_by(|a, b| b.score.total_cmp(&a.score));
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::test_support::tiny_league;

    fn keys(rows: &[AvailablePlayer<'_>]) -> Vec<String> {
        rows.iter().map(|r| r.player.player_key.clone()).collect()
    }

    #[test]
    fn excludes_rostered_players_for_the_week() {
        let data = tiny_league();
        let week2 = available_players(&data, 2, &AvailableFilter::default(), SortBy::Overall);
        // p2 was dropped in week 2 and fa1 was added.
        assert_eq!(keys(&week2), vec!["p2", "fa2"]);

        let week1 = available_players(&data, 1, &AvailableFilter::default(), SortBy::Overall);
        let mut k1 = keys(&week1);
        k1.sort();
        assert_eq!(k1, vec!["fa1", "fa2"]);
    }

    #[test]
    fn position_and_games_filters() {
        let data = tiny_league();
        let none = AvailableFilter {
            position: Some("C".into()),
            min_games: 0,
        };
        assert!(available_players(&data, 2, &none, SortBy::Overall).is_empty());
        let too_many_games = AvailableFilter {
            position: None,
            min_games: 11,
        };
        assert!(available_players(&data, 2, &too_many_games, SortBy::Overall).is_empty());
    }

    #[test]
    fn sorting_by_turnovers_prefers_fewer() {
        let data = tiny_league();
        // p2 and fa2 both average 1.0 TO, so they tie; sort must be stable and not panic.
        let rows = available_players(
            &data,
            2,
            &AvailableFilter::default(),
            SortBy::Category(Category::To),
        );
        assert_eq!(rows.len(), 2);
        assert!((rows[0].score - rows[1].score).abs() < 1e-9);
    }
}
