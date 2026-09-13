#!/usr/bin/env python3
"""Fetch school lunch menus from Mashie (Matilda Platform)."""

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
from pathlib import Path
from zoneinfo import ZoneInfo

SCHOOLS = {
    "kunskapsskolan-taby": {
        "provider": "google-docs",
        "url": "https://docs.google.com/document/d/1CtM2hp0F8hBbV-ZN-3hYWjwvsnFpxGUThdV34hanhFI/edit",
    },
    "olympia": {
        "provider": "mashie",
        "url": "https://mpi.mashie.matildaplatform.com/public/menu/Vallentuna%20kommun/b22e74ea",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dagens-skolmat/1.0)",
    "Cookie": "cookieLanguage=sv-SE",
}

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def normalize_mashie_url(url: str) -> str:
    url = url.rstrip(" /")
    if "/app/" in url:
        url = url.replace("/app/", "/menu/")
    if "mashie.com" in url:
        url = url.replace("mashie.com", "mashie.matildaplatform.com")
    return url


def fetch_html(url: str) -> str:
    request = urllib.request.Request(normalize_mashie_url(url), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def parse_mashie_menu(html: str) -> list[dict]:
    script_match = re.search(r"<script>\s*(var\s+\w+\s*=\s*\{.*?</script>)", html, re.DOTALL)
    if not script_match:
        raise ValueError("Could not find menu script in Mashie response")

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
            image_names = sorted(
                (name for name in archive.namelist() if name.startswith("word/media/")),
                key=lambda name: int(re.search(r"\d+", Path(name).stem).group()),
            )
            for image_name in image_names:
                image_path = Path(temporary_directory) / Path(image_name).name
                image_path.write_bytes(archive.read(image_name))
                result = subprocess.run(
                    [tesseract, str(image_path), "stdout", "-l", "eng", "--psm", "6"],
                    check=True,
                    capture_output=True,
                    text=True,
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
    menus: dict[str, dict] = {}
    errors: list[str] = []

    for school_key, school in SCHOOLS.items():
        try:
            url = school["url"]
            if school["provider"] == "mashie":
                days = parse_mashie_menu(fetch_html(url))
                source = normalize_mashie_url(url)
            elif school["provider"] == "google-docs":
                days = parse_google_docs_menu(fetch_bytes(google_docx_url(url)))
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
        except Exception as exc:  # noqa: BLE001 - report all fetch failures
            errors.append(f"{school_key}: {exc}")

    if not menus:
        print("\n".join(errors), file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(menus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
