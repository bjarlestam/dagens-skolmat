#!/usr/bin/env python3
"""Fetch school lunch menus from Mashie (Matilda Platform)."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SCHOOLS = {
    "kunskapsskolan-taby": {
        "provider": "google-docs",
        "url": "https://docs.google.com/document/d/1CtM2hp0F8hBbV-ZN-3hYWjwvsnFpxGUThdV34hanhFI/edit",
    },
    "olympia": {
        "provider": "mashie",
        "url": "https://mpi.mashie.matildaplatform.com/public/app/Vallentuna%20kommun/b22e74ea",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dagens-skolmat/1.0)",
    "Cookie": "cookieLanguage=sv-SE",
}

STOCKHOLM = ZoneInfo("Europe/Stockholm")
ALLOWED_HOSTS = {"docs.google.com", "mpi.mashie.matildaplatform.com"}
GOOGLE_DOC_EXPORT_HOST_RE = re.compile(r"^doc-[a-z0-9-]+-docstext\.googleusercontent\.com$")
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_MENU_IMAGES = 50
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 30 * 1024 * 1024


def validate_source_url(url: str) -> None:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or (hostname not in ALLOWED_HOSTS and not GOOGLE_DOC_EXPORT_HOST_RE.fullmatch(hostname))
    ):
        raise ValueError(f"Refusing untrusted menu URL: {url}")


class AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to the configured school-menu hosts."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_source_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


URL_OPENER = urllib.request.build_opener(AllowlistedRedirectHandler())


def normalize_mashie_url(url: str) -> str:
    url = url.rstrip(" /")
    if "mashie.com" in url:
        url = url.replace("mashie.com", "mashie.matildaplatform.com")
    return url


def fetch_bytes(url: str, max_bytes: int) -> bytes:
    request_url = normalize_mashie_url(url)
    validate_source_url(request_url)
    request = urllib.request.Request(request_url, headers=HEADERS)
    with URL_OPENER.open(request, timeout=30) as response:
        validate_source_url(response.geturl())
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("Menu response is too large")
        content = response.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Menu response is too large")
        return content


def fetch_html(url: str) -> str:
    return fetch_bytes(url, MAX_HTML_BYTES).decode()


class MashiePanelParser(HTMLParser):
    """Read Mashie's server-rendered daily menu panels without executing page JavaScript."""

    def __init__(self) -> None:
        super().__init__()
        self.panels: list[dict[str, str]] = []
        self._panel_depth = 0
        self._current_panel: dict[str, str] | None = None
        self._collecting: str | None = None
        self._collect_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set(dict(attrs).get("class", "").split())
        if tag == "div" and "panel" in classes and self._panel_depth == 0:
            self._panel_depth = 1
            self._current_panel = {"header": "", "dish": ""}
        elif self._panel_depth and tag == "div":
            self._panel_depth += 1

        if self._panel_depth and self._collecting is None and self._current_panel:
            if "panel-heading" in classes:
                self._collecting = "header"
                self._collect_depth = 1
            elif "app-daymenu-name" in classes and not self._current_panel["dish"]:
                self._collecting = "dish"
                self._collect_depth = 1
        elif self._collecting:
            self._collect_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._collecting:
            self._collect_depth -= 1
            if self._collect_depth == 0:
                self._collecting = None

        if self._panel_depth and tag == "div":
            self._panel_depth -= 1
            if self._panel_depth == 0 and self._current_panel:
                self.panels.append(self._current_panel)
                self._current_panel = None

    def handle_data(self, data: str) -> None:
        if self._collecting and self._current_panel:
            self._current_panel[self._collecting] += data


SWEDISH_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "maj": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}


def parse_mashie_panel_menu(html: str) -> list[dict]:
    parser = MashiePanelParser()
    parser.feed(html)
    days: list[dict] = []

    for panel in parser.panels:
        header = " ".join(panel["header"].split()).lower()
        dish = " ".join(panel["dish"].split())
        match = re.search(r"(\d{1,2})\s+([a-zåäö]+)", header)
        if not match or not dish:
            continue
        month = SWEDISH_MONTHS.get(match.group(2)[:3])
        if not month:
            continue
        day = int(match.group(1))
        days.append({"date": f"{infer_year(month, day):04d}-{month:02d}-{day:02d}", "dish": dish})

    return sorted(days, key=lambda item: item["date"])


def parse_mashie_menu(html: str) -> list[dict]:
    script_match = re.search(r"<script>\s*(var\s+\w+\s*=\s*\{.*?</script>)", html, re.DOTALL)
    if not script_match:
        return parse_mashie_panel_menu(html)

    script_body = script_match.group(1)
    json_start = script_body.find("{")
    if json_start == -1:
        raise ValueError("Could not find weekData JSON in Mashie response")

    json_text = script_body[json_start:]
    json_text = json_text[: json_text.rfind("}") + 1]
    json_text = re.sub(
        r"new Date\((\d+)\)",
        lambda m: m.group(1),
        json_text,
    )
    data = json.loads(json_text)

    days: list[dict] = []
    seen_dates: set[str] = set()

    for week in data.get("Weeks", [])[:2]:
        for day in week.get("Days", []):
            timestamp_ms = day.get("DayMenuDate")
            if timestamp_ms is None:
                continue

            entry_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone(
                STOCKHOLM
            )
            date_key = entry_date.date().isoformat()
            if date_key in seen_dates:
                continue

            dish = next(
                (
                    course.get("DayMenuName", "").strip()
                    for course in day.get("DayMenus", [])
                    if course.get("DayMenuName", "").strip()
                ),
                None,
            )
            if not dish:
                continue

            seen_dates.add(date_key)
            days.append({"date": date_key, "dish": dish})

    days.sort(key=lambda item: item["date"])
    return days


GOOGLE_DOC_ID_RE = re.compile(r"docs\.google\.com/document/d/([\w-]+)")
DAY_RE = re.compile(
    r"^(m[åa]ndag|tisdag|onsdag|torsdag|fredag)\s+(\d{1,2})/(\d{1,2})$", re.IGNORECASE
)
MAIN_DISH_RE = re.compile(r"^huvudr\w*t\s*:\s*(.+)$", re.IGNORECASE)
NEXT_FIELD_RE = re.compile(r"^(gr\w*|huvudr\w*t)\s*:?", re.IGNORECASE)


def google_docx_url(url: str) -> str:
    match = GOOGLE_DOC_ID_RE.search(url)
    if not match:
        raise ValueError("Could not extract Google document id")
    return f"https://docs.google.com/document/d/{match.group(1)}/export?format=docx"


def infer_year(month: int, day: int) -> int:
    """Choose the year nearest to today for a day/month with no year."""
    today = datetime.now(tz=STOCKHOLM).date()
    candidates = [datetime(today.year + offset, month, day).date() for offset in (-1, 0, 1)]
    return min(candidates, key=lambda candidate: abs((candidate - today).days)).year


def clean_ocr_dish(dish: str) -> str:
    """Correct a small set of stable OCR confusions in the school menu images."""
    return re.sub(r"\bcon came\b", "con carne", dish, flags=re.IGNORECASE)


def parse_google_docs_menu(document: bytes) -> list[dict]:
    """Extract main dishes from the menu images in Kunskapsskolan's public document."""
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise RuntimeError("tesseract is required to read the Google Docs menu images")

    days: list[dict] = []
    seen_dates: set[str] = set()

    with tempfile.TemporaryDirectory() as temporary_directory:
        with zipfile.ZipFile(io.BytesIO(document)) as archive:
            image_entries = sorted(
                (entry for entry in archive.infolist() if entry.filename.startswith("word/media/")),
                key=lambda entry: int(re.search(r"\d+", Path(entry.filename).stem).group()),
            )
            if len(image_entries) > MAX_MENU_IMAGES:
                raise ValueError("Menu document has too many images")
            total_image_bytes = sum(entry.file_size for entry in image_entries)
            if total_image_bytes > MAX_TOTAL_IMAGE_BYTES or any(
                entry.file_size > MAX_IMAGE_BYTES for entry in image_entries
            ):
                raise ValueError("Menu document images are too large")

            for image_entry in image_entries:
                image_path = Path(temporary_directory) / Path(image_entry.filename).name
                image_path.write_bytes(archive.read(image_entry))
                result = subprocess.run(
                    [tesseract, str(image_path), "stdout", "-l", "eng", "--psm", "6"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                lines = [" ".join(line.split()) for line in result.stdout.splitlines() if line.strip()]
                current_date: str | None = None
                collecting_dish = False
                dish_lines: list[str] = []

                def save_dish() -> None:
                    nonlocal collecting_dish, dish_lines
                    if current_date and dish_lines and current_date not in seen_dates:
                        days.append({"date": current_date, "dish": clean_ocr_dish(" ".join(dish_lines))})
                        seen_dates.add(current_date)
                    collecting_dish = False
                    dish_lines = []

                for line in lines:
                    day_match = DAY_RE.match(line)
                    if day_match:
                        save_dish()
                        day, month = int(day_match.group(2)), int(day_match.group(3))
                        current_date = f"{infer_year(month, day):04d}-{month:02d}-{day:02d}"
                        continue
                    dish_match = MAIN_DISH_RE.match(line)
                    if dish_match:
                        save_dish()
                        collecting_dish = True
                        dish_lines = [dish_match.group(1)]
                        continue
                    if collecting_dish and NEXT_FIELD_RE.match(line):
                        save_dish()
                    elif collecting_dish:
                        dish_lines.append(line)
                save_dish()

    days.sort(key=lambda item: item["date"])
    return days


def main() -> int:
    output_path = Path(__file__).resolve().parent.parent / "data" / "menus.json"
    existing_menus: dict[str, dict] = {}
    if output_path.exists():
        try:
            existing_menus = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Could not read existing menu cache", file=sys.stderr)
    menus: dict[str, dict] = {}
    errors: list[str] = []
    successful_schools: set[str] = set()

    for school_key, school in SCHOOLS.items():
        try:
            url = school["url"]
            if school["provider"] == "mashie":
                days = parse_mashie_menu(fetch_html(url))
                source = normalize_mashie_url(url)
            elif school["provider"] == "google-docs":
                days = parse_google_docs_menu(fetch_bytes(google_docx_url(url), MAX_DOCUMENT_BYTES))
                source = url
            else:
                raise ValueError(f"Unknown menu provider: {school['provider']}")
            if not days:
                raise ValueError("No menu days found")
            menus[school_key] = {
                "source": source,
                "updated": datetime.now(tz=STOCKHOLM).isoformat(),
                "days": days,
            }
            successful_schools.add(school_key)
        except Exception as exc:  # noqa: BLE001 - report all fetch failures
            errors.append(f"{school_key}: {exc}")
            if school_key in existing_menus:
                menus[school_key] = existing_menus[school_key]

    if not successful_schools:
        print("\n".join(errors), file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(menus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")

    if errors:
        print("\n".join(errors), file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
