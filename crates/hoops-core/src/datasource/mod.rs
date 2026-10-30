//! Pluggable ingestion.
//!
//! Analysis code never talks to Yahoo, files, or the network directly. It
//! asks a [`DataSource`] for a [`LeagueData`] and works on that. Swapping
//! where data comes from (JSON today, the Yahoo API once approved) is then a
//! one-line change in the CLI, and tests can feed hand-built data.
//!
//! Implementations:
//! * [`JsonSnapshotSource`] – reads a JSON file (fixtures, or files produced
//!   by the local laptop scraper). **Working.**
//! * [`YahooOAuthSource`] – read-only Yahoo Fantasy API via OAuth2. **Stub.**
//! * [`BoxScoreSource`] – public NBA box scores for weekly stats. **Stub.**

mod box_score;
mod json_snapshot;
mod yahoo;

pub use box_score::BoxScoreSource;
pub use json_snapshot::JsonSnapshotSource;
pub use yahoo::{YahooConfig, YahooOAuthSource};

use crate::error::Result;
use crate::models::LeagueData;

/// Anything that can produce a full snapshot of the league.
///
/// The trait is deliberately tiny: one method that returns owned data. It is
/// synchronous because the CLI runs one fetch at a time; an HTTP source can
/// use a blocking client internally (see LEARNING.md for going async).
///
/// `Send + Sync` is not required yet; add it if you start sharing sources
/// across threads.
pub trait DataSource {
    /// Human-readable name for logs and error messages.
    fn name(&self) -> &'static str;

    /// Fetch everything. Implementations should call
    /// [`LeagueData::validate`] before returning.
    fn load(&self) -> Result<LeagueData>;
}
