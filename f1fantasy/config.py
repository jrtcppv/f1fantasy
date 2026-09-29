from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from pathlib import Path
import tomllib


def decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Non-finite number: {value!r}")
    return result


@dataclass(frozen=True)
class PricingConfig:
    thresholds: tuple[Decimal, ...]
    tier_cutoff: Decimal
    low_price_changes: tuple[Decimal, ...]
    high_price_changes: tuple[Decimal, ...]
    minimum_price: Decimal
    ppm_decimals: int
    rounding: str
    score_step: Decimal
    boundary_tolerance: Decimal


@dataclass(frozen=True)
class Config:
    pricing: PricingConfig
    conservative_score: Decimal
    locked_threshold: Decimal
    scenarios: tuple[Decimal, ...]
    stress_scenarios: tuple[Decimal, ...]
    opportunity: dict[str, Decimal]
    weights: dict[str, Decimal]
    online: dict


def _merge(base: dict, overrides: dict) -> None:
    for key, value in overrides.items():
        if key not in base:
            raise ValueError(f"Unknown configuration key: {key}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"Expected configuration table: {key}")
            _merge(base[key], value)
        else:
            base[key] = value


def load_config(path: str | Path | None = None) -> Config:
    data = tomllib.loads(files("f1fantasy").joinpath("default_config.toml").read_text())
    if path:
        with open(path, "rb") as handle:
            _merge(data, tomllib.load(handle))
    p = data["pricing"]
    for key in ("thresholds", "low_price_changes", "high_price_changes"):
        p[key] = tuple(decimal(x) for x in p[key])
    for key in ("tier_cutoff", "minimum_price", "score_step", "boundary_tolerance"):
        p[key] = decimal(p[key])
    pricing = PricingConfig(**p)
    if (len(pricing.thresholds) != 3 or any(x <= 0 for x in pricing.thresholds)
            or list(pricing.thresholds) != sorted(set(pricing.thresholds))):
        raise ValueError("Exactly three strictly increasing positive thresholds are required")
    for changes in (pricing.low_price_changes, pricing.high_price_changes):
        if len(changes) != 4 or list(changes) != sorted(set(changes)) or not changes[1] < 0 < changes[2]:
            raise ValueError("Four increasing bands (two negative, two positive) are required")
    if not 0 < pricing.minimum_price < pricing.tier_cutoff or pricing.score_step <= 0:
        raise ValueError("Invalid floor, tier cutoff, or score increment")
    if (type(pricing.ppm_decimals) is not int or not -1 <= pricing.ppm_decimals <= 9
            or pricing.rounding not in ("half_up", "half_even") or pricing.boundary_tolerance < 0):
        raise ValueError("Invalid rounding or boundary tolerance")
    if pricing.ppm_decimals >= 0:
        factor = 10 ** pricing.ppm_decimals
        if any(t * factor != (t * factor).to_integral_value() for t in pricing.thresholds):
            raise ValueError("Thresholds must be representable at ppm_decimals precision")
    a = data["analysis"]
    opportunity = {k: decimal(v) for k, v in data["opportunity"].items() if k != "weights"}
    weights = {k: decimal(v) for k, v in data["opportunity"]["weights"].items()}
    if any(v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Opportunity weights must be nonnegative and sum to a positive value")
    if any(opportunity[k] <= 0 for k in ("drop_scale", "safety_scale", "max_rise_reference")):
        raise ValueError("Opportunity scales must be positive")
    if not a["scenarios"] or not a["stress_scenarios"]:
        raise ValueError("Scenario lists must not be empty")
    online = data["online"]
    if online["cache_ttl_seconds"] < 0 or online["timeout_seconds"] <= 0:
        raise ValueError("Invalid cache TTL or timeout")
    return Config(pricing, decimal(a["conservative_score"]), decimal(a["locked_threshold"]),
                  tuple(map(decimal, a["scenarios"])), tuple(map(decimal, a["stress_scenarios"])),
                  opportunity, weights, online)
