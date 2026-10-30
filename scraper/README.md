# scraper: Yahoo Fantasy league → `hoops` snapshot

A local tool that reads your Yahoo Fantasy Basketball league (default
[106518](https://basketball.fantasysports.yahoo.com/nba/106518)) through a
real, signed-in browser and writes a JSON snapshot that `hoops` loads with
`--snapshot`. It runs on your Mac only.

It collects:

- league name, current week and your team
- all 12 teams: names, managers, and the current roster from `/nba/106518/1` … `/12`
- standings, kept in the snapshot's `_yahoo` extra block because `hoops` has no standings model yet
- the scoreboard for every week so far, which gives `matchups`
- matchup pages for the last 2 weeks by default (`--stats-weeks`), which give per-player `weekly_stats` and past-week rosters
- transactions (adds and drops, following "Next" pages)
- players lists, which give season totals for the 9 categories (FG%, FT%, 3PTM, PTS, REB, AST, STL, BLK, TO) as FGM/FGA, FTM/FTA, 3PTM, PTS, REB, AST, ST, BLK, TO and GP. It reads every rostered player (`status=T`) and 6 pages of 25 free agents (`status=A`, `--fa-pages`).

## Why Python + Playwright?

- **Playwright** drives a real browser. You sign in yourself with a passkey,
  Touch ID or your phone, in a normal window. The script only ever sees the
  pages after you are signed in. Yahoo has no simple API key, and its OAuth app
  route needs a developer app, so driving the browser is the simplest route
  with no secrets.
- **Python** because the repo already uses it (`scripts/gen_fixture.py`), and
  BeautifulSoup is forgiving with messy HTML. Playwright's Python package
  ships the same browser automation as the Node one. With `uv`, setup takes
  two commands and needs no C compiler.
- Rust could do this too (with `chromiumoxide` or `fantoccini`), but those are
  less mature for logins and would add many heavy crates to a project that is
  meant for learning. The boundary between the two languages is a JSON file,
  and `cargo test` checks it (see "Tests").

## Security model

- **No credentials in the script.** It never asks for, types, reads or
  stores a password or passkey. `login` just opens a window at the league page
  and waits until the league loads.
- **Dedicated browser profile** at `~/.fantasy-hoops/browser-profile/<browser>/`
  (mode 0700). It sits outside the repo and is separate from your everyday Brave
  profile. Your Yahoo session cookie lives there, as it would in any
  browser. To sign out completely, delete that folder.
- Snapshots and debug dumps go to `data/`, which is git-ignored. The debug HTML
  contains your league's pages, so keep it local.
- **Polite:** one page at a time, about 2.5–3.75 s apart (`--delay`). Images
  and fonts are not downloaded. It backs off on HTTP 429/5xx. A full run is
  about 40–60 page loads.

## Setup on a Mac (Apple Silicon)

```sh
# 1. Install uv (Python package manager), once. Either:
brew install uv
#    or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. From the repo root:
cd scraper
uv sync                              # creates scraper/.venv with playwright + beautifulsoup4
uv run playwright install chromium   # fallback browser (~120 MB; used only if Brave is missing)

# 3. Sign in once. A Brave window opens on your league; sign in with your passkey.
uv run python -m fantasy_scraper login
#    It prints "Signed in." and exits when the league page loads.

# 4. Check the session at any time (headless, about 5 s):
uv run python -m fantasy_scraper status

# 5. Scrape (headless). Writes ../data/snapshot-YYYY-MM-DD.json
uv run python -m fantasy_scraper snapshot
#    useful flags: --debug-dump  --out ../data/mine.json  --headed  --relogin

# 6. Analyse it with hoops (from the repo root)
cd ..
cargo run -- --snapshot data/snapshot-$(date +%F).json available-players
cargo run -- --snapshot data/snapshot-$(date +%F).json team-report
cargo run -- --snapshot data/snapshot-$(date +%F).json add-impact
cargo run -- --snapshot data/snapshot-$(date +%F).json suggest
```

**Without uv** (plain venv):

```sh
cd scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m fantasy_scraper login
python -m fantasy_scraper snapshot
```

### Browser choice

`--browser auto` is the default. It uses Brave from
`/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` if it exists,
and Playwright's bundled Chromium otherwise. You can force either with
`--browser brave|chromium`, or point at another Brave with `--brave-path`.
Each browser gets its own profile subfolder, because Chromium-family browsers
encrypt cookies with a per-browser key, so one browser can't read another's
sessions. If you switch browsers, run `login` again.

### Passkeys

Passkeys are handled by macOS and the browser, not by this script. If Brave
in the dedicated profile doesn't offer your iCloud Keychain passkey, choose
"use a phone or tablet" and scan the QR code with your iPhone, or use another
sign-in method Yahoo offers. The bundled Chromium is not a signed Apple app,
so it is the more likely of the two to lack iCloud Keychain passkeys. That
is one reason Brave is preferred. Either way, you only need to do this when
the session expires, which is typically every few weeks.

### When the session expires

`snapshot` exits with code 2 and prints the following (`status` prints a similar hint):

    Yahoo session expired (...). Run `uv run python -m fantasy_scraper login` and then retry (or pass --relogin).

`--relogin` opens the sign-in window when needed and then continues the
scrape.

## Options (snapshot)

| flag | default | meaning |
|---|---|---|
| `--out PATH` | `data/snapshot-<date>.json` | output file (date in `--tz`) |
| `--debug-dump` | off | save every page's HTML (+ embedded JSON, `index.json`) to `data/debug/<timestamp>/` |
| `--stats-weeks` | `last2` | weeks to read weekly player stats for: `last2`, `current`, `all`, `1-4`, `3,5` |
| `--fa-pages N` | 6 | free-agent pages of 25 |
| `--taken-pages N` | 10 | max pages of rostered players (season totals) |
| `--tx-pages N` | 4 | max transaction pages |
| `--current-week N` | detected | override if detection is wrong |
| `--my-team-id N` / `--my-team-name` | name "Cripples and Bastards" | which team is yours (`N` in `/nba/106518/N`) |
| `--season YYYY` | from today | Yahoo season year (2026 = 2026-27) |
| `--tz` | America/Los_Angeles | time zone Yahoo shows transaction times in |
| `--delay S` | 2.5 | seconds between pages |
| `--headed` | off | watch the browser work |
| `--league-id`, `--browser`, `--brave-path`, `--profile-dir` | | shared by all commands |

The snapshot matches `LeagueData` in `crates/hoops-core/src/models.rs`. Keys
are `nba.l.106518.t.N` for teams and `nba.p.<yahoo player id>` for players.
Season stats are totals. Two extra keys (`_comment`, `_yahoo` with standings,
week date ranges and warnings) are ignored by `hoops`. Before writing, the
scraper runs a Python copy of Rust's `validate()`. Warnings, such as a
skipped trade or a player with no stats, are printed and stored in
`_yahoo.warnings`.

## How it reads pages (and why it may need fixes)

Yahoo doesn't document its HTML. This has been tested only against **fake
pages shaped like Yahoo's**, never against your live league, so treat every
selector as best-effort. The parsers are written defensively:

1. **Embedded JSON first:** `embedded.py` looks in `<script>` tags
   (`application/json`, `__NEXT_DATA__`, `root.App.main = {...}`) for player
   records and fills in team, positions and stats when found.
2. **DOM fallback:** `parse.py` matches what a reader sees, not class names:
   - players: links to `/nba/players/<id>`
   - teams: links to `/nba/106518/<N>`
   - NBA team and positions: text like `LAL - PG,SG`
   - stats: columns by header text (`FGM/A`, `3PTM`, `ST`, `TO`, `GP`), aligned from the right
   - matchups: links with `week=`, `mid1=` and `mid2=`
   - transactions: `+`/`-` icons, or "Added"/"Dropped" labels
3. Each step can fail by itself. A failure becomes a warning, and the rest
   still runs.

If something comes out empty or wrong:

```sh
uv run python -m fantasy_scraper snapshot --debug-dump
open ../data/debug/        # find the page (index.json lists label -> URL)
```

Then adjust the matching function in `parse.py`. Copy a trimmed piece of the
real HTML into a test in `tests/test_parse.py`, remove any names first, and
run the tests. URL query parameters (`urls.py`) are also best-effort. If
Yahoo ignores `stat1=S_S_2026`, for example, you will see weekly or today's
numbers in the players table instead of season totals.

## Tests (offline, no browser, no network)

```sh
cd scraper
uv run python -m unittest discover -s tests -t . -v
```

- `tests/fake_site.py` is a fake 12-team "Yahoo" (invented names and numbers).
- `test_stats` / `test_timeutil` / `test_parse` / `test_build` are unit tests for
  each mapping step, including the schema mapping and the validator.
- `test_end_to_end` runs the real crawl plan against the fake site and compares
  the result with `fixtures/scraper_sample_snapshot.json`. Regenerate that file
  after an intended change with `UPDATE_FIXTURES=1 uv run python -m unittest tests.test_end_to_end`.
- On the Rust side, `crates/hoops-cli/tests/cli.rs` runs
  `hoops --snapshot fixtures/scraper_sample_snapshot.json available-players` (plus
  `team-report`, `add-impact`, `suggest`), so `cargo test` fails if the two drift apart.

## Code map

| file | role |
|---|---|
| `fantasy_scraper/cli.py` | `login` / `status` / `snapshot` commands |
| `fantasy_scraper/browser.py` | Playwright: persistent profile, Brave/Chromium, polite fetcher, debug dumps (the only network code) |
| `fantasy_scraper/scrape.py` | crawl plan; takes a `fetch(url, label)` function (testable) |
| `fantasy_scraper/urls.py` | Yahoo URLs (best-effort query params) |
| `fantasy_scraper/parse.py` | pure HTML → rows parsers |
| `fantasy_scraper/embedded.py` | JSON-in-`<script>` extraction |
| `fantasy_scraper/stats.py` | column names / Yahoo stat ids → `StatLine` |
| `fantasy_scraper/timeutil.py` | week ranges, "Yesterday, 8:05 pm" → RFC 3339 |
| `fantasy_scraper/build.py` | rows → snapshot JSON + validator |
