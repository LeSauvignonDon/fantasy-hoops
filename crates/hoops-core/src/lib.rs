//! # hoops-core
//!
//! Library crate for analysing a Yahoo head-to-head categories fantasy
//! basketball league. It has no CLI or I/O opinions of its own beyond the
//! data sources and SQLite store; the `hoops-cli` crate is a thin front end.
//!
//! Module map (see `LEARNING.md` at the repo root for the long version):
//!
//! * [`models`]     – plain data types: categories, stat lines, players, rosters...
//! * [`datasource`] – the [`datasource::DataSource`] trait plus implementations
//!   (JSON snapshot today; Yahoo OAuth2 and public box scores are stubs).
//! * [`db`]         – SQLite persistence with versioned migrations.
//! * [`analysis`]   – the actual fantasy logic: available players, team
//!   category ranks, add/drop impact, free-agent suggestions.
//! * [`error`]      – the crate-wide [`Error`] type and [`Result`] alias.

pub mod analysis;
pub mod datasource;
pub mod db;
pub mod error;
pub mod models;

// Re-export the most commonly used items so callers can write
// `hoops_core::Category` instead of `hoops_core::models::Category`.
pub use error::{Error, Result};
pub use models::{Category, LeagueData, Player, StatLine, Team};
