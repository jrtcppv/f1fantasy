import csv
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import json
from urllib.error import URLError

import pytest

from f1fantasy.presentation import json_output
from f1fantasy.providers.csv_provider import LocalProvider, parse_bundle
from f1fantasy.providers.online import CachedHTTP, OnlineProvider, ProviderError, parse_schedule
from f1fantasy.storage import Storage, bundle


def test_json_roundtrip_missing_and_zero(dataset, tmp_path):
    dataset.scores[0] = replace(dataset.scores[0], points=None)
    path = tmp_path / "data.json"
    path.write_text(json_output(bundle(dataset)))
    result = LocalProvider(path).fetch()
    assert result.scores[0].points is None
    assert result.scores[1].points == -25
    assert result.races == dataset.races
    assert result.assets == dataset.assets


def test_csv_roundtrip_and_blank(dataset, tmp_path):
    data = json.loads(json_output(bundle(dataset)))
    data["fantasy_scores"][0]["points"] = ""
    data["fantasy_scores"][1]["points"] = "0"
    for table in ("races", "assets", "fantasy_scores", "prices"):
        with (tmp_path / (table + ".csv")).open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(data[table][0]))
            writer.writeheader()
            writer.writerows(data[table])
    result = LocalProvider(tmp_path).fetch()
    assert result.scores[0].points is None
    assert result.scores[1].points == 0


def test_duplicate_and_nonfinite_rejected(dataset):
    data = json.loads(json_output(bundle(dataset)))
    data["fantasy_scores"][0]["points"] = "NaN"
    with pytest.raises(ValueError, match="Non-finite"):
        parse_bundle(data)
    dataset.scores.append(dataset.scores[0])
    with pytest.raises(ValueError, match="Duplicate"):
        dataset.check()


def test_sqlite_replaces_obsolete_values_and_preserves_other_season(dataset, tmp_path):
    storage = Storage(tmp_path / "history.sqlite")
    storage.save(dataset, 2026)
    assert storage.load(2026).scores == dataset.scores
    # A separate season uses namespaced IDs, so the seasons cannot contaminate each other.
    data = json_output(bundle(dataset)).replace("2026", "2025")
    older = parse_bundle(json.loads(data))
    storage.save(older, 2025)
    dataset.scores.pop(0)
    storage.save(dataset, 2026)
    assert len(storage.load(2026).scores) == 7
    assert len(storage.load(2025).scores) == 8


def schedule_rows():
    return [{"SessionType": session, "Season": "2026", "GamedayId": n, "Gameday": str(n),
             "MeetingName": f"Synthetic GP {n}", "MeetingLocation": f"Circuit {n}",
             "SessionStartDateISO8601": f"2026-0{n}-01T15:00:00+01:00",
             "GDStatus": 4 if n < 5 else 1, "MatchStatus": "4" if n < 5 else "0"}
            for n in range(1, 6) for session in ("Sprint", "Qualifying", "Race")]


def test_schedule_one_weekend_per_race_and_season_guard():
    races = parse_schedule({"Data": {"Value": schedule_rows()}}, 2026)
    assert len(races) == 5
    assert not races[-1].completed
    with pytest.raises(ProviderError, match="current-season"):
        parse_schedule({"Data": {"Value": schedule_rows()}}, 2025)


def test_online_adapter_keeps_player_identity_missing_scores_and_pre_prices(config, tmp_path):
    class FakeHTTP:
        timestamps = ["2026-05-01T00:00:00+00:00"]

        def get(self, url):
            if "schedule" in url:
                return {"Data": {"Value": schedule_rows()}}
            return {"Data": {"Value": [
                {"PlayerId": "1", "DriverTLA": "SYN", "DisplayName": "Synthetic", "PositionName": "DRIVER",
                 "IsActive": "1", "Value": "8.0", "GamedayPoints": "", "ProjectedGamedayPoints": "99"},
                {"PlayerId": "2", "DriverTLA": "SYN", "DisplayName": "Legacy Synthetic", "PositionName": "DRIVER",
                 "IsActive": "0", "Value": "9.0", "GamedayPoints": "85"},
                {"PlayerId": "3", "DriverTLA": "SYC", "DisplayName": "Synthetic Constructor", "PositionName": "CONSTRUCTOR",
                 "IsActive": "1", "Value": "20.0", "GamedayPoints": "0"},
            ]}}
    data = OnlineProvider(config.online, tmp_path, 2026, http=FakeHTTP()).fetch()
    assert len(data.assets) == 3  # duplicate TLA is not a duplicate asset
    assert len(data.scores) == 12  # upcoming placeholders are never scored
    assert data.scores[0].points is None
    assert data.scores[1].points is None
    assert data.scores[2].points == 0
    assert data.prices[-1].price == 20
    assert data.assets[1].active is False


def test_http_cache_offline_refresh_and_network_failure(tmp_path, monkeypatch):
    calls = []

    def fetch(request, timeout):
        calls.append(request.full_url)
        return BytesIO(b'{"Data": {"Value": [1]}}')

    monkeypatch.setattr("f1fantasy.providers.online.urlopen", fetch)
    url = "https://example.test/official-feed"
    http = CachedHTTP(tmp_path)
    expected = http.get(url)
    assert http.get(url) == expected
    assert len(calls) == 1
    assert CachedHTTP(tmp_path, offline=True, ttl=0).get(url) == expected
    assert CachedHTTP(tmp_path, refresh=True).get(url) == expected
    assert len(calls) == 2
    with pytest.raises(ProviderError, match="No cached"):
        CachedHTTP(tmp_path, offline=True).get(url + "/missing")

    def fail(*args, **kwargs):
        raise URLError("unavailable")

    monkeypatch.setattr("f1fantasy.providers.online.urlopen", fail)
    with pytest.raises(ProviderError, match="explicit cache fallback"):
        CachedHTTP(tmp_path, refresh=True).get(url)


def test_malformed_feed():
    with pytest.raises(ProviderError, match="schema changed"):
        parse_schedule({"unexpected": []}, 2026)
