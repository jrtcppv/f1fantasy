from dataclasses import replace
from decimal import Decimal as D

from f1fantasy.models import PriceChange
from f1fantasy.validation import validate_pricing


def test_observed_validation_and_price_alignment(dataset, config):
    # At race 4 total is 13: pre-race driver price 8 => -0.6.
    dataset.prices = [replace(p, price=D("7.4")) if p.asset_id == "2026:D" and p.race_id == "2026:5" else p for p in dataset.prices]
    report = validate_pricing(dataset, config.pricing, 2026)
    case = next(c for c in report.cases if c.asset_id == "2026:D" and c.round == 4)
    assert case.total == 13
    assert case.price == 8
    assert case.predicted == case.actual == D("-0.6")
    assert case.match
    assert 0 < report.accuracy < 100
    assert len(report.cases) == 8
    assert len(report.skipped) == 0


def test_missing_prices_do_not_bridge_gaps(dataset, config):
    dataset.prices = [p for p in dataset.prices if p.race_id != "2026:4"]
    report = validate_pricing(dataset, config.pricing, 2026)
    assert all(c.round < 3 for c in report.cases)
    assert all(any(s["race"] == f"Test race {n}" for s in report.skipped) for n in (3, 4))


def test_explicit_changes_and_conflicts(dataset, config):
    dataset.price_changes = [PriceChange("2026:D", "2026:4", D("-0.6"))]
    report = validate_pricing(dataset, config.pricing, 2026)
    assert any("conflicting" in x["reason"] for x in report.skipped)
    dataset.prices = [p for p in dataset.prices if p.race_id != "2026:5"]
    report = validate_pricing(dataset, config.pricing, 2026)
    assert next(c for c in report.cases if c.asset_id == "2026:D" and c.round == 4).match


def test_threshold_reporting(dataset, config):
    # Driver race 4 window: -25 + 18 + 35.68 = 28.68, exactly AvgPPM 1.195 at $8.
    dataset.scores = [replace(s, points=D("35.68")) if s.asset_id == "2026:D" and s.race_id == "2026:4" else s for s in dataset.scores]
    report = validate_pricing(dataset, config.pricing, 2026)
    case = next(c for c in report.cases if c.asset_id == "2026:D" and c.round == 4)
    assert case.near_boundary and case.boundary_distance == 0
    assert case.predicted == D("0.6")


def test_floor_in_historical_validation(dataset, config):
    dataset.prices = [replace(p, price=D(3)) for p in dataset.prices]
    dataset.scores = [replace(s, points=D(-20)) for s in dataset.scores]
    report = validate_pricing(dataset, config.pricing, 2026)
    assert report.accuracy == 100
