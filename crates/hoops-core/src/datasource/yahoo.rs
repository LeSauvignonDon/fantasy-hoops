//! STUB: read-only Yahoo Fantasy Sports API source (OAuth2).
//!
//! Yahoo API approval is pending, so this compiles and documents the plan but
//! returns [`Error::NotImplemented`]. When access is granted:
//!
//! 1. Register an app at <https://developer.yahoo.com/apps/> with the
//!    *Fantasy Sports - Read* permission. Keep the client secret in an env
//!    var (never in the repo; `.gitignore` already excludes token files).
//! 2. OAuth2 authorization-code flow: open
//!    `https://api.login.yahoo.com/oauth2/request_auth`, exchange the code at
//!    `https://api.login.yahoo.com/oauth2/get_token`, store the refresh token
//!    at [`YahooConfig::token_path`], refresh when the access token expires.
//! 3. Endpoints (append `?format=json`), base
//!    `https://fantasysports.yahooapis.com/fantasy/v2`:
//!    * `/league/{league_key}/settings` – categories, add limits
//!    * `/league/{league_key}/teams`
//!    * `/team/{team_key}/roster;week={w}`
//!    * `/league/{league_key}/transactions;types=add,drop`
//!    * `/league/{league_key}/scoreboard;week={w}`
//!    * `/league/{league_key}/players;status=A;start={n}` – free agents (paged by 25)
//! 4. Map the responses into [`LeagueData`] and call `validate()`.
//!
//! Suggested crates: `oauth2` for the flow, `reqwest` (blocking + json) for HTTP.

use std::path::PathBuf;

use super::DataSource;
use crate::error::{Error, Result};
use crate::models::LeagueData;

/// Settings needed to talk to Yahoo. Nothing secret is stored in the struct
/// itself: the secret is read from an environment variable at runtime.
#[derive(Debug, Clone)]
pub struct YahooConfig {
    /// e.g. `"nba.l.106518"` (game key `nba` + league id).
    pub league_key: String,
    pub client_id: String,
    /// Name of the env var holding the client secret, e.g. `YAHOO_CLIENT_SECRET`.
    pub client_secret_env: String,
    /// Where the refresh token is cached between runs.
    pub token_path: PathBuf,
}

impl YahooConfig {
    /// Config for Thomas's league with conventional defaults.
    pub fn for_league_id(league_id: u32, client_id: impl Into<String>) -> Self {
        Self {
            league_key: format!("nba.l.{league_id}"),
            client_id: client_id.into(),
            client_secret_env: "YAHOO_CLIENT_SECRET".into(),
            token_path: PathBuf::from("yahoo_token.json"),
        }
    }
}

/// Read-only Yahoo Fantasy API data source (not implemented yet).
#[derive(Debug, Clone)]
pub struct YahooOAuthSource {
    config: YahooConfig,
}

impl YahooOAuthSource {
    pub fn new(config: YahooConfig) -> Self {
        Self { config }
    }

    /// Exposed so callers/tests can check what would be queried.
    pub fn config(&self) -> &YahooConfig {
        &self.config
    }
}

impl DataSource for YahooOAuthSource {
    fn name(&self) -> &'static str {
        "yahoo-oauth"
    }

    fn load(&self) -> Result<LeagueData> {
        Err(Error::NotImplemented {
            source_name: self.name(),
            detail: "waiting on Yahoo API approval; use a JSON snapshot for now",
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_league_key_and_is_a_clear_stub() {
        let src = YahooOAuthSource::new(YahooConfig::for_league_id(106518, "client"));
        assert_eq!(src.config().league_key, "nba.l.106518");
        assert!(matches!(src.load(), Err(Error::NotImplemented { .. })));
    }
}
