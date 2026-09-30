#!/usr/bin/env python3
"""Search Facebook Groups in a local browser and export results to CSV."""

from __future__ import annotations

import argparse
import csv
import html
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


PROJECT_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
EXPORT_DIR = PROJECT_DIR / "exports"
PROFILE_DIR = PROJECT_DIR / "browser-profile"
SEARCH_URL = "https://www.facebook.com/groups/search/groups_home/?q={}"
CSV_COLUMNS = [
    "group_name",
    "url",
]
EXCLUDED_GROUP_PATHS = {
    "create",
    "discover",
    "feed",
    "joined",
    "search",
    "your_groups",
}


class FacebookScannerError(RuntimeError):
    """Raised for a recoverable, user-facing scanner problem."""


@dataclass
class RawGroup:
    name: str
    url: str
    card_text: str


def clean_text(value: Any) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_lines(value: Any) -> list[str]:
    if not value:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for raw_line in str(value).replace("\r", "\n").split("\n"):
        line = clean_text(raw_line)
        key = line.casefold()
        if line and key not in seen:
            output.append(line)
            seen.add(key)
    return output


def canonical_group_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.netloc and not parsed.netloc.casefold().endswith("facebook.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].casefold() != "groups":
        return ""
    identifier = parts[1].strip()
    if not identifier or identifier.casefold() in EXCLUDED_GROUP_PATHS:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        return ""
    return f"https://www.facebook.com/groups/{identifier}/"


def choose_group_name(anchor_name: str, card_text: str, url: str) -> str:
    ignored = {
        "join",
        "join group",
        "view group",
        "visit group",
        "see more",
        "facebook",
    }
    for candidate in [anchor_name, *clean_lines(card_text)]:
        cleaned = clean_text(candidate)
        folded = cleaned.casefold()
        if (
            cleaned
            and folded not in ignored
            and " members" not in folded
            and not re.match(r"^(public|private) group\b", folded)
            and len(cleaned) <= 200
        ):
            return cleaned
    return url.rstrip("/").rsplit("/", 1)[-1]


def group_row(raw: RawGroup) -> dict[str, str]:
    url = canonical_group_url(raw.url)
    name = choose_group_name(raw.name, raw.card_text, url)
    return {
        "group_name": name,
        "url": url,
    }


def launch_browser(playwright: Any) -> tuple[BrowserContext, str]:
    errors: list[str] = []
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for channel, label in (("chrome", "Google Chrome"), ("msedge", "Microsoft Edge")):
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel=channel,
                headless=False,
                viewport={"width": 1365, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
                locale="en-US",
            )
            context.set_default_timeout(15_000)
            return context, label
        except PlaywrightError as exc:
            errors.append(f"{label}: {exc}")
    raise FacebookScannerError(
        "Could not start installed Google Chrome or Microsoft Edge. " + " | ".join(errors)
    )


def looks_logged_out(page: Page) -> bool:
    url = page.url.casefold()
    if "login" in url or "checkpoint" in url:
        return True
    selectors = (
        'input[name="email"]',
        'input[name="pass"]',
        'button[name="login"]',
        'form[action*="login"]',
    )
    return any(page.locator(selector).count() > 0 for selector in selectors)


def wait_for_login(page: Page, skip_wait: bool) -> None:
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60_000)
    time.sleep(random.uniform(1.2, 2.2))
    if not looks_logged_out(page):
        print("  Existing Facebook login found in the scanner profile.")
        return

    if skip_wait:
        raise FacebookScannerError(
            "Facebook login is required. Run run.bat and log in in the browser window."
        )

    print("\nFacebook login is required for Groups search.")
    print("Log in normally in the browser window. Your password is never read or stored by this app.")
    try:
        input("After Facebook finishes loading your account, return here and press Enter...")
    except EOFError as exc:
        raise FacebookScannerError(
            "Could not wait for login because the terminal is not interactive."
        ) from exc

    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60_000)
    time.sleep(random.uniform(1.0, 2.0))
    if looks_logged_out(page):
        raise FacebookScannerError(
            "Facebook still appears logged out. Complete login or any checkpoint and try again."
        )
    print("  Facebook login detected and saved in the local browser profile.")


def check_page_errors(page: Page) -> None:
    body = clean_text(page.locator("body").inner_text(timeout=20_000))
    blocked_phrases = (
        "you're temporarily blocked",
        "you’re temporarily blocked",
        "we limit how often you can",
        "too many requests",
        "something went wrong",
    )
    for phrase in blocked_phrases:
        if phrase in body.casefold():
            raise FacebookScannerError(
                "Facebook temporarily limited or blocked the search. Wait and try again later."
            )


def raw_groups_from_page(page: Page) -> list[RawGroup]:
    items = page.locator('a[href*="/groups/"]').evaluate_all(
        """
        (anchors) => anchors.map((anchor) => {
          let node = anchor;
          let bestText = '';
          for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
            const text = (node.innerText || '').trim();
            if (text.length > bestText.length && text.length <= 2500) bestText = text;
            if (node.getAttribute && node.getAttribute('role') === 'article') {
              bestText = text;
              break;
            }
          }
          return {
            name: (anchor.innerText || anchor.getAttribute('aria-label') || '').trim(),
            url: anchor.href || anchor.getAttribute('href') || '',
            card_text: bestText,
          };
        })
        """
    )
    output: list[RawGroup] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        output.append(
            RawGroup(
                name=str(item.get("name", "")),
                url=str(item.get("url", "")),
                card_text=str(item.get("card_text", "")),
            )
        )
    return output


def search_groups(page: Page, keyword: str, maximum: int) -> list[dict[str, str]]:
    url = SEARCH_URL.format(quote_plus(keyword))
    print(f'Opening Facebook Groups search for "{keyword}"...')
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightTimeoutError:
        print("  Facebook is still loading; continuing with the visible page...")
    time.sleep(random.uniform(2.0, 3.5))

    if looks_logged_out(page):
        raise FacebookScannerError("Facebook logged out before the search completed.")
    check_page_errors(page)

    rows: dict[str, dict[str, str]] = {}
    stalled_rounds = 0
    round_number = 0
    last_height = 0
    while len(rows) < maximum and stalled_rounds < 5:
        round_number += 1
        before = len(rows)
        for raw in raw_groups_from_page(page):
            row = group_row(raw)
            if not row["url"] or not row["group_name"]:
                continue
            rows.setdefault(row["url"].casefold(), row)
            if len(rows) >= maximum:
                break
        print(f"  Scan {round_number}: {len(rows)} unique groups found")

        if len(rows) == before:
            stalled_rounds += 1
        else:
            stalled_rounds = 0
        if len(rows) >= maximum:
            break

        current_height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(random.uniform(1.5, 3.0))
        check_page_errors(page)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height <= current_height and new_height == last_height:
            stalled_rounds += 1
        last_height = new_height

    return list(rows.values())[:maximum]


def scan_facebook(keyword: str, maximum: int, skip_login_wait: bool) -> list[dict[str, str]]:
    with sync_playwright() as playwright:
        context, browser_name = launch_browser(playwright)
        print(f"Using {browser_name} with profile: {PROFILE_DIR}")
        try:
            page = context.pages[0] if context.pages else context.new_page()
            wait_for_login(page, skip_login_wait)
            return search_groups(page, keyword, maximum)
        finally:
            context.close()


def merge_groups(
    collected: dict[str, dict[str, str]], rows: list[dict[str, str]]
) -> int:
    before = len(collected)
    for row in rows:
        url = canonical_group_url(row.get("url", ""))
        name = clean_text(row.get("group_name", ""))
        if url and name:
            collected.setdefault(url.casefold(), {"group_name": name, "url": url})
    return len(collected) - before


def load_saved_groups() -> dict[str, dict[str, str]]:
    collected: dict[str, dict[str, str]] = {}
    for path in sorted(EXPORT_DIR.glob("facebook_groups_*.csv")):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not set(CSV_COLUMNS).issubset(reader.fieldnames or []):
                    print(f"  Skipping CSV with unsupported columns: {path.name}")
                    continue
                merge_groups(collected, list(reader))
        except (OSError, UnicodeError, csv.Error) as exc:
            print(f"  Could not load {path.name}: {exc}", file=sys.stderr)
    return collected


def interactive_menu(args: argparse.Namespace) -> int:
    collected = load_saved_groups()
    print(f"\nFacebook Group Scanner — {len(collected)} saved unique groups loaded.")
    while True:
        print(f"\nCollected groups: {len(collected)}")
        print("1. Search for a keyword")
        print("2. Export all scanned groups to one CSV")
        print("3. Exit")
        try:
            choice = input("Choose an option (1-3): ").strip()
            if choice == "3":
                return 0
            if choice == "2":
                if not collected:
                    print("No groups collected yet. Run a search first.")
                    continue
                try:
                    output = export_csv(list(collected.values()), "all_searches")
                    print(f"Exported {len(collected)} unique groups.\nCSV file: {output}")
                except OSError as exc:
                    print(f"ERROR: Could not write the CSV: {exc}", file=sys.stderr)
                continue
            if choice != "1":
                print("Please choose 1, 2, or 3.")
                continue
            keyword = prompt_keyword()
            maximum = args.max_results or prompt_maximum()
            try:
                rows = scan_facebook(keyword, maximum, args.skip_login_wait)
            except (FacebookScannerError, PlaywrightError, OSError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                print("Previous results are still available from the export menu.")
                continue
            if not rows:
                print("No matching groups were found.")
                continue
            added = merge_groups(collected, rows)
            print(f"Search found {len(rows)} groups; {added} new groups added.")
            try:
                output = export_csv(rows, keyword)
                print(f"Search results saved: {output}")
            except OSError as exc:
                print(f"ERROR: Could not save this search: {exc}", file=sys.stderr)
                print("Results remain in this session. Use option 2 to retry saving.")
        except KeyboardInterrupt:
            print("\nCancelled. Returning to the menu; collected groups are retained.")
        except EOFError:
            print("\nInput closed. Exiting scanner.")
            return 0


def filename_for(keyword: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", keyword).strip("_")[:50] or "search"
    return f"facebook_groups_{slug}_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"


def export_csv(rows: list[dict[str, str]], keyword: str) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = EXPORT_DIR / filename_for(keyword)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output.resolve()


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc
    if not 1 <= number <= 500:
        raise argparse.ArgumentTypeError("must be between 1 and 500")
    return number


def prompt_keyword() -> str:
    while True:
        keyword = input("Search keyword: ").strip()
        if keyword:
            return keyword
        print("Please enter a keyword.")


def prompt_maximum() -> int:
    while True:
        value = input("Maximum number of results (1-500): ").strip()
        try:
            return positive_int(value)
        except argparse.ArgumentTypeError as exc:
            print(f"Please enter a valid number: {exc}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", help="Run a single search and export (otherwise open the menu)")
    parser.add_argument("--max-results", type=positive_int, help="Maximum groups (1-500)")
    parser.add_argument(
        "--skip-login-wait",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.keyword or "").strip():
        return interactive_menu(args)
    keyword = args.keyword.strip()
    maximum = args.max_results or prompt_maximum()
    print(f'\nSearching for Facebook groups matching "{keyword}" (up to {maximum})...')
    try:
        rows = scan_facebook(keyword, maximum, args.skip_login_wait)
    except KeyboardInterrupt:
        print("\nSearch cancelled.", file=sys.stderr)
        return 1
    except (FacebookScannerError, PlaywrightError, OSError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("\nNo matching groups were found. No CSV was created.")
        print("Facebook's page layout or search availability may have changed.")
        return 0

    try:
        output = export_csv(rows, keyword)
    except OSError as exc:
        print(f"\nERROR: Could not write the CSV: {exc}", file=sys.stderr)
        return 1

    print(f"\nExported {len(rows)} unique Facebook groups.")
    print(f"CSV file: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
