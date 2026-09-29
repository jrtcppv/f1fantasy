"""Exact thresholds using rational arithmetic; Decimal at the public boundary."""
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .config import PricingConfig


@dataclass(frozen=True)
class Projection:
    band: int
    nominal_change: Decimal
    change: Decimal
    price: Decimal


@dataclass(frozen=True)
class PriceBand:
    band: int
    nominal_change: Decimal
    effective_change: Decimal
    minimum_score: Decimal | None
    maximum_score: Decimal | None


class PricingModel:
    def __init__(self, config: PricingConfig):
        self.config = config

    def changes(self, price: Decimal) -> tuple[Decimal, ...]:
        return (self.config.low_price_changes if price < self.config.tier_cutoff
                else self.config.high_price_changes)

    def ppm(self, total: Decimal, price: Decimal, count: int = 3) -> Fraction:
        if price < self.config.minimum_price or count <= 0:
            raise ValueError("Price is below configured floor, or window length is invalid")
        value = Fraction(total) / (count * Fraction(price))
        places = self.config.ppm_decimals
        if places < 0:
            return value
        factor = 10 ** places
        scaled = abs(value) * factor
        whole, remainder = divmod(scaled.numerator, scaled.denominator)
        if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator
                and (self.config.rounding == "half_up" or whole % 2)):
            whole += 1
        return Fraction(whole if value >= 0 else -whole, factor)

    def band(self, total: Decimal, price: Decimal, count: int = 3) -> int:
        value = self.ppm(total, price, count)
        return sum(value >= Fraction(t) for t in self.config.thresholds)

    def project(self, total: Decimal, price: Decimal, count: int = 3) -> Projection:
        band = self.band(total, price, count)
        nominal = self.changes(price)[band]
        new_price = max(self.config.minimum_price, price + nominal)
        return Projection(band, nominal, new_price - price, new_price)

    def required_score(self, retained: Decimal, price: Decimal, band: int, count: int = 3) -> Decimal:
        """Minimum attainable upcoming score entering band or higher (bands 1..3)."""
        if band not in (1, 2, 3):
            raise ValueError("Band 0 has no lower bound; choose 1, 2, or 3")
        self.ppm(retained, price, count)  # validate price
        threshold = Fraction(self.config.thresholds[band - 1])
        if self.config.ppm_decimals >= 0:
            threshold -= Fraction(1, 2 * 10 ** self.config.ppm_decimals)
        raw = (threshold * count * Fraction(price) - Fraction(retained)) / Fraction(self.config.score_step)
        ticks = -(-raw.numerator // raw.denominator)
        result = Decimal(ticks) * self.config.score_step
        # Half-even at an odd threshold excludes the exact halfway boundary.
        if self.band(retained + result, price, count) < band:
            result += self.config.score_step
        return result

    def ranges(self, retained: Decimal, price: Decimal, count: int = 3) -> list[tuple[Decimal | None, Decimal | None]]:
        starts = [self.required_score(retained, price, b, count) for b in (1, 2, 3)]
        step = self.config.score_step
        return [(None, starts[0] - step), (starts[0], starts[1] - step),
                (starts[1], starts[2] - step), (starts[2], None)]

    def score_bands(self, retained: Decimal, price: Decimal, count: int = 3) -> list[PriceBand]:
        return [PriceBand(i, change, max(self.config.minimum_price, price + change) - price, low, high)
                for i, (change, (low, high)) in enumerate(zip(self.changes(price), self.ranges(retained, price, count)))]
