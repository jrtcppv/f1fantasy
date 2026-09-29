from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from .config import PricingConfig
from .models import Dataset
from .pricing import PricingModel
from .rollover import asset_history, ordered_races


@dataclass(frozen=True)
class ValidationCase:
    asset_id: str
    asset: str
    race: str
    round: int
    price: Decimal
    total: Decimal
    ppm: Decimal
    predicted: Decimal
    actual: Decimal
    match: bool
    near_boundary: bool
    boundary_distance: Decimal
    observation: str
    history_count: int


@dataclass
class ValidationReport:
    cases: list[ValidationCase] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> Decimal | None:
        return (100 * Decimal(sum(c.match for c in self.cases)) / len(self.cases)) if self.cases else None


def validate_pricing(dataset: Dataset, config: PricingConfig, season: int) -> ValidationReport:
    model = PricingModel(config)
    races = ordered_races(dataset, season)
    prices = {(p.asset_id, p.race_id): p.price for p in dataset.prices}
    changes = {(p.asset_id, p.race_id): p.change for p in dataset.price_changes}
    report = ValidationReport()
    for index, race in enumerate(races):
        if not race.completed:
            continue
        window = races[max(0, index - 2):index + 1]
        for asset in dataset.assets:
            key = (asset.id, race.id)
            reason = None
            observed = changes.get(key)
            price = prices.get(key)
            observation = "explicit price_changes"
            adjacent = None
            if index + 1 < len(races) and races[index + 1].round == race.round + 1:
                following = prices.get((asset.id, races[index + 1].id))
                if price is not None and following is not None:
                    adjacent = following - price
            if observed is None and adjacent is not None:
                observed = adjacent
                observation = "adjacent pre-race prices"
            _, values, missing = asset_history(dataset, asset.id, race, include_target=True)
            score = next((s for s in dataset.scores if s.asset_id == asset.id and s.race_id == race.id), None)
            if [r.round for r in window] != list(range(max(1, race.round - 2), race.round + 1)) or not all(r.completed for r in window):
                reason = "incomplete calendar window"
            elif score is None or score.points is None or missing:
                reason = "missing fantasy score in asset pricing history"
            elif price is None:
                reason = "missing pre-race price"
            elif price < config.minimum_price:
                reason = "pre-race price below configured floor"
            elif observed is None:
                reason = "missing observed price change / adjacent price"
            elif adjacent is not None and observed != adjacent:
                reason = "conflicting explicit and adjacent observed price changes"
            if reason:
                report.skipped.append({"asset": asset.code, "asset_id": asset.id, "race": race.name, "reason": reason})
                continue
            total = sum(values)
            raw_ppm = Fraction(total) / (len(values) * Fraction(price))
            effective_ppm = model.ppm(total, price, len(values))
            distance = min(abs(raw_ppm - Fraction(t)) for t in config.thresholds)
            predicted = model.project(total, price, len(values)).change
            report.cases.append(ValidationCase(
                asset.id, asset.code, race.name, race.round, price, total,
                Decimal(effective_ppm.numerator) / effective_ppm.denominator,
                predicted, observed, predicted == observed, distance <= Fraction(config.boundary_tolerance),
                Decimal(distance.numerator) / distance.denominator, observation, len(values)))
    return report
