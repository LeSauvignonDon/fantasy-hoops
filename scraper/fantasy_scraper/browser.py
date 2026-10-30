"""Playwright glue: a persistent, dedicated browser profile on *your* Mac.

Security model (why this is safe for a passkey login):

* The script never asks for, types, reads or stores your password/passkey.
  ``login`` just opens a normal browser window; *you* sign in, and the
  browser keeps Yahoo's session cookies in the profile directory.
* The profile lives in ``~/.fantasy-hoops/browser-profile/<browser>/`` by
  default: outside the repo, so it can't be committed. It is separate from
  your everyday Brave profile (which we never touch, and which Brave locks
  while it is running anyway).
* Nothing is sent anywhere except normal page loads to yahoo.com.
* Treat the profile dir like a password: anyone with a copy is signed in
  as you on Yahoo. Delete it (``rm -rf ~/.fantasy-hoops/browser-profile``)
  to sign out completely.

Why one sub-directory per browser? Chromium-family browsers encrypt cookies
with a browser-specific key, so a profile written by Brave is not readable
by Playwright's Chromium (and vice versa). Keeping them apart avoids a
confusing "session expired" right after logging in.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import parse, urls
from .scrape import SessionExpired

BRAVE_MAC = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
BRAVE_OTHER = ["/usr/bin/brave-browser", "/usr/bin/brave",
               r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"]
DEFAULT_PROFILE_BASE = Path.home() / ".fantasy-hoops" / "browser-profile"


def resolve_browser(choice: str, brave_path: str | None) -> tuple[str, str | None]:
    """Return ``(name, executable_path)``. ``None`` path = Playwright's Chromium.

    ``auto`` uses Brave if it is installed, else bundled Chromium."""
    candidates = [brave_path] if brave_path else [BRAVE_MAC, *BRAVE_OTHER]
    brave = next((c for c in candidates if c and os.path.exists(c)), None)
    if choice == "brave":
        if not brave:
            raise SystemExit(f"Brave not found at {candidates[0]!r}; pass --brave-path or --browser chromium")
        return "brave", brave
    if choice == "auto" and brave:
        return "brave", brave
    return "chromium", None


def profile_dir(base: Path | None, browser_name: str) -> Path:
    path = (base or DEFAULT_PROFILE_BASE) / browser_name
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)  # only your macOS user can read the cookies
    except OSError:
        pass
    return path


@contextmanager
def open_context(headless: bool, browser: str, brave_path: str | None,
                 profile_base: Path | None) -> Iterator[object]:
    """Launch a persistent browser context (cookies survive between runs)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as err:
        raise SystemExit("Playwright is not installed. Run `uv sync` (or `pip install -r requirements.txt`) "
                         "and `uv run playwright install chromium` in scraper/.") from err
    name, exe = resolve_browser(browser, brave_path)
    pdir = profile_dir(profile_base, name)
    print(f"browser: {name}{' (' + exe + ')' if exe else ' (Playwright bundled)'}; profile: {pdir}",
          file=sys.stderr)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(pdir),
            executable_path=exe,
            headless=headless,
            viewport={"width": 1400, "height": 1000},
            # Drop the "controlled by automated software" infobar flag so the
            # login window looks like a normal browser. No other tricks.
            ignore_default_args=["--enable-automation"],
        )
        try:
            yield ctx
        finally:
            ctx.close()


def _first_page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def signed_in(page, league_id: str) -> bool:
    """Load league home and decide if the session is valid."""
    page.goto(urls.league_home(league_id), wait_until="domcontentloaded", timeout=60_000)
    html = page.content()
    return not parse.is_login_page(page.url, html) and parse.looks_like_league_page(html, league_id)


def login(ctx, league_id: str, timeout_s: int = 600) -> bool:
    """Open Yahoo Fantasy in the (headed) window and wait until the user has
    signed in. Returns True on success. The user does all the typing."""
    page = _first_page(ctx)
    page.goto(urls.league_home(league_id), wait_until="domcontentloaded", timeout=60_000)
    print("\nA browser window is open. Sign in to Yahoo there (passkey / Touch ID / phone).\n"
          "This script does not see or store your credentials. Waiting up to "
          f"{timeout_s // 60} minutes...", file=sys.stderr)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if ctx.pages:
                page = ctx.pages[-1]
            url = page.url
            if re.search(rf"fantasysports\.yahoo\.com/nba/{league_id}(?:[/?#]|$)", url) \
                    and not parse.is_login_page(url):
                html = page.content()
                if parse.looks_like_league_page(html, league_id):
                    return True
            elif "fantasysports.yahoo.com" in url and "/nba/" not in url:
                # Yahoo sometimes lands on the Fantasy home page after login.
                page.goto(urls.league_home(league_id), wait_until="domcontentloaded", timeout=60_000)
        except Exception:  # noqa: BLE001 - page navigating mid-check; try again
            pass
        time.sleep(2)
    return False


class PlaywrightFetcher:
    """``fetch(url, label) -> html`` backed by one browser tab.

    Polite by design: one request at a time, ``delay`` seconds (+ jitter)
    between pages, images/fonts/media not downloaded, backs off on HTTP 429."""

    def __init__(self, ctx, delay: float = 2.5, debug_dir: Path | None = None):
        self.page = _first_page(ctx)
        self.delay = delay
        self.debug_dir = debug_dir
        self._last = 0.0
        self.index: list[dict] = []
        # Skip heavy resources we don't parse: lighter on Yahoo and faster.
        self.page.route(re.compile(r".*\.(png|jpe?g|gif|webp|svg|woff2?|ttf|mp4)(\?.*)?$"),
                        lambda route: route.abort())
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)

    def _wait_turn(self) -> None:
        wait = self._last + self.delay + random.uniform(0, self.delay / 2) - time.time()
        if wait > 0:
            time.sleep(wait)

    def __call__(self, url: str, label: str) -> str:
        for attempt in range(3):
            self._wait_turn()
            resp = self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:  # let late JS fill in tables, but don't wait forever
                self.page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:  # noqa: BLE001
                pass
            self._last = time.time()
            status = resp.status if resp else 0
            if status == 429 or status >= 500:
                backoff = 30 * (attempt + 1)
                print(f"  HTTP {status} on {label}; backing off {backoff}s", file=sys.stderr)
                time.sleep(backoff)
                continue
            break
        html = self.page.content()
        final_url = self.page.url
        if self.debug_dir:
            self._dump(label, url, final_url, status, html)
        if parse.is_login_page(final_url, html):
            raise SessionExpired(f"redirected to sign-in while loading {label}")
        return html

    def _dump(self, label: str, url: str, final_url: str, status: int, html: str) -> None:
        """Save raw HTML (and any embedded JSON) so parsers can be fixed later."""
        from .embedded import extract_embedded_json

        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label)
        (self.debug_dir / f"{safe}.html").write_text(html, encoding="utf-8")
        state = extract_embedded_json(html)
        if state:
            (self.debug_dir / f"{safe}.state.json").write_text(json.dumps(state, indent=1)[:5_000_000],
                                                               encoding="utf-8")
        self.index.append({"label": label, "url": url, "final_url": final_url, "status": status,
                           "bytes": len(html), "embedded_json_blobs": len(state)})
        (self.debug_dir / "index.json").write_text(json.dumps(self.index, indent=1), encoding="utf-8")
