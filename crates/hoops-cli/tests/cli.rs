//! End-to-end tests: run the real `hoops` binary against the sample fixture.
//!
//! Files in `tests/` are compiled as separate crates that can only use the
//! public interface, which for a binary means "run it and read stdout".

use std::path::{Path, PathBuf};
use std::process::Command;

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// Run `hoops <args>` from the workspace root and return stdout.
fn hoops(args: &[&str]) -> String {
    // Cargo sets CARGO_BIN_EXE_<name> for integration tests of a binary crate.
    let out = Command::new(env!("CARGO_BIN_EXE_hoops"))
        .args(args)
        .current_dir(workspace_root())
        .env_remove("HOOPS_SNAPSHOT")
        .output()
        .expect("binary runs");
    assert!(
        out.status.success(),
        "hoops {args:?} failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).expect("utf-8 output")
}

#[test]
fn available_players_runs_on_fixture() {
    let out = hoops(&["available-players", "--limit", "5"]);
    assert!(out.contains("30 available of 150 players"), "{out}");
    // Header + 5 rows after the summary line and blank line.
    assert_eq!(out.lines().count(), 2 + 1 + 5);
}

#[test]
fn team_report_runs_on_fixture() {
    let out = hoops(&["team-report", "--all"]);
    assert!(out.contains("Cripples and Bastards"));
    for cat in [
        "FG%", "FT%", "3PTM", "PTS", "REB", "AST", "STL", "BLK", "TO",
    ] {
        assert!(out.contains(cat), "missing {cat}");
    }
    assert!(out.contains("(lower is better)"));
}

#[test]
fn add_impact_and_suggest_run_on_fixture() {
    assert!(hoops(&["add-impact"]).contains("Adds used: 3/5"));
    assert!(hoops(&["suggest", "--cats", "blk,reb", "--limit", "3"]).contains("zBLK"));
}

#[test]
fn import_then_read_back_from_db() {
    let db = std::env::temp_dir().join(format!("hoops-test-{}.db", std::process::id()));
    let _ = std::fs::remove_file(&db);
    let db_str = db.to_str().unwrap();
    assert!(hoops(&["import", "--db", db_str]).contains("150 players"));
    let from_db = hoops(&["--from-db", db_str, "available-players", "--limit", "5"]);
    let from_json = hoops(&["available-players", "--limit", "5"]);
    assert_eq!(from_db, from_json, "SQLite round trip changes nothing");
    let _ = std::fs::remove_file(&db);
}

#[test]
fn unknown_team_fails_cleanly() {
    let out = Command::new(env!("CARGO_BIN_EXE_hoops"))
        .args(["team-report", "--team", "no such team"])
        .current_dir(workspace_root())
        .output()
        .unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("unknown team"));
}

/// `fixtures/scraper_sample_snapshot.json` is written by the Python scraper
/// (`scraper/`) crawling a *fake* Yahoo site in its test suite. Loading it
/// here proves the scraper's output matches the Rust snapshot schema.
const SCRAPER_SAMPLE: &str = "fixtures/scraper_sample_snapshot.json";

#[test]
fn scraper_shaped_snapshot_loads() {
    let out = hoops(&[
        "--snapshot",
        SCRAPER_SAMPLE,
        "available-players",
        "--limit",
        "5",
    ]);
    assert!(out.contains("34 available of 190 players"), "{out}");
    assert!(out.contains("Fakey Player"), "{out}");
}

#[test]
fn scraper_shaped_snapshot_supports_every_report() {
    let report = hoops(&["--snapshot", SCRAPER_SAMPLE, "team-report"]);
    assert!(report.contains("Cripples and Bastards"), "{report}");

    // Week 2: one add/drop by my team; weekly stats + matchup come from the
    // scraped matchup pages.
    let impact = hoops(&["--snapshot", SCRAPER_SAMPLE, "add-impact"]);
    assert!(impact.contains("Adds used: 1/5"), "{impact}");
    assert!(impact.contains("Fake Team 03"), "{impact}");

    // Week 1 (a past week): roster comes from the week-1 matchup page.
    let week1 = hoops(&["--snapshot", SCRAPER_SAMPLE, "--week", "1", "add-impact"]);
    assert!(week1.contains("Adds used: 0/5"), "{week1}");

    let suggest = hoops(&["--snapshot", SCRAPER_SAMPLE, "suggest", "--limit", "3"]);
    assert!(suggest.contains("Free-agent suggestions"), "{suggest}");
}
