"""Public league lineups; private cash balances are deliberately not inferred."""
from decimal import Decimal
from urllib.parse import unquote

from .online import OnlineProvider, ProviderError
from ..rollover import analyze
from ..config import decimal


def fetch_league(config, cache_dir, season, league_id, league_name, offline=False, refresh=False):
    if not str(league_id).isdigit():
        raise ValueError("--league-id must be numeric")
    provider = OnlineProvider(config.online, cache_dir, season, offline, refresh)
    base = config.online["base_url"].rstrip("/")
    url = f"{base}/feeds/leaderboard/privateleague/list_1_{league_id}_0_1.json"
    payload = provider.http.get(url)
    try:
        members = payload["Value"]["leaderboard"]
        if not isinstance(members, list) or not members:
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("League feed changed or leaderboard is empty") from exc
    dataset = provider.fetch()
    analysis = analyze(dataset, config, season, None, config.conservative_score, None)
    assets = {x.asset.id: x for x in analysis.opportunities}
    prices = {x.asset_id: x.price for x in dataset.prices if x.race_id == analysis.target.id}
    names = {x.id: x.code for x in dataset.assets}
    observations = []
    seen = set()
    for member in members:
        team_id = f"{member['social_id']}:{member['team_no']}"
        if team_id in seen:
            raise ProviderError(f"Duplicate leaderboard team {team_id}")
        seen.add(team_id)
        lineup = member.get("user_team")
        if not isinstance(lineup, list) or len(lineup) != 7 or len(set(map(str, lineup))) != 7:
            raise ProviderError(f"Expected seven unique lineup assets for {team_id}")
        ids = [f"{season}:{x}" for x in lineup]
        roster = sum((prices[x] for x in ids), Decimal(0)) if all(prices.get(x) is not None for x in ids) else None
        change = sum((assets[x].assumed_projection.change for x in ids), Decimal(0)) if all(x in assets for x in ids) else None
        observations.append({"league_id": str(league_id), "league_name": league_name,
                             "season": season, "round": analysis.target.round, "team_id": team_id,
                             "team_name": unquote(member["team_name"]), "manager": member.get("user_name", ""),
                             "points": decimal(member["cur_points"]) if member.get("cur_points") is not None else None,
                             "roster_value": roster, "bank": None, "cost_cap": None,
                             "observed_at": min(provider.http.timestamps) if provider.http.timestamps else "",
                             "lineup": [names.get(x, x) for x in ids], "modeled_lineup_change": change})
    return {"source": url, "observations": observations}, [
        *dataset.warnings,
        "Public leaderboard cash balances are unavailable: cost cap and actual cost-cap change remain unknown.",
        f"Roster values use prices for {analysis.target.name}; leaderboard lineups may be stale or reflect a chip. They are not verified current portfolios.",
        f"Modeled lineup change assumes every asset scores {config.conservative_score} next round, with no transfers or chip effects; it is not an observed cost-cap change.",
        "Leaderboard points are overall totals at its feed time, not points earned in the upcoming round.",
        f"Leaderboard feed time (UTC): {payload.get('FeedTime', {}).get('UTCTime', 'unknown')}",
        "League name is a user-supplied label; the public feed does not verify it."]
