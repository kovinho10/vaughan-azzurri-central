#!/usr/bin/env python3
"""Fill data/recent-scores.json with real world football results only.

Preserves local/OSL verified results already present, then adds ESPN-powered
completed world football results up to maxResults. Intended for the 4am
source-of-truth cron.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORES_PATH = ROOT / "data" / "recent-scores.json"
TORONTO = ZoneInfo("America/Toronto")
# At 4 AM Toronto time, ESPN "today" is usually still upcoming fixtures.
# Query a small Toronto-local date range so late finals and previous-day results are not missed.
LOCAL_NOW = datetime.now(TORONTO)
WINDOW_DAYS = 3
TARGET_DATES = [(LOCAL_NOW - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(1, WINDOW_DAYS + 1)]
UPDATED = LOCAL_NOW.strftime("%Y-%m-%d")
MAX_RESULTS = 20

LEAGUES = [
    ("eng.1", "Premier League"),
    ("esp.1", "La Liga"),
    ("ita.1", "Serie A"),
    ("ger.1", "Bundesliga"),
    ("fra.1", "Ligue 1"),
    ("uefa.champions", "Champions League"),
    ("uefa.europa", "Europa League"),
    ("uefa.europa.conf", "Conference League"),
]


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 OpenClaw Vaughan score updater"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def event_to_score(event: dict, league_label: str) -> dict | None:
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    home_name = (home.get("team") or {}).get("shortDisplayName") or (home.get("team") or {}).get("displayName")
    away_name = (away.get("team") or {}).get("shortDisplayName") or (away.get("team") or {}).get("displayName")
    if not home_name or not away_name:
        return None

    status_type = ((comp.get("status") or {}).get("type") or {})
    completed = bool(status_type.get("completed"))
    if not completed:
        return None

    return {
        "comp": league_label,
        "source": "ESPN World Football",
        "date": (event.get("date") or "")[:10],
        "home": home_name,
        "away": away_name,
        "homeScore": int(home.get("score") or 0),
        "awayScore": int(away.get("score") or 0),
        "status": "Final",
    }


def load_existing() -> dict:
    if not SCORES_PATH.exists():
        return {"meta": {}, "scores": []}
    return json.loads(SCORES_PATH.read_text())


def main() -> int:
    existing = load_existing()
    existing_scores = existing.get("scores") if isinstance(existing.get("scores"), list) else []
    local_scores = [s for s in existing_scores if (s.get("source") or "").lower() not in {"espn world football", "world football"}]

    world_scores = []
    sources = []
    seen_world = set()
    for slug, label in LEAGUES:
        for target_date in TARGET_DATES:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={target_date}"
            sources.append(url)
            try:
                data = fetch_json(url)
            except Exception as exc:
                print(f"warn: failed {slug} {target_date}: {exc}", file=sys.stderr)
                continue
            for event in data.get("events") or []:
                item = event_to_score(event, label)
                if not item:
                    continue
                key = (item["comp"], item["date"], item["home"], item["away"])
                if key in seen_world:
                    continue
                seen_world.add(key)
                world_scores.append(item)

    combined = (local_scores + world_scores)[:MAX_RESULTS]
    meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    meta.update({
        "updated": UPDATED,
        "windowDays": WINDOW_DAYS,
        "maxResults": MAX_RESULTS,
        "status": "local_plus_world_results" if local_scores and world_scores else ("world_results_only" if world_scores else "no_verified_recent_results_found"),
        "worldSource": "ESPN soccer scoreboard APIs",
        "sources": list(dict.fromkeys((meta.get("sources") or []) + sources)),
    })
    SCORES_PATH.write_text(json.dumps({"meta": meta, "scores": combined}, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {len(combined)} score-centre item(s): {len(local_scores)} local, {len(world_scores)} world fetched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
