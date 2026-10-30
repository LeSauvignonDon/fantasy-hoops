"""Local Yahoo Fantasy Basketball scraper for the `hoops` Rust tool.

Module map (read in this order if you're learning):

* ``stats``     - turn table cells / Yahoo stat ids into the Rust ``StatLine`` shape
* ``timeutil``  - dates, fantasy weeks, transaction timestamps
* ``embedded``  - find JSON "app state" that Yahoo embeds in <script> tags
* ``parse``     - pure functions: HTML string in, plain Python data out
* ``build``     - assemble parsed pieces into the exact snapshot JSON + validate
* ``scrape``    - the crawl plan (which pages, in which order), browser-agnostic
* ``browser``   - Playwright: persistent profile, Brave/Chromium, login check
* ``cli``       - ``login`` / ``status`` / ``snapshot`` commands

Everything except ``browser`` and ``cli`` is pure and unit-tested offline.
"""

__version__ = "0.1.0"
