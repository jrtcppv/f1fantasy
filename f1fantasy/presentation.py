from collections import Counter
from dataclasses import asdict
from decimal import Decimal
import json

from .config import Config
from .models import Dataset
from .pricing import PricingModel
from .rollover import Analysis, Opportunity
from .validation import ValidationReport


def number(value: Decimal) -> str:
    return format(value.normalize(), "f")


def money(value: Decimal, signed: bool = False) -> str:
    places = max(1, -value.normalize().as_tuple().exponent)
    return f"{value:+.{places}f}" if signed else f"${value:.{places}f}M"


def table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "(none)"
    # Remove terminal control characters from externally supplied display strings.
    clean = lambda x: "".join(c if c.isprintable() else " " for c in str(x))
    rows = [[clean(cell) for cell in row] for row in rows]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = lambda row: "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths]), *(line(row) for row in rows)])


def metadata(dataset: Dataset) -> str:
    return f"Source: {dataset.source}\nData fetched: {dataset.fetched_at or 'unknown'}\n" + "\n".join(f"Note: {w}" for w in dataset.warnings)


def overview(rows: list[Opportunity], assumed: Decimal) -> str:
    return table(["Asset", "Type", "Price", "Team", "history_count", "Status", "Drop Race", "DropPts", "Retained", "Total3", "Keep2", "Need +Rise", "Need Max", f"Score={number(assumed)} Δ$M", "Safety", "Opportunity"], [
        [x.asset.code, x.asset.kind, money(x.price), x.asset.team or "unknown", str(x.history_count),
         "NEW ASSET" if x.history_count == 0 else "SHORT HISTORY" if x.history_count < 3 else "",
         x.races[0].name if x.history_count == 3 else "—",
         number(x.scores[0]) if x.history_count == 3 else "—",
         ", ".join(map(number, x.scores[-2:])) or "—", number(x.current_three_race_total),
         number(x.retained_two_race_total), number(x.positive_rise_required_score),
         number(x.max_rise_required_score), money(x.assumed_projection.change, True),
         f"{x.max_rise_safety_margin:+g}", f"{x.cost_cap_opportunity_score:.1f}"] for x in rows])


def render_analysis(result: Analysis, config: Config, assumed: Decimal, view: str,
                    locked_threshold: Decimal) -> str:
    rows = result.opportunities
    parts = [f"Next race: {result.target.name} ({result.target.date})",
             "Recent calendar races (asset histories may differ): " + " → ".join(r.name for r in result.window) + " → upcoming",
             "Conditional on the configured pricing model; opportunity is a heuristic, not a probability."]
    if view in ("all", "opportunities"):
        parts += ["Cost-Cap Opportunities", overview(rows, assumed)]
    if view in ("all", "locked"):
        locked = [x for x in rows if x.max_rise_required_score <= locked_threshold]
        parts += [f"Maximum Rise Nearly Locked In (need ≤ {number(locked_threshold)})",
                  f"Need ≤ 5: {sum(x.max_rise_required_score <= 5 for x in rows)} | "
                  f"Need ≤ 0: {sum(x.max_rise_required_score <= 0 for x in rows)} | "
                  f"Can score negative: {sum(x.max_rise_required_score < 0 for x in rows)}",
                  overview(sorted(locked, key=lambda x: x.max_rise_required_score), assumed)]
    if view in ("all", "dropping"):
        parts += ["Bad Result Rolling Off", overview(sorted((x for x in rows if x.history_count == 3), key=lambda x: x.scores[0]), assumed)]
    if view in ("all", "retained"):
        parts += ["Two Strong Races Banked", overview(sorted(rows, key=lambda x: -x.retained_two_race_total), assumed)]
    if view in ("all", "scenarios"):
        parts += ["Projected Cost Cap Under Scenario Scores (actual change in $M, including floor)",
                  table(["Asset", "Price", *map(number, config.scenarios)], [
                      [x.asset.code, money(x.price), *(money(x.scenarios[s].change, True) for s in config.scenarios)] for x in rows])]
    parts += [f"Analyzed: {len(rows)} | Inactive excluded: {result.inactive_count} | Missing/invalid excluded: {len(result.exclusions)}"]
    parts.extend(f"INACTIVE {name}: {reason}" for name, reason in result.inactive_details.items())
    parts.extend(f"EXCLUDED {name}: {reason}" for name, reason in result.exclusions.items())
    return "\n\n".join(parts)


def explanation(x: Opportunity, threshold: Decimal) -> str:
    if x.history_count < 3:
        return (f"{x.asset.name}: {x.history_count} historical scores for this asset ID; "
                f"the upcoming average uses {x.upcoming_window_count} scores. No score rolls off yet.")
    poor = x.scores[0] < min(x.scores[1:])
    if x.max_rise_required_score <= threshold:
        if poor:
            return (f"{x.asset.name} is a strong rollover candidate: a poorer score is dropping out, "
                    f"and the retained races leave only {number(x.max_rise_required_score)} points needed for the maximum rise.")
        return (f"{x.asset.name} needs only {number(x.max_rise_required_score)} points for the maximum rise, "
                "but the dropping result is not worse than both retained races. This is a robust appreciation case without the full bad-good-good pattern.")
    if x.positive_rise_required_score <= threshold:
        return (f"{x.asset.name} needs only {number(x.positive_rise_required_score)} points to enter a positive band, "
                f"but still needs {number(x.max_rise_required_score)} for the maximum rise.")
    return (f"{x.asset.name} is not an attractive low-score rollover candidate under this model: "
            f"a positive rise still requires {number(x.positive_rise_required_score)} points "
            f"and the maximum requires {number(x.max_rise_required_score)}.")


def render_inspect(x: Opportunity, config: Config, assumed: Decimal,
                   locked_threshold: Decimal | None = None) -> str:
    model = PricingModel(config.pricing)
    parts = [f"{x.asset.name} ({x.asset.code}, {x.asset.kind}, ID {x.asset.id})", f"Current price: {money(x.price)}; team: {x.asset.team or 'unknown'}",
             f"history_count: {x.history_count}" + (" — NEW ASSET" if x.history_count == 0 else ""),
             f"Upcoming average divisor: {x.upcoming_window_count}"]
    for i, (race, score) in enumerate(zip(x.races, x.scores)):
        parts.append(f"Race N{'-' + str(x.history_count-1-i) if i < x.history_count-1 else ''}: {race.name}\nFantasy score: {number(score)}\nStatus: "
                     + ("dropping after next race" if i == 0 and x.history_count == 3 else "retained"))
    parts += [f"Current history total (up to three scores): {number(x.current_three_race_total)}\nRetained total: {number(x.retained_two_race_total)}",
              "Required upcoming fantasy score by nominal price band (inclusive, score increment " + number(config.pricing.score_step) + "): "]
    for change, (low, high) in zip(model.changes(x.price), model.ranges(x.retained_two_race_total, x.price, x.upcoming_window_count)):
        interval = f"≤ {number(high)}" if low is None else f"≥ {number(low)}" if high is None else f"{number(low)} to {number(high)}"
        if low is not None and high is not None and low > high:
            interval = "unattainable with configured score increment"
        parts.append(f"{money(change, True)}M: {interval}")
    parts += ["The price floor can reduce a nominal loss to a smaller loss or zero; zero is not a positive band.",
              f"POSITIVE_RISE_REQUIRED_SCORE: {number(x.positive_rise_required_score)}\nMAX_RISE_REQUIRED_SCORE: {number(x.max_rise_required_score)}",
              f"Max-rise safety margin at score {number(assumed)}: {x.max_rise_safety_margin:+g}",
              (f"Rollover improvement: {number(x.rollover_improvement)} (next-score baseline {number(x.expected_next_score)} minus dropping score; baseline is descriptive, not in ranking)" if x.rollover_improvement is not None else "Rollover improvement: N/A (no dropping score)"),
              "Projected price change / new price:"]
    parts.extend(f"{number(s):>4}: {money(p.change, True)}M → {money(p.price)}" for s, p in x.scenarios.items())
    parts += [f"COST_CAP_OPPORTUNITY_SCORE: {x.cost_cap_opportunity_score:.1f}/100",
              "Components (0–1): " + ", ".join(f"{k}={v:.3f}" for k, v in x.components.items()),
              explanation(x, config.locked_threshold if locked_threshold is None else locked_threshold),
              "All price rises are conditional on the inferred model. No probability of a race outcome is estimated."]
    return "\n\n".join(parts)


def render_validation(report: ValidationReport) -> str:
    accuracy = "N/A (no comparable observations)" if report.accuracy is None else f"{report.accuracy:.2f}%"
    parts = [f"Pricing validation: {sum(c.match for c in report.cases)}/{len(report.cases)} matched; accuracy {accuracy}",
             f"Skipped: {len(report.skipped)}. No thresholds were fitted or changed."]
    def rows(cases):
        return table(["Asset", "ID", "Race", "Pre $M", "history_count", "Total", "AvgPPM", "Pred Δ$M", "Actual Δ$M", "Distance"], [
            [c.asset, c.asset_id, c.race, number(c.price), str(c.history_count), number(c.total), f"{c.ppm:.6f}", money(c.predicted, True),
             money(c.actual, True), f"{c.boundary_distance:.6f}"] for c in cases])
    parts += ["Mismatches", rows([c for c in report.cases if not c.match]),
              "Near threshold boundaries (distance uses unrounded AvgPPM)", rows([c for c in report.cases if c.near_boundary])]
    counts = Counter(s["reason"] for s in report.skipped)
    parts.extend(f"Skipped {count}: {reason}" for reason, count in counts.items())
    parts.append("Use --format json for all matched, mismatched, and individually skipped observations.")
    return "\n\n".join(parts)


def json_output(value) -> str:
    # JSON object keys cannot be Decimals; scenarios become explicit keyed strings.
    def convert(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return convert(asdict(obj))
        if isinstance(obj, dict):
            return {str(k): convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [convert(v) for v in obj]
        if isinstance(obj, Decimal):
            return str(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj
    return json.dumps(convert(value), indent=2, ensure_ascii=False)
