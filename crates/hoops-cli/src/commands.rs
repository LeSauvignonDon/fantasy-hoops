//! One function per subcommand. Each loads nothing itself: it receives the
//! already-loaded `LeagueData`, calls into `hoops_core::analysis`, and prints.

use std::path::Path;

use anyhow::{Context, Result};
use hoops_core::analysis::add_impact::add_drop_impact;
use hoops_core::analysis::available::{
    available_players as find_available, AvailableFilter, SortBy,
};
use hoops_core::analysis::suggest::suggest_free_agents;
use hoops_core::analysis::team_report::team_report as build_report;
use hoops_core::datasource::{DataSource, JsonSnapshotSource};
use hoops_core::db::Store;
use hoops_core::{Category, LeagueData, Team};

use crate::format;
use crate::SourceArgs;

/// Pick a data source from the CLI flags and load it.
///
/// `Box<dyn DataSource>` is a *trait object*: the concrete type is chosen at
/// runtime. Adding the Yahoo source later is one more `match` arm here.
pub fn load(args: &SourceArgs) -> Result<LeagueData> {
    if let Some(db) = &args.from_db {
        let store = Store::open(db).with_context(|| format!("opening {}", db.display()))?;
        return Ok(store.load_league_data()?);
    }
    let source: Box<dyn DataSource> = Box::new(JsonSnapshotSource::new(&args.snapshot));
    source
        .load()
        .with_context(|| format!("loading data with the '{}' source", source.name()))
}

/// `--team` if given, otherwise the league's "my team".
fn resolve_team<'a>(data: &'a LeagueData, team: Option<&str>) -> Result<&'a Team> {
    Ok(match team {
        Some(q) => data.find_team(q)?,
        None => data.my_team()?,
    })
}

pub fn available_players(
    data: &LeagueData,
    week: u32,
    position: Option<String>,
    sort: Option<Category>,
    min_games: u32,
    limit: usize,
) -> Result<()> {
    let filter = AvailableFilter {
        position,
        min_games,
    };
    let sort = sort.map_or(SortBy::Overall, SortBy::Category);
    let rows = find_available(data, week, &filter, sort);

    let rostered = data.rostered_keys(week).len();
    println!(
        "{} — week {week}: {} available of {} players ({} rostered across {} teams)\n",
        data.league.name,
        rows.len(),
        data.players.len(),
        rostered,
        data.teams.len()
    );
    let sort_label = match sort {
        SortBy::Overall => "z(9cat)".to_string(),
        SortBy::Category(c) => format!("z({c})"),
    };
    print!(
        "{}",
        format::available_table(&rows[..rows.len().min(limit)], &sort_label)
    );
    Ok(())
}

pub fn team_report(data: &LeagueData, week: u32, team: Option<String>, all: bool) -> Result<()> {
    let team = resolve_team(data, team.as_deref())?;
    let report = build_report(data, &team.team_key, week)?;
    print!("{}", format::team_report(&report));
    if all {
        println!();
        print!("{}", format::league_rank_grid(data, &report));
    }
    Ok(())
}

pub fn add_impact(data: &LeagueData, week: u32, team: Option<String>) -> Result<()> {
    let team = resolve_team(data, team.as_deref())?;
    let impact = add_drop_impact(data, &team.team_key, week)?;
    print!("{}", format::add_impact(data, team, &impact));
    Ok(())
}

pub fn suggest(
    data: &LeagueData,
    week: u32,
    team: Option<String>,
    mut cats: Vec<Category>,
    position: Option<String>,
    limit: usize,
) -> Result<()> {
    let team = resolve_team(data, team.as_deref())?;
    if cats.is_empty() {
        cats = build_report(data, &team.team_key, week)?.weak_categories();
        if cats.is_empty() {
            println!(
                "{} has no bottom-third categories; targeting overall value.",
                team.name
            );
        }
    }
    let names: Vec<_> = cats.iter().map(|c| c.abbrev()).collect();
    println!(
        "Free-agent suggestions for {} (week {week}), targeting: {}\n",
        team.name,
        if names.is_empty() {
            "all".to_string()
        } else {
            names.join(", ")
        }
    );
    let filter = AvailableFilter {
        position,
        min_games: 0,
    };
    let rows = suggest_free_agents(data, week, &cats, &filter, limit);
    print!("{}", format::suggestions(&rows, &cats));
    Ok(())
}

pub fn import(data: &LeagueData, db: &Path) -> Result<()> {
    let mut store = Store::open(db).with_context(|| format!("opening {}", db.display()))?;
    store.save_league_data(data)?;
    println!(
        "Imported {} teams, {} players, {} roster snapshots, {} transactions, {} weekly stat lines, {} matchups into {} (schema v{}).",
        data.teams.len(),
        data.players.len(),
        data.rosters.len(),
        data.transactions.len(),
        data.weekly_stats.len(),
        data.matchups.len(),
        db.display(),
        store.schema_version()?
    );
    Ok(())
}
