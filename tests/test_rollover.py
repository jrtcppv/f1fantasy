from dataclasses import replace
from decimal import Decimal as D

from f1fantasy.rollover import analyze


def test_dnf_and_negative_max_requirement(dataset, config):
    result = analyze(dataset, config, 2026)
    driver = next(x for x in result.opportunities if x.asset.kind == "driver")
    assert driver.scores[0] == -25
    assert driver.max_rise_required_score == -9
    assert driver.positive_rise_required_score == -16
    assert driver.max_rise_safety_margin == 9
    assert driver.rollover_improvement == 44
    assert driver.assumed_projection.change == D("0.6")
    assert 0 <= driver.cost_cap_opportunity_score <= 100
    assert result.opportunities[0] == driver


def test_constructors_and_scenarios(dataset, config):
    rows = analyze(dataset, config, 2026).opportunities
    driver = next(x for x in rows if x.asset.kind == "driver")
    constructor = next(x for x in rows if x.asset.kind == "constructor")
    assert constructor.max_rise_required_score == 34
    assert [p.change for p in driver.scenarios.values()] == list(map(D, (".2", ".6", ".6", ".6", ".6", ".6", ".6")))
    assert set(driver.scenarios) == set(map(D, (-10, -5, 0, 5, 10, 15, 20)))


def test_expected_performance_does_not_affect_ranking(dataset, config):
    a = analyze(dataset, config, 2026, expected_score=D(-100))
    b = analyze(dataset, config, 2026, expected_score=D(100))
    assert [x.cost_cap_opportunity_score for x in a.opportunities] == [x.cost_cap_opportunity_score for x in b.opportunities]
    assert a.opportunities[0].rollover_improvement != b.opportunities[0].rollover_improvement


def test_assumed_score(dataset, config):
    row = analyze(dataset, config, 2026, assume_score=D(-5)).opportunities[0]
    assert row.max_rise_safety_margin == 4


def test_missing_price_and_status(dataset, config):
    dataset.prices = [p for p in dataset.prices if not (p.asset_id == "2026:D" and p.race_id == "2026:5")]
    dataset.assets[1] = replace(dataset.assets[1], active=None)
    result = analyze(dataset, config, 2026)
    assert not result.opportunities
    assert len(result.exclusions) == 2


def test_inactive_asset(dataset, config):
    dataset.assets[0] = replace(dataset.assets[0], active=False)
    result = analyze(dataset, config, 2026)
    assert result.inactive_count == 1
    assert len(result.opportunities) == 1
