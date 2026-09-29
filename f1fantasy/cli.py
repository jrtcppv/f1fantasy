import argparse
import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
import sys

from .config import decimal, load_config
from .league import analyze_league, load_observations, render_league
from .presentation import (json_output, metadata, render_analysis, render_inspect,
                           render_validation)
from .providers.csv_provider import LocalProvider
from .providers.online import OnlineProvider
from .providers.league import fetch_league
from .rollover import analyze
from .storage import Storage, bundle
from .validation import validate_pricing


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Find F1 Fantasy appreciation banked in retained scores.")
    sub = root.add_subparsers(dest="command", required=True)
    league = sub.add_parser("league", help="Compare league team cost caps and points from JSON/CSV observations")
    league.add_argument("name", help="Exact league name or league ID")
    league.add_argument("--local", type=Path, help="Normalized league observations (JSON or CSV)")
    league.add_argument("--league-id", help="Official numeric league ID for public lineup analysis")
    league.add_argument("--config", type=Path)
    league.add_argument("--cache-dir", type=Path, default=Path(".f1fantasy/cache"))
    league.add_argument("--offline", action="store_true")
    league.add_argument("--refresh", action="store_true")
    league.add_argument("--export", type=Path, help="Save normalized observations as JSON")
    league.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    league.add_argument("--round", type=int, dest="round_number", help="Default: latest supplied round")
    league.add_argument("--compare-round", type=int, help="Default: immediately preceding round")
    league.add_argument("--initial-cap", type=decimal, default=decimal("100"), help="Growth baseline in $M (default 100)")
    league.add_argument("--format", choices=("table", "json"), default="table")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help="TOML overrides for the inferred pricing model and ranking")
    common.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    common.add_argument("--db", type=Path, default=Path(".f1fantasy/history.sqlite"))
    common.add_argument("--cache-dir", type=Path, default=Path(".f1fantasy/cache"))
    source = common.add_mutually_exclusive_group()
    source.add_argument("--local", type=Path, help="JSON bundle or directory of CSV tables")
    source.add_argument("--stored", action="store_true", help="Read the SQLite snapshot without downloading")
    source.add_argument("--offline", action="store_true", help="Read cached official HTTP responses only")
    common.add_argument("--refresh", action="store_true", help="Bypass HTTP cache TTL")
    common.add_argument("--format", choices=("table", "json"), default="table")
    analysis = argparse.ArgumentParser(add_help=False, parents=[common])
    analysis.add_argument("--next-race", help="Race name, location (e.g. baku), round number, or ID")
    analysis.add_argument("--assume-score", type=decimal, help="Conservative score for safety margin and main table")
    analysis.add_argument("--expected-score", type=decimal, help="Descriptive rollover baseline only; default is retained mean")
    analysis.add_argument("--locked-threshold", type=decimal, help="Nearly-locked max-rise score cutoff (default 5)")
    roll = sub.add_parser("rollover", aliases=["analyze"], parents=[analysis], help="Rank rollover opportunities")
    roll.add_argument("--view", choices=("all", "opportunities", "locked", "dropping", "retained", "scenarios"), default="all")
    inspect = sub.add_parser("inspect", parents=[analysis], help="Explain one asset and every price-change band")
    inspect.add_argument("asset", help="Code, exact name, or unique asset ID")
    sync = sub.add_parser("sync", parents=[common], help="Download/import a full season snapshot into SQLite")
    sync.add_argument("--export", type=Path, help="Also write a portable normalized JSON bundle")
    sub.add_parser("validate-pricing", parents=[common], help="Compare model predictions with observed historical movements")
    init = sub.add_parser("init-config", help="Write an editable copy of all defaults")
    init.add_argument("path", nargs="?", type=Path, default=Path("pricing.toml"))
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "league":
            warnings = []
            if args.refresh and (args.offline or args.local):
                raise ValueError("--refresh requires the online provider")
            if args.local and (args.league_id or args.offline):
                raise ValueError("--local cannot be combined with --league-id or --offline")
            if args.local:
                observations, source = load_observations(args.local)
                snapshot = {"source": source, "observations": observations}
                if args.local.suffix.lower() != ".csv":
                    warnings = json.loads(args.local.read_text(encoding="utf-8")).get("warnings", [])
                    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
                        raise ValueError("League warnings must be a list of strings")
            else:
                league_id = args.league_id or (args.name if args.name.isdigit() else None)
                if league_id is None:
                    raise ValueError("Name lookup requires account access. Supply --league-id (2093801 for "
                                     "Fantasy2Survive Season 3), or --local league.json for budget snapshots.")
                if args.round_number is not None or args.compare_round is not None:
                    raise ValueError("Historical round comparisons require --local observations")
                snapshot, warnings = fetch_league(load_config(args.config), args.cache_dir, args.season,
                                                 league_id, args.name, args.offline, args.refresh)
                observations, source = snapshot["observations"], snapshot["source"]
            report = analyze_league(observations, args.name, args.season, args.round_number,
                                   args.compare_round, args.initial_cap)
            report["source"] = source
            report["warnings"].extend(warnings)
            snapshot["warnings"] = warnings
            if args.export:
                with args.export.open("x", encoding="utf-8") as handle:
                    handle.write(json_output(snapshot) + "\n")
            print(json_output(report) if args.format == "json" else render_league(report))
            return 0 if report["summary"]["known_caps"] or any(x["roster_value"] is not None for x in observations) else 2
        if args.command == "init-config":
            # Avoid overwriting explicitly tuned thresholds.
            with args.path.open("x") as handle:
                handle.write(files("f1fantasy").joinpath("default_config.toml").read_text())
            print(f"Wrote {args.path}")
            return 0
        config = load_config(args.config)
        storage = Storage(args.db)
        if args.refresh and (args.offline or args.stored or args.local):
            raise ValueError("--refresh requires the online provider")
        if args.stored:
            dataset = storage.load(args.season)
            dataset.warnings.append("STORED SNAPSHOT: run sync to update calendar, status, and prices.")
        else:
            provider = LocalProvider(args.local) if args.local else OnlineProvider(
                config.online, args.cache_dir, args.season, args.offline, args.refresh)
            dataset = provider.fetch()
            storage.save(dataset, args.season)
        if args.command == "sync":
            if args.export:
                args.export.write_text(json_output(bundle(dataset)) + "\n", encoding="utf-8")
            summary = {"source": dataset.source, "fetched_at": dataset.fetched_at, "races": len(dataset.races),
                       "assets": len(dataset.assets), "scores": len(dataset.scores), "prices": len(dataset.prices), "db": str(args.db),
                       "warnings": dataset.warnings}
            print(json_output(summary) if args.format == "json" else metadata(dataset) + f"\nStored {len(dataset.races)} races, {len(dataset.assets)} assets, {len(dataset.scores)} scores in {args.db}")
            return 0
        if args.command == "validate-pricing":
            report = validate_pricing(dataset, config.pricing, args.season)
            print(json_output({"source": dataset.source, "fetched_at": dataset.fetched_at, "warnings": dataset.warnings,
                               "pricing": config.pricing, "accuracy_percent": report.accuracy, "report": report})
                  if args.format == "json" else metadata(dataset) + "\n\n" + render_validation(report))
            return 0 if report.cases else 2
        assumed = config.conservative_score if args.assume_score is None else args.assume_score
        threshold = config.locked_threshold if args.locked_threshold is None else args.locked_threshold
        result = analyze(dataset, config, args.season, args.next_race, assumed, args.expected_score)
        if args.command == "inspect":
            query = args.asset.casefold()
            matches = [x for x in result.opportunities if query in (x.asset.code.casefold(), x.asset.name.casefold(), x.asset.id.casefold())]
            if len(matches) != 1:
                excluded = [f"{key}: {reason}" for key, reason in result.exclusions.items() if query in key.casefold()]
                raise ValueError("Asset unknown, inactive, excluded, or ambiguous; use unique ID. " + "; ".join(excluded))
            output = matches[0]
            text = render_inspect(output, config, assumed, threshold)
        else:
            output = result
            text = render_analysis(result, config, assumed, args.view, threshold)
        print(json_output({"source": dataset.source, "fetched_at": dataset.fetched_at, "warnings": dataset.warnings,
                           "config": config, "assume_score": assumed, "locked_threshold": threshold, "result": output})
              if args.format == "json" else metadata(dataset) + "\n\n" + text)
        return 0 if result.opportunities else 2
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
