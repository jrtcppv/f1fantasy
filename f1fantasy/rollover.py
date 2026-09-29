from dataclasses import dataclass, field
from decimal import Decimal

from .config import Config
from .models import Asset, Dataset, Race
from .pricing import PriceBand, PricingModel, Projection


def ordered_races(dataset: Dataset, season: int) -> list[Race]:
    return sorted((r for r in dataset.races if r.season == season), key=lambda r: r.round)


def select_next_race(dataset: Dataset, season: int, query: str | None = None) -> Race:
    races = ordered_races(dataset, season)
    if query:
        term = query.casefold()
        matches = [r for r in races if term in (r.id.casefold(), str(r.round), r.name.casefold(), r.location.casefold())]
        if not matches:
            matches = [r for r in races if term in (r.name + " " + r.location).casefold()]
        if len(matches) != 1:
            raise ValueError(f"Race {query!r} is unknown or ambiguous; use its round number")
        target = matches[0]
    else:
        target = next((r for r in races if not r.completed), None)
        if target is None:
            raise ValueError("No upcoming race in this season's calendar")
    if target.completed:
        raise ValueError("Rollover is for the upcoming race; use validate-pricing for completed races")
    return target


def select_window(dataset: Dataset, target: Race) -> tuple[Race, ...]:
    before = [r for r in ordered_races(dataset, target.season) if r.round < target.round]
    if any(not r.completed for r in before):
        raise ValueError("An earlier race is incomplete; the target must be the next race")
    window = before[-3:]
    # A hole in a local calendar must not masquerade as a completed three-race window.
    if [r.round for r in window] != list(range(max(1, target.round - 3), target.round)):
        raise ValueError("Calendar gap before target; provide the missing race metadata")
    return tuple(window)


def asset_history(dataset: Dataset, asset_id: str, target: Race, *, include_target: bool = False):
    """Latest pricing observations for this ID; explicit inactive rounds are not scores.

    A price/score record establishes existence. After that, unexplained holes
    are missing data, not evidence of a new asset. Legacy ambiguous inactivity
    markers remain missing until reimported from a feed with explicit status.
    """
    races = [r for r in ordered_races(dataset, target.season)
             if r.round < target.round or (include_target and r.round == target.round)]
    scores = {s.race_id: s for s in dataset.scores if s.asset_id == asset_id}
    prices = {p.race_id for p in dataset.prices if p.asset_id == asset_id}
    started = False
    history = []
    for race in races:
        score = scores.get(race.id)
        if score is not None and score.status == "inactive":
            continue
        started = started or score is not None or race.id in prices
        if started:
            history.append((race, score.points if score is not None else None))
    recent = history[-3:]
    missing = [r.name for r, points in recent if points is None]
    return tuple(r for r, _ in recent), tuple(points for _, points in recent), missing


@dataclass(frozen=True)
class Opportunity:
    asset: Asset
    price: Decimal
    races: tuple[Race, ...]
    scores: tuple[Decimal, ...]
    current_three_race_total: Decimal
    retained_two_race_total: Decimal
    positive_rise_required_score: Decimal
    max_rise_required_score: Decimal
    max_rise_safety_margin: Decimal
    expected_next_score: Decimal | None
    rollover_improvement: Decimal | None
    assumed_projection: Projection
    scenarios: dict[Decimal, Projection]
    cost_cap_opportunity_score: Decimal
    components: dict[str, Decimal]
    price_bands: list[PriceBand]
    history_count: int
    upcoming_window_count: int


@dataclass
class Analysis:
    target: Race
    window: tuple[Race, ...]
    opportunities: list[Opportunity]
    exclusions: dict[str, str]
    inactive_count: int
    inactive_details: dict[str, str] = field(default_factory=dict)


def clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def analyze(dataset: Dataset, config: Config, season: int, next_race: str | None = None,
            assume_score: Decimal | None = None, expected_score: Decimal | None = None) -> Analysis:
    target = select_next_race(dataset, season, next_race)
    window = select_window(dataset, target)
    model = PricingModel(config.pricing)
    prices = {(p.asset_id, p.race_id): p.price for p in dataset.prices}
    assumed = config.conservative_score if assume_score is None else assume_score
    result = Analysis(target, window, [], {}, 0)
    for asset in dataset.assets:
        label = f"{asset.code} [{asset.id}]"
        price = prices.get((asset.id, target.id))
        context = f"price=${price}M" if price is not None else "price=unknown"
        context += f" team={asset.team or 'unknown'}"
        if asset.active is False:
            result.inactive_count += 1
            result.inactive_details[label] = context + "; inactive"
            continue
        if asset.active is None:
            result.exclusions[label] = context + "; missing active status"
            continue
        history_races, values, missing = asset_history(dataset, asset.id, target)
        reasons = []
        if missing:
            reasons.append("missing fantasy scores: " + ", ".join(missing))
        if price is None:
            reasons.append(f"missing pre-race price for {target.name}")
        elif price < config.pricing.minimum_price:
            reasons.append("observed price below configured floor; check season/model")
        if reasons:
            result.exclusions[label] = context + "; " + "; ".join(reasons)
            continue
        history_count = len(values)
        retained_values = values[-2:]
        retained = sum(retained_values, Decimal(0))
        count = len(retained_values) + 1
        dropping = values[0] if history_count == 3 else None
        need_max = model.required_score(retained, price, 3, count)
        need_positive = model.required_score(retained, price, 2, count)
        safety = assumed - need_max
        max_rise = model.changes(price)[3]
        o = config.opportunity
        components = {
            "dropping": clamp((o["drop_reference"] - dropping) / o["drop_scale"]) if dropping is not None else Decimal(0),
            "retained": clamp(retained / (count * price * config.pricing.thresholds[2])),
            "safety": clamp(Decimal("0.5") + safety / o["safety_scale"]),
            "magnitude": clamp(max_rise / o["max_rise_reference"]),
            "robustness": sum((clamp(model.project(retained + s, price, count).change / max_rise)
                               for s in config.stress_scenarios), Decimal(0)) / len(config.stress_scenarios),
        }
        opportunity = 100 * sum((components[k] * w for k, w in config.weights.items()), Decimal(0)) / sum(config.weights.values())
        expected = (retained / len(retained_values) if retained_values else None) if expected_score is None else expected_score
        result.opportunities.append(Opportunity(
            asset, price, history_races, values, sum(values, Decimal(0)), retained, need_positive, need_max, safety,
            expected, expected - dropping if dropping is not None and expected is not None else None, model.project(retained + assumed, price, count),
            {s: model.project(retained + s, price, count) for s in config.scenarios}, opportunity, components,
            model.score_bands(retained, price, count), history_count, count))
    result.opportunities.sort(key=lambda x: (-x.cost_cap_opportunity_score, x.max_rise_required_score, x.asset.id))
    return result
