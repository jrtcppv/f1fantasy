"""League budget comparisons from explicitly dated, normalized observations."""
import csv
from decimal import Decimal
import json
from pathlib import Path
from statistics import median

from .config import decimal
from .presentation import money, number, table


def optional_number(value):
    return None if value is None or value == "" else decimal(value)


def positive_integer(value, field):
    result = decimal(value)
    if result < 1 or result != result.to_integral_value():
        raise ValueError(f"{field} must be a positive integer")
    return int(result)


def load_observations(path: Path) -> tuple[list[dict], str]:
    """One row per league/season/team/round, all money in millions."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        source = str(path)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError("League JSON must contain an observations list")
        rows = payload.get("observations")
        source = str(payload.get("source") or path)
    if not isinstance(rows, list) or not rows:
        raise ValueError("League input requires a nonempty observations list")
    observations, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each league observation must be an object")
        item = {}
        for key in ("league_id", "league_name", "team_id", "team_name"):
            value = row.get(key)
            if value is None or not str(value).strip():
                raise ValueError(f"League observation requires {key}")
            item[key] = str(value).strip()
        for key in ("season", "round"):
            item[key] = positive_integer(row.get(key), key)
        for key in ("cost_cap", "roster_value", "bank", "points", "modeled_lineup_change"):
            item[key] = optional_number(row.get(key))
            if key in ("cost_cap", "roster_value", "bank") and item[key] is not None and item[key] < 0:
                raise ValueError(f"{key} must be nonnegative")
        roster, bank = item["roster_value"], item["bank"]
        if roster is not None and bank is not None:
            derived = roster + bank
            if item["cost_cap"] is not None and item["cost_cap"] != derived:
                raise ValueError("cost_cap conflicts with roster_value + bank")
            item["cost_cap"] = derived
        item["manager"] = str(row.get("manager") or "")
        item["lineup"] = row.get("lineup", [])
        item["observed_at"] = str(row.get("observed_at") or "")
        key = (item["league_id"], item["season"], item["team_id"], item["round"])
        if key in seen:
            raise ValueError(f"Duplicate league/team/round observation: {key}")
        seen.add(key)
        observations.append(item)
    return observations, source


def analyze_league(observations: list[dict], query: str, season: int,
                   round_number: int | None = None, compare_round: int | None = None,
                   initial_cap: Decimal = Decimal("100")) -> dict:
    if not initial_cap.is_finite() or initial_cap <= 0:
        raise ValueError("--initial-cap must be positive")
    seasonal = [x for x in observations if x["season"] == season]
    ids = {x["league_id"] for x in seasonal if x["league_id"] == query}
    if not ids:
        ids = {x["league_id"] for x in seasonal if x["league_name"].casefold() == query.strip().casefold()}
    if len(ids) != 1:
        raise ValueError("League not found or name ambiguous for this season; use its league ID")
    rows = [x for x in seasonal if x["league_id"] in ids]
    current_round = max(x["round"] for x in rows) if round_number is None else round_number
    prior_round = current_round - 1 if compare_round is None else compare_round
    if current_round < 1 or prior_round < 0 or prior_round >= current_round:
        raise ValueError("Comparison round must be earlier than the report round")
    current = [x for x in rows if x["round"] == current_round]
    if not current:
        raise ValueError(f"No league observations for round {current_round}")
    prior = {x["team_id"]: x for x in rows if x["round"] == prior_round}
    caps = [x["cost_cap"] for x in current if x["cost_cap"] is not None]
    richest = max(caps) if caps else None
    points = [x["points"] for x in current if x["points"] is not None]
    leader_points = max(points) if points else None
    result = []
    for row in current:
        cap = row["cost_cap"]
        previous = prior.get(row["team_id"], {})
        old_cap = previous.get("cost_cap")
        old_points = previous.get("points")
        change = cap - old_cap if cap is not None and old_cap is not None else None
        result.append({**row, "previous_cost_cap": old_cap, "cost_cap_change": change,
                       "cost_cap_change_percent": change / old_cap * 100 if change is not None and old_cap else None,
                       "growth_from_initial_cap": cap - initial_cap if cap is not None else None,
                       "gap_to_richest": richest - cap if cap is not None else None,
                       "cost_cap_rank": 1 + sum(c > cap for c in caps) if cap is not None else None,
                       "points_rank": 1 + sum(p > row["points"] for p in points) if row["points"] is not None else None,
                       "points_gap": leader_points - row["points"] if row["points"] is not None else None,
                       "points_change": row["points"] - old_points if row["points"] is not None and old_points is not None else None})
    result.sort(key=lambda x: (x["cost_cap"] is None, -(x["cost_cap"] or 0), x["team_id"]))
    changes = [x["cost_cap_change"] for x in result if x["cost_cap_change"] is not None]
    warnings = ["Ranks and summaries cover supplied teams only; input may be a partial league.",
                "Compare snapshots taken at the same stage of each round. Changes are observed budget differences, not inferred asset price gains.",
                "Growth uses the configured initial cap; it does not establish a team's actual starting budget."]
    if len(caps) != len(current):
        warnings.append(f"{len(current) - len(caps)} teams have unknown cost caps; roster value alone is insufficient.")
    if len(changes) != len(current):
        warnings.append(f"{len(current) - len(changes)} teams lack comparable caps in round {prior_round}; changes remain unknown.")
    if any(not x["observed_at"] for x in current):
        warnings.append("Some observations have no observed_at timestamp; data freshness is unknown.")
    return {"league_id": next(iter(ids)), "league_name": current[0]["league_name"], "season": season,
            "round": current_round, "compare_round": prior_round, "initial_cap": initial_cap,
            "summary": {"teams": len(current), "known_caps": len(caps), "comparable_teams": len(changes),
                        "mean_cost_cap": sum(caps) / len(caps) if caps else None,
                        "median_cost_cap": median(caps) if caps else None,
                        "mean_cost_cap_change": sum(changes) / len(changes) if changes else None},
            "warnings": warnings, "teams": result}


def render_league(report: dict) -> str:
    def fmt(value, monetary=False, signed=False):
        if value is None:
            return "N/A"
        return money(value, signed) if monetary else number(value)
    summary = report["summary"]
    return "\n\n".join([
        f"{report['league_name']} ({report['season']}) — round {report['round']} vs {report['compare_round']}",
        f"Source: {report['source']}",
        f"Teams: {summary['teams']} | Known caps: {summary['known_caps']} | Comparable: {summary['comparable_teams']}\n"
        f"Mean cap: {fmt(summary['mean_cost_cap'], True)} | Median cap: {fmt(summary['median_cost_cap'], True)} | "
        f"Mean change ($M): {fmt(summary['mean_cost_cap_change'], True, True)}\n"
        f"Initial cap baseline: {money(report['initial_cap'])}",
        table(["Cap rank", "Team", "Manager", "Cost cap", "Δ cap $M", "Growth $M", "Gap $M", "Bank", "Roster value", "Model Δ $M", "Pts rank", "Points", "Δ points"], [
            [str(x["cost_cap_rank"] or "N/A"), x["team_name"], x["manager"], fmt(x["cost_cap"], True),
             fmt(x["cost_cap_change"], True, True), fmt(x["growth_from_initial_cap"], True, True),
             fmt(x["gap_to_richest"]), fmt(x["bank"], True), fmt(x["roster_value"], True),
             fmt(x.get("modeled_lineup_change"), True, True), str(x["points_rank"] or "N/A"),
             fmt(x["points"]), fmt(x["points_change"])] for x in report["teams"]]),
        "\n".join("Note: " + x for x in report["warnings"])])
