"""Adapter for observed public official feeds (undocumented, schema may change)."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import Asset, Dataset, FantasyScore, Price, Race
from .csv_provider import boolean, nullable_number


class ProviderError(ValueError):
    pass


class CachedHTTP:
    def __init__(self, directory: Path, ttl: int = 3600, timeout: int = 20,
                 offline: bool = False, refresh: bool = False):
        self.directory = directory
        self.ttl = ttl
        self.timeout = timeout
        self.offline = offline
        self.refresh = refresh
        self.timestamps: list[str] = []

    def get(self, url: str) -> dict:
        path = self.directory / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        cached = None
        if path.exists():
            try:
                cached = json.loads(path.read_text())
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
                if cached["url"] != url or "body" not in cached:
                    raise ValueError("Invalid cache envelope")
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderError(f"Invalid cache {path}; remove this file and refresh") from exc
            if self.offline or (not self.refresh and age < self.ttl):
                self.timestamps.append(cached["fetched_at"])
                return cached["body"]
        if self.offline:
            raise ProviderError(f"No cached response for {url}; run sync online first")
        try:
            request = Request(url, headers={"User-Agent": "f1fantasy-rollover/0.1", "Accept": "application/json"})
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise ProviderError(f"Could not fetch {url}: {exc}. Use --offline for an explicit cache fallback, "
                                "or --local PATH for a CSV/JSON import.") from exc
        timestamp = datetime.now(timezone.utc).isoformat()
        self.directory.mkdir(parents=True, exist_ok=True)
        # Atomic cache replacement prevents partial JSON after interruption.
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as handle:
            json.dump({"url": url, "fetched_at": timestamp, "body": body}, handle)
            temporary = handle.name
        os.replace(temporary, path)
        self.timestamps.append(timestamp)
        return body


def feed_rows(data: dict) -> list[dict]:
    try:
        rows = data["Data"]["Value"]
    except (KeyError, TypeError) as exc:
        raise ProviderError("Official feed schema changed: expected Data.Value") from exc
    if not isinstance(rows, list) or not rows or not all(isinstance(x, dict) for x in rows):
        raise ProviderError("Official feed is empty or Data.Value is not a list of objects")
    return rows


def parse_schedule(payload: dict, season: int) -> list[Race]:
    races = []
    for row in feed_rows(payload):
        if row.get("SessionType") != "Race":
            continue  # sprint and qualifying belong to the same fantasy weekend
        if int(row["Season"]) != season:
            continue
        if boolean(row.get("IsPostponed", 0)):
            continue
        completed = str(row["GDStatus"]) == "4" and str(row["MatchStatus"]) == "4"
        races.append(Race(f"{season}:{row['GamedayId']}", season, int(row["Gameday"]),
                          row["MeetingName"], datetime.fromisoformat(row["SessionStartDateISO8601"]).date(),
                          completed, row.get("MeetingLocation", "")))
    if not races:
        raise ProviderError(f"Official feed contains no races for {season}; it is a current-season feed. "
                            "Use a local historical export for older seasons.")
    return sorted(races, key=lambda r: r.round)


class OnlineProvider:
    def __init__(self, settings: dict, cache_dir: Path, season: int,
                 offline: bool = False, refresh: bool = False, http=None):
        self.settings = settings
        self.season = season
        self.http = http or CachedHTTP(cache_dir, settings["cache_ttl_seconds"],
                                       settings["timeout_seconds"], offline, refresh)
        self.offline = offline

    def fetch(self) -> Dataset:
        base = self.settings["base_url"].rstrip("/")
        races = parse_schedule(self.http.get(base + self.settings["schedule_path"]), self.season)
        dataset = Dataset(races=races, source=f"Official public F1 Fantasy feeds: {base}")
        upcoming = next((r for r in races if not r.completed), None)
        selected = [r for r in races if r.completed or r == upcoming]
        assets: dict[str, Asset] = {}
        current_ids: set[str] = set()
        for race in selected:
            path = self.settings["drivers_path"].format(round=race.id.split(":")[-1])
            rows = feed_rows(self.http.get(base + path))
            seen: set[str] = set()
            for row in rows:
                asset_id = f"{self.season}:{row['PlayerId']}"
                if asset_id in seen:
                    raise ProviderError(f"Duplicate PlayerId {asset_id} in {path}")
                seen.add(asset_id)
                active = boolean(row.get("IsActive"), nullable=True)
                asset = Asset(asset_id, row["DriverTLA"], row.get("FUllName") or row["DisplayName"],
                              row["PositionName"].lower(), active, row.get("TeamName") or "")
                assets[asset_id] = asset
                dataset.prices.append(Price(asset_id, race.id, nullable_number(row.get("Value"))))
                if race.completed:
                    points = nullable_number(row.get("GamedayPoints"))
                    # Inactive legacy records contain stale/placeholder points; never merge by TLA.
                    if active is not True:
                        points = None
                    dataset.scores.append(FantasyScore(asset_id, race.id, points,
                                                      "official" if active is True else "inactive" if active is False else "unknown"))
            current_ids = seen
        dataset.assets = [a if a.id in current_ids else replace(a, active=False)
                          for a in assets.values()]
        dataset.fetched_at = min(self.http.timestamps) if self.http.timestamps else ""
        dataset.warnings.append("Undocumented official feeds; inferred pricing model. Prices are interpreted as pre-race Value; validate before relying on it.")
        if self.offline:
            dataset.warnings.append("OFFLINE CACHE: calendar, prices, and status may be stale; fetched_at is the oldest response used.")
        dataset.check()
        return dataset
