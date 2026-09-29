"""Regression against a field-filtered official snapshot, fetched 2026-09-22.

These are observed feed records, not synthetic threshold-fitting inputs.
"""
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path

from f1fantasy.providers.online import OnlineProvider
from f1fantasy.rollover import analyze
from f1fantasy.validation import validate_pricing


class RecordedHTTP:
    def __init__(self, upcoming=None):
        self.records = json.loads((Path(__file__).parent / 'fixtures/official_substitution_2026.json').read_text())
        self.timestamps = [r['fetched_at'] for r in self.records.values()]
        self.upcoming = upcoming

    def get(self, url):
        body = self.records[url]['body']
        if 'schedule' in url and self.upcoming:
            for row in body['Data']['Value']:
                if int(row['Gameday']) >= self.upcoming:
                    row['GDStatus'] = row['MatchStatus'] = '0'
        return body


def test_august_substitution_first_race_thresholds(config, tmp_path):
    data = OnlineProvider(config.online, tmp_path, 2026, http=RecordedHTTP(upcoming=12)).fetch()
    rows = {x.asset.id: x for x in analyze(data, config, 2026).opportunities}
    for asset_id, team, price, maximum in [('2026:116', 'Red Bull Racing', '14.5', 18),
                                         ('2026:130', 'Racing Bulls', '10.3', 13)]:
        row = rows[asset_id]
        assert row.asset.team == team and row.price == D(price)
        assert row.history_count == 0 and row.max_rise_required_score == maximum
    # The same human's previous constructor has its own ID and scores.
    assert any(s.asset_id == '2026:114' and s.points is not None for s in data.scores)
    assert rows['2026:116'].scores == ()


def test_substitution_observed_movements_validate_without_fitting(config, tmp_path):
    data = OnlineProvider(config.online, tmp_path, 2026, http=RecordedHTTP()).fetch()
    cases = [c for c in validate_pricing(data, config.pricing, 2026).cases
             if c.asset_id in ('2026:116', '2026:130') and c.round in (12, 13, 14)]
    assert len(cases) == 6
    assert [c.history_count for c in cases] == [1, 1, 2, 2, 3, 3]
    assert all(c.match for c in cases), [(c.asset, c.round, c.predicted, c.actual) for c in cases if not c.match]
    # A contradictory observation must remain visible as a mismatch.
    data.prices = [replace(p, price=D('15.1')) if p.asset_id == '2026:116' and p.race_id == '2026:13' else p for p in data.prices]
    contradictory = next(c for c in validate_pricing(data, config.pricing, 2026).cases
                         if c.asset_id == '2026:116' and c.round == 12)
    assert not contradictory.match
    assert contradictory.predicted == D('-.2') and contradictory.actual == D('.6')


def test_returning_current_assets_keep_exact_id_history(config, tmp_path):
    data = OnlineProvider(config.online, tmp_path, 2026, http=RecordedHTTP()).fetch()
    result = analyze(data, config, 2026)
    assert not result.exclusions
    rows = {x.asset.id: x for x in result.opportunities}
    assert rows['2026:114'].scores == (22, 3, 13)
    assert rows['2026:11032'].scores == (23, 38, 15)
    assert rows['2026:114'].max_rise_required_score == 19
    assert rows['2026:11032'].max_rise_required_score == -1
