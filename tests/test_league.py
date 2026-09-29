import json
from decimal import Decimal as D

import pytest

from f1fantasy.cli import main
from f1fantasy.league import analyze_league, load_observations
from f1fantasy.providers.league import fetch_league
from f1fantasy.config import load_config


def row(team='a', round=2, **values):
    return dict(league_id='2093801', league_name='Fantasy2Survive Season 3', season=2026,
                round=round, team_id=team, team_name=team, **values)


def load(tmp_path, rows):
    path = tmp_path / 'league.json'
    path.write_text(json.dumps({'observations': rows}))
    return load_observations(path)[0]


def test_exact_caps_identity_and_missing_values(tmp_path):
    rows = load(tmp_path, [row(round=1, cost_cap='101.1', points=20),
                          row(roster_value='99.9', bank='2.3', points=35),
                          row('b', cost_cap='102.2'), row('c', roster_value='105')])
    report = analyze_league(rows, 'fantasy2survive season 3', 2026)
    a, b, c = report['teams']
    assert a['cost_cap'] == D('102.2')
    assert a['cost_cap_change'] == D('1.1')
    assert a['points_change'] == 15
    assert a['cost_cap_rank'] == b['cost_cap_rank'] == 1
    assert b['cost_cap_change'] is None
    assert c['cost_cap'] is None
    assert report['summary']['comparable_teams'] == 1


def test_no_bridging_gaps_and_explicit_comparison(tmp_path):
    rows = load(tmp_path, [row(round=1, cost_cap=100), row(round=3, cost_cap=102)])
    assert analyze_league(rows, '2093801', 2026)['teams'][0]['cost_cap_change'] is None
    assert analyze_league(rows, '2093801', 2026, compare_round=1)['teams'][0]['cost_cap_change'] == 2
    with pytest.raises(ValueError, match='earlier'):
        analyze_league(rows, '2093801', 2026, compare_round=3)


@pytest.mark.parametrize('rows,match', [([row(), row()], 'Duplicate'),
    ([row(cost_cap=101, roster_value=99, bank=1)], 'conflicts'),
    ([row(cost_cap='NaN')], 'Non-finite'), ([row(bank=-1)], 'nonnegative'),
    ([row(round=1.5)], 'positive integer')])
def test_bad_observations(tmp_path, rows, match):
    with pytest.raises(ValueError, match=match):
        load(tmp_path, rows)


def test_cli_csv_and_json(tmp_path, capsys):
    path = tmp_path / 'league.csv'
    path.write_text('league_id,league_name,season,round,team_id,team_name,cost_cap,bank\n'
                    '2093801,Fantasy2Survive Season 3,2026,1,a,Team A,100,0\n'
                    '2093801,Fantasy2Survive Season 3,2026,2,a,Team A,101,0\n')
    args = ['league', 'Fantasy2Survive Season 3', '--local', str(path), '--season', '2026']
    assert main(args) == 0
    assert 'Team A' in capsys.readouterr().out
    assert main([*args, '--format', 'json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['teams'][0]['cost_cap_change'] == '1'
    assert main(['league', 'Unknown league']) == 2
    assert '--league-id' in capsys.readouterr().err


def test_ambiguous_name(tmp_path):
    other = row('b'); other['league_id'] = 'other'
    rows = load(tmp_path, [row(), other])
    with pytest.raises(ValueError, match='ambiguous'):
        analyze_league(rows, 'Fantasy2Survive Season 3', 2026)


def test_public_lineup_never_implies_cash_or_cap(monkeypatch, dataset, tmp_path):
    from f1fantasy.providers import league
    from types import SimpleNamespace
    ids = ['1', '2', '3', '4', '5', '6', '7']
    target = dataset.races[-1]
    dataset.prices = [SimpleNamespace(asset_id='2026:'+i, race_id=target.id, price=D('10')) for i in ids]
    http = SimpleNamespace(timestamps=['2026-09-29T15:00:00+00:00'], get=lambda _: {
        'Value': {'leaderboard': [dict(social_id=1, team_no=1, team_name='Team%20A',
                                     user_team=ids, cur_points=50)]}})
    monkeypatch.setattr(league, 'OnlineProvider', lambda *a: SimpleNamespace(http=http, fetch=lambda: dataset))
    opportunities = [SimpleNamespace(asset=SimpleNamespace(id='2026:'+i),
                                    assumed_projection=SimpleNamespace(change=D('.2'))) for i in ids]
    monkeypatch.setattr(league, 'analyze', lambda *a: SimpleNamespace(target=target, opportunities=opportunities))
    snapshot, warnings = fetch_league(load_config(), tmp_path, 2026, '2093801', 'Test')
    team = snapshot['observations'][0]
    assert team['team_name'] == 'Team A'
    assert team['roster_value'] == 70
    assert team['modeled_lineup_change'] == D('1.4')
    assert team['cost_cap'] is team['bank'] is None
    assert any('not an observed' in w for w in warnings)


def test_live_cli_and_export_round_trip(monkeypatch, tmp_path, capsys):
    from f1fantasy import cli
    observation = row(cost_cap=None, roster_value=D('117.7'), bank=None, points=D('3582'),
                      observed_at='2026-09-29T15:00:00Z', modeled_lineup_change=D('-1.3'))
    monkeypatch.setattr(cli, 'fetch_league', lambda *a: (
        {'source': 'mock public feed', 'observations': [observation]}, ['Cash unavailable']))
    export = tmp_path / 'export.json'
    assert main(['league', 'Fantasy2Survive Season 3', '--league-id', '2093801', '--season', '2026',
                 '--export', str(export), '--format', 'json']) == 0
    live = json.loads(capsys.readouterr().out)
    assert live['teams'][0]['points_rank'] == 1
    assert live['teams'][0]['cost_cap'] is None
    assert main(['league', '2093801', '--local', str(export), '--season', '2026', '--format', 'json']) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported['teams'][0]['modeled_lineup_change'] == '-1.3'
    assert 'Cash unavailable' in imported['warnings']
