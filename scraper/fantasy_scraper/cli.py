"""Command line: ``login``, ``status`` and ``snapshot``.

Run from ``scraper/``::

    uv run python -m fantasy_scraper login
    uv run python -m fantasy_scraper status
    uv run python -m fantasy_scraper snapshot [--debug-dump] [--out PATH]

Exit codes: 0 ok, 1 error, 2 session expired / not signed in.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build_snapshot, validate_snapshot
from .scrape import ScrapeError, ScrapeOptions, SessionExpired, run_scrape
from .timeutil import now_in

# scraper/fantasy_scraper/cli.py -> repo root is two levels up from scraper/
REPO_ROOT = Path(__file__).resolve().parents[2]
EXIT_SESSION = 2


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("browser")
    g.add_argument("--browser", choices=["auto", "brave", "chromium"], default="auto",
                   help="auto = Brave if installed, else Playwright's Chromium (default: auto)")
    g.add_argument("--brave-path", help="path to the Brave executable "
                   "(default: /Applications/Brave Browser.app/Contents/MacOS/Brave Browser)")
    g.add_argument("--profile-dir", type=Path,
                   help="base dir for the dedicated browser profile (default: ~/.fantasy-hoops/browser-profile)")
    common.add_argument("--league-id", default="106518", help="Yahoo league id (default: 106518)")

    p = argparse.ArgumentParser(prog="fantasy_scraper", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    lg = sub.add_parser("login", parents=[common], help="open a window and sign in to Yahoo once")
    lg.add_argument("--timeout", type=int, default=600, help="seconds to wait for you to sign in")

    sub.add_parser("status", parents=[common], help="check (headless) whether the saved session works")

    s = sub.add_parser("snapshot", parents=[common], help="scrape the league into a hoops JSON snapshot")
    s.add_argument("--out", type=Path, help="output file (default: <repo>/data/snapshot-<date>.json)")
    s.add_argument("--debug-dump", action="store_true",
                   help="save raw HTML of every page to <repo>/data/debug/<timestamp>/")
    s.add_argument("--headed", action="store_true", help="show the browser while scraping")
    s.add_argument("--relogin", action="store_true",
                   help="if the session expired, open a login window instead of exiting")
    s.add_argument("--delay", type=float, default=2.5, help="seconds between page loads (default 2.5)")
    s.add_argument("--num-teams", type=int, default=12)
    s.add_argument("--fa-pages", type=int, default=6, help="free-agent pages of 25 (default 6 = 150 players)")
    s.add_argument("--taken-pages", type=int, default=10, help="max rostered-player pages of 25")
    s.add_argument("--tx-pages", type=int, default=4, help="max transaction pages")
    s.add_argument("--stats-weeks", default="last2",
                   help="weeks to fetch weekly player stats for: last2 | current | all | 1-4 | 3,5")
    s.add_argument("--current-week", type=int, help="override detected current week")
    s.add_argument("--season", type=int, help="Yahoo season year, e.g. 2026 for 2026-27 (default: from today)")
    s.add_argument("--tz", default="America/Los_Angeles",
                   help="time zone your Yahoo account shows times in (default America/Los_Angeles)")
    s.add_argument("--my-team-id", type=int, help="your team number (the N in /nba/106518/N)")
    s.add_argument("--my-team-name", default="Cripples and Bastards", help="your team's name")
    s.add_argument("--max-weekly-adds", type=int, default=5)
    return p


def _open(args, headless: bool):
    from .browser import open_context  # imported late so --help works without Playwright

    return open_context(headless, args.browser, args.brave_path, args.profile_dir)


def cmd_login(args) -> int:
    from .browser import login

    with _open(args, headless=False) as ctx:
        ok = login(ctx, args.league_id, args.timeout)
    if ok:
        _log("Signed in. Session saved in the dedicated profile; `snapshot` can now run headless.")
        return 0
    _log("Timed out waiting for sign-in (or the league page didn't load). Try again.")
    return EXIT_SESSION


def cmd_status(args) -> int:
    from .browser import _first_page, signed_in

    with _open(args, headless=True) as ctx:
        ok = signed_in(_first_page(ctx), args.league_id)
    _log("Session OK." if ok else "Not signed in / session expired. Run: uv run python -m fantasy_scraper login")
    return 0 if ok else EXIT_SESSION


def cmd_snapshot(args) -> int:
    from .browser import PlaywrightFetcher, login

    now = now_in(args.tz)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    out = args.out or REPO_ROOT / "data" / f"snapshot-{now.date().isoformat()}.json"
    debug_dir = REPO_ROOT / "data" / "debug" / stamp if args.debug_dump else None
    opts = ScrapeOptions(
        league_id=args.league_id, num_teams=args.num_teams, fa_pages=args.fa_pages,
        taken_pages=args.taken_pages, tx_pages=args.tx_pages, stats_weeks=args.stats_weeks,
        season=args.season, tz=args.tz, my_team_id=args.my_team_id, my_team_name=args.my_team_name,
        current_week=args.current_week, max_weekly_adds=args.max_weekly_adds, now=now,
    )

    for attempt in (1, 2):
        try:
            with _open(args, headless=not args.headed) as ctx:
                fetcher = PlaywrightFetcher(ctx, delay=args.delay, debug_dir=debug_dir)
                result = run_scrape(fetcher, opts, log=_log)
            break
        except SessionExpired as e:
            _log(f"Yahoo session expired ({e}).")
            if args.relogin and attempt == 1:
                with _open(args, headless=False) as ctx:
                    if not login(ctx, args.league_id):
                        return EXIT_SESSION
                continue
            _log("Run `uv run python -m fantasy_scraper login` and then retry (or pass --relogin).")
            return EXIT_SESSION
        except ScrapeError as e:
            _log(f"error: {e}")
            _log("If you are signed in, this is a parser problem: re-run with --debug-dump and "
                 "inspect data/debug/.")
            return EXIT_SESSION if "not signed in" in str(e) else 1
    else:
        return EXIT_SESSION

    snap = build_snapshot(result, now, args.my_team_name)
    problems = validate_snapshot(snap)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    _summary(snap, out, debug_dir, problems)
    return 1 if problems else 0


def _summary(snap: dict, out: Path, debug_dir: Path | None, problems: list[str]) -> None:
    lg = snap["league"]
    _log(f"\nWrote {out}")
    _log(f"  {lg['name']}: week {lg['current_week']}, my team {lg['my_team_key']}")
    _log(f"  {len(snap['teams'])} teams, {len(snap['players'])} players, {len(snap['rosters'])} rosters, "
         f"{len(snap['transactions'])} transaction halves, {len(snap['weekly_stats'])} weekly lines, "
         f"{len(snap['matchups'])} matchups")
    for w in snap["_yahoo"]["warnings"][:25]:
        _log(f"  warning: {w}")
    if debug_dir:
        _log(f"  raw pages saved in {debug_dir}")
    for p in problems:
        _log(f"  INVALID: {p}")
    rel = out.resolve()
    try:
        rel = out.resolve().relative_to(REPO_ROOT)
    except ValueError:
        pass
    _log(f"\nNext (from the repo root): cargo run -- --snapshot {rel} team-report")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"login": cmd_login, "status": cmd_status, "snapshot": cmd_snapshot}
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        _log("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
