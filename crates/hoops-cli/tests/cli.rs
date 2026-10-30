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
