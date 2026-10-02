#!/usr/bin/env python3
"""One Chromium per test process, shared by every browser test in it.

Each browser test used to start Playwright and launch a fresh Chromium of its own, pay ~0.29s for
it, and throw it away. Across the suite's browser tests that is most of a minute of doing nothing
but starting and stopping a browser. The browser is stateless between tests as far as these tests
care, so there is no reason to have more than one.

WHAT IS NOT SHARED: the page. `browser.new_page()` opens a fresh BrowserContext under the hood, so
every test gets its own cookies, its own `localStorage` and its own routes. That matters here more
than usual — the viewer remembers a reader's settings and which tab they were on, all in
`localStorage`. A shared context would leak one test's remembered state into the next and the failure
would look like a viewer bug.

WHY NOT A FIXTURE: the project's tests are plain top-level functions with `make_*` builders and no
pytest fixtures, so this is a lazy module-level singleton behind a function, closed at exit.

Under `-n auto` every xdist worker is its own PROCESS, so each gets its own browser and nothing is
shared across them. Playwright's sync API is single-threaded by design and this keeps it that way.

WHICH ENGINE: Chromium by default. `COYOMAP_BROWSER=webkit` runs the same tests in Safari's engine,
on request, for a layout break only Safari shows (`playwright install webkit` first). Firefox is
accepted too, but it does not start from inside the Claude desktop app.
"""
from __future__ import annotations

import atexit
import os
from typing import Any

import pytest

_STATE: dict[str, Any] = {}


def shared_browser() -> Any:
    """The process's one browser (Chromium unless `COYOMAP_BROWSER` names another), launched on first use.

    Skips the calling test (rather than erroring) when Playwright or the browser binary is missing —
    the same bargain the rest of the suite makes, so a Python-only environment still gets a clean
    run."""
    if "browser" in _STATE:
        return _STATE["browser"]
    api = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
    pw = api.sync_playwright().start()
    engine = os.environ.get("COYOMAP_BROWSER", "chromium")
    if engine not in ("chromium", "webkit", "firefox"):
        pw.stop()
        raise ValueError(f"COYOMAP_BROWSER must be chromium, webkit or firefox, not {engine!r}")
    try:
        browser = getattr(pw, engine).launch()
    except Exception as exc:  # the driver is installed but the browser binary is not
        pw.stop()
        pytest.skip(f"{engine} not available: {exc}")
    _STATE["pw"] = pw
    _STATE["browser"] = browser
    atexit.register(_close)
    return browser


def new_page(stylesheet: str | None = None) -> Any:
    """A fresh page on the shared browser, wired the way every browser test wants it.

    `page.js_errors` collects anything the viewer throws: a page that renders the right thing while
    throwing has still failed. `stylesheet` serves that text in place of the viewer's own from the
    first layout on, which is the only way to test what the viewer does when its stylesheet cannot
    give the drawing room."""
    page = shared_browser().new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.js_errors = errors  # type: ignore[attr-defined]
    if stylesheet is not None:
        page.route("**/viewer.css", lambda route: route.fulfill(
            status=200, content_type="text/css", body=stylesheet))
    return page


def _close() -> None:
    """Shut the browser down at process exit. Every step is best-effort: the interpreter is on its
    way out, and a noisy teardown would turn a green run into a confusing one."""
    browser = _STATE.pop("browser", None)
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    pw = _STATE.pop("pw", None)
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass
