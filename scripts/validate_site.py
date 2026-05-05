#!/usr/bin/env python3
"""Lightweight static validation for the Vaughan Azzurri Central site."""
from __future__ import annotations

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

def main() -> int:
    parser = SiteHTMLParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))

    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    if duplicates:
        fail(f"duplicate ids: {', '.join(duplicates)}")

    for target in ("previewHomeLogo", "previewOppLogo", "tickerTrack"):
        if target not in parser.ids:
            fail(f"missing expected id: {target}")

    for rel in parser.assets:
        if rel.startswith(("/", "//")):
            continue
        if not (ROOT / rel).exists():
            fail(f"missing asset referenced by HTML: {rel}")

    for path in sorted(DATA_DIR.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))

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
