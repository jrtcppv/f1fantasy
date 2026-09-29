# Data sources and what is realistically obtainable

Investigation and live verification: 2026-09-13. This tool analyzes the official
F1 Fantasy game, not alternative fantasy leagues or the FIA financial cost cap.

| Source | Available data | Decision / limitation |
| --- | --- | --- |
| [Official schedule JSON](https://fantasy.formula1.com/feeds/schedule/raceday_en.json) | Season, fantasy gameweek IDs, GP names, locations, session dates, completion flags | Default calendar. One `SessionType=Race` entry per fantasy weekend; sprint sessions are not separate pricing races. |
| [Official round JSON, example round 14](https://fantasy.formula1.com/feeds/drivers/14_en.json) | Both asset types, unique `PlayerId`, `IsActive`, `Value`, `GamedayPoints`, session breakdowns | Default prices, scores, and status. Public GET requests worked without credentials. Round parameter is the calendar's `GamedayId`. |
| [Official game rules](https://fantasy.formula1.com/en/game-rules) | Game rules and scoring explanations, rendered by a JavaScript app | Useful reference, not a documented bulk historical API or a published pricing formula. |
| [mzafram2001 archive](https://github.com/mzafram2001/f1-fantasy) | Round files advertised for 2023–2026; values and fantasy totals | Investigated but not enabled automatically. Its [collector](https://github.com/mzafram2001/f1-fantasy/blob/main/scripts/get_round_data.py) replaces missing/invalid numbers with zero and omits official player IDs and active status. Duplicate TLAs can represent different asset records. A zero in that archive cannot reliably distinguish zero from missing. |
| [JoshCBruce fantasy-data](https://github.com/JoshCBruce/fantasy-data) | Scraped fantasy breakdowns, particularly 2025; handles some team swaps | Potential manually audited historical input. DOM scraping and code-based merging need careful review before import. |
| [EduardoFAFernandes historical data](https://github.com/EduardoFAFernandes/F1FantasyData) | Older price/sentiment snapshots, 2021 and 2022 | Different game era; unsuitable for validating the configured modern formula by default. |

The official feeds are operationally convenient, but **undocumented and mutable**.
They do not offer a stability guarantee or a verified season parameter. The online
adapter checks the schedule season and refuses to relabel the current feed as an
older year. Keep normalized exports and raw cached responses for historical work.
Third-party race results and estimated fantasy scoring are not substituted for
official fantasy totals. All imported points must be unboosted whole-weekend totals,
including sprint points where applicable.

## Price timing and identity

The observed interpretation is:

* `drivers/r_en.json → Value`: **pre-race r price**.
* `drivers/r_en.json → GamedayPoints`: **race r weekend total**, used only when
  the schedule marks the Grand Prix completed (`GDStatus=4`, `MatchStatus=4`).
* Pre-race r+1 price minus pre-race r price: observed change after race r.
* `IsActive` in the latest available/current gameweek feed determines the active
  universe. Missing status is unknown and excluded, not assumed active.
* `PlayerId`, prefixed with season, is the primary key. Codes are display/search
  aliases, not identity. An inactive legacy record is never merged into an active
  one by surname or TLA; inactive historical placeholders are treated as missing.

`OldPlayerValue` was also present, but is not used as an undocumented shortcut for
the before/after price pair. `ProjectedGamedayPoints`, `old_Value`, and `new_value`
are ignored. Upcoming-gameweek point fields are never accepted as completed scores.
The last completed race needs the following round's price feed for validation;
without that price or an explicit observed change it is skipped.

Calendar `Gameday` supplies sequential fantasy rounds. Local calendars must also
use consecutive played-weekend indices, not cancelled calendar slots. Postponed
official entries are omitted. A remaining sequence gap is reported rather than
filled by guesswork.

## Pricing model evidence and limits

The [community pricing analysis](https://www.patreon.com/f1fantasytools/posts/updates-to-2025-125291547)
describes an inferred formula. The [tool author's March 2026 explanation](https://www.reddit.com/r/F1Fantasy/comments/1rp2m11/required_points_for_price_changes_for_the_chinese/)
also describes rounding AvgPPM to three decimal places. These are hypotheses,
not an official specification. Defaults implement the user's unrounded formula;
`ppm_decimals=3` is an explicit alternate configuration for testing rounding.

The live snapshot fetched on 2026-09-13 at approximately 21:53 UTC produced:

* 23 scheduled fantasy weekends, 14 marked completed, 35 unique asset records.
* 33 active assets analyzed for the next race, Azerbaijan; 2 inactive records.
* Default-model validation: **391/392 comparable movements matched (99.74%)**.
* 98 skipped asset/race combinations: 70 from the first two races, where a
  complete three-race window does not exist, and 28 with missing/inactive scores.
* Mismatch: Gasly, Monaco (round 6), pre-race price $12.2M, three-race total 33,
  AvgPPM about 0.901639. Model predicted +$0.2M; adjacent observed prices gave
  -$0.6M. Its proximity to 0.900 is reported, without attributing a cause.

These are reproducibility notes for that downloaded snapshot, not permanent
accuracy claims. No parameters were fitted. Feed corrections, pricing exceptions,
or an incorrect source interpretation can change the result. The score thresholds
are exact **conditional on the supplied model and input data**; this tool does not
estimate the probability that the next race meets them.

## Failure and freshness behavior

HTTP responses are cached with URL and UTC retrieval timestamp, one SHA-256-named
JSON envelope per URL. Default TTL is one hour. The displayed acquisition time is
the oldest response used, making a mixed-age cache visible. `--refresh` refetches;
`--offline` explicitly uses the HTTP cache regardless of TTL; `--stored` explicitly
uses the SQLite snapshot. Neither mode claims live freshness. HTTP errors do not
silently fall back to stale data or a different provider.

Missing/null/blank fantasy scores remain missing. Explicit numeric zero remains
zero. Malformed/nonfinite values, duplicate primary keys, broken references, and
unexpected feed structures fail the import. A successful season import replaces
its previous SQLite snapshot transactionally, so a removed or newly missing field
cannot retain an obsolete value. Other seasons remain intact. Raw HTTP cache files
are replaced atomically; use dated `sync --export` files to retain successive
normalized snapshots across source revisions.

## Asset-history validation, snapshot fetched 2026-09-22

A field-filtered copy of the official schedule and LAW/TSU/HAD round records is
checked into `tests/fixtures/official_substitution_2026.json`. Each entry retains
its source URL and retrieval timestamp. Tests replay the adapter without network
access. This snapshot supports the August 23 Dutch GP substitution:

| Asset ID | Team | Initial price | Prior scores | Modeled maximum-rise cutoff |
| --- | --- | --- | --- | --- |
| 2026:116 LAW | Red Bull Racing | $14.5M | 0 | 18 |
| 2026:130 TSU | Racing Bulls | $10.3M | 0 | 13 |

These cutoffs reproduce the requested approximate thresholds using the unchanged
1.195 threshold and a one-score average. Actual point/price observations also
agree: LAW scored 12, 25, 16 in rounds 12–14, with observed changes −$0.2M,
+$0.6M, +$0.2M. TSU scored 5, 17, 1, with changes −$0.6M, +$0.2M, −$0.2M.
All six match available-score averaging (counts 1, 2, 3). Observed movements
support the model but do not by themselves establish exact cutoff boundaries.
Tests also inject a contradictory observation and assert it remains a mismatch.

The current active LAW (2026:114, Racing Bulls) and HAD (2026:11032, Red Bull)
are returning IDs in this snapshot, not newly created IDs. Both have earlier
same-ID scores through Hungary; rounds 12–14 explicitly mark them inactive.
Their most recent three valid scores are respectively 22, 3, 13 and 23, 38, 15.
At current prices $9.7M and $14.5M, their modeled maximum-rise requirements are
19 and −1. No other asset's scores are inherited and no inactive zero placeholder
is included. The observed subsequent price change for their return is not yet
available, so that return behavior remains an unvalidated model assumption.

The adapter now distinguishes `inactive` from `unknown` historical status.
Snapshots imported by the older adapter with `inactive/unknown` cannot reliably
distinguish the two; reimport with `--offline` from the raw cache or sync online
to recover explicit status and team names. Unknown status remains a data problem.

Full-snapshot validation with the updated model matches 460/462 comparable
movements. Two full-three-score-history discrepancies remain visible at Austria
(round 8): GAS predicts −$0.2M versus observed +$0.6M; LAW (2026:114) predicts
+$0.6M versus observed +$0.2M. Neither is part of the August substitution check.
These differ from the older snapshot's results above; no thresholds were changed
to fit either snapshot.

## League feed verification, 2026-09-29

The official web app's public JavaScript identifies the private-league feed as
`/feeds/leaderboard/privateleague/list_{optType}_{leagueId}_{tourGameDayId}_{phaseId}.json`.
For league ID `2093801`, `list_1_2093801_0_1.json` returned four entries with
`social_id`, `team_no`, URL-encoded `team_name`, `user_name`, `user_team` asset IDs,
and `cur_points`. The feed was stamped September 26, 2026, 18:00:55 UTC.
There is no league name, cash balance, or cost cap in this payload. The supplied
name is not independently confirmed by the feed. No completeness guarantee is
available, so summaries describe returned entries only.

The app's name-search endpoint and opponent-team-detail endpoint both returned
HTTP 401 without an authenticated account. Historical leaderboard requests with
round IDs 14 and 15 returned HTTP 403. No authentication workaround or guessed
cash balance is implemented. The league command uses current public lineups for
roster valuation and conditional price scenarios, and normalized user-supplied
observations for actual budget comparisons. Raw public responses use the existing
HTTP cache. Normalized league exports are separate from asset snapshots.
