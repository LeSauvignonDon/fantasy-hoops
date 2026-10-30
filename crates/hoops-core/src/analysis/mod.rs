//! Fantasy analysis. Every function here is pure: it takes a
//! [`crate::LeagueData`] (plus options) and returns plain structs, leaving
//! printing to the caller. That makes each piece trivially unit-testable.

pub mod add_impact;
pub mod available;
pub mod suggest;
pub mod team_report;
pub mod valuation;

#[cfg(test)]
pub(crate) mod test_support;
