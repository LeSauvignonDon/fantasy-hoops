//! Crate-wide error type.
//!
//! Libraries usually define a concrete error enum (here via the `thiserror`
//! derive macro) so callers can `match` on what went wrong. Applications such
//! as the CLI typically wrap these in `anyhow::Error` for easy reporting.

use std::path::PathBuf;

/// Everything that can go wrong inside `hoops-core`.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// Reading a file failed. We keep the path so the message is actionable.
    #[error("could not read {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },

    /// A JSON snapshot did not match the expected shape.
    #[error("invalid JSON snapshot: {0}")]
    Json(#[from] serde_json::Error),

    /// Any SQLite failure. `#[from]` lets `?` convert `rusqlite::Error` automatically.
    #[error("database error: {0}")]
    Db(#[from] rusqlite::Error),

    /// Data loaded fine but is internally inconsistent (e.g. a roster refers
    /// to a player that does not exist).
    #[error("inconsistent league data: {0}")]
    InvalidData(String),

    /// A team key or name that does not match any team in the league.
    #[error("unknown team: {0}")]
    UnknownTeam(String),

    /// A category abbreviation we could not parse (e.g. from the command line).
    #[error(
        "unknown category '{0}' (expected one of FG%, FT%, 3PTM, PTS, REB, AST, STL, BLK, TO)"
    )]
    UnknownCategory(String),

    /// A data source that exists as a stub but is not wired up yet.
    #[error("data source '{source_name}' is not implemented yet: {detail}")]
    NotImplemented {
        source_name: &'static str,
        detail: &'static str,
    },
}

/// Shorthand used throughout the crate: `Result<T>` means `Result<T, Error>`.
pub type Result<T> = std::result::Result<T, Error>;
