//! Player valuation with per-category z-scores.
//!
//! A z-score says how many standard deviations a player is above the mean of
//! a pool: `z = (x - mean) / stddev`. Summing z-scores across categories is
//! the classic way to rank players for 9-cat leagues.
//!
//! Two twists:
//! * **TO** is negated, so a positive z is always "good".
//! * **FG% / FT%** use *impact* instead of raw percentage:
//!   `makes - pool_pct * attempts`. A 60% shooter on 2 attempts barely moves a
//!   team's FG%; a 52% shooter on 18 attempts moves it a lot.

use std::collections::HashMap;

use crate::models::{Category, CategoryMap, Player, PlayerKey, StatLine};

/// Per-category z-scores for a pool of players, based on per-game averages.
#[derive(Debug, Clone, Default)]
pub struct Valuation {
    z: HashMap<PlayerKey, CategoryMap<f64>>,
}

impl Valuation {
    /// Compute z-scores for every player in `players` relative to that same
    /// pool. Players with zero games played get all-zero scores.
    ///
    /// `impl IntoIterator<Item = &'a Player>` accepts a `Vec<&Player>`, a
    /// slice iterator, a filtered iterator...: whatever the caller has.
    pub fn compute<'a>(players: impl IntoIterator<Item = &'a Player>) -> Self {
        let pool: Vec<(&PlayerKey, StatLine)> = players
            .into_iter()
            .map(|p| (&p.player_key, p.season.per_game()))
            .collect();
        let active: Vec<StatLine> = pool
            .iter()
            .filter(|(_, pg)| pg.gp > 0)
            .map(|(_, pg)| *pg)
            .collect();

        // Pool-wide shooting percentages: total makes / total attempts.
        let totals: StatLine = active.iter().copied().sum();
        let fg_pct = totals.fg_pct().unwrap_or(0.0);
        let ft_pct = totals.ft_pct().unwrap_or(0.0);

        // The raw number we z-score for each category.
        let raw = |pg: &StatLine, cat: Category| -> f64 {
            match cat {
                Category::FgPct => pg.fgm - fg_pct * pg.fga,
                Category::FtPct => pg.ftm - ft_pct * pg.fta,
                other => pg.value(other),
            }
        };

        // Mean and (population) standard deviation per category.
        let stats = CategoryMap::from_fn(|cat| {
            let xs: Vec<f64> = active.iter().map(|pg| raw(pg, cat)).collect();
            mean_std(&xs)
        });

        let z = pool
            .into_iter()
            .map(|(key, pg)| {
                let scores = CategoryMap::from_fn(|cat| {
                    if pg.gp == 0 {
                        return 0.0;
                    }
                    let (mean, std) = stats[cat];
                    let z = if std > 0.0 {
                        (raw(&pg, cat) - mean) / std
                    } else {
                        0.0
                    };
                    if cat.lower_is_better() {
                        -z
                    } else {
                        z
                    }
                });
                (key.clone(), scores)
            })
            .collect();

        Valuation { z }
    }

    /// Per-category z-scores for one player (if they were in the pool).
    pub fn z(&self, player_key: &str) -> Option<&CategoryMap<f64>> {
        self.z.get(player_key)
    }

    /// Sum of z-scores over `cats` (pass `&Category::ALL` for overall value).
    pub fn total(&self, player_key: &str, cats: &[Category]) -> f64 {
        self.z(player_key)
            .map(|z| cats.iter().map(|&c| z[c]).sum())
            .unwrap_or(0.0)
    }
}

/// Mean and population standard deviation. Empty input gives `(0, 0)`.
fn mean_std(xs: &[f64]) -> (f64, f64) {
    if xs.is_empty() {
        return (0.0, 0.0);
    }
    let n = xs.len() as f64;
    let mean = xs.iter().sum::<f64>() / n;
    let var = xs.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n;
    (mean, var.sqrt())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::test_support::player;

    #[test]
    fn mean_std_basics() {
        assert_eq!(mean_std(&[]), (0.0, 0.0));
        let (m, s) = mean_std(&[2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]);
        assert_eq!(m, 5.0);
        assert_eq!(s, 2.0);
    }

    #[test]
    fn better_scorer_has_higher_points_z_and_turnovers_are_inverted() {
        let scorer = player("a", 30.0, 2.0);
        let bench = player("b", 10.0, 4.0);
        let v = Valuation::compute([&scorer, &bench]);
        assert!(v.z("a").unwrap()[Category::Pts] > 0.0);
        assert!(v.z("b").unwrap()[Category::Pts] < 0.0);
        // "a" commits fewer turnovers, so its TO z must be positive.
        assert!(v.z("a").unwrap()[Category::To] > 0.0);
        assert!(v.total("a", &Category::ALL) > v.total("b", &Category::ALL));
    }

    #[test]
    fn unknown_player_scores_zero() {
        let v = Valuation::compute(std::iter::empty());
        assert_eq!(v.total("nobody", &Category::ALL), 0.0);
    }
}
