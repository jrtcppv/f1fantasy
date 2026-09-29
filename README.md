# F1 Fantasy rollover analyzer

Find drivers and constructors whose next price rise needs very little from the
upcoming race. The central calculation is **MAX_RISE_REQUIRED_SCORE**: how many
points are still needed after up to two retained scores are already banked.
Pricing history belongs to the exact fantasy asset ID, including after team changes.
Negative requirements are preserved and highlighted. This is a team-value tool,
with no race-result prediction model.

Python 3.11+, no runtime dependencies. Public official data feeds are supported,
along with SQLite snapshots and local JSON/CSV. Read [data availability and live
validation findings](docs/data-sources.md) for source semantics and limitations.

## Quick start

From the repository root:

```bash
python -m f1fantasy rollover
python -m f1fantasy analyze --next-race baku
python -m f1fantasy inspect ALB
python -m f1fantasy validate-pricing
```

Commands automatically acquire the official current-season calendar, every
completed round, and the upcoming round's asset prices/status; downloads are
cached and normalized data is saved in `.f1fantasy/history.sqlite`. No account,
token, or login is required by the public endpoints tested. `--season` defaults
to the current UTC year. Internet restrictions may require running from a
network-enabled environment.

Optional installation provides the `f1fantasy` executable:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Try the completely **synthetic** example without network access:

```bash
python -m f1fantasy rollover --local examples/synthetic.json --season 2026 --db /tmp/f1-demo.sqlite
python -m f1fantasy inspect SYN --local examples/synthetic_csv --season 2026 --db /tmp/f1-demo.sqlite
```

The sample driver has a dropping score of -25 and retained scores 18, 20 at $8M.
The default formula requires **-9** points for +$0.6M, giving a safety margin of
**+9** at score zero. All sample names and values are fabricated test fixtures,
never fallback data for the online provider.

## League analysis

Analyze the public lineups in your league:

```bash
python -m f1fantasy league "Fantasy2Survive Season 3" --league-id 2093801
python -m f1fantasy league "Fantasy2Survive Season 3" --league-id 2093801 --format json
python -m f1fantasy league "Fantasy2Survive Season 3" --league-id 2093801 --export league-snapshot.json
```

A numeric ID can also be the positional argument. Names are labels for online
reports: name search requires authentication, so provide `--league-id`.
`--season`, `--config`, `--cache-dir`, `--offline`, and `--refresh` are supported.
Exports refuse to overwrite existing files. League observations are kept separate
from the asset-history SQLite database.

**Public lineups do not reveal total cost cap.** Live reports show overall points,
points rank/gap (gap in JSON), roster value at upcoming-round prices, and modeled
lineup price change assuming every asset earns the configured conservative score
(default zero). These are conditional calculations for the published lineup;
transfers, stale lineups, and chips can make that lineup different from the team's
current owned portfolio. Cash balances, cost caps, and observed changes remain
N/A. Public leaderboards may contain only part of a larger league.

For exact cost caps and changes, supply normalized JSON or CSV observations:

```bash
python -m f1fantasy league "Fantasy2Survive Season 3" --local league-history.csv
python -m f1fantasy league "Fantasy2Survive Season 3" --local league-history.csv --round 15 --compare-round 12
```

CSV format (the following values are **synthetic**, not your league's results):

```csv
league_id,league_name,season,round,team_id,team_name,manager,cost_cap,roster_value,bank,points,observed_at
2093801,Fantasy2Survive Season 3,2026,14,demo:1,Example Team,Example Manager,105,103,2,2000,2026-09-13T18:00:00Z
2093801,Fantasy2Survive Season 3,2026,15,demo:1,Example Team,Example Manager,106.2,104.5,1.7,2200,2026-09-26T18:00:00Z
```

JSON uses `{"source": "description", "observations": [...]}` with the same row
fields. Required fields are `league_id`, `league_name`, `season`, `round`,
`team_id`, and `team_name`. Use stable team IDs, including team number when a
manager has multiple teams. Money is in millions. `points` means cumulative
season points. Optional missing values stay unknown; explicit zero is preserved.
`cost_cap` can be supplied directly or computed as `roster_value + bank` when
both are known. Conflicting values and duplicate team/round records fail.

The report ranks known caps, calculates gaps to the richest team, mean/median
caps, matched-team budget changes and points changes, and growth against
`--initial-cap` (default $100M, an explicit baseline assumption). JSON additionally
includes percentage budget change and points gaps. Latest supplied round is the
default; comparison is strictly the preceding round. Missing rounds are not
bridged unless you explicitly choose `--compare-round`. Use observations from
the same stage of each round. A points correction can affect points differences;
a budget difference is not independently proof of asset appreciation.

Live exports can be reimported, but contain no private budgets. Combine consistent
round observations and add independently obtained cost-cap or cash values to
measure actual growth. Repeated observations for the same team/round must be
resolved before import. Historical online league retrieval is not supported.

## Practical views

The default report includes all five views, with the main table sorted by
`COST_CAP_OPPORTUNITY_SCORE` descending:

```bash
python -m f1fantasy rollover --view opportunities
python -m f1fantasy rollover --view locked --locked-threshold 5
python -m f1fantasy rollover --view locked --locked-threshold 0
python -m f1fantasy rollover --view dropping
python -m f1fantasy rollover --view retained
python -m f1fantasy rollover --view scenarios
python -m f1fantasy rollover --assume-score -5
python -m f1fantasy rollover --assume-score 5 --format json > opportunities.json
```

* **Maximum Rise Nearly Locked In:** filter `Need Max ≤ threshold`, sort by
  required score ascending; show counts needing ≤5, ≤0, or negative points.
* **Bad Result Rolling Off:** dropping score ascending, including the race and
  retained scores. There is no DNF inference; actual negative scores carry through.
* **Two Strong Races Banked:** retained two-race total descending.
* **Scenario matrix:** actual price movements at -10, -5, 0, 5, 10, 15, 20 points,
  applying the price floor. Inspect/JSON also include resulting prices.

`Total3` is the current three-race total; `Keep2` is the retained total. `Need +Rise`
enters a strictly positive nominal band, even at the $3M floor where a bad score
may cause zero loss. `Safety = --assume-score − Need Max`. Scenario scores stay
fixed when `--assume-score` changes; edit the configuration to change them.

Race names, locations such as `baku`, round numbers, and IDs are accepted.
Only the next uncompleted race can be analyzed: a later race would require
unknown intervening scores. Assets use up to their three most recent fantasy scores, keeping the latest two
for the upcoming calculation. `history_count` counts prior scores (0–3);
`NEW ASSET` marks zero history and `SHORT HISTORY` marks one or two scores.
Absent pre-creation races never become zeros, and scores never transfer between
asset IDs, even when both IDs represent the same driver.

A historical price or score establishes that an asset existed. Unexplained
missing/null scores after that point exclude the asset; explicitly inactive
rounds do not count as races in its pricing history. A returning ID retains its
own earlier scores. With no historical records, the asset is treated as new;
truncated imports cannot independently prove a creation date. Exclusions and
short histories show current price and team (`unknown` if unavailable).


## Exact pricing and configuration

```bash
python -m f1fantasy init-config pricing.toml
python -m f1fantasy rollover --config pricing.toml
python -m f1fantasy validate-pricing --config pricing.toml
```

The full defaults are in [default_config.toml](f1fantasy/default_config.toml).
Overrides may contain only the fields you change; unknown fields and invalid
threshold ordering fail explicitly. `init-config` refuses to overwrite a file.

For current price `P` in millions, retained points `R`, and
`N = min(history_count, 2) + 1` scores in the upcoming window:

```text
AvgPPM = (R + next_score) / (N × P)

AvgPPM band           Price < $18.5M   Price >= $18.5M
< 0.605                  -$0.6M          -$0.3M
>= 0.605 and < 0.900      -$0.2M          -$0.1M
>= 0.900 and < 1.195      +$0.2M          +$0.1M
>= 1.195                 +$0.6M          +$0.3M

minimum_next_score(t) = ceil((N × P × t − R) / score_step) × score_step
POSITIVE_RISE_REQUIRED_SCORE uses t = 0.900
MAX_RISE_REQUIRED_SCORE uses t = 1.195
new_price = max($3.0M, P + nominal_change)
actual_change = new_price − P
```

Defaults assume integer upcoming fantasy scores (`score_step=1`). `inspect`
shows the complete inclusive score interval for each of the four nominal bands;
JSON includes `price_bands` for every analyzed asset. The bottom band is unbounded
below. Decimal score increments can be configured if scoring changes. Required
scores mean entering that band **or a higher band**; coarse increments can make
an intermediate interval unattainable, which inspect reports.

All prices and input scores use `Decimal`; threshold comparisons and inversions
use exact rational arithmetic to avoid binary float errors. Comparisons include
the lower threshold and exclude the upper threshold. The current pre-race price
determines both the divisor and tier, including exactly $18.5M.

The requested default does **not** round AvgPPM. To test the community rounding
hypothesis explicitly:

```toml
[pricing]
ppm_decimals = 3
rounding = "half_up" # alternatively "half_even"
```

The inverse calculation also honors rounding, including halfway ties. Scores
are exact for the chosen configuration; the underlying pricing formula remains
inferred. No parameters change automatically during validation.

## Opportunity formula

Every component is clamped to [0, 1]. The score is a transparent heuristic on
[0, 100], **not a probability**, and does not measure expected fantasy points.
Defaults (`drop`, `R`, `P`, `need_max`, and `assume` are per asset):

```text
dropping   = clamp((5 − drop) / 25), or 0 if no score drops
retained   = clamp(R / (N × P × 1.195))
safety     = clamp(0.5 + (assume − need_max) / 40)
magnitude  = clamp(maximum_dollar_rise / 0.6)
robustness = mean(clamp(actual_change(score) / maximum_dollar_rise))
             over stress scores [-10, -5, 0, 5]

COST_CAP_OPPORTUNITY_SCORE =
  100 × (20×dropping + 15×retained + 35×safety
         + 10×magnitude + 20×robustness) / 100
```

The denominator is the sum of configured weights. All weights, reference values,
scales, and stress scenarios are configurable. Robustness credits positive
appreciation only: being unable to lose at the floor does not count as growth.
Cheaper assets benefit from retained performance relative to price and eligibility
for the larger maximum dollar rise. Individual components appear in `inspect` and
JSON. Ties break on lower max-rise required score, then asset ID.

Assets with excellent retained totals can rank highly even without a terrible
dropping result. Inspect explains that distinction, and the dropping-score view
lets you focus directly on the bad-good-good pattern. No arbitrary "good race"
classification is required to use the exact score cutoffs.

`rollover_improvement = expected_next_score − dropping_score`. By default,
`expected_next_score` is the mean of available retained scores: a
descriptive baseline, not an inferred missing score or a race forecast. Override
with `--expected-score`. With no retained scores the baseline is N/A; without
a dropping score, rollover improvement is N/A. This metric has **zero influence** on the ranking.

## Historical validation

```bash
python -m f1fantasy sync --refresh --export season-2026-snapshot.json
python -m f1fantasy validate-pricing --stored
python -m f1fantasy validate-pricing --stored --format json > validation.json
```

For race r, validation uses up to three scores from that exact asset ID, ending
at r, divides by the available count, and uses the price
**before r**. It compares the modeled, floor-adjusted change to the difference
between pre-race prices r+1 and r. It never uses today's price in a historical
window, skips calendar gaps, and never bridges missing adjacent price snapshots.

Explicit `price_changes` can supply an observed after-race movement when the next
price is unavailable. Conflicts with an adjacent observed price pair are reported
as data conflicts and excluded from accuracy. Historical inactive assets can be
validated where their earlier recorded scores are available.

Reports include accuracy, all mismatches, cases near thresholds, and exclusion
counts by reason. JSON contains every comparable and individually skipped case.
`boundary_tolerance` is in unrounded AvgPPM units and affects reporting only.
First- and second-race histories use one and two scores respectively. No-observation accuracy is `null`/N/A, never 100%. The August substitution regression matches six observed movements; source
notes distinguish this check from the earlier three-score-only validation.

## Local data, cache, and storage

```bash
python -m f1fantasy sync --local my-season.json --season 2025
python -m f1fantasy rollover --local path/to/csv-directory --season 2026
python -m f1fantasy rollover --offline
python -m f1fantasy rollover --stored
python -m f1fantasy sync --cache-dir /tmp/f1-cache --db /tmp/f1.sqlite
```

`--offline` reads HTTP cache only, including expired entries with an explicit
warning. `--stored` reads SQLite only. `--refresh` forces online requests and is
incompatible with local/offline/stored sources. Network errors never silently
substitute stale, estimated, or synthetic data. The report includes provenance and
the oldest response retrieval timestamp. Local files without `fetched_at` use
import time; this does not establish when their observations were collected.

A JSON bundle contains `races`, `assets`, `fantasy_scores`, `prices`, and optional
`price_changes`, `source`, `fetched_at`, `warnings`. A CSV directory contains the
same five table names with `.csv` suffixes (`price_changes.csv` is optional).
Use the [synthetic JSON](examples/synthetic.json) or [CSV directory](examples/synthetic_csv)
as a template:

| Table | Columns |
| --- | --- |
| races | `id,season,round,name,date,completed,location` |
| assets | `id,code,name,kind,active,team` (`team` optional) |
| fantasy_scores | `asset_id,race_id,points,status` |
| prices | `asset_id,race_id,price` (pre-race, $M) |
| price_changes | `asset_id,race_id,change` (observed after this race, $M) |

Dates use YYYY-MM-DD; booleans use true/false or 1/0. Asset kind is `driver` or
`constructor`. Unknown active status and scores/prices use JSON null or blank CSV
cells, never guessed zeros. `status` is optional descriptive text such as DNF; `inactive` explicitly marks
a non-participating asset round whose placeholder score must not be counted.
IDs should be season-qualified and stable; display codes need not be unique.
Use a unique ID for `inspect` if a code is ambiguous. Supply one whole season per
import and match `--season`. Import transactionally replaces that season's SQLite
snapshot, including missing values, while preserving other seasons. Keep a
separate `--db` for demo data or independent sources.

SQLite contains `races`, `assets`, `fantasy_scores`, `prices`, `price_changes`, and
snapshot provenance. Price and score values are stored as decimal text, avoiding
SQLite floating-point conversion. Raw HTTP cache envelopes retain URL/timestamp
and the original parsed payload. Dated JSON exports preserve audited snapshots.

## Development

```bash
python -m pytest -q
# If unrelated globally installed pytest plugins interfere in a restricted shell:
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Tests cover race windows/gaps, negative DNF scores, retained totals, threshold
inequalities and inverse cutoffs, rounding ties, both tiers, floor clipping,
constructors, missing data, scenarios, ranking independence from expected scores,
historical timing/conflicts, provider schema/cache behavior, SQLite persistence,
JSON/CSV imports, and CLI views. Network tests use isolated mock feeds; no live
result is hardcoded into unit tests.

Business logic lives in `pricing.py`, `rollover.py`, and `validation.py`.
Providers implement `fetch() -> Dataset`; acquisition stays behind that interface.
`storage.py` owns SQLite; `presentation.py` formats tables and exact-decimal JSON;
`cli.py` composes them. Exit code 0 means successful execution (validation
mismatches remain a successfully produced report); 2 means invalid input, failed
acquisition, insufficient windows, no analyzable assets, or no validation cases.
