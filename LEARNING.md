# LEARNING.md: how this project is put together

This is a guided tour for learning Rust through this codebase. Read it next
to the code; every module also has a `//!` doc comment at the top.
`cargo doc --open --no-deps` renders all of it as browsable HTML.

## 1. The big picture

```
 JSON file  ──▶ JsonSnapshotSource       ─┐
 Yahoo API  ──▶ YahooOAuthSource  (stub)  ├─ impl DataSource
 box scores ──▶ BoxScoreSource    (stub) ─┘
                        │
                        ▼
                    LeagueData  ◀──▶  db::Store (SQLite)
                        │
                        ▼
      analysis::{available, team_report, add_impact, suggest, valuation}
                        │  plain structs
                        ▼
            hoops-cli: format.rs ──▶ stdout
```

The key idea is **one central data type** (`models::LeagueData`) with
*producers* on one side (data sources, the database) and *consumers* on the
other (analysis). Neither side knows about the other. That is why the Yahoo
API can arrive later without touching any analysis code.

### Why a workspace with two crates?

* `hoops-core` (library) holds all logic. Libraries are easy to test and could
  later be reused by, say, a web server or a scheduled job.
* `hoops-cli` (binary) is thin: parse args, call core, print.

A *crate* is Rust's unit of compilation; a *workspace* groups crates that share
`Cargo.lock` and `target/`. Shared dependency versions and lints live in the
root `Cargo.toml` under `[workspace.dependencies]` / `[workspace.lints]`.

## 2. Tour of `hoops-core`

| File | What to look at |
|---|---|
| `models.rs` | `enum Category` with `const ALL`, `impl FromStr`, `impl Display`; `CategoryMap<T>` (a generic type + `Index` trait); `StatLine` with `impl Add`/`Sum` so you can `.sum()` stat lines; `LeagueData` helper methods returning `Option`/`Result`. |
| `error.rs` | One `enum Error` derived with `thiserror`; `#[from]` makes `?` auto-convert library errors. `pub type Result<T>` alias. |
| `datasource/mod.rs` | The `DataSource` **trait**: the plug-in point. |
| `datasource/json_snapshot.rs` | `serde_json::from_str` into `LeagueData`, `map_err` to attach context. |
| `datasource/yahoo.rs`, `box_score.rs` | Stubs that return `Error::NotImplemented`, with the plan in comments. |
| `db/mod.rs` | `rusqlite`: migrations via `PRAGMA user_version`, transactions, prepared statements, `query_map` + `collect::<Result<Vec<_>>>()`. |
| `analysis/valuation.rs` | Z-scores; closures capturing local variables. |
| `analysis/available.rs` | Iterator chains (`filter` → `map` → `collect`) and **lifetimes**: results borrow `&'a Player` instead of cloning. |
| `analysis/team_report.rs` | Ranking with ties, bucketing into strong / middle / weak. |
| `analysis/add_impact.rs` | Undoing transactions to build a "what if I hadn't moved" roster. |
| `analysis/suggest.rs` | Weighted scoring for weak categories. |
| `analysis/test_support.rs` | A tiny 3-team league used by unit tests (`#[cfg(test)]` only). |

### Fantasy math in one paragraph

*Team strength* is the sum of each rostered player's season **per-game**
averages, so teams compare fairly regardless of games played. Percentages are
always `sum(makes) / sum(attempts)`, never an average of percentages (see the
test `percentages_come_from_summed_makes_and_attempts`). Player value is a
**z-score** per category against the whole player pool; TO is negated so
higher is always better; FG%/FT% use *impact* (`makes − pool% × attempts`) so
volume matters. `add-impact` uses **weekly** stat lines instead.

## 3. Crate choices

| Crate | Why |
|---|---|
| `serde` + `serde_json` | The standard for (de)serialization. `#[derive(Serialize, Deserialize)]` on the models *is* the JSON format. |
| `rusqlite` (`bundled`) | Small, synchronous, close to SQL. `bundled` compiles SQLite in, so there is nothing to install. Alternatives: `sqlx` (async, compile-time-checked queries, more setup), `diesel` (full ORM). |
| `thiserror` | Concise typed errors for the **library**. |
| `anyhow` | Easy error handling for the **application** (`.context("...")`, `main() -> anyhow::Result<()>`). Rule of thumb: thiserror in libs, anyhow in bins. |
| `clap` (`derive`, `env`) | Argument parsing from structs/enums; doc comments become `--help`. Because `Category: FromStr`, `--sort blk` just works. |

Deliberately *not* used yet: `chrono` (timestamps are RFC 3339 strings),
`tokio`/async (one request at a time is fine for a CLI), table-printing crates
(`format!` width specifiers like `{:>6}` are enough).

## 4. Rust concepts you will meet, and where

* **Ownership & borrowing**: `available_players` returns `Vec<AvailablePlayer<'a>>` that borrow from `data`. Try making it return owned `Player`s: you will need `.clone()`.
* **Traits & trait objects**: `DataSource` is a trait; `commands::load` stores a `Box<dyn DataSource>`, choosing the concrete type at runtime.
* **Generics**: `CategoryMap<T>`, `Store::query_all<T>`, `impl IntoIterator<Item = &'a Player>`.
* **Operator overloading**: `impl Add for StatLine`, `impl Index<Category> for CategoryMap<T>`.
* **Error handling**: `?`, `Option::ok_or_else`, `map_err`, `#[from]`.
* **Pattern matching**: `match` on enums everywhere; `matches!` macro in tests.
* **Testing**: unit tests in `#[cfg(test)] mod tests` beside the code; integration tests in `crates/hoops-cli/tests/cli.rs` run the compiled binary.

## 5. How to extend it

### Add a CLI command
1. Write a pure function in a new `hoops-core/src/analysis/<name>.rs`, add `pub mod <name>;` in `analysis/mod.rs`, and unit-test it with `test_support::tiny_league()`.
2. Add a variant to `enum Command` in `hoops-cli/src/main.rs` and a `match` arm.
3. Add the function in `commands.rs` and a formatter in `format.rs`.

### Implement the Yahoo source (once approved)
Follow the numbered plan in `datasource/yahoo.rs`. Add `reqwest = { version = "0.12", features = ["blocking", "json"] }` and `oauth2`. Deserialize Yahoo's (deeply nested) JSON into private `Yahoo*` structs, then convert to `LeagueData` with `impl From<...>`. Keep Yahoo types private to `yahoo.rs` so the rest of the code never sees them. Finally add a `--source yahoo` flag in `commands::load`. Keep the client secret in an env var; tokens go in a git-ignored file.

### The scraper (`scraper/`, Python)
Until the API route is approved, `scraper/` produces snapshots by reading the
league's web pages in a real browser. Read its modules in this order:
`stats.py` (column name -> `StatLine` field), `parse.py` (HTML -> plain
Python rows; pure functions), `build.py` (rows -> the exact JSON `LeagueData`
expects, plus a Python copy of `validate`), `scrape.py` (which pages, in what
order), `browser.py` (Playwright; the only file that touches the network).
`scrape.run_scrape` takes the fetch function as a parameter, so the tests
crawl a fake site (`scraper/tests/fake_site.py`) with no browser. That
crawl's output is committed as `fixtures/scraper_sample_snapshot.json`, and
`tests/cli.rs` loads it with the real `hoops` binary, so a schema mismatch
between the two languages fails `cargo test`.

### Combining sources
Box scores provide weekly stats only. Write a `MergedSource { base: Box<dyn DataSource>, stats: BoxScoreSource }` whose `load` takes rosters/transactions from `base` and replaces `weekly_stats`. That is the *composite* pattern and needs no change to the trait.

### Change the database schema
Never edit `0001_init.sql` once you have a real database. Add `migrations/0002_<what>.sql` and append it to `MIGRATIONS` in `db/mod.rs`; `Store::open` applies it automatically and bumps `user_version`. Add a test.

### Better add-impact accuracy
With **daily** stat lines (box scores give these), store `daily_player_stats(date, player_key, ...)`, give transactions a date, and count only games while the player was actually on the roster. The `AddDropImpact` struct can stay the same.

### Type-safety upgrades (good exercises)
* Replace `type PlayerKey = String` with a newtype `struct PlayerKey(String)` so a team key can never be passed where a player key is expected. The compiler will show you every place to update.
* Add `Category`-specific weights to `suggest` (e.g. punt FT%).
* Add a `--json` output flag using `serde_json::to_string_pretty` on the analysis structs (derive `Serialize` on them first).
