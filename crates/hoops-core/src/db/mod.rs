//! SQLite persistence.
//!
//! [`Store`] wraps a `rusqlite::Connection`. Opening a store runs any pending
//! migrations, so callers never see an out-of-date schema.
//!
//! Imports are *idempotent*: saving the same snapshot twice leaves the
//! database unchanged (rows are upserted with `INSERT OR REPLACE`).

use std::collections::BTreeMap;
use std::path::Path;

use rusqlite::{params, Connection, Row};

use crate::error::Result;
use crate::models::{
    League, LeagueData, Matchup, Player, RosterSnapshot, StatLine, Team, Transaction,
    WeeklyPlayerStats,
};

/// Ordered list of migrations. Index 0 is schema version 1, and so on.
/// `include_str!` embeds the SQL file into the binary at compile time.
const MIGRATIONS: &[&str] = &[include_str!("../../migrations/0001_init.sql")];

/// The 12 stat columns, in the same order everywhere we read/write them.
const STAT_COLS: &str = "gp, fgm, fga, ftm, fta, tpm, pts, reb, ast, stl, blk, tov";

/// A handle to the SQLite database.
#[derive(Debug)]
pub struct Store {
    conn: Connection,
}

impl Store {
    /// Open (or create) a database file and migrate it.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        Self::init(Connection::open(path)?)
    }

    /// A throwaway in-memory database, ideal for tests.
    pub fn open_in_memory() -> Result<Self> {
        Self::init(Connection::open_in_memory()?)
    }

    fn init(conn: Connection) -> Result<Self> {
        conn.pragma_update(None, "foreign_keys", true)?;
        let mut store = Store { conn };
        store.migrate()?;
        Ok(store)
    }

    /// Current schema version (`PRAGMA user_version`).
    pub fn schema_version(&self) -> Result<u32> {
        Ok(self
            .conn
            .query_row("PRAGMA user_version", [], |r| r.get(0))?)
    }

    /// Apply every migration newer than the database's `user_version`,
    /// each inside its own transaction so a failure leaves nothing half-done.
    fn migrate(&mut self) -> Result<()> {
        let current = self.schema_version()? as usize;
        for (i, sql) in MIGRATIONS.iter().enumerate().skip(current) {
            let tx = self.conn.transaction()?;
            tx.execute_batch(sql)?;
            // Record the new version inside the same transaction as the schema change.
            tx.pragma_update(None, "user_version", (i + 1) as u32)?;
            tx.commit()?;
        }
        Ok(())
    }

    /// Persist a whole snapshot in one transaction.
    pub fn save_league_data(&mut self, data: &LeagueData) -> Result<()> {
        let tx = self.conn.transaction()?;
        {
            let l = &data.league;
            tx.execute(
                "INSERT OR REPLACE INTO league VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    l.league_key,
                    l.name,
                    l.num_teams,
                    l.max_weekly_adds,
                    l.current_week,
                    l.my_team_key
                ],
            )?;

            // Prepared statements are compiled once and reused per row.
            let mut stmt = tx.prepare("INSERT OR REPLACE INTO teams VALUES (?1, ?2, ?3)")?;
            for t in &data.teams {
                stmt.execute(params![t.team_key, t.name, t.manager])?;
            }

            let mut stmt = tx.prepare(&format!(
                "INSERT OR REPLACE INTO players (player_key, name, nba_team, positions, {STAT_COLS})
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)"
            ))?;
            for p in &data.players {
                let s = &p.season;
                stmt.execute(params![
                    p.player_key,
                    p.name,
                    p.nba_team,
                    p.positions.join(","),
                    s.gp,
                    s.fgm,
                    s.fga,
                    s.ftm,
                    s.fta,
                    s.tpm,
                    s.pts,
                    s.reb,
                    s.ast,
                    s.stl,
                    s.blk,
                    s.tov
                ])?;
            }

            // A snapshot fully describes a (week, team) roster, so replace it wholesale.
            let mut del =
                tx.prepare("DELETE FROM roster_snapshots WHERE week = ?1 AND team_key = ?2")?;
            let mut ins = tx.prepare("INSERT INTO roster_snapshots VALUES (?1, ?2, ?3)")?;
            for r in &data.rosters {
                del.execute(params![r.week, r.team_key])?;
                for pk in &r.player_keys {
                    ins.execute(params![r.week, r.team_key, pk])?;
                }
            }

            let mut stmt =
                tx.prepare("INSERT OR REPLACE INTO transactions VALUES (?1, ?2, ?3, ?4, ?5, ?6)")?;
            for t in &data.transactions {
                stmt.execute(params![
                    t.id,
                    t.week,
                    t.timestamp,
                    t.team_key,
                    t.kind.as_str(),
                    t.player_key
                ])?;
            }

            let mut stmt = tx.prepare(&format!(
                "INSERT OR REPLACE INTO weekly_player_stats (week, player_key, {STAT_COLS})
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)"
            ))?;
            for w in &data.weekly_stats {
                let s = &w.stats;
                stmt.execute(params![
                    w.week,
                    w.player_key,
                    s.gp,
                    s.fgm,
                    s.fga,
                    s.ftm,
                    s.fta,
                    s.tpm,
                    s.pts,
                    s.reb,
                    s.ast,
                    s.stl,
                    s.blk,
                    s.tov
                ])?;
            }

            let mut stmt = tx.prepare("INSERT OR REPLACE INTO matchups VALUES (?1, ?2, ?3)")?;
            for m in &data.matchups {
                stmt.execute(params![m.week, m.team_a, m.team_b])?;
            }
        } // statements borrow `tx`, so they must be dropped before commit.
        tx.commit()?;
        Ok(())
    }

    /// Read everything back into a [`LeagueData`]. This is what makes the
    /// store usable as a data source for the analysis commands.
    pub fn load_league_data(&self) -> Result<LeagueData> {
        let league = self.conn.query_row(
            "SELECT league_key, name, num_teams, max_weekly_adds, current_week, my_team_key FROM league LIMIT 1",
            [],
            |r| {
                Ok(League {
                    league_key: r.get(0)?,
                    name: r.get(1)?,
                    num_teams: r.get(2)?,
                    max_weekly_adds: r.get(3)?,
                    current_week: r.get(4)?,
                    my_team_key: r.get(5)?,
                })
            },
        )?;

        let teams = self.query_all(
            "SELECT team_key, name, manager FROM teams ORDER BY team_key",
            |r| {
                Ok(Team {
                    team_key: r.get(0)?,
                    name: r.get(1)?,
                    manager: r.get(2)?,
                })
            },
        )?;

        let players = self.query_all(
            &format!("SELECT player_key, name, nba_team, positions, {STAT_COLS} FROM players ORDER BY player_key"),
            |r| {
                let positions: String = r.get(3)?;
                Ok(Player {
                    player_key: r.get(0)?,
                    name: r.get(1)?,
                    nba_team: r.get(2)?,
                    positions: positions.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
                    season: stat_line_from_row(r, 4)?,
                })
            },
        )?;

        // Group (week, team, player) rows back into one snapshot per (week, team).
        // BTreeMap keeps a deterministic order.
        let rows = self.query_all(
            "SELECT week, team_key, player_key FROM roster_snapshots ORDER BY week, team_key, player_key",
            |r| Ok((r.get::<_, u32>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)),
        )?;
        let mut grouped: BTreeMap<(u32, String), Vec<String>> = BTreeMap::new();
        for (week, team, player) in rows {
            grouped.entry((week, team)).or_default().push(player);
        }
        let rosters = grouped
            .into_iter()
            .map(|((week, team_key), player_keys)| RosterSnapshot {
                week,
                team_key,
                player_keys,
            })
            .collect();

        let transactions = self.query_all(
            "SELECT id, week, timestamp, team_key, kind, player_key FROM transactions ORDER BY id",
            |r| {
                let kind: String = r.get(4)?;
                Ok(Transaction {
                    id: r.get(0)?,
                    week: r.get(1)?,
                    timestamp: r.get(2)?,
                    team_key: r.get(3)?,
                    // The CHECK constraint guarantees add/drop; map anything else to a SQL error.
                    kind: kind.parse().map_err(|e| {
                        rusqlite::Error::FromSqlConversionFailure(
                            4,
                            rusqlite::types::Type::Text,
                            Box::new(e),
                        )
                    })?,
                    player_key: r.get(5)?,
                })
            },
        )?;

        let weekly_stats = self.query_all(
            &format!("SELECT week, player_key, {STAT_COLS} FROM weekly_player_stats ORDER BY week, player_key"),
            |r| Ok(WeeklyPlayerStats { week: r.get(0)?, player_key: r.get(1)?, stats: stat_line_from_row(r, 2)? }),
        )?;

        let matchups = self.query_all(
            "SELECT week, team_a, team_b FROM matchups ORDER BY week, team_a",
            |r| {
                Ok(Matchup {
                    week: r.get(0)?,
                    team_a: r.get(1)?,
                    team_b: r.get(2)?,
                })
            },
        )?;

        let data = LeagueData {
            league,
            teams,
            players,
            rosters,
            transactions,
            weekly_stats,
            matchups,
        };
        data.validate()?;
        Ok(data)
    }

    /// Run a query and map every row with `f`. Generic over the row type `T`.
    fn query_all<T>(
        &self,
        sql: &str,
        f: impl FnMut(&Row<'_>) -> rusqlite::Result<T>,
    ) -> Result<Vec<T>> {
        let mut stmt = self.conn.prepare(sql)?;
        let rows = stmt.query_map([], f)?;
        // Collecting an iterator of Results into Result<Vec<_>> stops at the first error.
        Ok(rows.collect::<rusqlite::Result<Vec<T>>>()?)
    }
}

/// Read the 12 stat columns starting at column index `start`.
fn stat_line_from_row(r: &Row<'_>, start: usize) -> rusqlite::Result<StatLine> {
    Ok(StatLine {
        gp: r.get(start)?,
        fgm: r.get(start + 1)?,
        fga: r.get(start + 2)?,
        ftm: r.get(start + 3)?,
        fta: r.get(start + 4)?,
        tpm: r.get(start + 5)?,
        pts: r.get(start + 6)?,
        reb: r.get(start + 7)?,
        ast: r.get(start + 8)?,
        stl: r.get(start + 9)?,
        blk: r.get(start + 10)?,
        tov: r.get(start + 11)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::datasource::{DataSource, JsonSnapshotSource};

    fn fixture() -> LeagueData {
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/sample_snapshot.json");
        JsonSnapshotSource::new(path).load().unwrap()
    }

    /// Normalise ordering so we can compare JSON-loaded and DB-loaded data.
    fn sorted(mut d: LeagueData) -> LeagueData {
        d.teams.sort_by(|a, b| a.team_key.cmp(&b.team_key));
        d.players.sort_by(|a, b| a.player_key.cmp(&b.player_key));
        for r in &mut d.rosters {
            r.player_keys.sort();
        }
        d.rosters
            .sort_by(|a, b| (a.week, &a.team_key).cmp(&(b.week, &b.team_key)));
        d.transactions.sort_by_key(|t| t.id);
        d.weekly_stats
            .sort_by(|a, b| (a.week, &a.player_key).cmp(&(b.week, &b.player_key)));
        d.matchups
            .sort_by(|a, b| (a.week, &a.team_a).cmp(&(b.week, &b.team_a)));
        d
    }

    #[test]
    fn migrations_set_schema_version() {
        let store = Store::open_in_memory().unwrap();
        assert_eq!(store.schema_version().unwrap() as usize, MIGRATIONS.len());
    }

    #[test]
    fn round_trips_fixture_and_is_idempotent() {
        let data = fixture();
        let mut store = Store::open_in_memory().unwrap();
        store.save_league_data(&data).unwrap();
        store.save_league_data(&data).unwrap(); // second import must not duplicate
        let loaded = store.load_league_data().unwrap();
        assert_eq!(sorted(loaded), sorted(data));
    }
}
