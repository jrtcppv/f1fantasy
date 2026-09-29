from dataclasses import replace
from decimal import Decimal as D

import pytest

from f1fantasy.pricing import PricingModel


@pytest.mark.parametrize("threshold,band", [("0.605", 1), ("0.900", 2), ("1.195", 3)])
def test_exact_boundaries(config, threshold, band):
    model = PricingModel(config.pricing)
    total = D(threshold) * 3 * D("10")
    assert model.band(total, D(10)) == band
    assert model.band(total - D("0.00000000000001"), D(10)) == band - 1


def test_integer_and_negative_required(config):
    m = PricingModel(config.pricing)
    assert m.required_score(D(38), D(8), 3) == -9
    assert m.required_score(D(38), D(8), 2) == -16
    assert m.required_score(D(0), D(8), 3) == 29
    for band in (1, 2, 3):
        need = m.required_score(D(38), D(8), band)
        assert m.band(D(38) + need, D(8)) >= band
        assert m.band(D(38) + need - 1, D(8)) < band


@pytest.mark.parametrize("price,rise", [("18.4", "0.6"), ("18.5", "0.3"), ("25", "0.3")])
def test_tiers(config, price, rise):
    assert PricingModel(config.pricing).project(D(200), D(price)).change == D(rise)


@pytest.mark.parametrize("price,change", [("3", "0"), ("3.1", "-0.1"), ("3.5", "-0.5"), ("4", "-0.6")])
def test_floor(config, price, change):
    result = PricingModel(config.pricing).project(D(-100), D(price))
    assert result.change == D(change)
    assert result.nominal_change == D("-0.6")
    assert result.price >= 3


@pytest.mark.parametrize("rounding", ["half_up", "half_even"])
def test_rounded_boundary_inverse(config, rounding):
    m = PricingModel(replace(config.pricing, ppm_decimals=3, rounding=rounding, score_step=D("0.0001")))
    for band in (1, 2, 3):
        need = m.required_score(D(0), D(10), band)
        assert m.band(need, D(10)) == band
        assert m.band(need - D("0.0001"), D(10)) == band - 1
    assert m.required_score(D(0), D(10), 1) == D("18.135") + (D("0.0001") if rounding == "half_even" else 0)


def test_inverse_many_prices_and_retained_scores(config):
    for rounding in (-1, 3):
        model = PricingModel(replace(config.pricing, ppm_decimals=rounding))
        for price in map(D, ("3", "3.1", "5.8", "18.4", "18.5", "37.7")):
            for retained in map(D, (-75, -1, 0, 24, 38, 115)):
                for band in (1, 2, 3):
                    need = model.required_score(retained, price, band)
                    assert model.band(retained + need, price) >= band
                    assert model.band(retained + need - 1, price) < band
