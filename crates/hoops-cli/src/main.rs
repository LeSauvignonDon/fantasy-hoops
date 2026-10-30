//! `hoops`: command-line front end for `hoops-core`.
//!
//! This file only parses arguments and dispatches. Each subcommand's logic
//! lives in `commands.rs`, and table formatting lives in `format.rs`.

mod commands;
mod format;

use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};
use hoops_core::Category;

/// `#[derive(Parser)]` turns this struct into a full argument parser; the doc
/// comments become `--help` text.
#[derive(Debug, Parser)]
#[command(
    name = "hoops",
    version,
    about = "Yahoo fantasy basketball (9-cat H2H) analysis"
)]
struct Cli {
    #[command(flatten)]
    source: SourceArgs,

    #[command(subcommand)]
    command: Command,
}

/// Where league data comes from. Shared by every subcommand.
#[derive(Debug, Args)]
pub struct SourceArgs {
    /// JSON snapshot to read.
    #[arg(
        long,
        global = true,
        default_value = "fixtures/sample_snapshot.json",
        env = "HOOPS_SNAPSHOT"
    )]
    pub snapshot: PathBuf,

    /// Read from a SQLite database (created by `import`) instead of a snapshot.
    #[arg(long, global = true, conflicts_with = "snapshot")]
    pub from_db: Option<PathBuf>,

    /// Week to analyse (defaults to the league's current week).
    #[arg(long, global = true)]
    pub week: Option<u32>,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// List players not on any of the league's rosters, best first.
    AvailablePlayers {
        /// Only players eligible at this position (PG, SG, SF, PF, C).
        #[arg(long)]
        position: Option<String>,
        /// Sort by one category's z-score instead of overall value.
        #[arg(long)]
        sort: Option<Category>,
        /// Minimum games played.
        #[arg(long, default_value_t = 0)]
        min_games: u32,
        /// How many rows to print.
        #[arg(long, default_value_t = 20)]
        limit: usize,
    },

    /// Rank a team in every category against the rest of the league.
    TeamReport {
        /// Team key or (part of) a team name. Defaults to your team.
        #[arg(long)]
        team: Option<String>,
        /// Also print every team's rank in every category.
        #[arg(long)]
        all: bool,
    },

    /// Show how a week's adds/drops changed the head-to-head matchup.
    AddImpact {
        /// Team key or (part of) a team name. Defaults to your team.
        #[arg(long)]
        team: Option<String>,
    },

    /// Suggest free agents for weak categories.
    Suggest {
        /// Team key or (part of) a team name. Defaults to your team.
        #[arg(long)]
        team: Option<String>,
        /// Categories to target, comma separated (default: your weak ones).
        #[arg(long, value_delimiter = ',')]
        cats: Vec<Category>,
        /// Only players eligible at this position.
        #[arg(long)]
        position: Option<String>,
        #[arg(long, default_value_t = 10)]
        limit: usize,
    },

    /// Save the current snapshot into a SQLite database (idempotent).
    Import {
        /// Database file to create or update.
        #[arg(long, default_value = "hoops.db")]
        db: PathBuf,
    },
}

/// `anyhow::Result` in `main` prints a readable error chain and exits non-zero.
fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let data = commands::load(&cli.source)?;
    let week = cli.source.week.unwrap_or(data.league.current_week);

    match cli.command {
        Command::AvailablePlayers {
            position,
            sort,
            min_games,
            limit,
        } => commands::available_players(&data, week, position, sort, min_games, limit),
        Command::TeamReport { team, all } => commands::team_report(&data, week, team, all),
        Command::AddImpact { team } => commands::add_impact(&data, week, team),
        Command::Suggest {
            team,
            cats,
            position,
            limit,
        } => commands::suggest(&data, week, team, cats, position, limit),
        Command::Import { db } => commands::import(&data, &db),
    }
}
