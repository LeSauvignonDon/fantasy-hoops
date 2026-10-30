//! STUB: public NBA box-score source.
//!
//! Yahoo does not expose per-player *weekly* stat lines cheaply, so the plan
//! is to compute them from public box scores: fetch each game's box score
//! for the days in a fantasy week, sum per player, and emit
//! [`crate::models::WeeklyPlayerStats`]. Player identity then needs a mapping
//! from box-score player ids to Yahoo player keys (by name + team is a good
//! first approximation; store the mapping in SQLite).
//!
//! This source alone cannot produce rosters or transactions, so in practice
//! it will be *merged* with another source (see LEARNING.md, "Combining
//! sources"). For now `load` returns [`Error::NotImplemented`].

use super::DataSource;
use crate::error::{Error, Result};
use crate::models::LeagueData;

/// Public box-score data source (not implemented yet).
#[derive(Debug, Clone, Default)]
pub struct BoxScoreSource {
    /// Base URL of whichever public box-score provider is chosen.
    pub base_url: Option<String>,
}

impl DataSource for BoxScoreSource {
    fn name(&self) -> &'static str {
        "box-score"
    }

    fn load(&self) -> Result<LeagueData> {
        Err(Error::NotImplemented {
            source_name: self.name(),
            detail: "public box-score ingestion is planned but not written",
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_a_clear_stub() {
        let err = BoxScoreSource::default().load().unwrap_err();
        assert!(err.to_string().contains("box-score"));
    }
}
