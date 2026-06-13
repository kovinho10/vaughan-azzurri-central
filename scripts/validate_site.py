#!/usr/bin/env python3
"""Lightweight static validation for the Vaughan Azzurri Central site."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
DATA_DIR = ROOT / "data"

class SiteHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.assets: list[str] = []
        self.scripts: list[str] = []
        self._in_script = False
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
        data = dict(attrs)
        if data.get("id"):
            self.ids.append(data["id"] or "")
        for key in ("src", "href"):
            value = data.get(key)
            if value and not re.match(r"^(https?:|webcal:|mailto:|tel:|#)", value):
                self.assets.append(value.split("?", 1)[0])
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._in_script = False
    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.scripts.append(data)

def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)

def warn(msg: str) -> None:
    print(f"WARN: {msg}")

def main() -> int:
    parser = SiteHTMLParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))

    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    if duplicates:
        fail(f"duplicate ids: {', '.join(duplicates)}")

    for rel in parser.assets:
        if rel.startswith(("/", "//")):
            continue
        if not (ROOT / rel).exists():
            fail(f"missing asset referenced by HTML: {rel}")

    site_data = None
    for path in sorted(DATA_DIR.glob("*.json")):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "site-data.json":
            site_data = parsed

    roster_names = set()
    roster_csv = DATA_DIR / "roster.csv"
    if roster_csv.exists():
        with roster_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("full_name") or "").strip()
                if name:
                    roster_names.add(name)
    elif site_data:
        roster_names = {
            f"{player.get('first', '')} {player.get('last', '')}".strip()
            for player in site_data.get("roster", [])
            if f"{player.get('first', '')} {player.get('last', '')}".strip()
        }

    results_csv = DATA_DIR / "match-results.csv"
    if results_csv.exists() and roster_names:
        with results_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for item in filter(None, (row.get("scorers") or "").split(";")):
                    name = item.split(":", 1)[0].strip()
                    if name and name not in roster_names:
                        # Official OSL scorer feeds can include spelling variants or call-ups before
                        # the local roster is refreshed. Warn, but do not block automated fixture/result sync.
                        warn(f"match-results.csv scorer is not on roster: {name}")

    attendance_csv = DATA_DIR / "attendance.csv"
    if attendance_csv.exists() and roster_names:
        with attendance_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for column in ("present", "absent"):
                    for name in filter(None, (row.get(column) or "").split(";")):
                        name = name.strip()
                        if name and name not in roster_names:
                            fail(f"attendance.csv {column} player is not on roster: {name}")

    if parser.scripts:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tmp:
            tmp.write("\n".join(parser.scripts))
            tmp_path = tmp.name
        result = subprocess.run(["node", "--check", tmp_path], capture_output=True, text=True)
        Path(tmp_path).unlink(missing_ok=True)
        if result.returncode != 0:
            fail(result.stderr.strip() or "JavaScript syntax check failed")

    print("OK: site validation passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
