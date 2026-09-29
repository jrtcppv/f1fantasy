import json

import pytest

from f1fantasy.cli import main
from f1fantasy.config import load_config
from f1fantasy.presentation import json_output
from f1fantasy.storage import bundle


@pytest.mark.parametrize("view,title", [("all", "Projected Cost Cap"), ("locked", "Nearly Locked"),
                                       ("dropping", "Bad Result"), ("retained", "Two Strong"),
                                       ("scenarios", "Projected Cost Cap")])
def test_cli_views(dataset, tmp_path, capsys, view, title):
    path = tmp_path / "data.json"
    path.write_text(json_output(bundle(dataset)))
    assert main(["rollover", "--local", str(path), "--db", str(tmp_path / "history.sqlite"),
                 "--season", "2026", "--view", view]) == 0
    assert title in capsys.readouterr().out


def test_inspect_and_json_and_validation(dataset, tmp_path, capsys):
    path = tmp_path / "data.json"
    path.write_text(json_output(bundle(dataset)))
    common = ["--local", str(path), "--db", str(tmp_path / "db.sqlite"), "--season", "2026"]
    assert main(["inspect", "SYN", *common, "--assume-score", "-5"]) == 0
    output = capsys.readouterr().out
    assert "MAX_RISE_REQUIRED_SCORE: -9" in output
    assert "Synthetic Driver" in output
    assert main(["analyze", *common, "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["result"]["opportunities"][0]["max_rise_required_score"] == "-9"
    assert main(["validate-pricing", *common, "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["report"]["cases"]) == 8


def test_empty_analysis_reports_exclusions(dataset, tmp_path, capsys):
    dataset.scores = []
    path = tmp_path / "data.json"
    path.write_text(json_output(bundle(dataset)))
    assert main(["rollover", "--local", str(path), "--db", str(tmp_path / "db.sqlite"), "--season", "2026"]) == 2
    assert "EXCLUDED SYN" in capsys.readouterr().out


def test_config_overrides_strict_and_no_overwrite(tmp_path, capsys):
    path = tmp_path / "pricing.toml"
    assert main(["init-config", str(path)]) == 0
    assert main(["init-config", str(path)]) == 2
    path.write_text('[pricing]\nthresholds=["0.5","0.8","1.1"]\n')
    assert str(load_config(path).pricing.thresholds[0]) == "0.5"
    path.write_text('[pricing]\nthreshold=["0.5","0.8","1.1"]\n')
    with pytest.raises(ValueError, match="Unknown"):
        load_config(path)


def test_no_validation_observations_is_not_success(dataset, tmp_path, capsys):
    dataset.prices = []
    path = tmp_path / "data.json"
    path.write_text(json_output(bundle(dataset)))
    assert main(["validate-pricing", "--local", str(path), "--db", str(tmp_path / "db.sqlite"), "--season", "2026"]) == 2
    assert "no comparable observations" in capsys.readouterr().out
