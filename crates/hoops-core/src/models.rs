//! Domain models: the vocabulary of the whole project.
//!
//! These are plain data structs with `serde` derives so the same types can be
//! read from JSON snapshots, written to SQLite, and passed to analysis code.
//! Keeping them free of I/O makes them easy to construct in unit tests.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::ops::{Add, AddAssign, Index, IndexMut};
use std::str::FromStr;

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};

/// Yahoo player key, e.g. `"nba.p.6583"` (fixtures use `"fake.p.1000"`).
///
/// A type alias keeps things simple while learning; see LEARNING.md for how
/// a "newtype" (`struct PlayerKey(String)`) would add compile-time safety.
pub type PlayerKey = String;
/// Yahoo team key, e.g. `"nba.l.106518.t.1"`.
pub type TeamKey = String;

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------

/// The nine head-to-head scoring categories in the league.
///
/// `#[derive(Copy)]` is fine because the enum is just a small tag; passing it
/// by value is cheaper and simpler than passing references.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Category {
    FgPct,
    FtPct,
    ThreePm,
    Pts,
    Reb,
    Ast,
    Stl,
    Blk,
    To,
}

impl Category {
    /// All categories in Yahoo's display order. Handy for loops.
    pub const ALL: [Category; 9] = [
        Category::FgPct,
        Category::FtPct,
        Category::ThreePm,
        Category::Pts,
        Category::Reb,
        Category::Ast,
        Category::Stl,
        Category::Blk,
        Category::To,
    ];

    /// Short label as shown on Yahoo.
    pub fn abbrev(self) -> &'static str {
        match self {
            Category::FgPct => "FG%",
            Category::FtPct => "FT%",
            Category::ThreePm => "3PTM",
            Category::Pts => "PTS",
            Category::Reb => "REB",
            Category::Ast => "AST",
            Category::Stl => "STL",
            Category::Blk => "BLK",
            Category::To => "TO",
        }
    }

    /// Turnovers are the only category where a smaller number wins.
    pub fn lower_is_better(self) -> bool {
        matches!(self, Category::To)
    }

    /// FG% and FT% are ratios, not counting stats. They must be computed from
    /// summed makes/attempts, never by averaging percentages.
    pub fn is_percentage(self) -> bool {
        matches!(self, Category::FgPct | Category::FtPct)
    }

    /// Returns `true` if value `a` beats value `b` in this category.
    pub fn beats(self, a: f64, b: f64) -> bool {
        if self.lower_is_better() {
            a < b
        } else {
            a > b
        }
    }

    /// Position of this category in [`Category::ALL`]; used by [`CategoryMap`].
    fn index(self) -> usize {
        self as usize
    }
}

impl fmt::Display for Category {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.abbrev())
    }
}

/// Parse `"fg%"`, `"FG"`, `"3ptm"`, `"3pm"`, `"to"`... (case-insensitive).
/// Implementing `FromStr` lets you write `"reb".parse::<Category>()` and lets
/// clap parse categories from the command line for free.
impl FromStr for Category {
    type Err = Error;

    fn from_str(s: &str) -> Result<Self> {
        let normalized = s.trim().to_ascii_uppercase();
        let cat = match normalized.as_str() {
            "FG%" | "FG" | "FGPCT" | "FG_PCT" => Category::FgPct,
            "FT%" | "FT" | "FTPCT" | "FT_PCT" => Category::FtPct,
            "3PTM" | "3PM" | "3P" | "3S" | "TPM" | "THREES" => Category::ThreePm,
            "PTS" | "POINTS" => Category::Pts,
            "REB" | "REBOUNDS" => Category::Reb,
            "AST" | "ASSISTS" => Category::Ast,
            "STL" | "STEALS" => Category::Stl,
            "BLK" | "BLOCKS" => Category::Blk,
            "TO" | "TOV" | "TURNOVERS" => Category::To,
            _ => return Err(Error::UnknownCategory(s.to_string())),
        };
        Ok(cat)
    }
}

/// A fixed-size map from every [`Category`] to a `T`.
///
/// Backed by an array, so lookups are just indexing: no hashing, no `Option`.
/// `map[Category::Reb]` works thanks to the `Index` impl below.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct CategoryMap<T>([T; 9]);

impl<T> CategoryMap<T> {
    /// Build a map by calling `f` once per category.
    pub fn from_fn(mut f: impl FnMut(Category) -> T) -> Self {
        CategoryMap(Category::ALL.map(&mut f))
    }

    /// Iterate `(category, &value)` pairs in display order.
    pub fn iter(&self) -> impl Iterator<Item = (Category, &T)> {
        Category::ALL.into_iter().zip(self.0.iter())
    }
}

impl<T> Index<Category> for CategoryMap<T> {
    type Output = T;
    fn index(&self, cat: Category) -> &T {
        &self.0[cat.index()]
    }
}

impl<T> IndexMut<Category> for CategoryMap<T> {
    fn index_mut(&mut self, cat: Category) -> &mut T {
        &mut self.0[cat.index()]
    }
}

// ---------------------------------------------------------------------------
// Stat lines
// ---------------------------------------------------------------------------

/// Box-score totals over some span (a season, a week, a single game).
///
/// Counting stats are `f64` so the same struct can also hold per-game
/// averages (e.g. 2.4 threes per game) without a second type.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct StatLine {
    /// Games played.
    pub gp: u32,
    pub fgm: f64,
    pub fga: f64,
    pub ftm: f64,
    pub fta: f64,
    /// Three-pointers made (3PTM).
    pub tpm: f64,
    pub pts: f64,
    pub reb: f64,
    pub ast: f64,
    pub stl: f64,
    pub blk: f64,
    /// Turnovers.
    pub tov: f64,
}

impl StatLine {
    /// Field-goal percentage, or `None` with zero attempts (avoids NaN).
    pub fn fg_pct(&self) -> Option<f64> {
        ratio(self.fgm, self.fga)
    }

    /// Free-throw percentage, or `None` with zero attempts.
    pub fn ft_pct(&self) -> Option<f64> {
        ratio(self.ftm, self.fta)
    }

    /// The value of one category. Percentages with no attempts read as 0.0.
    pub fn value(&self, cat: Category) -> f64 {
        match cat {
            Category::FgPct => self.fg_pct().unwrap_or(0.0),
            Category::FtPct => self.ft_pct().unwrap_or(0.0),
            Category::ThreePm => self.tpm,
            Category::Pts => self.pts,
            Category::Reb => self.reb,
            Category::Ast => self.ast,
            Category::Stl => self.stl,
            Category::Blk => self.blk,
            Category::To => self.tov,
        }
    }

    /// Per-game averages. A player with zero games returns all zeros.
    /// The result has `gp = 1` so it reads as "one average game".
    pub fn per_game(&self) -> StatLine {
        if self.gp == 0 {
            return StatLine::default();
        }
        let g = f64::from(self.gp);
        StatLine {
            gp: 1,
            fgm: self.fgm / g,
            fga: self.fga / g,
            ftm: self.ftm / g,
            fta: self.fta / g,
            tpm: self.tpm / g,
            pts: self.pts / g,
            reb: self.reb / g,
            ast: self.ast / g,
            stl: self.stl / g,
            blk: self.blk / g,
            tov: self.tov / g,
        }
    }
}

fn ratio(made: f64, attempts: f64) -> Option<f64> {
    (attempts > 0.0).then(|| made / attempts)
}

/// `a + b` adds every field. Because percentages are derived from makes and
/// attempts, summing stat lines and then calling `fg_pct()` gives the correct
/// *team* percentage automatically.
impl Add for StatLine {
    type Output = StatLine;
    fn add(mut self, rhs: StatLine) -> StatLine {
        self += rhs;
        self
    }
}

impl AddAssign for StatLine {
    fn add_assign(&mut self, rhs: StatLine) {
        self.gp += rhs.gp;
        self.fgm += rhs.fgm;
        self.fga += rhs.fga;
        self.ftm += rhs.ftm;
        self.fta += rhs.fta;
        self.tpm += rhs.tpm;
        self.pts += rhs.pts;
        self.reb += rhs.reb;
        self.ast += rhs.ast;
        self.stl += rhs.stl;
        self.blk += rhs.blk;
        self.tov += rhs.tov;
    }
}

/// Lets you write `lines.iter().copied().sum::<StatLine>()`.
impl std::iter::Sum for StatLine {
    fn sum<I: Iterator<Item = StatLine>>(iter: I) -> StatLine {
        iter.fold(StatLine::default(), Add::add)
    }
}

// ---------------------------------------------------------------------------
// League entities
// ---------------------------------------------------------------------------

/// League-level settings.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct League {
    pub league_key: String,
    pub name: String,
    pub num_teams: u32,
    /// Yahoo's per-manager weekly add limit (5 in this league).
    pub max_weekly_adds: u32,
    pub current_week: u32,
    /// Which team is "mine": the default for reports.
    pub my_team_key: TeamKey,
}

/// One fantasy team (manager).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Team {
    pub team_key: TeamKey,
    pub name: String,
    pub manager: String,
}

/// An NBA player and their season-to-date totals.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Player {
    pub player_key: PlayerKey,
    pub name: String,
    pub nba_team: String,
    /// Eligible positions, e.g. `["PG", "SG"]`.
    pub positions: Vec<String>,
    /// Season-to-date totals (not averages).
    pub season: StatLine,
}

/// Who was on a fantasy roster at the end of a given week.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RosterSnapshot {
    pub week: u32,
    pub team_key: TeamKey,
    pub player_keys: Vec<PlayerKey>,
}

/// Add or drop. `serde(rename_all)` maps `Add` <-> `"add"` in JSON.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TransactionKind {
    Add,
    Drop,
}

impl TransactionKind {
    /// Lowercase string form, used for the SQLite `kind` column.
    pub fn as_str(self) -> &'static str {
        match self {
            TransactionKind::Add => "add",
            TransactionKind::Drop => "drop",
        }
    }
}

impl FromStr for TransactionKind {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "add" => Ok(TransactionKind::Add),
            "drop" => Ok(TransactionKind::Drop),
            other => Err(Error::InvalidData(format!(
                "unknown transaction kind '{other}'"
            ))),
        }
    }
}

/// A single roster move. Yahoo bundles add+drop into one transaction; we
/// store each half separately because analysis treats them independently.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Transaction {
    pub id: i64,
    pub week: u32,
    /// RFC 3339 timestamp as text (kept as a string to avoid a date crate).
    pub timestamp: String,
    pub team_key: TeamKey,
    pub kind: TransactionKind,
    pub player_key: PlayerKey,
}

/// One player's totals for one fantasy week.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WeeklyPlayerStats {
    pub week: u32,
    pub player_key: PlayerKey,
    pub stats: StatLine,
}

/// A head-to-head pairing for a week.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Matchup {
    pub week: u32,
    pub team_a: TeamKey,
    pub team_b: TeamKey,
}

impl Matchup {
    /// The opponent of `team`, if `team` is in this matchup.
    pub fn opponent_of(&self, team: &str) -> Option<&TeamKey> {
        if self.team_a == team {
            Some(&self.team_b)
        } else if self.team_b == team {
            Some(&self.team_a)
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// LeagueData: everything a DataSource produces
// ---------------------------------------------------------------------------

/// A complete picture of the league at some point in time.
///
/// Every [`crate::datasource::DataSource`] returns one of these, and every
/// analysis function reads from one. This is the "seam" that keeps
/// ingestion and analysis independent of each other.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LeagueData {
    pub league: League,
    pub teams: Vec<Team>,
    pub players: Vec<Player>,
    pub rosters: Vec<RosterSnapshot>,
    #[serde(default)]
    pub transactions: Vec<Transaction>,
    #[serde(default)]
    pub weekly_stats: Vec<WeeklyPlayerStats>,
    #[serde(default)]
    pub matchups: Vec<Matchup>,
}

impl LeagueData {
    /// Look up a player by key. Linear scan: fine for a few hundred players.
    pub fn player(&self, key: &str) -> Option<&Player> {
        self.players.iter().find(|p| p.player_key == key)
    }

    /// Look up a team by key.
    pub fn team(&self, key: &str) -> Option<&Team> {
        self.teams.iter().find(|t| t.team_key == key)
    }

    /// Resolve user input to a team: exact key, exact name (case-insensitive),
    /// or a unique case-insensitive substring of the name.
    pub fn find_team(&self, query: &str) -> Result<&Team> {
        if let Some(t) = self.team(query) {
            return Ok(t);
        }
        let q = query.to_lowercase();
        if let Some(t) = self.teams.iter().find(|t| t.name.to_lowercase() == q) {
            return Ok(t);
        }
        let mut hits = self
            .teams
            .iter()
            .filter(|t| t.name.to_lowercase().contains(&q));
        match (hits.next(), hits.next()) {
            (Some(t), None) => Ok(t),
            _ => Err(Error::UnknownTeam(query.to_string())),
        }
    }

    /// The team marked as "mine" in league settings.
    pub fn my_team(&self) -> Result<&Team> {
        self.team(&self.league.my_team_key)
            .ok_or_else(|| Error::UnknownTeam(self.league.my_team_key.clone()))
    }

    /// The most recent week that has any roster snapshot.
    pub fn latest_roster_week(&self) -> Option<u32> {
        self.rosters.iter().map(|r| r.week).max()
    }

    /// A team's roster as of the end of `week`: the newest snapshot whose
    /// week is `<= week`. Returns `None` if no snapshot exists yet.
    pub fn roster_at(&self, team_key: &str, week: u32) -> Option<&RosterSnapshot> {
        self.rosters
            .iter()
            .filter(|r| r.team_key == team_key && r.week <= week)
            .max_by_key(|r| r.week)
    }

    /// Every player key on any fantasy roster as of `week`.
    pub fn rostered_keys(&self, week: u32) -> HashSet<&str> {
        self.teams
            .iter()
            .filter_map(|t| self.roster_at(&t.team_key, week))
            .flat_map(|r| r.player_keys.iter().map(String::as_str))
            .collect()
    }

    /// Weekly stats for `week`, indexed by player key for fast lookup.
    pub fn weekly_stats_index(&self, week: u32) -> HashMap<&str, &StatLine> {
        self.weekly_stats
            .iter()
            .filter(|w| w.week == week)
            .map(|w| (w.player_key.as_str(), &w.stats))
            .collect()
    }

    /// Sanity-check cross references. Data sources call this after loading
    /// so problems surface early with a clear message.
    pub fn validate(&self) -> Result<()> {
        let player_keys: HashSet<&str> =
            self.players.iter().map(|p| p.player_key.as_str()).collect();
        let team_keys: HashSet<&str> = self.teams.iter().map(|t| t.team_key.as_str()).collect();

        if player_keys.len() != self.players.len() {
            return Err(Error::InvalidData("duplicate player_key".into()));
        }
        if !team_keys.contains(self.league.my_team_key.as_str()) {
            return Err(Error::InvalidData(format!(
                "my_team_key '{}' is not a team in the league",
                self.league.my_team_key
            )));
        }
        for r in &self.rosters {
            if !team_keys.contains(r.team_key.as_str()) {
                return Err(Error::InvalidData(format!(
                    "roster for unknown team {}",
                    r.team_key
                )));
            }
            if let Some(p) = r
                .player_keys
                .iter()
                .find(|k| !player_keys.contains(k.as_str()))
            {
                return Err(Error::InvalidData(format!(
                    "roster {} week {} lists unknown player {p}",
                    r.team_key, r.week
                )));
            }
        }
        for t in &self.transactions {
            if !team_keys.contains(t.team_key.as_str())
                || !player_keys.contains(t.player_key.as_str())
            {
                return Err(Error::InvalidData(format!(
                    "transaction {} references unknown team or player",
                    t.id
                )));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line(fgm: f64, fga: f64, pts: f64, tov: f64) -> StatLine {
        StatLine {
            gp: 2,
            fgm,
            fga,
            pts,
            tov,
            ..StatLine::default()
        }
    }

    #[test]
    fn category_parsing_is_case_insensitive_and_has_aliases() {
        assert_eq!("fg%".parse::<Category>().unwrap(), Category::FgPct);
        assert_eq!("3pm".parse::<Category>().unwrap(), Category::ThreePm);
        assert_eq!("TOV".parse::<Category>().unwrap(), Category::To);
        assert!("dunks".parse::<Category>().is_err());
    }

    #[test]
    fn every_category_round_trips_through_its_abbreviation() {
        for cat in Category::ALL {
            assert_eq!(cat.abbrev().parse::<Category>().unwrap(), cat);
        }
    }

    #[test]
    fn turnovers_lower_is_better() {
        assert!(Category::To.beats(10.0, 12.0));
        assert!(!Category::To.beats(12.0, 10.0));
        assert!(Category::Pts.beats(12.0, 10.0));
        assert!(!Category::Pts.beats(10.0, 10.0), "ties do not beat");
    }

    #[test]
    fn percentages_come_from_summed_makes_and_attempts() {
        // 1/1 (100%) plus 4/9 (44%) must be 5/10 = 50%, not the 72% average.
        let total = line(1.0, 1.0, 0.0, 0.0) + line(4.0, 9.0, 0.0, 0.0);
        assert!((total.fg_pct().unwrap() - 0.5).abs() < 1e-9);
    }

    #[test]
    fn zero_attempts_is_none_not_nan() {
        assert_eq!(StatLine::default().fg_pct(), None);
        assert_eq!(StatLine::default().value(Category::FtPct), 0.0);
    }

    #[test]
    fn per_game_divides_counting_stats() {
        let pg = line(10.0, 20.0, 30.0, 4.0).per_game();
        assert_eq!(pg.gp, 1);
        assert_eq!(pg.pts, 15.0);
        assert_eq!(pg.tov, 2.0);
        assert_eq!(StatLine::default().per_game(), StatLine::default());
    }

    #[test]
    fn stat_lines_sum() {
        let total: StatLine = [line(1.0, 2.0, 3.0, 1.0); 3].into_iter().sum();
        assert_eq!(total.gp, 6);
        assert_eq!(total.pts, 9.0);
    }

    #[test]
    fn category_map_indexing() {
        let mut m = CategoryMap::from_fn(|c| c.abbrev().len());
        assert_eq!(m[Category::ThreePm], 4);
        m[Category::To] = 99;
        assert_eq!(m[Category::To], 99);
        assert_eq!(m.iter().count(), 9);
    }

    #[test]
    fn matchup_opponent() {
        let m = Matchup {
            week: 1,
            team_a: "a".into(),
            team_b: "b".into(),
        };
        assert_eq!(m.opponent_of("a").map(String::as_str), Some("b"));
        assert_eq!(m.opponent_of("b").map(String::as_str), Some("a"));
        assert_eq!(m.opponent_of("c"), None);
    }
}
