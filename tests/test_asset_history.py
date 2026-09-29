from dataclasses import replace
from decimal import Decimal as D

import pytest

from f1fantasy.models import Asset, FantasyScore, Price
from f1fantasy.pricing import PricingModel
from f1fantasy.presentation import render_analysis, render_inspect, json_output
from f1fantasy.rollover import analyze
from f1fantasy.storage import Storage


def new_history(dataset, count):
    first = 5 - count
    dataset.scores = [s for s in dataset.scores if s.asset_id != '2026:D' or int(s.race_id.split(':')[1]) >= first]
    dataset.prices = [p for p in dataset.prices if p.asset_id != '2026:D' or int(p.race_id.split(':')[1]) >= first]
    dataset.assets[0] = replace(dataset.assets[0], team='New Team')


@pytest.mark.parametrize('count,retained,need_max,need_positive', [
    (3, 38, -9, -16), (2, 38, -9, -16), (1, 20, 0, -5), (0, 0, 10, 8),
])
def test_available_history_windows(dataset, config, count, retained, need_max, need_positive):
    new_history(dataset, count)
    row = next(x for x in analyze(dataset, config, 2026).opportunities if x.asset.id == '2026:D')
    assert row.history_count == count
    assert row.upcoming_window_count == min(count, 2) + 1
    assert row.retained_two_race_total == retained
    assert row.max_rise_required_score == need_max
    assert row.positive_rise_required_score == need_positive
    assert len(row.scores) == count
    model = PricingModel(config.pricing)
    for band in row.price_bands[1:]:
        assert model.band(retained + band.minimum_score, row.price, row.upcoming_window_count) >= band.band
        assert model.band(retained + band.minimum_score - 1, row.price, row.upcoming_window_count) < band.band
    for score, projection in row.scenarios.items():
        assert projection == model.project(retained + score, row.price, min(count, 2) + 1)
    output = render_analysis(analyze(dataset, config, 2026), config, D(0), 'all', D(5))
    assert 'history_count' in output and 'New Team' in output
    inspect = render_inspect(row, config, D(0))
    assert f'history_count: {count}' in inspect
    assert f'"history_count": {count}' in json_output(row)
    if count == 0:
        assert 'NEW ASSET' in output and 'NEW ASSET' in inspect
        assert row.expected_next_score is None
    if count < 3:
        assert row.rollover_improvement is None
        assert row.components['dropping'] == 0


def test_constructor_change_does_not_inherit_old_id(dataset, config):
    old = dataset.assets[0]
    dataset.assets[0] = replace(old, active=False, team='Old Team')
    dataset.assets.append(replace(old, id='2026:NEW', team='New Team'))
    dataset.prices.append(Price('2026:NEW', '2026:5', D('14.5')))
    row = next(x for x in analyze(dataset, config, 2026).opportunities if x.asset.id == '2026:NEW')
    assert row.history_count == 0 and row.scores == ()
    assert row.max_rise_required_score == 18
    assert row.retained_two_race_total == 0


@pytest.mark.parametrize('null_score', [False, True])
def test_established_missing_data_not_new_asset(dataset, config, null_score):
    dataset.assets[0] = replace(dataset.assets[0], team='Known Team')
    dataset.scores = [replace(s, points=None) if s.asset_id == '2026:D' else s for s in dataset.scores] if null_score else [s for s in dataset.scores if s.asset_id != '2026:D']
    result = analyze(dataset, config, 2026)
    reason = result.exclusions['SYN [2026:D]']
    assert 'missing fantasy scores' in reason
    assert 'price=$8M' in reason and 'team=Known Team' in reason


def test_same_id_returns_after_inactive_rounds(dataset, config):
    dataset.scores = [replace(s, points=None, status='inactive') if s.asset_id == '2026:D' and s.race_id in ('2026:3', '2026:4') else s for s in dataset.scores]
    row = next(x for x in analyze(dataset, config, 2026).opportunities if x.asset.id == '2026:D')
    assert row.scores == (99, -25)
    assert row.history_count == 2


def test_inactive_precreation_placeholders_are_not_zero_scores(dataset, config):
    dataset.scores = [replace(s, points=None, status='inactive') if s.asset_id == '2026:D' else s for s in dataset.scores]
    row = next(x for x in analyze(dataset, config, 2026).opportunities if x.asset.id == '2026:D')
    assert row.history_count == 0
    assert row.max_rise_required_score == 10


def test_team_storage_roundtrip(dataset, tmp_path):
    dataset.assets[0] = replace(dataset.assets[0], team='New Team')
    storage = Storage(tmp_path / 'history.sqlite')
    storage.save(dataset, 2026)
    assert storage.load(2026).assets == dataset.assets


def test_first_race_of_season(dataset, config):
    dataset.races = [replace(r, completed=False) for r in dataset.races]
    dataset.scores = []
    rows = analyze(dataset, config, 2026).opportunities
    assert all(x.history_count == 0 and x.upcoming_window_count == 1 for x in rows)


def test_legacy_storage_adds_optional_team(dataset, tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.sqlite'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE assets (id TEXT PRIMARY KEY, season INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, active INTEGER)')
    dataset.assets[0] = replace(dataset.assets[0], team='Known Team')
    storage = Storage(path)
    storage.save(dataset, 2026)
    assert storage.load(2026).assets[0].team == 'Known Team'
