"""A real browser (Playwright + Chromium) for forms a plain HTTP fetch can't handle.

Optional add-on: Playwright is imported only when a browser is needed, so the rest of the app
runs without it.

Privacy: the saved profile (`<data_dir>/browser-profile`) is only ever opened for signing in to
Google. Reading and submitting forms happens in a throwaway context that is handed copies of the
login cookies, so nothing typed into a form (autofill, history, cache) can land on disk.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import get_settings

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Frame, Page, Playwright

INSTALL_HINT = (
    "This form needs the browser add-on: run `pip install playwright` then `playwright install chromium`, "
    "restart Form Finder, and try again."
)
LOGIN_URL = "https://accounts.google.com/"
_CONTROLS = "input:not([type=hidden]), select, textarea"
_GOOGLE_AUTH_COOKIES = {"SID", "__Secure-1PSID", "__Secure-3PSID"}


class BrowserError(RuntimeError):
    """The browser couldn't do its job. The message is shown to the user as-is."""


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def profile_dir(data_dir: Path | None = None) -> Path:
    """Where the Google login cookies live. Never holds form answers."""
    return (data_dir or get_settings().data_dir) / "browser-profile"


def on_login_page(url: str) -> bool:
    return "accounts.google.com" in url


def _short(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


@asynccontextmanager
async def _playwright() -> AsyncIterator[Playwright]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise BrowserError(INSTALL_HINT) from e
    try:
        pw = await async_playwright().start()
    except NotImplementedError as e:
        # Windows' selector event loop can't start subprocesses (uvicorn --reload uses it).
        raise BrowserError("The browser can't start in this mode. Run Form Finder without --reload.") from e
    try:
        yield pw
    finally:
        await pw.stop()


def _plain(e: Exception) -> str:
    """A Playwright failure in words a user can act on."""
    msg = str(e)
    if "Timeout" in msg:
        return "The page took too long to respond. Try again in a moment, or open the form yourself."
    if "net::" in msg:
        return "Couldn't reach the form's website. Check your internet connection and try again."
    return "The browser couldn't finish on that page. Try again, or open the form yourself."


def _launch_error(e: Exception) -> BrowserError:
    msg = str(e)
    if "Executable doesn't exist" in msg:
        return BrowserError("The browser add-on is missing Chromium. Run `playwright install chromium` and retry.")
    if "ProcessSingleton" in msg or "SingletonLock" in msg or "user data directory is already in use" in msg:
        return BrowserError("The Google sign-in window is still open. Close it, then try again.")
    return BrowserError(f"Couldn't start the browser: {_short(e)}")


async def _saved_login(pw: Playwright, profile: Path) -> dict[str, Any] | None:
    """Copy the login cookies out of the saved profile (if there is one) and close it again."""
    if not profile.is_dir():
        return None
    try:
        ctx = await pw.chromium.launch_persistent_context(str(profile), headless=True)
    except Exception as e:
        raise _launch_error(e) from e
    try:
        return await ctx.storage_state()
    except Exception as e:
        raise BrowserError("Couldn't read the saved Google sign-in. Sign in to Google again and retry.") from e
    finally:
        await ctx.close()


@asynccontextmanager
async def browser_context(profile: Path | None = None) -> AsyncIterator[BrowserContext]:
    """A headless, throwaway browser context carrying the saved Google login (if any).

    Playwright errors raised while using it come out as `BrowserError` with a short message.
    """
    async with _playwright() as pw:
        from playwright.async_api import Error as PlaywrightError  # _playwright() checked it's installed

        state = await _saved_login(pw, profile or profile_dir())
        try:
            browser: Browser = await pw.chromium.launch(headless=True)
        except Exception as e:
            raise _launch_error(e) from e
        try:
            context = await browser.new_context(storage_state=state)
            try:
                yield context
            except PlaywrightError as e:
                raise BrowserError(_plain(e)) from e
            finally:
                await context.close()
        finally:
            await browser.close()


async def goto(page: Page, url: str, timeout_ms: int = 30_000) -> None:
    from playwright.async_api import Error as PlaywrightError

    try:
        await page.goto(url, wait_until="load", timeout=timeout_ms)
    except PlaywrightError as e:
        raise BrowserError(f"Couldn't open that link in the browser: {_short(e)}") from e


async def settle(page: Page, timeout_ms: int = 10_000) -> None:
    """Wait until the page stops talking to the network (or give up quietly)."""
    from playwright.async_api import Error as PlaywrightError

    with suppress(PlaywrightError):
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)


async def _count_controls(frame: Frame) -> int:
    from playwright.async_api import Error as PlaywrightError

    try:
        return await frame.locator(_CONTROLS).count()
    except PlaywrightError:  # frame detached or navigating
        return 0


async def find_form_frame(page: Page, timeout_ms: int = 20_000) -> Frame | None:
    """The frame (main page or nested iframe) with the most form controls.

    Apps Script renders the user's page two iframes deep and fills them in after load, so poll
    until some frame has controls and the count stops changing.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000
    best, last = None, -1
    while True:
        counts = [(await _count_controls(f), f) for f in page.frames]
        n, frame = max(counts, key=lambda c: c[0], default=(0, None))
        if n and n == last:
            return frame
        best, last = (frame if n else best), n
        if loop.time() >= deadline:
            return best
        await asyncio.sleep(0.4)


def _has_display() -> bool:
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


async def login_interactive(profile: Path | None = None, timeout_s: float = 300) -> bool:
    """Open a visible Chromium on Google's sign-in page using the saved profile.

    Returns once the user closes the window (or after `timeout_s`), saying whether a Google login
    is now stored.
    """
    if not _has_display():
        raise BrowserError(
            "Signing in opens a browser window, which only works when Form Finder runs on your own computer "
            "(no screen found here). Use the “Open prefilled in my browser” option instead."
        )
    profile = profile or profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    async with _playwright() as pw:
        try:
            ctx = await pw.chromium.launch_persistent_context(str(profile), headless=False, no_viewport=True)
        except Exception as e:
            raise _launch_error(e) from e
        closed = asyncio.Event()
        ctx.on("close", lambda _: closed.set())

        def page_closed(_: Any) -> None:
            if not ctx.pages:
                closed.set()

        ctx.on("page", lambda p: p.on("close", page_closed))
        for p in ctx.pages:
            p.on("close", page_closed)
        signed_in = False
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(LOGIN_URL)
            except Exception as e:
                raise BrowserError("Couldn't open Google's sign-in page. Check your internet connection.") from e
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout_s
            while not closed.is_set() and loop.time() < deadline:
                with suppress(Exception):  # the window may be closing under us
                    cookies = await ctx.cookies("https://accounts.google.com")
                    signed_in = any(c["name"] in _GOOGLE_AUTH_COOKIES for c in cookies)
                with suppress(TimeoutError):
                    await asyncio.wait_for(closed.wait(), timeout=1)
        finally:
            with suppress(Exception):
                await ctx.close()
        return signed_in
