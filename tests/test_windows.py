from dataclasses import replace

import pytest

from f1fantasy.rollover import analyze, select_next_race, select_window


def test_calendar_order_not_input_order(dataset, config):
    dataset.races.reverse()
    result = analyze(dataset, config, 2026)
    assert [r.round for r in result.window] == [2, 3, 4]
    assert result.opportunities[0].scores == (-25, 18, 20)
    assert result.opportunities[0].retained_two_race_total == 38
    assert result.opportunities[0].current_three_race_total == 13


def test_not_last_three_available_scores(dataset, config):
    dataset.scores = [s for s in dataset.scores if not (s.asset_id == "2026:D" and s.race_id == "2026:3")]
    result = analyze(dataset, config, 2026)
    assert len(result.opportunities) == 1
    assert "Test race 3" in result.exclusions["SYN [2026:D]"]


def test_fewer_than_three_races(dataset):
    target = replace(dataset.races[2], completed=False)
    assert len(select_window(dataset, target)) == 2


def test_calendar_gap_and_future_target(dataset):
    dataset.races.pop(2)
    with pytest.raises(ValueError, match="Calendar gap"):
        select_window(dataset, dataset.races[-1])


def test_incomplete_prior_race(dataset):
    dataset.races[2] = replace(dataset.races[2], completed=False)
    with pytest.raises(ValueError, match="earlier race is incomplete"):
        select_window(dataset, dataset.races[-1])


def test_location_lookup_and_past_target(dataset):
    assert select_next_race(dataset, 2026, "circuit 5").round == 5
    with pytest.raises(ValueError, match="completed races"):
        select_next_race(dataset, 2026, "1")
