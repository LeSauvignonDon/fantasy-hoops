-- 0001_init.sql: initial schema.
-- Migrations are applied in order and tracked with SQLite's PRAGMA user_version.
-- Never edit a migration that has shipped; add 0002_*.sql instead.

CREATE TABLE league (
    league_key      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    num_teams       INTEGER NOT NULL,
    max_weekly_adds INTEGER NOT NULL,
    current_week    INTEGER NOT NULL,
    my_team_key     TEXT NOT NULL
);

CREATE TABLE teams (
    team_key TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    manager  TEXT NOT NULL
);

-- Season-to-date totals live on the player row (overwritten on each import).
CREATE TABLE players (
    player_key TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    nba_team   TEXT NOT NULL,
    positions  TEXT NOT NULL,          -- comma separated, e.g. "PG,SG"
    gp  INTEGER NOT NULL, fgm REAL NOT NULL, fga REAL NOT NULL,
    ftm REAL NOT NULL,    fta REAL NOT NULL, tpm REAL NOT NULL,
    pts REAL NOT NULL,    reb REAL NOT NULL, ast REAL NOT NULL,
    stl REAL NOT NULL,    blk REAL NOT NULL, tov REAL NOT NULL
);

-- One row per (week, team, player): who was rostered at the end of that week.
CREATE TABLE roster_snapshots (
    week       INTEGER NOT NULL,
    team_key   TEXT NOT NULL REFERENCES teams(team_key),
    player_key TEXT NOT NULL REFERENCES players(player_key),
    PRIMARY KEY (week, team_key, player_key)
);

CREATE TABLE transactions (
    id         INTEGER PRIMARY KEY,
    week       INTEGER NOT NULL,
    timestamp  TEXT NOT NULL,
    team_key   TEXT NOT NULL REFERENCES teams(team_key),
    kind       TEXT NOT NULL CHECK (kind IN ('add', 'drop')),
    player_key TEXT NOT NULL REFERENCES players(player_key)
);
CREATE INDEX idx_transactions_team_week ON transactions(team_key, week);

CREATE TABLE weekly_player_stats (
    week       INTEGER NOT NULL,
    player_key TEXT NOT NULL REFERENCES players(player_key),
    gp  INTEGER NOT NULL, fgm REAL NOT NULL, fga REAL NOT NULL,
    ftm REAL NOT NULL,    fta REAL NOT NULL, tpm REAL NOT NULL,
    pts REAL NOT NULL,    reb REAL NOT NULL, ast REAL NOT NULL,
    stl REAL NOT NULL,    blk REAL NOT NULL, tov REAL NOT NULL,
    PRIMARY KEY (week, player_key)
);

CREATE TABLE matchups (
    week   INTEGER NOT NULL,
    team_a TEXT NOT NULL REFERENCES teams(team_key),
    team_b TEXT NOT NULL REFERENCES teams(team_key),
    PRIMARY KEY (week, team_a)
);
