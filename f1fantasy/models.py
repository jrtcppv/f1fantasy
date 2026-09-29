from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Race:
    id: str
    season: int
    round: int
    name: str
    date: date
    completed: bool
    location: str = ""


@dataclass(frozen=True)
class Asset:
    id: str
    code: str
    name: str
    kind: str
    active: bool | None
    team: str = ""


@dataclass(frozen=True)
class FantasyScore:
    asset_id: str
    race_id: str
    points: Decimal | None
    status: str = ""


@dataclass(frozen=True)
class Price:
    """An observed pre-race price, never a modeled price."""
    asset_id: str
    race_id: str
    price: Decimal | None


@dataclass(frozen=True)
class PriceChange:
    asset_id: str
    race_id: str
    change: Decimal


@dataclass
class Dataset:
    races: list[Race] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    scores: list[FantasyScore] = field(default_factory=list)
    prices: list[Price] = field(default_factory=list)
    price_changes: list[PriceChange] = field(default_factory=list)
    source: str = ""
    fetched_at: str = ""
    warnings: list[str] = field(default_factory=list)

    def check(self) -> None:
        def unique(rows: list, key, label: str) -> None:
            values = [key(row) for row in rows]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label}; ambiguous input is not merged")
        unique(self.races, lambda r: r.id, "race IDs")
        unique(self.races, lambda r: (r.season, r.round), "season/round")
        unique(self.assets, lambda a: a.id, "asset IDs")
        for rows, label in ((self.scores, "scores"), (self.prices, "prices"), (self.price_changes, "price changes")):
            unique(rows, lambda x: (x.asset_id, x.race_id), label)
        race_ids = {r.id for r in self.races}
        asset_ids = {a.id for a in self.assets}
        for row in [*self.scores, *self.prices, *self.price_changes]:
            if row.race_id not in race_ids or row.asset_id not in asset_ids:
                raise ValueError(f"Unknown race or asset reference: {row}")
        if any(a.kind not in ("driver", "constructor") or not a.id or not a.code for a in self.assets):
            raise ValueError("Assets need IDs, codes, and kind driver/constructor")
        if any(r.round < 1 for r in self.races):
            raise ValueError("Race rounds must be positive")
        if any(p.price is not None and (not p.price.is_finite() or p.price <= 0) for p in self.prices):
            raise ValueError("Observed prices must be finite and positive")
        if any(s.points is not None and not s.points.is_finite() for s in self.scores):
            raise ValueError("Scores must be finite or null")
