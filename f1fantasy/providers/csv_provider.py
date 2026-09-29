"""A JSON bundle or directory of normalized CSV tables; blanks remain missing."""
import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path

from ..config import decimal
from ..models import Asset, Dataset, FantasyScore, Price, PriceChange, Race


def nullable_number(value):
    return None if value is None or str(value).strip() == "" else decimal(value)


def boolean(value, *, nullable=False):
    if value is None or value == "":
        if nullable:
            return None
        raise ValueError("Missing required boolean")
    if str(value).lower() in ("true", "1"):
        return True
    if str(value).lower() in ("false", "0"):
        return False
    raise ValueError(f"Invalid boolean: {value!r}")


def parse_bundle(data: dict, source: str = "") -> Dataset:
    dataset = Dataset(
        races=[Race(str(r["id"]), int(r["season"]), int(r["round"]), r["name"],
                    date.fromisoformat(r["date"]), boolean(r["completed"]), r.get("location", ""))
               for r in data["races"]],
        assets=[Asset(str(a["id"]), a["code"], a["name"], a["kind"], boolean(a.get("active"), nullable=True), a.get("team") or "")
                for a in data["assets"]],
        scores=[FantasyScore(str(s["asset_id"]), str(s["race_id"]), nullable_number(s.get("points")), s.get("status", ""))
                for s in data.get("fantasy_scores", [])],
        prices=[Price(str(p["asset_id"]), str(p["race_id"]), nullable_number(p.get("price")))
                for p in data.get("prices", [])],
        price_changes=[PriceChange(str(p["asset_id"]), str(p["race_id"]), decimal(p["change"]))
                       for p in data.get("price_changes", [])],
        source=data.get("source", source),
        fetched_at=data.get("fetched_at", datetime.now(timezone.utc).isoformat()),
        warnings=list(data.get("warnings", [])),
    )
    dataset.check()
    return dataset


class LocalProvider:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self) -> Dataset:
        if self.path.is_dir():
            data = {}
            for name in ("races", "assets", "fantasy_scores", "prices", "price_changes"):
                path = self.path / f"{name}.csv"
                if path.exists():
                    with path.open(newline="", encoding="utf-8-sig") as handle:
                        data[name] = list(csv.DictReader(handle))
            return parse_bundle(data, f"Local CSV: {self.path.resolve()}")
        with self.path.open(encoding="utf-8") as handle:
            return parse_bundle(json.load(handle), f"Local JSON: {self.path.resolve()}")
