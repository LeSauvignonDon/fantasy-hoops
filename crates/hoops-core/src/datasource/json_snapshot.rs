//! A [`DataSource`] backed by a JSON file on disk.
//!
//! The file format is exactly the serde representation of [`LeagueData`]
//! (see `fixtures/sample_snapshot.json`). A local scraper can write this
//! format and the rest of the tool does not need to know or care.

use std::fs;
use std::path::{Path, PathBuf};

use super::DataSource;
use crate::error::{Error, Result};
use crate::models::LeagueData;

/// Reads a [`LeagueData`] snapshot from a JSON file.
#[derive(Debug, Clone)]
pub struct JsonSnapshotSource {
    path: PathBuf,
}

impl JsonSnapshotSource {
    /// `impl AsRef<Path>` accepts `&str`, `String`, `PathBuf`, `&Path`...
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self {
            path: path.as_ref().to_path_buf(),
        }
    }

    /// Parse a snapshot from an in-memory string (useful in tests).
    pub fn parse(json: &str) -> Result<LeagueData> {
        let data: LeagueData = serde_json::from_str(json)?;
        data.validate()?;
        Ok(data)
    }
}

impl DataSource for JsonSnapshotSource {
    fn name(&self) -> &'static str {
        "json-snapshot"
    }

    fn load(&self) -> Result<LeagueData> {
        // `map_err` attaches the path so "file not found" says *which* file.
        let text = fs::read_to_string(&self.path).map_err(|source| Error::Io {
            path: self.path.clone(),
            source,
        })?;
        Self::parse(&text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Path to the shared fixture, relative to this crate's Cargo.toml.
    /// `env!("CARGO_MANIFEST_DIR")` is set by Cargo at compile time.
    fn fixture() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/sample_snapshot.json")
    }

    #[test]
    fn loads_sample_fixture() {
        let data = JsonSnapshotSource::new(fixture())
            .load()
            .expect("fixture loads");
        assert_eq!(data.teams.len(), 12);
        assert_eq!(data.league.max_weekly_adds, 5);
        assert_eq!(data.my_team().unwrap().name, "Cripples and Bastards");
    }

    #[test]
    fn missing_file_reports_path() {
        let err = JsonSnapshotSource::new("/no/such/file.json")
            .load()
            .unwrap_err();
        assert!(err.to_string().contains("/no/such/file.json"));
    }

    #[test]
    fn rejects_rosters_with_unknown_players() {
        let json = r#"{
            "league": {"league_key": "x", "name": "x", "num_teams": 1,
                       "max_weekly_adds": 5, "current_week": 1, "my_team_key": "t1"},
            "teams": [{"team_key": "t1", "name": "T", "manager": "M"}],
            "players": [],
            "rosters": [{"week": 1, "team_key": "t1", "player_keys": ["ghost"]}]
        }"#;
        let err = JsonSnapshotSource::parse(json).unwrap_err();
        assert!(matches!(err, Error::InvalidData(_)), "got {err}");
    }
}
