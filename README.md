# OpenTTDAI

A fun project to "vibe code" an AI Player for the game OpenTTD using GPT 6 Astra and GLM 5.3 flash. 

Mostly an exercise in prompting, even using game images to convey complex issues.

Haven't been able to get this to the efficiency levels of top human coded AIs, but instead changed focus to attempting to make a less irritating AI player than others.

---

A rail-first [OpenTTD](https://www.openttd.org/) NoAI. It builds coal and passenger services, starting each route with one train on a single main line, then expands successful services as demand grows.

OpenTTD AIs are **Squirrel** scripts using the NoAI API — not machine-learning models.

## Load it in OpenTTD

1. Copy (or symlink) this folder into OpenTTD’s AI directory so the game sees `info.nut` and `main.nut`:

   - **macOS:** `~/Documents/OpenTTD/ai/OpenTTDAI/`
   - **Linux:** `~/.openttd/ai/OpenTTDAI/`
   - **Windows:** `%USERPROFILE%\Documents\OpenTTD\ai\OpenTTDAI\`

2. Start OpenTTD → **AI Settings** (on the main menu or in game setup).
3. Slot an AI company and choose **OpenTTDAI**.
4. Set **Start date** / delay low so you don’t wait years for it to wake up.
5. Start a new game. Watch the AI debug window (**Help → AI Debug**) for `AILog` lines.

Restart OpenTTD after changing `info.nut`. Changes to `main.nut` and the other `.nut` files apply when the AI next starts (new game or reload).

API version in `info.nut` is **14**. If your OpenTTD is older, lower `GetAPIVersion()` to match (e.g. `"12"` or `"13"`). If it is newer and refuses the AI, bump that string.

## Layout

| File | Role |
| --- | --- |
| `info.nut` | Name, version, short name `OTAI`, difficulty settings |
| `main.nut` | Company loop: pick towns, handle events |
| `pathfinder.nut` | Grid A* used to lay track (no BaNaNaS library) |
| `builder.nut` | Stations, track, depot |
| `single_track.nut` | Initial single-line planning and deferred return-track construction |
| `trains.nut` | Engine / wagon choice and orders |
| `util.nut` | Money, rail type, passengers |

## What it does today

- Takes a loan and picks the fastest available rail type.
- Prioritises coal mines producing at least 100 tonnes per month, then passenger town-to-town routes.
- Starts routes with one unsignalled main line and one train travelling in both directions, retaining the existing station layouts.
- Extends trains as demand grows; at the length limit, builds and signals a return track before allowing a second train.
- Pathfinds with a small A* in `pathfinder.nut` (rail tiles, bridge spans and tunnels).
- Caps passenger rail routes with `max_routes` in AI settings.
- Builds city bus loops with four or five stops and adjusts their fleets as demand changes.

The sections below describe the development history; the single-line construction
policy at the end supersedes earlier descriptions of building both tracks upfront.

## City bus networks

The construction schedule now includes local buses alongside rail projects. It
tries the largest unserved towns first, requiring at least 1,000 residents and
population at or above the map's median. Each town receives one network of four
or five separate drive-through stops, with a depot and two initial buses running
the circuit in opposite directions.

Stop selection greedily adds the most passenger-producing house coverage that
is not already covered by the selected stops. Stops must accept passengers, add
coverage, and sit at least five tiles apart. Candidates are limited to a
28-tile radius around the town centre and must share a verified two-way road
component. The circuit visits nearby stops in sequence. This is a bounded
coverage heuristic rather than a guarantee of the global optimum.

A completed bus network also makes that city a priority rail destination. The
next construction opportunities attempt passenger rail and a ready factory goods
outlet; these two follow-ups are saved and consumed once so failed attempts do
not monopolise construction. Within ordinary route selection, eligible bus cities
outrank other towns for passenger connections and goods destinations, including
farm/factory, ore/steel/factory and forest/sawmill chains. Geometry, distance,
cargo acceptance, route limits and failure cooldowns still apply. If no goods
source is ready, normal supply-chain construction continues with bus cities
preferred as its eventual destinations.

Passenger stations serving a bus city also receive an early mail review. When
both rail stations accept mail and mail demand exists, the optimiser can queue a
dedicated mail train on the passenger tracks before its usual review date. It
still checks fleet limits, congestion and existing mail service, and does not buy
a duplicate mail train merely because a bus network was added. Priorities are
rebuilt from saved bus networks when a game loads.

Buses use existing streets; houses are not cleared and missing streets, bridges
or tunnels are not constructed. Towns without four suitable connected sites or
space for a connected depot are retried after 180 game days. Unfinished stops
and depots are removed, including after loading a save, without removing the town
streets beneath the stops. Bus networks are independent of the passenger rail
`max_routes` setting.

Every 90 game days the fleet review adds a bus when the total waiting passengers
exceed fleet capacity, up to 12 buses per town. It restores missing vehicles to a
minimum of two and replaces buses within 180 days of the end of their life,
buying the replacement before sending the old vehicle to its depot for sale.
Four consecutive reviews with low queues and a loss in the previous year's
combined fleet profit trigger the sale of one surplus bus, retaining at least
two. Normal orders include depot servicing when needed. Fleet state, pending
sales and unfinished construction survive saving and loading; older saves begin
with no bus networks.

Run `python3 tests/buses.py` for two live-game map checks covering stop coverage
and spacing, all-stop visits, passenger income, demand-driven fleet growth,
vehicle recovery, retirement, age renewal, construction cleanup and persistence.
`python3 tests/bus_rail_priority.py` checks rail destination priorities and bounded
follow-ups; `python3 tests/mail.py --bus-city` checks early mail expansion.
`python3 tests/rotation.py` checks fair construction turns, and
`python3 tests/headless.py` checks the complete AI alongside its rail services.

## Git

This folder is ready to be a repo. On this Mac, `git` is the Xcode stub until Command Line Tools are installed:

```bash
xcode-select --install
cd ~/Development/OpenTTDAI
git init
git add .
git commit -m "Initial OpenTTDAI OpenTTD NoAI"
```

## Route planning and troubleshooting

OpenTTDAI now finds a route before building either station. It reserves station
tiles, chooses a depot branch clear of the planned route, tests rail pieces (including legal road crossings), and bounds
failed searches. It remembers failed town connections permanently, skipping the same pair in either
direction while allowing each town to connect to other partners. Failure memory
is retained in saved games. Temporary construction failures still use a cooldown.
If construction fails after planning, it attempts to remove the unfinished track
and stations. Existing abandoned stations from earlier versions are not repaired.

To exercise the AI in the Steam macOS installation, run `python3 tests/headless.py`.
This uses a temporary copy of your game configuration with autosaving disabled,
two fixed seeds, and a 64-by-64 map. Diagnostic logs go into `tests/seed-*.log`.
It checks train creation and absence of script errors/lost-train warnings; it does
not prove passenger delivery or profitability. Start a new game to load changes.

## Maintenance

New routes place a depot beside a straight section between the stations, preferring
the route midpoint. The junction connects the depot to both directions while
preserving the through track. Orders repeat: station A, station B, service at depot. Trains leave after servicing and still load available passengers
without waiting for a full load. Existing routes require a new game to use this layout.
The headless checks also verify depot placement, junction connections and depot orders.

## Straighter routes

Station candidates are first ranked by distance from the nearest platform tile to
the town centre. Alignment with the destination and platform direction break ties. Candidates must accept and produce passengers. The planner
ranks station candidates and tries the nearest platform exits first, stopping at
the first complete, validated pair of tracks. A bounded pass tries central sites first, followed by an alignment-ranked fallback
if needed. Each pass shortlists up to eight origin candidates and tries two
destination candidates per origin before remembering a connection as failed.
Each bend carries just over half the search penalty of one extra track tile, including bends
at the station approaches. Terrain and road constraints can still require turns;
the bounded search does not guarantee a globally straightest route. AI Debug reports
the selected route's tile and bend counts. Changes apply to newly started AIs.

## Minimum route distance

Town centres must be at least 50 tiles apart for passenger routes, so city
shuttles do not crowd out longer links. Freight chain legs (mine to mill,
sawmill to city, farm to factory and so on) have no minimum: they may be any
distance apart, and short legs are built when they score best. The
maximum-distance limits (120 tiles for town pairs and freight legs, 140 for
farms and goods-branch towns) remain, and distances still use the tile grid.

## Corner spacing

The finder compares actual track headings, allowing alternating corner pieces to
form continuous diagonal track. It rejects 90-degree heading changes and favors
at least two straight pieces between 45-degree bends. Closer bends carry an extra
penalty instead of being forbidden, so constrained terrain can still be routed.
Complete routes are scored with the same heading and spacing rules, including
station approaches. The first track tile outside each station must be straight;
turning is allowed from the following tile. Depot junctions retain straight approaches on both sides.

## Two platforms and paired tracks

Each new station has two platforms. Both connecting tracks are planned before
construction, with a separate track for each platform. The second route prefers a
corridor beside the first, with increasing cost for moving farther away, and may
separate around obstacles. On flat diagonal sections, the tracks can share a tile
using opposite, independent curve pieces. Shared pieces cannot cross, merge, or
use the same rail piece; station approaches remain reserved. Both retain a straight first
tile outside the platform. The station X crossovers link the tracks for depot access;
the depot remains between the stations. Station distance checks cover both platforms.

The AI still starts one passenger train per route; the running lines now use
left-hand one-way signalling. Maintenance remains once per round trip. Existing saved
layouts are not converted. Headless tests verify both station footprints, both track
connections, the crossover, carriages and orders before reporting success.

Run `python3 tests/diagonal.py` to check close diagonal construction in the game
on two map seeds. It verifies independent rail pieces sharing tiles, opposing
one-way signals on those pieces, and removal of one piece without damaging the
other track or its signal.

## Planning performance

The planner stops after finding a complete paired route instead of exhaustively
comparing every candidate. It tries nearby exits first, skips station construction
tests for candidates that cannot enter the shortlist, caches track feasibility
within each individual search, and rejects dominated search states before running
construction checks. Searches retain the same 8,000-node budget but use larger
batches and no extra sleep after completion. Actual construction is still checked
against the current map, so cached results cannot silently approve missing track.

AI Debug reports planning time in AI ticks. On the two current 64-by-64 test maps,
first-route planning fell from 33,906 to 157 and from 22,689 to 2,642 AI ticks.
These are planning measurements, not total construction time or a guarantee for
other maps. The planner trades exhaustive route comparison for earlier completion;
ranked station placement, bend costs, approach rules and paired-track checks remain.

## Station crossovers and signals

Both station entrances have two opposite diagonals overlapping on the same pair of
track tiles to form an X crossover, allowing either
line to reach either platform. The first tile outside each platform stays straight
and carries a normal path signal facing the platform, controlling departing trains;
trains may still arrive from the opposite direction. Crossovers sit farther out.

Station selection now tests three straight approach tiles on each line before
pathfinding, to ensure room for this layout. Routes with insufficient space are
rejected before construction. Every crossover connection and all four platform
signals are checked before a train is purchased. Maintenance remains once per
round trip. The extra approach space can make hilly-map routing more restrictive.

Only the two station X crossovers are built. There is no additional crossover
between the stations; the depot branches from the return track.

## Left-hand traffic and multiple trains

The paired running lines carry opposing directions using one-way path signals.
The outbound track is selected from the station orientation for left-hand traffic;
station pairs whose orientations disagree are rejected. Signals are placed roughly
one platform length plus one tile apart (five tiles with default settings), moving
past junctions or road crossings where a signal cannot be placed. Departure signals sit on the first tile immediately beyond each station X
crossover on the left-hand outbound track. The depot junction avoids these tiles.

The short platform stubs keep normal path signals because terminal trains must
arrive and reverse on them. One-way running signals sit beyond the crossovers.
The depot is on the B-to-A return line so A, B, depot remains a valid three-order
cycle. No extra mid-route crossover is introduced.

Run `python3 tests/traffic.py` for an isolated two-train test. It copies the AI into
a temporary folder, creates two passenger trains on one route, and requires both
to visit A, B, the depot, then A again on each of two fixed-seed maps. Production
still buys one train per route; signalling is ready for additional trains.

## Small earthworks for paired climbs

Before building a viable route, the AI attempts small cuttings and embankments
beside straight sections of the first track. It matches all four corner heights
so the adjacent track can follow the same climb, then replans that second track.
It keeps the earthworks only when more track tiles run beside each other with
matching height profiles and the station crossovers and depot remain viable.
Otherwise it restores the terrain and uses the original plan.

Each corner may move by at most two height levels, including neighbouring slope
adjustments. A pass changes at most 48 corners and has a 20,000 estimated cost
limit, retaining money for construction and restoration. Water, existing transport,
station approaches, the first track and the planned depot are protected.
This is a bounded improvement to a viable route, not a replacement for bridges,
tunnels or large mountain cuttings; tracks can still separate around obstacles.

Run `python3 tests/earthworks.py` to verify two-level raising and lowering in the
actual game, bounded slope propagation, protected corners and exact restoration.
The two-train traffic checks also exercise routes built after these earthworks.


## Failed connections

A town pair for which no viable route is found is recorded once and never selected
again by that AI, including after save/load. Reversing the endpoints is the same
connection. This does not blacklist either town for other destinations. The first
attempt checks the bounded station shortlist before giving up; it is not a proof
that no possible route exists. Changes to terrain later do not reset this memory.
Older saves without failure memory start with an empty list.

Connection keys distinguish towns from industries, ready for industry routing;
the AI currently operates town passenger services only. Run `python3 tests/memory.py`
for live-game checks of selection, duplicate suppression, endpoint types and the
save/load callbacks, including older save data.


## Town-centre stations

Station searches start at the town centre and include both platform orientations.
In the first pass, any closer buildable station ranks ahead of a farther one;
distance is measured to the nearest platform tile, not the station's anchor corner.
Passenger coverage, room for both platforms and crossovers, and the minimum
20-tile separation between stations are still required. Existing buildings are
not demolished to make room.

The central pass uses shorter path searches and stops starting new attempts after
2,400 AI ticks, with up to 1,600 search states per path. A second pass gives town
proximity eight times the weight of route distance, using the remaining budget
up to 4,000 ticks. An alignment-ranked fallback remains available when these
coverage-focused candidates cannot be connected. This favours central locations
without guaranteeing the globally closest possible pair or spending years on
inaccessible sites. AI Debug reports the chosen distances from both town centres.


## Similar-elevation town pairs

Town selection favours similar elevations as well as population and distance.
Each level of height difference between town-centre tiles counts like ten extra
route tiles in the selection score. Otherwise comparable towns at the same height
therefore rank higher, while a larger population or shorter distance can still
justify a climb. The existing 60–120 tile town-distance limits and failed-pair
memory still apply. Heights are sampled once per eligible town per selection pass;
this preference does not require additional path searches or guarantee flat terrain
between the towns.


Depot junctions now have mandatory one-way path signals on the running track
immediately before and after the branch, facing the line's travel direction.
Depot placement avoids road crossings on these two tiles. These signals also
serve as spacing points for the regular signals along the line; overlapping
station/depot signal positions use a single signal. Both signals must be verified
before a train is purchased. This applies to newly built routes.


## Larger cities and multiple routes

Town selection uses explicit priority tiers: big-to-big pairs first, preferring
pairs that serve an unserved big town. Remaining connections involving an unserved
big town come next, then smaller-town services. Big towns are those at or above
the median population of eligible towns; the threshold includes already-served
towns, so it does not shift merely because a town received a service.

Population, distance, elevation and existing service count rank pairs within each
tier only. A cheap small-town route cannot outrank an available big-to-big route.
Failed connections, route capacity, distance limits and temporary cooldowns still
apply; impossible big-town connections do not block smaller-town service forever. Existing
connections reduce a pair's priority so the AI also considers unserved towns.

Ordinary towns can have one route. The threshold for extra routes is the greater
of 1,000 people and twice the median population of all eligible towns. A city
reaching that threshold can have two routes; at twice the threshold it can have
three, and at three times the threshold it can have four. Population and limits
are recalculated as towns grow. The overall `max_routes` setting still applies.

Each extra route serves a different destination with its own station and paired
tracks. Completed town pairs and their route counts are saved alongside failed
connections, preventing duplicate connections in either direction after reload.
Saves made before completed-pair tracking was added cannot recover that history.
`tests/memory.py` also checks hub thresholds, route counts and their save/load
callbacks.


## Reviewing and improving running services

New trains are registered for automatic review after 90 game days. The AI
computes each route's demand — a freight source's output last month, or the
pickup station's catchment production for town routes — and queues an upgrade
when demand plus the station backlog exceeds what the fleet carries, either
from a full departure with passengers waiting or from the calculation alone.
The next scheduled depot visit adds every carriage the computed shortfall
needs, up to the platform limit: it temporarily sets that depot
order to stop, buys and attaches compatible passenger carriages, restores the
original order and restarts the train. It waits another 30 days before reviewing
that train for another upgrade. It does not add full-load station orders or extra
depot visits.

Each addition must fit the original platform length and available funds. An
unavailable or oversized carriage does not prevent the train resuming service.
Service records and queued upgrades persist through save/load. Older saves without
service records do not automatically register their existing trains. Reviews also
run between path-search batches; long construction operations may miss individual
departures, so upgrades are based on observed departures rather than every trip.

Run `python3 tests/optimiser.py` for an isolated live-game test with increased town
passenger production. It verifies a genuine full departure with a backlog, queued
upgrade save/load callbacks, attachment in the depot, the platform limit and
resumption of normal orders on both test maps.

## Retiring consistently unprofitable trains

The optimiser records each train's profit once per completed game year. After the
train is over five years old, three consecutive losing years qualify it for sale,
provided its current year has not recovered into profit. A profitable or break-even
year resets the streak. Partial first-year results are ignored, and missing years
cannot be counted as consecutive losses.

Retirement overrides a queued carriage upgrade. The AI redirects the train to its
existing depot with a stop order, then sells the engine and all carriages only once
the train is stopped inside. Annual loss history and pending sales survive save/load;
older service records begin collecting history when loaded. Tracks and stations
remain, and the completed connection is retained to avoid immediately rebuilding
the same service.

Run `python3 tests/retirement.py` for live-game checks using a test train with
passenger loading disabled. It incurs real running losses, passes the five-year
age gate, returns to its depot and is sold. The test also covers saved history,
pending-sale reloads, and resets for profitable, break-even or missing years.

## Adding trains when platforms are full

If the computed shortfall survives after the platform is full of carriages,
the next depot review builds a second train for the same route. This also handles
trains already exactly at the platform limit. The new train copies the engine,
carriages and independent route orders, with the temporary depot-stop flag removed.
The original train resumes as usual; unavailable funds or vehicles postpone expansion.

A route-wide 90-day cooldown prevents several crowded trains from immediately
buying multiple additional trains. The new train is registered for capacity and
profit reviews with fresh age/profit history. These records and the route cooldown
survive save/load. Extra trains use existing stations and tracks and do not count
as additional town connections or newly built routes.

Run `python3 tests/fleet.py` for a full-platform-length train test. The isolated
fixture uses high passenger production and initially waits for a full load to
exercise the demand trigger, then restores normal station orders before expansion.
It checks queued save/load, matching consists, normal depot orders, route cooldown,
and both trains completing A–B–depot–A on both maps.


## Reliability-driven engine upgrades

Once a train is at least five years old, reliability below 66% makes the optimiser look for a
buildable locomotive with a strictly newer design date and greater horsepower.
It must run and have power on the route's rail type. Among qualifying models it
uses the same balanced engine score as new purchases. If none is available, it checks again
later rather than replacing the engine with the same model.

The swap occurs at the next scheduled depot service, even if servicing has since
restored reliability. The train temporarily stops there; its carriages are moved
to the new engine and its station and maintenance orders are retained. Capacity
and platform length are verified before selling the old engine. If the new
consist cannot fit, the carriages are returned to the old engine and service
resumes. No new rail type or additional depot visit is introduced.

Queued replacements survive save/load, and the replacement train remains enrolled
in service reviews. Retirement takes priority; an engine upgrade can defer a
capacity upgrade until a subsequent review. Run `python3 tests/engine.py` to check
the reliability trigger, saved requests, an oversized replacement rollback,
retained carriages and a complete service circuit after the successful swap.


## More flexible routes and varied town selection

The turn penalty is now 55 (previously 100), and closely spaced bends cost 150
(previously 300). Sharp 90-degree turns remain prohibited. Only the three straight
approach tiles needed for the station crossover and its departure signal are
required, allowing turns sooner when reaching a more central station site.

Town-pair scores receive a random multiplier from 0.75 to 1.25, within the existing
big-town priority tiers. Each AI also has a small random startup delay. These
changes vary the choices of simultaneous AIs without promoting small-town routes
over available big-to-big routes. They reduce identical choices rather than
reserving connections or guaranteeing competitors will never overlap.

`tests/selection.py` runs two AI instances and verifies that comparable candidates
produce varied selection sequences. Single-AI regression tests explicitly limit
the game to one competitor rather than inheriting that setting from the player.


## Engine purchase preferences

New route engines and eligible replacement engines are ranked by power (40%),
model reliability (40%), and top speed (20%). Power and speed are measured relative
to the best eligible candidate; reliability uses its percentage out of 100. Equal
scores favour the cheaper engine. Rail compatibility and the replacement rules
(newer design, more power, at least five years old and below 66% reliability)
remain in place. Extra trains added to a full route still clone its existing consist.


## Competition when choosing towns

Rival stations reduce route scores for all towns, including large cities. Each
endpoint is weighted by `1 / (1 + 9 * rival_station_count)`: one rival station
reduces the score by 90%, two by about 95%. Distinct stations are counted once,
regardless of platform length. Existing big-town priority tiers remain in place.

Checks use public station tiles within 20 tiles of the town centre, their closest
town and a conservative three-tile passenger production radius. Own stations are
ignored. Results refresh every seven game days. Rival activity is not exposed;
unused or freight stations near houses can count, and distant catchments can be missed.

Route attempts have a random start delay. Immediately before construction, the AI
checks again and drops a plan if another company added a station during planning.
This reduces simultaneous duplication but cannot reserve towns across companies.
Run `python3 tests/competition.py` to check rival detection and town penalties.

## Staggered extra trains

An extra train cloned for an existing route waits stopped in its depot for 15–30
game days before starting. Its departure date survives save/load, while the original
train resumes service normally. This is an initial spacing delay, not ongoing
headway control. `python3 tests/fleet.py` checks delayed departure across save/load
and both trains completing their route.


## Bounded second-track search and cheaper station selection

The second track first searches within two tiles on each map axis of the first
track, for at most 400 search iterations. Failure falls back to the original full
search budget. Rail feasibility checks are reused between those two attempts only;
station approaches, shared diagonal pieces and turn rules still apply. The first
track retains its original search, and the first fully viable route is accepted.

Station candidates are scored before expensive terrain, cargo and construction
checks, so candidates outside the shortlist are discarded cheaply. Square search
rings visit only their perimeter, and platform separation uses an exact rectangular
footprint calculation instead of comparing every pair of platform tiles.

On fixed hilly 64x64 traffic fixtures (seeds 42 and 7), first-route planning changed
from 321 to 212 AI ticks and from 1,968 to 1,765 ticks (about 34% and 10% less time).
Station distances from town centres stayed at 4/2 and 6/3 tiles respectively.
Both trains completed their circuits; shared diagonal rails and earthworks checks
also passed. These figures are fixture results, not a speed guarantee on other maps.
The traffic and headless fixtures now explicitly set town layout and terrain.


## Passenger coverage when placing stations

Station shortlists now rank the game's passenger producer count over the full
two-platform footprint and train-station catchment first. Distance to the town
centre is the next preference; track alignment only breaks remaining ties. All
three placement passes use this order. The full 28-tile search radius is checked
because farther sites can cover more buildings. Sites still need passenger
acceptance, nonzero production and buildable platforms and approaches.

AI Debug reports production coverage at both selected stations. This measures
passenger-producing coverage, not predicted monthly passengers or guaranteed
profit. Existing stations are unchanged. `python3 tests/coverage.py` checks the
shortlist order and both-platform catchment calculation in the game.

## Reusing station evaluations during planning

Each route-planning attempt keeps terrain/coverage evaluations and construction
feasibility results for station candidates, plus shortlists for identical placement
queries. Passenger coverage and town-centre ranking remain unchanged. These caches
are discarded before earthworks or construction, and both selected stations are
checked again against the live map. Nothing is cached across separate route attempts
or saved games.

An identical station pair is searched only once at a given iteration budget within
an attempt. The larger fallback budget still gets its own attempt. On the fixed
traffic fixtures, planning fell from 555 to 485 AI ticks and from 1,184 to 1,164,
with unchanged passenger coverage (18/31 and 16/11). Gains depend on how much
repeated work a route needs. Coverage tests compare cached and uncached shortlists
with town growth disabled so the fixture does not change during comparison.

## Cheap town-pair screening

Town locations, populations, route counts and endpoint heights are read once per
selection. Distance limits and known failed/built connections are checked first.
An optimistic score (including the existing random variation) allows pairs that
cannot beat the current winner to skip further work. Only competitive pairs need
terrain sampling and rival-station checks, and each town's competition weight is
read at most once per selection.

Eight intervals along the direct line estimate terrain difficulty. Extra rises
and falls cost six equivalent distance tiles per height level beyond the endpoint
difference; each interior water sample costs eight. These are soft penalties,
not a feasibility verdict: detours remain possible. Existing population priority
tiers, endpoint elevation preference, competition penalties and station coverage
ranking remain intact.

On the two 128x128 multi-AI fixtures, 30 selections per company dropped from
240–252 to 89–90 AI ticks and from 477–479 to 86–87. This measures town selection,
not the full time to build a network. Small route fixtures selected the same
routes and retained their coverage; traffic and competition checks passed.

## Duplicate-route protection from live trains

Before town selection and again at the start of route planning, the builder reads
its own non-crashed trains' station orders and restores missing town connections.
This supplements saved connection records, including older saves with incomplete
bookkeeping. Town pairs use the same direction-independent key, so A–B and B–A
cannot become separate new lines. Multiple trains on one connection count once;
adding capacity to an existing line remains allowed. Recovered records are saved
normally. Train orders are evidence of an assigned service, not a fresh physical
reachability test of every rail tile.

The traffic test deletes connection memory with two trains operating, verifies
recovery and duplicate blocking in both directions, and then checks that both
trains complete their station/depot circuits.


## Securing station sites before rail planning

After choosing a candidate pair with the existing passenger-coverage ranking, the
AI builds both two-platform stations before searching for connecting tracks. Each
purchased pair receives the full path-search budget. After a failed connection,
endpoint diagnostics guide which station to relocate; the other can remain built. If the second station
cannot be built, the first is removed too. Later construction failures also clean
up the reserved stations through the route cleanup path.

Pending station footprints are saved before issuing construction commands. After
loading, unfinished reservations are removed before new planning begins. Cleanup
only targets owned station tiles in those recorded footprints; failed removal is
retained for another attempt. Successful routes keep their stations and clear the
reservation record. This secures sites by building actual stations, not buying
land, so unsuccessful attempts incur construction and demolition costs.

`python3 tests/reservation.py` verifies stations exist before path search, failure
cleanup, partial station purchase cleanup and recovery of saved reservations.
Headless construction, two-train traffic and route-memory tests also pass.

## Temporary pathfinding signs

Planning shows up to three temporary signs with the `[VT search]` prefix:
station-selection locations, then the active track's start, target and sampled
search position. `T1` is the first track, `T2` the second; `narrow` is its initial
corridor search. The moving sign reports examined search states, which can include
several headings on the same tile. It marks a branch being explored, not committed
track or a percentage complete. It updates after the first batch and every five
batches thereafter to limit sign-command overhead.

AI Debug reports track/stage, endpoint tiles, examined states, queue size, failed
rail-build tests, elapsed AI ticks and whether a path was found, the search area
was exhausted or the iteration budget was reached. Failed rail tests count actual
API test calls, not all candidate rejections. Time includes sign commands.
Markers are removed after each search and route attempt, and leftover owned
markers with this prefix are removed at startup. Other signs are retained.
`python3 tests/signs.py` checks moving-marker visibility, bounded sign count,
success/failure cleanup and preservation of unrelated signs.


## Destination-facing station sites

The first placement pass now restricts both towns to the half facing the other
endpoint, using the centre of the full station footprint. Passenger production
remains the first ranking criterion within that half. The nearest station end
must also support the required straight two-track throat and crossover. Station
pairs still try their nearest endpoints first when searching for rails.

If the facing-side pass cannot find a connection, later passes allow sites on
other sides of either town. Empty facing shortlists advance to that fallback
instead of rejecting the town pair. Cached shortlists distinguish facing and
unrestricted passes. AI Debug reports when the fallback is being used.


## Relocating only the blocked endpoint

Failed searches record the closest distance reached to the target and maximum
spread from the start across examined states, rather than using the last tile.
Getting within six tiles of the goal suggests a target-side blockage. An exhausted
search confined within six tiles of the origin suggests a start-side blockage;
a mere iteration timeout is not enough to blame the origin. Narrow second-track
failures are diagnosed only after the full search fallback. Conflicting evidence
from station-end combinations, or junction/depot failures, is inconclusive.

For an origin-side failure, the next candidate origin is tried with the current
target station still built. For a target-side failure, more destination candidates
are tried while retaining the origin station. Matching reservations are kept;
only replaced footprints are removed and purchased again. When alternatives are
exhausted, normal fallback passes may move both endpoints. Middle/inconclusive
failures first retry the same station pair with twice the search budget.

AI Debug explains the measured failure location and relocation choice. These are
heuristics, not proof of a bad station. `tests/relocation.py` injects each failure
classification into live station construction to verify one-end retention, larger
middle retries without rebuilding, and cleanup after all candidates fail.


## Continuing after a near-target failure

Once a search gets near the destination but cannot connect, the origin station
is locked for the rest of that planning attempt, including fallback passes. Only
destination candidates change. Near-target evidence takes precedence over failures
from less promising station ends. If every destination alternative fails, the
attempt is cancelled and its unfinished station reservations are cleaned up.

The pathfinder keeps approximately the first half of the closest explored path.
On a new target it revalidates that prefix against current terrain, reservations
and rail compatibility, reconstructs its heading and bend-spacing state, and seeds
the new search at the midpoint. The result includes the original prefix unchanged.
First- and second-track prefixes are retained separately when available. An invalid
prefix triggers a fresh search from the same fixed origin, with an AI Debug message.
This retains planned rail geometry, not the old search queue or already-built rails.
Prefixes last only for the current attempt; reload uses existing reservation cleanup.

`tests/prefix.py` blocks an old station approach, verifies a near-target failure,
moves the target and checks that the retained 19-tile prefix is unchanged and the
whole new route can be built. `tests/relocation.py` also verifies the origin never
moves during target-side retries. Both tests and two-train traffic pass on two seeds.

## Depots on the station approach

New routes prefer a depot 10–20 track tiles before station A's crossover,
aiming for 15. It connects to the track heading towards the station, with
one-way signals immediately on either side once the route has two tracks.
Single-track routes retain signal-free running and use the future inbound lane
so the depot remains accessible after upgrading. Later freight-network stages
also receive an approach depot near their own pickup station.

Placement requires a straight, level junction and free space beside the track.
If the preferred range is unavailable, the closest suitable position is used,
at least five track tiles from the crossover. Existing depots stay in place.
Orders still include one maintenance visit per circuit.

## Spacing additional town stations

Additional stations favour sites farther from the company's existing rail stations
in the same town. Passenger production is discounted by up to 75% near an existing
platform footprint; the penalty fades to zero at twice the catchment radius plus
one tile (normally nine tiles). This is a spacing preference, not a count of unique
passengers. Temporary station reservations do not penalise their own retries.
The existing station footprint is included in the shortlist cache key.

## Bridges around obstacles

The pathfinder now considers rail bridges when a straight approach meets water,
transport infrastructure, an unsuitable rail tile, or a drop in terrain. It tests
available bridge designs against the actual terrain before adding a span to the
search. Spans are limited to 13 tiles including both ramps, and have an extra cost
so short ground detours and shorter bridges remain attractive. It selects the
fastest available design that can be built for that span.

Each track plans its own span, favouring the first track's corridor. The first
span's footprint is kept clear of the second track, and station throats remain
on the ground. Construction builds and verifies the bridges as well as the rail
approaches; one-way signals stay on ordinary track. Failed-route cleanup removes
built bridges without clearing the infrastructure below them. Earthworks are
skipped for routes containing bridges, to preserve ramp heights and clearance.
Retained search prefixes stop before a bridge when necessary.

`tests/bridge.py` and `tests/bridge.py --water` build adjacent spans over a railway
and canal respectively, run a train through A, B, the depot and A again, and verify
cleanup preserves the crossed infrastructure. Both fixtures pass on two seeds;
the existing traffic, diagonal and retained-prefix tests also pass.

## Reverse-direction retry

If a connection attempt fails, the AI releases its temporary station reservations
and makes one fresh attempt with the source and destination towns exchanged.
Station shortlists and retained path prefixes are cleared between directions;
the normal station-relocation strategy still applies within each attempt.
Competition counts are exchanged with the towns so rival checks stay correct.

A pair is permanently remembered as unreachable only if both directions fail to
find a plan. Construction failures keep the existing temporary retry cooldown.
Cancellation because a rival added a station does not trigger a reverse retry,
and existing routes and previously remembered failures remain excluded.

`tests/reverse.py` checks reversal, state reset, competition-count mapping,
reverse success, two-direction failure memory and cancellation. Reservation and
relocation tests cover real station cleanup and retention within an attempt.

## Station earthworks

High-coverage station candidates are no longer rejected solely because uneven
land prevents station or entrance construction. For a candidate that can improve
the shortlist, the planner considers levelling both platforms and a four-tile
entrance on one side, including the crossover. Destination-facing searches keep
that entrance facing the destination. It tries nearby heights and favours the
plan with the fewest corner-height changes; passenger coverage and station spacing
remain the main site-ranking criteria.

Earthworks use clear, dry land, change each corner by at most two levels, and cap
the full plan at 48 changed corners including slope propagation. Existing roads,
railways, buildings and water are protected. Actual work is performed only when
reserving a selected station, with the existing 20,000 earthworks cost limit and
railway/rollback cash reserve. Station and throat construction are then tested on
the prepared ground before the station is built.

Original heights are saved with temporary station reservations before work starts.
If reservation or route construction fails, the station is removed and those
heights are restored; save/reload cleanup uses the same record. Successful routes
keep the prepared land. `tests/station_terrain.py` checks one- and two-level bumps
and dips, actual station and entrance viability, and exact terrain restoration
through save/reload cleanup on two maps.

Non-terrain station refusals (such as local-authority refusal) do not trigger
levelling. If a selected site's preparation fails, another shortlisted site is
tried; an already-built origin is retained when only its target fails. Failed
reservations remain temporary failures rather than permanently banning the pair.
The two-train traffic fixture uses a 128x128 map for the 60-tile town separation
and a 500,000 loan limit to fund both trains on the longer test route.

## Save-safe station reservations

Station reservations now save only their tile, orientation and original terrain
heights. Shortlist metadata, including the floating-point station-spacing score,
is deliberately excluded: OpenTTD rejects floats in AI save data. Live planning
records remain unchanged, and older reservation records can still be loaded.

`tests/save.py` uses an isolated loopback dedicated server to write actual saves
while a station and earthworks are pending, then reloads them on two map seeds.
It verifies exact terrain restoration, search-sign removal and preservation of
unrelated signs. The terrain test also injects a decimal score to check that it
never enters the saved reservation. Data discarded by an earlier failed AI save
cannot be reconstructed; search signs can still be cleared at startup.

## Prefer fewer climbs and descents

Ground height changes now add 55 search-cost units per level in either direction,
the same as the base corner penalty. This accumulates total ascent and descent,
so repeated hills cost more than a flatter alternative with similar length and
bends. Tile-top heights provide a terrain-height estimate and are cached within
each search; this is not a simulation of train speed on individual track pieces.
Bridge spans charge only the rise/fall between the ground and their level deck,
not the terrain underneath. Retained prefixes and route-quality scores use the
same height penalty. Existing routes are unchanged.

`tests/gradient.py` compares identical live terrain with the penalty disabled and
enabled: both map seeds select a buildable 47-tile route with four height changes
instead of the 43-tile route with 24 changes. The retained-prefix, bridge/traffic
fixture and normal route-construction checks also pass.

## More willing route earthworks

Before construction, ground-only routes now get one targeted smoothing trial.
The planner looks for short level cuttings or straight shortcuts (up to ten tiles)
through a local hill or detour, levels a corridor for both tracks, then replans
between the same stations. It retains the work only if the combined route score
improves, including length, turns and climbs/descents. Otherwise it restores the
terrain and keeps the original route; when the restore itself fails (cash, town
growth or slope rules), the earthwork is kept and planning continues on the
adjusted terrain instead of abandoning the connection. Station footprints,
entrance junctions and the depot are protected; bridge routes retain their
existing clearance protection.

Route earthworks now allow three levels per corner, 96 changed corners including
propagation, and up to 40,000 in estimated cost per trial, while retaining the cash reserve
for construction and rollback. Station earthworks keep their existing two-level,
48-corner, 20,000 limits. The adjacent-track pass also accepts a smoother route
without requiring more matching tiles, and no longer accepts a worse route score
just to improve adjacency. Original route-earthwork heights are included in the
pending station recovery record as integers.

`tests/smoothing.py` verifies a better two-track route across a real ridge, a train
completing its station/depot circuit, and exact restoration after cleanup on two
maps. The earthworks test covers the optional third level and the unchanged
station limits; normal construction and two-train traffic are also checked.

## Cutting hills beside diagonal tracks

Smoothing now examines diagonal corridors as well as axis-aligned shortcuts, and
looks for higher ground in the intended second lane even when the primary track
itself is already flat. A diagonal corridor includes tiles where the two opposite
rail pieces can share a square. This addresses small hills that previously made
the second track detour while the first track stayed direct. The original paired
matching pass only handled repeated, identical grid steps, so it skipped these
alternating-step diagonal sections.

Both tracks are replanned and validated after a proposed cut, with the existing
three-level/cost limits, protected station junctions and rollback behaviour.
`tests/sidehill.py` creates an obstruction beside a shared diagonal, verifies that
the second track initially diverts, then checks that the hill is lowered and the
original close second track restored with the primary geometry unchanged. Real
train traffic and exact terrain restoration also pass on both test maps. This
changes planning for new routes; existing tracks are not rebuilt automatically.

## Tunnels under obstructions

The pathfinder now tests rail tunnels at suitable existing slopes. This allows it
to pass beneath raised land carrying a town or other surface obstruction, without
demolishing the surface buildings. It does not excavate artificial entrances for
flat towns: OpenTTD determines the far portal from the entrance slope, and the AI
tests the actual tunnel command before accepting it. Portal separation is capped
at 32 tiles (33 including both portals), with a 60,000 construction-cost cap per
tunnel and an 80,000 cash reserve at construction.

Both running lines plan separate tunnels, favouring adjacent portals. Protected
station approaches and the other planned track are excluded from tunnel spans.
Paths record whether a jump is a bridge or tunnel, including the original tunnel
construction direction. Construction verifies the actual connected portals;
signals remain on the approach tracks. Earthworks avoid tunnel routes, and
failed-route cleanup removes the tunnels without clearing the land above them.

`tests/tunnel.py` builds a plateau with road depots blocking its surface route,
verifies adjacent tunnel selection and construction, runs a train through both
stations and maintenance, then checks cleanup preserves every surface building.
Both seeds pass. Bridge, ground-route, retained-prefix and sidehill tests cover
the shared path representation and its existing behaviours.

## Stronger station orientation preference

Station ranking now multiplies its coverage/spacing score by a destination-facing
orientation weight. A platform aligned with the dominant direction to the other
end receives full weight; a perpendicular one receives about one quarter. This
applies at both towns and in fallback placement passes. For destinations at roughly
45 degrees, either platform axis remains suitable. Existing destination-facing
station-side and entrance checks remain in place, and lower-coverage sites can
now win when their platform orientation is substantially better.

The weight uses the full platform footprint centre. Orientation scores stay in
planning memory only; the save whitelist continues to store just station recovery
information. Coverage tests check strong east/west and north/south preferences
in both directions, alongside real shortlist ranking and station-spacing checks.

## Preferred paired-track planner

New route searches first try a bounded joint search. Each state contains both
track frontiers; they advance together, or one briefly waits for an inner/outer
bend. Frontiers remain within two Manhattan tiles, and completed track pieces
must be independent. Opposite corner pieces may share a flat tile. The search
reuses existing ground, bridge and tunnel legality checks, station throat rules,
and climb/turn costs. Its distance estimate accounts for shorter diagonal pieces.

This is a weighted, bounded search, not a guarantee of the shortest route. It
tries at most 1,000 queue entries for the closest viable station exits, yielding
between batches and showing temporary progress signs. Station crossovers and
the depot must also fit before a result is accepted. On exhaustion, budget limit,
or rejected junction/depot layout, the existing sequential planner runs with its
original budget. Retained-prefix retries and widened searches use that fallback
directly. Existing terrain improvement and construction checks still run after
planning; neither track is built speculatively while the search is running.

`tests/paired.py` verifies a joint diagonal result within this budget, 11 shared
independent tiles, construction, opposing signals and independent removal on two
seeds. The sidehill fixture exercises accepted paired routes, terrain improvement
and a train circuit; bridge, tunnel and normal route fixtures also exercise the
sequential fallback. Performance on difficult maps still depends on that fallback.

## Smaller towns after eligible connections run out

The population setting is now the initial minimum. When town selection finds no
eligible pair, it halves the active threshold and retries, stopping at 50 people.
For example, 350 becomes 175, then 87, then 50. The threshold stays unchanged
while eligible pairs remain, and the reduced value survives saving/loading.
Older saves start from their configured setting. Threshold changes are logged.

Population boundaries are inclusive. Existing large-town priorities, competition
weights, route limits, distance bounds and failed/duplicate connection exclusions
continue to apply, as do station coverage checks. This expands the pool of towns;
it does not guarantee that a smaller-town route can be built or be profitable.
`tests/population.py` checks relaxation, stability, the floor, failed-pair exclusion
and save/load compatibility on two maps with two AI instances each.

## Depot access to both station platforms

The depot at station A's crossover now includes a straight crossing piece through
its adjacent main-line track. This connects the depot mouth to the far track's
existing crossover curves, allowing departure into either platform. The original
two depot curves still provide access along the near track in both directions.
Planning tests the extra piece, construction verifies it, and failed construction
or signal setup removes it during cleanup. The traffic test checks continuous
connections to both platforms before running two complete train circuits.

## Mail wagon on the penultimate carriage upgrade

When a depot passenger upgrade leaves room for exactly one further carriage of
the same measured length, the buyer also attempts to attach one compatible mail
wagon. This normally fills the last space with mail instead of passengers. Actual
vehicle lengths enforce the platform limit. Trains already carrying mail are
skipped, including cloned consists. If no compatible default-mail wagon is
available, affordable or short enough, the passenger upgrade still succeeds.
Initial train purchases are unchanged. `tests/mail.py` checks upgrade timing,
length limits and duplicate prevention in the game on two seeds.

## Annual surplus loan repayment

When bank cash is at least twice the outstanding loan, the controller repays
roughly half, at most once per calendar game year. The remaining half is rounded
down to a legal loan increment, so the final increment is eventually cleared.
Only successful repayments consume the year's allowance. The last repayment year
is saved; older saves begin with no repayment recorded. Payments are logged.
Startup no longer borrows up to the maximum simply on loading; construction can
still borrow as needed. `tests/loan.py` controls the eligibility balance while
executing real repayments, checking accounting, annual gating, reload persistence
and eventual clearance on two map seeds.

## Preferred roll-in / roll-out stations

New routes now attempt a through-platform station at each end, retaining the
existing two-platform terminus independently wherever the extra loop cannot fit.
Both platforms accept trains from the original station crossover. Trains leave
through the opposite end, merge beyond the platforms, and follow a return loop
along the outbound side back to the main-line crossover. The station A depot
remains on its existing crossover and can feed either platform.

Near-platform signals face into the platforms and far-platform signals face out,
all one-way path signals. A further signal on the return loop provides a waiting
point clear of the exits. Platforms retain a straight approach tile at both ends.
The first version uses a bounded flat-land template: it needs three extra tiles
past the platform ends and space for the return line alongside the station. It
never demolishes buildings to fit a loop or sacrifices the chosen station's town
coverage. Each station's chosen layout is logged. Existing stations are unchanged.

Loop construction is optional and rolls back to the terminus on failure. Its
added rail pieces and changed signals are journalled as integer arrays in pending
station save data, allowing recovery after interruption without saving planner
objects. `tests/roro.py` covers both axes on two seeds, the production layout
selection, independently blocked-end fallback, interrupted construction rollback,
save-data recovery, two full-platform-length trains traversing both loops and
maintenance, and cleanup. Existing traffic and station reservation tests also pass.

## Coal first, then passenger routes

The AI now starts with coal-producing industries and power-station-style coal
consumers (coal acceptance and no produced cargo). It uses the COAL cargo label,
not translated industry names. Eligible industry centres are 50–150 Manhattan
tiles apart. Production, distance, nearby competing stations and a small random
variation rank the pairs. One operating connection per mine is enough; separate
mines may supply the same power station. Failed attempted pairs are remembered.

Both coal stations must have roll-in / roll-out loops. Industry coverage and coal
acceptance are checked independently of passenger coverage. The entire loop
footprint is checked while choosing station sites and kept out of the main-line
search. If either loop cannot be completed, the route is cleaned up instead of
commissioning a coal terminus. This initial version uses the existing flat-land
loop template, so not every mine/power-station pair will have a suitable site.

Coal trains start with a modest consist of compatible coal wagons, full-load at
the mine, unload with no loading at the power station, and visit the depot once
per circuit. Engines use the same power/reliability scoring, excluding engines
with built-in capacity for an unrelated cargo. Construction waits for funds
before another coal attempt. Once one coal service is commissioned, selection opens to passengers
and other freight, with further coal attempts interleaved; the existing maximum-routes setting
continues to cap passenger routes. The coal phase, attempted pairs, operating
services and optimiser state survive saving/loading. Industry routes do not
populate town-connection memory.

Coal uses the same ServiceOptimiser as passengers, with a coal TrainBuyer:
full departures leaving cargo behind trigger one extra wagon; the platform limit
triggers another train with the existing 15–30-day departure delay and route
cooldown. The existing five-year / below-66% engine replacement rule and
persistent-loss retirement rule apply. Only passenger cargo can trigger a mail
wagon. Both optimisers continue reviewing services during route searches.

`tests/coal.py` runs real coal delivery on two 256×256 maps. It verifies loading,
unloading, maintenance, mandatory loops, coal-first priority, the passenger
transition, wagon growth at the penultimate-slot boundary without mail, a
staggered clone retaining freight orders, saved service state and duplicate-mine
exclusion. Shared engine-replacement and retirement tests, passenger construction,
mail upgrades, and roll-through station tests also pass. The engine/retirement
fixtures use 128×128 maps to accommodate the existing 60-tile town-distance rule.

## Separate RIRO entrance and return tracks

The through-station conversion now removes the three old crossover pieces that
connected the return line to the platform entrances. Incoming trains retain a
branch to either platform; the return loop connects only to the outbound main
line. At their closest point these paths use opposite, independent corner pieces
on one tile, with no junction or crossing between them. Depot access remains on
the incoming side and still reaches both platforms. Terminus layouts keep their
original crossover.

Removed pieces are included in the saved construction journal and restored if the
conversion fails or is recovered after interruption. The RIRO test explicitly
checks both entry branches, absence of all three unwanted connections, and the
independent corner-piece mask, alongside two full-length trains, both orientations,
depot visits and rollback. The live coal delivery and optimiser test also passes
with the separated layout.

## Progressively more cautious fleet expansion

The first additional train still follows the existing full-departure/backlog rule.
For later additions, the station backlog at the depot review must cover at least
one full trainload per existing train on the route. After a successful addition,
the next clone is blocked for 90 × fleet-size² game days: 360 days with two trains,
810 with three, and so on. This separate expansion cooldown does not change the
existing carriage-upgrade cooldown, and survives save/load.

No clone is purchased while another train is awaiting dispatch, or another running
train on that route has remained on the same tile for seven game days. Loading and
depot stops are excluded from this congestion check. The rules apply to passenger
and coal fleets. Controlled tests cover backlog boundaries for one to four trains,
congestion/loading, dispatch and persistence; the live coal optimisation test
still verifies the first added train and its staggered departure.

## Highest-output coal mines first

Monthly coal production now takes strict precedence in source selection. The AI
chooses the highest-output unserved mine with an eligible, untried destination,
then steps down as mines are serviced or their candidate connections are exhausted.
Distance, competition and random variation only break ties within the same output
level or rank destinations; they cannot make a lower-output mine win. Output is
refreshed at every selection. `tests/coal_production.py` exhausts the eligible pairs
on two maps and checks the maximum available output at every step.

## RIRO exit signals and orientation

RIRO stations now have one-way path signals after the platform-exit merge and
at the start of the return straight, in addition to the existing platform and
return-line signals. Incoming and returning tracks remain separate.

Coal station selection checks both ends of each proposed station and retains
layouts whose entrance/return mouth faces the destination. Each selected pair
is checked against the actual opposite station position. Shared route planning
also tries destination-facing station exits first; optional passenger RIRO
conversion retains the terminus if its planned mouth faces away.

Live RIRO tests check all seven signals and their directions, both station axes,
opposite destination directions, train circulation and rollback. The coal test
also verifies delivery and fleet optimisation with the new layout.

## Flatten short hills on coal routes

Coal routes now run the same bounded terrain improvement used by passenger
routes before laying rails. Short cuttings can remove climbs and help keep the
two tracks together. Smoothing also checks two- and three-tile spans, alongside
the longer spans, to catch small bumps.

Reserved RIRO loop tiles are protected from earthworks and excluded from the
replacement track/depot search. Changes remain limited to three height levels,
96 corners and the existing construction budget; a trial is restored if it does
not improve the route. The live smoothing test checks actual hill lowering,
reserved terrain preservation, train circulation and restoration after cleanup.

## Coal-to-passenger production threshold

The initial coal phase now only considers mines producing at least 100 tonnes
last month, still taking the highest-output eligible mine first. Other traffic unlocks after one working coal route, or when no viable
untried connections remain at or above that threshold. Existing coal services keep operating
and being optimised. Exactly 100 tonnes qualifies; 99 does not.

## Deferred stations and quiet pathfinding

Pathfinding no longer creates temporary signs; cleanup still removes old search
signs from saved games. Passenger and coal routes plan both tracks before
building either station. Station footprints are reserved only within the planner,
not occupied by station buildings. Necessary station earthworks may still be
prepared during planning and are restored when an attempt is abandoned. Before
construction, both footprints are checked again in case a rival has occupied them.

## Twenty-year engine renewal

At 20 × 365 days old, passenger and coal trains queue engine replacement at
their next scheduled depot visit, regardless of reliability. A newer, more
powerful engine is preferred; otherwise a fresh engine of the current design
is used if available, or a compatible available design if it has been withdrawn.
Carriages, cargo capacity, platform length and orders are preserved by the
existing replacement checks. When a newer engine is a poor fit — typically a
capacity-maxed train whose consist no longer leaves room for a longer
locomotive — the renewal falls back to a fresh current-design engine, which
fits the same consist by construction, instead of rolling back and re-queuing
forever. The platform-fit rollback still applies unchanged to the
reliability-driven upgrade path, where waiting for a fitting newer design is
intended. If funds or a suitable replacement are unavailable,
the original train resumes and retries at a later visit. The existing retirement
rule for consistently loss-making trains still takes precedence.

OpenTTDAI disables built-in company autorenew at startup so it can retain
optimiser tracking when vehicle IDs change. Live age-renewal tests pass on two
maps, including queued save/load, platform-limit rollback and a complete circuit
after replacement. Existing reliability-upgrade tests also pass.

## Hierarchical corridor planning

A bounded coarse A* search over 8×8-tile regions now guides the detailed paired
rail planner. Four terrain samples per region penalise hills, water and occupied
land without declaring them impassable: bridges, tunnels and exact rail legality
remain the detailed planner's responsibility. This is an HPA*-inspired corridor
planner, not a precomputed portal graph or an optimal-path guarantee.

Refinement first allows a one-region margin, then widens to two regions. Each
trial has a limited search budget. If neither works, the existing unrestricted
planner runs with its original budget. Retained-midpoint retries and already
widened searches bypass this extra stage. No signs, station buildings or new
saved planner objects are introduced. Logs identify refinement, widening and
unrestricted fallback.

`tests/hierarchy.py` compares the same ridge route with hierarchy disabled/enabled,
forces both corridors to fail, verifies successful unrestricted fallback, then
checks construction, train circulation and terrain restoration on two seeds.
The small fixture currently takes 37 ticks without hierarchy and 38 with it,
with identical route scores; no broad speedup is claimed. Coal delivery and
terrain-smoothing integration tests also pass.

The longer seed-42 run took 92,359 AI ticks to plan its first route, versus
68,545 in the previous unrestricted run. The ordinary short headless test still
exceeded its simulation budget. Because this trial has not demonstrated a speed
improvement, normal startup leaves it disabled. Set “Experimental hierarchical
pathfinding” to 1 in AI settings to try it; 0 retains the existing planner.

## Experimental rail jump search

“Experimental rail jump search” defaults to 1 for this trial; set it to 0 to
compare with the previous planner. It is independent of hierarchical planning.
The preferred paired planner stays unchanged. When individual-track search is
needed, a bounded JPS-inspired trial precedes ordinary A* and logs its result,
jumped intermediate steps and fallback. Midpoint-reuse searches bypass the trial.

Standard JPS assumes uniform grid costs and its symmetry pruning does not apply
to our heading, bend-spacing and terrain costs. This variant follows up to eight
rail steps in clear, flat terrain, including alternating steps forming a diagonal.
It stops near obstacles, reservations, slopes, station throats and target turning
points. Every rail connection is tested, all costs are accumulated, and all
intermediate tiles remain in the path for construction, signals and recovery.
A failed trial restores the original prefix state and runs normal A* with its
usual budget. It does not guarantee a shortest route.

`tests/jump.py` measures identical flat fixtures with the trial off/on, builds
and removes the resulting rail, checks straight-axis jumps, forces successful
ordinary-search fallback, and checks paired/shared-tile signals. Both seeds
measured 101 versus 38 AI ticks and 400 versus 78 expanded states. These are
small-fixture results, not a general speedup claim. Longer exploratory runs
remain map-dependent. Coal delivery and passenger smoothing/circulation tests
also run with jump search enabled.

## Startup search budgets

With no operating trains, a whole connection attempt gets a shared 2,400-AI-tick
planning allowance. After each four unsuccessful attempts it grows by 2,400,
capped at 8,000, so difficult maps are not permanently starved of search time.
An operating train younger than two years allows 4,800 ticks; once an operating
train reaches two years, the whole-project allowance is capped at 8,000 ticks.
Stopped/depot trains do not qualify. The deadline is checked between station
search rings and pathfinding batches, so a running batch can slightly overrun it.

The allowance covers alternate station positions, both route directions, paired
planning and ordinary A*. Terrain replanning shares the same deadline; physical
construction and necessary rollback can finish. Timeout abandons the attempt and cleans up
its temporary earthworks. Towns receive a cooldown, not a permanent failure mark.
Coal connections timed out during startup are saved separately from proven failed
attempts; other coal pairs are tried, then passengers if necessary. Deferred coal
connections become eligible for a longer retry once services are established.

The two fixed-map headless startup tests pass. `tests/startup.py` verifies the
initial/adaptive budget, timeout cleanup and town cooldown, and coal deferral,
save/load and later retry. Live coal delivery and optimisation also pass.

## AyStar-style weighted pruning trial

“Experimental AyStar-style pruning” defaults to 1. It uses queue priority g+2h
and permanently closes expanded states for a bounded individual-track trial.
Unlike the example's tile/direction-only closure, it preserves incoming tile,
heading, recent bend spacing and bridge/tunnel arrival context. Existing best-g
filtering still removes inferior queued duplicates. The estimate targets the
outer station approach until the train is correctly aligned for entry.

The paired planner remains unchanged. When both AyStar-style and jump settings
are enabled, AyStar-style takes precedence for the individual-track trial, avoiding
stacked preliminary searches. Failure restarts ordinary A* with closure disabled
and its original budget, subject to the shared startup deadline. Turn off
AyStar-style pruning to compare jump search; turn both off for ordinary A*.
Hierarchical corridor planning remains independent. The added example files are
reference material, not runtime dependencies.

On two identical flat fixtures, ordinary search took 106 AI ticks / 400 states;
the weighted trial took 18 ticks / 64 states. Route score changed from 3910 to
4020 and bends from two to four: a measurable speed/shape trade-off, not a
shortest-path guarantee or a general map-wide performance claim.
`tests/pruning.py` checks actual construction, bend-state separation and forced
ordinary-search fallback alongside paired-track signals. Coal service, passenger
smoothing and startup headless tests exercise the integration.

## Single main line first

New coal routes plan and build only one inter-station main line; passenger
and mail routes between towns are built in the two-track configuration from
the start, because deferred return-line upgrades kept failing once town
growth blocked the second path. The existing two-platform stations, coal
roll-in/roll-out loops and depot remain.
Short local connections let both platforms use the single line. No signals are
installed initially, including at the stations, loops and depot; only one train
is permitted on the route and it travels along the main line in both directions.

The optimiser continues adding wagons under the existing demand rules. When a
train has reached its length limit and demand justifies another train, the AI
holds it in the depot and plans the return track alongside the original line.
After building that track, it removes the temporary station merges and installs
left-hand one-way main-line signals, platform signals and RIRO loop signals.
Only a completed conversion permits another train to be purchased. Existing
fleet congestion checks and staggered dispatch still apply.

If planning fails, the route keeps its original single-train operation. Partial
construction and signal changes are journalled for rollback, including across
save/load. If rollback cannot finish, the train stays in the depot until recovery
succeeds. Existing double-track routes remain double-track and need no conversion.

`tests/single.py` checks coal delivery, wagon growth, conversion, second-train
purchase and both trains visiting both stations on two maps. The passenger
fixture in `tests/single_passenger.py` checks both-way initial operation, blocked
conversion, interrupted construction with save/load recovery, rollback and
successful one-way operation. The normal headless startup tests also exercise
single-line construction.

### Legacy iron ore services

Existing independent iron-ore services loaded from saves retain their RIRO
stations, wagon growth, deferred return-track construction, staggered additional
trains, and renewal/retirement rules. New independent iron-ore lines are disabled;
new ore traffic is part of the shared freight network described below.

Mine selection discounts effective output by half when a rival station already
serves the mine. Own stations are excluded, and actual production still determines
coal eligibility at the startup threshold of 100 tonnes/month.

### Route shape and fleet limits

The planner no longer adds penalties for bends or close turns. Route distance and gradients still contribute to cost; right-angle turns follow the game setting. Required station and junction geometry is retained. Existing track is not rebuilt automatically.

Queued wagon/engine work no longer puts a stop-and-wait flag on the regular depot order. The optimiser stops a train only when it observes it inside its depot and can perform the work. If the AI is busy planning, servicing trains continue normally and the work waits for another visit. Existing queued stop flags are cleared on review. Return-track construction/recovery still holds the original train for safety, and newly purchased trains retain their one-off staggered departure.

Additional trains are newly assembled with three cargo wagons rather than copying the full train (no initial mail wagon). They grow under the existing demand rules. A route cannot expand beyond four valid trains; existing larger fleets are not forcibly sold.

### Dedicated mail trains

Passenger upgrades no longer attach mail wagons. When a passenger train reaches its platform limit and demand permits fleet expansion, the AI checks mail acceptance at both stations. If both accept mail and the route has no mail train, the next addition is a separate engine with three mail wagons. Otherwise it adds another passenger train. A mail train is also added on its own — without waiting for the platform limit — whenever both stations of a passenger route receive mail and mail is waiting or being produced there, subject to the same fleet cap, congestion checks and cooldowns. The return line and signals must be complete before either addition can run.

Mail trains use the same two station stops and maintenance depot, take available mail without full-load waiting, and grow using mail-specific demand. Renewal and retirement follow the existing rules. Cargo identity survives save/load; passenger and mail trains share the four-train cap, congestion checks and staggered dispatch. Existing passenger consists retain previously purchased mail wagons; no new ones are attached.

### Shared freight network

Independent iron-ore lines remain disabled. After the first coal service (or exhaustion of eligible coal choices),
network and passenger planning take turns. Freight turns alternate between an
iron ore → steel → goods → city chain and a forest → sawmill → city chain. An
unavailable chain yields to the other. The iron-ore network builds:

- A two-track ore backbone joins a mine to a steel mill.
- A factory branch joins that backbone at a suitable straight, flat section.
- A goods-delivery branch joins the network and reaches a city accepting goods.

All four stations use two-platform RIRO layouts. The steel mill station handles
ore deliveries and steel collection; the factory station handles steel deliveries
and goods collection. Each leg has its own cargo-specific train and a maintenance depot at its pickup
station, while sharing the network tracks. New steel and goods trains start with three wagons. Existing wagon growth,
renewal and retirement rules apply. The four-train limit is per station pair;
network-wide congestion also suppresses fleet expansion.

The AI records suitable junction locations internally; these are planning anchors,
not visible signs or compulsory train waypoints. Larger cities take precedence as
goods destinations: the chain score carries a population weighting, and the
fallback town scan for a goods branch prefers larger towns within the distance
band. Branch planning runs while existing
trains operate. Trains return to the depot before the junction is modified, then
resume after construction or rollback. Partial branch construction is journalled,
and planned branches and network data survive save/load. Station signal positions
are rechecked before building because towns can grow during planning.

The complete industry chain must be available before the backbone is attempted.
Once a supplying link is commissioned, its next branch takes priority over new
routes, without waiting for the first output to be produced.
Mine output is discounted by half when a rival already serves the mine. Failed
chain choices are remembered. Coal, passenger and mail routes retain their existing
construction models; legacy independent iron-ore trains remain supported.

The wood network builds a double-track forest–sawmill backbone and a goods branch
from that backbone to a city accepting goods. Its three stations use the same RIRO
layout; the sawmill station receives wood and supplies goods. The goods train starts
with three wagons and follows the existing capacity, renewal and four-train rules.
The goods branch is prioritised as soon as the forest–sawmill route is built.
Sawmills must accept WOOD and produce GOOD; unsupported industry chains are skipped.
Rival service halves the forest's effective production when ranking candidates.

Multiple chains of each type can operate, each with shared tracks and separate service depots.
Completed and delayed networks remain maintained while other sources are explored.
It does not yet merge the wood network into the iron-ore network. Completed factory networks can also accept farm branches carrying grain and livestock:
multiple farms may feed the same factory, each with its own station, depot and
grain and livestock trains. Connecting farms to an existing factory outranks everything, including new
city routes: while an eligible, unconnected farm remains near the factory,
every scheduling pass goes to the farm branch first (previously every second
pass), and new city routes wait until the farm build-out is done or the
remaining farms hit their retry cooldowns. The industry
scan backing that priority refreshes once per game month.
General expansion to other industries and cargo types is a later step. Older saves
without a wood network remain compatible; new saves retain each chain and its
planning turn.

`tests/network.py` and `tests/network.py --wood` exercise shared-track delivery, planned/completed network
save/load, failed-branch rollback and the no-compatible-chain fallback in OpenTTD.
The traffic fixture suppresses fleet growth/retirement and full-load waiting to
isolate routing from fluctuating industry output; separate optimiser tests cover
those policies.

### Coal startup priority

One commissioned coal route now ends exclusive coal startup priority. Passenger,
ore and wood planning can then begin without exhausting the remaining mines.
Further coal routes remain eligible: they receive a planning turn after two
opportunities for other traffic. Unfinished freight chains get a priority turn, followed by a normal scheduling turn.
Timed-out searches yield for seven days; other failed extensions wait 90 days. If no eligible coal connection exists, the AI
still moves on. The 100-tonne coal eligibility threshold is unchanged.

The startup milestone and scheduling turn survive save/load. Older saves with
a valid coal service unlock other traffic immediately; losing that service later
does not reinstate exclusive coal priority.

### Separated freight junctions

New network branches use a flying junction: one branch lane turns away from the
main line and crosses both running tracks on a bridge, or through a naturally
fitting tunnel. The other lane joins on its own side. The planner tries both
sides and orientations; if the separated layout does not fit, it tries another
site rather than constructing a flat crossing. This requires more space than
the old junction.

One-way path signals are mandatory immediately before and after each main-line
merge/diverge, on each branch approach, and just outside the crossing structure.
Unrelated main-line signals are retained. Junction paths, structures and signals
are included in save/load and rollback; failed construction restores the previous
main-line geometry before restoring its signals.

Existing built junctions are retained. Unbuilt flat-junction plans from old saves
are discarded and replanned. Station entrance fans and station crossovers retain
their existing designs. Network tests check the crossing structure, unchanged
rails beneath it, close signal placement, rollback, and subsequent cargo delivery.

### Unrestricted ordinary track curvature

Ordinary pathfinding and route scoring no longer charge extra for bends or
closely spaced turns. Right-angle turns follow the game's own setting, rather
than an additional AI restriction. Route length, gradients, construction legality
and keeping paired tracks close still matter. Straight station throats, bridge
and tunnel approaches, and space for separated junctions remain structural
requirements. Existing rails are not rebuilt.

### Ordinary A* only

All route construction now goes directly to the ordinary A* search previously
used as the fallback. AyStar, jump-search, hierarchical and paired-planner trials
are no longer run or offered as AI settings. Both lanes use ordinary A*, retaining
the second-track corridor, rail separation, junction templates, search budgets
and saved midpoint recovery. Old experimental settings cannot reactivate trials.

### Build the first track before return planning

Double-track freight backbones and network branches now construct the first line
before searching for the return line. For branches, the first section remains
disconnected from the live junction until the return path is ready and trains
are held for the junction work. Stations are still built after the full route
has been determined. Ordinary passenger and coal routes retain their existing
single-track startup and demand-triggered return-track construction.

Only newly constructed pieces are journalled. A failed return search removes
the unfinished first line before another layout is attempted; save/load recovery
cleans up an interrupted search, while a completed saved branch plan retains its first line. Terrain optimisation does not relocate an
already constructed first line. Network tests inspect actual rails and structures
at the start of every return search.

### Depots for later freight-chain stages

Each new stage uses its own depot beside the entrance fan of its pickup station:
steel trains at the steel mill, factory goods trains at the factory, and sawmill
goods trains at the sawmill. The depot can feed either platform without joining
the RIRO return curve to the entrance tracks. Its approach has a one-way path
signal; existing platform signals remain in place.

The train is purchased there, receives that depot in its servicing order, and
uses it for carriage changes, replacement and additional trains. Depot ownership
is saved in the service record. Failed branch construction removes the new depot
and connections while restoring the existing network. Existing commissioned
services keep their depots; this applies when constructing a new stage.

### Farm branches: grain and livestock together

After the ore → steel → factory → city network is operating, the AI can connect
farms to its existing factory station using shared, signalled double track and
separated junctions. Farms are ranked by combined grain and livestock production,
with the usual competition discount. The production test is reduced for farms —
they start with much lower output than other industries: 50 tonnes a month of
either grain or livestock qualifies a farm (other freight industries are
tested against far higher output), and the factory needs only half the
standard acceptance level on the delivery side. Farms producing both cargoes
still rank highest.

Each farm gets a two-platform RIRO station and a pickup-station depot. The AI
purchases one grain train and one livestock train, each with three wagons, before
dispatching either. If either purchase fails, both the unfinished branch and any
purchased train are rolled back. Both services retain their own cargo identity
through save/load and follow the existing capacity, renewal and retirement rules.
They share the four-train route limit and use the farm depot for optimisation.
This supports the temperate grain/livestock farm chain; unsupported cargo sets
are skipped.

`python3 tests/network.py --farm --seed 43` exercises both farm deliveries,
returns to the farm depot, save/load and rollback after a failed second purchase.

### Sustained expansion and bounded waits

A waiting network no longer claims the entire construction turn. Depot requests
that fail are retried; accepted requests are not toggled off. If all trains have
not reached depots within 180 game days, the unstarted extension is cancelled,
its detached first line is removed, and stopped or travelling trains are released.
Partly modified junctions remain isolated until rollback succeeds, while other
networks can build independently. Wait dates and cleanup journals survive saves.

Every branch attempt shares one planning deadline across station searches,
junction alternatives and both track searches. Retry cursors and attempted
layouts prevent restarting the same exploration each turn. Interrupted searches
are not recorded as impossible. Deferred backbone choices are retried only after
fresh choices are exhausted, so a difficult high-production source cannot
monopolise expansion. Waiting for coal funds also yields to other work.

The controller manages multiple ore and wood networks, excludes sources already
served by those networks, and rotates their construction opportunities. Legacy
single-network saves migrate automatically and retain their existing services.
Passenger `max_routes` now defaults to 0 (unlimited); explicit nonzero limits,
including those already stored in a running game's AI settings, remain honoured.
Set that setting to 0 in an existing game to remove its previous passenger cap.

`tests/expansion.py` checks actual depot-request retries/cancellation, bounded
budgets, fair scheduling, additional-network selection and old/new save formats.
The fixed-map network delivery tests cover construction, depot returns and rollback
under the bounded planner. These checks do not establish performance parity with
AAAHogEx; a controlled network-growth comparison is still needed.

### Quick first attempts and progressive retry delays

New passenger, coal and freight-backbone connections start with at most 1,200 AI
planning ticks and 1,600 search states per full search. The next attempt allows
2,400 ticks and 3,200 states; subsequent attempts use the existing age-dependent
budget. These are planning limits, not construction or rollback deadlines.

The first attempt tries at most four distinct station pairs, skipping layouts
within three tiles of an already-tried pair when both station orientations and
approach directions match. The next attempt allows eight pairs with one-tile
spacing; later attempts permit fine station adjustments. Passenger planning no
longer immediately restarts the same search with a doubled state limit.

Failed connections receive persistent, pair-specific cooldowns of 30, 60, 180,
and then at most 365 game days. Other destinations remain eligible. Successful
construction clears the history. Legacy saves start with empty retry history;
existing permanently rejected connections remain rejected. Freight branch
extensions retain their existing planning policy, and train optimisation is
unchanged. These changes reduce time spent on individual failed candidates;
they do not guarantee a higher route count on every map.

### Continuous construction pacing

Route attempts repeat every 10 AI ticks instead of 75, and the per-attempt
random delay is a token 1-5 ticks: it still varies simultaneous AIs' choices
without idling most of the schedule. A timed-out coal pair keeps startup
priority during its seven-day retry cooldown; passengers unlock when coal has
exhausted its eligible pairs or is waiting for funds. Failed coal pair probes
retry after seven days. When every passenger pair is deferred or cooled down,
the idle message is logged at most once per game day. Live train-order
connection recovery runs once per game day rather than on every selection.
Fleet reviews during long pathfinding calls run once per game day; the main
loop otherwise reviews the fleet every few ticks. In the fixed headless
fixtures these changes removed roughly 90% of the previously idle days and
shortened the common failure cooldowns from 180 to 30 days.

### Equivalent A* states

Ordinary A* now merges states that differ only in recent straight-run length
when close-turn penalties are zero. Arrival heading and structure-arrival state
remain distinct. Straight-run length stays in the key when close-turn penalties
or the legacy jump-search mode require it.

`tests/state_pruning.py` compares the original and reduced keys on the same
above-sea-level terrain, with and without an obstacle. On seeds 42 and 7 the open
fixture takes 198 expansions / 49 AI ticks instead of 380 / 94; the obstacle
fixture takes 55 instead of 58 expansions, with both taking 13 ticks. Both retain
the same 38-tile route length. It also verifies cost-sensitive keys, shared-track
construction, signals and independent removal. Normal headless route tests pass.
These are small search benchmarks, not measured network-growth multipliers.
The older diagonal-spacing, bridge and tunnel fixtures also fail against the
unchanged baseline and are not counted as passing integration coverage here.

### Entrance-aware A* guidance

Ordinary passenger and coal route searches now estimate distance via the outer
end of the destination's mandatory straight approach, then add its three remaining
steps. Once correctly aligned inside that approach, only the remaining steps are
counted. This is still ordinary A*: costs and legal track moves are unchanged.
The same estimate is used for ground rail, structure arrivals and retained prefixes.

Shared freight networks retain direct-goal guidance (`entrance_guidance=false`).
Although individual searches improved, enabling the new estimate throughout the
shared-network fixture changed route geometry and delayed downstream branches
until its cargo-delivery check failed. Keeping the previous estimate there restores
ore/steel/goods delivery, rollback and saved-network checks.

`tests/approach.py` compares both estimates on six fixed layouts for two seeds,
including opposite-facing entrances, an obstacle and an unreachable throat.
Success/failure and shortest route lengths match. Total expanded states per seed
fall from 13,101 to 5,781; one opposite-facing case falls from 1,925 to 33 states
(476 to 9 AI ticks). The completely blocked case explores the same number of states
and has slight estimate overhead. These controlled search gains are not a network
growth forecast: a short replay of the supplied 20-year save commissioned one new
route with each estimate before the shared-network exception was introduced.
The prefix fixture now selects land above sea level to prevent flooding between
its first search and the retained-prefix retry.

### Approach-depot validation

Depot selection follows the main-line search, allowing a safe site along the
actual approach rather than requiring one fixed crossover tile. An unavailable
depot reports an origin failure for station relocation. The single-track test
checks preferred spacing, bidirectional traffic, rollback and dual-track conversion.

Normal headless runs pass. A 30,000-tick replay of
`autosave15.sav` started three new trains across five OpenTTDAI companies versus
one before this change; that short sample does not establish a sustained growth
rate or resolve every failed connection.

## Demand-sized consists

New consists are sized from the demand model rather than a fixed three wagons:
the same monthly-demand figure the optimiser uses for growth (industry output
for freight sources, catchment production for town routes, halved when a rival
station serves the source) is divided by the best wagon's capacity, giving the
carriage count for the first train of a new passenger line, the first coal
train, network branch trains (per cargo: grain, livestock, steel, goods), and
fleet-expansion clones (sharing the route's demand across the enlarged fleet).
Every consist stays within the platform length and above the two-wagon
minimum; the demand-driven add-carriage and shed-carriage machinery then
adjusts the consist as real traffic shows its hand.

## Rail type evaluation and electrification

New construction is re-evaluated once per game month: the AI switches to the
fastest rail type that the entire fleet can run on, judged by the fastest
buildable engine each type supports rather than the type's nominal speed
(many train sets leave that at zero and phase the real gains into which
engines the type carries). Monorail and maglev fail the fleet check while
rail-based vehicles are in service, so base changes never strand a fleet;
they become eligible only once nothing rail-based remains. Commissioned
freight networks also convert their recorded running lines progressively —
one segment per game month, oldest first — so existing lines gain
electrification when the game's rail types allow a compatible conversion.
Passenger, coal and mail line tiles are not yet tracked; their existing
lines keep their original type until tile tracking is added, though all new
construction uses the selected type.

## Rival-served industries in fleet sizing

The fleet-expansion calculation now mirrors the route-selection discount: when
another company's station sits inside the source industry's producing
catchment, only half of that industry's output counts towards demand, on the
assumption that the rival takes the rest. The halved demand applies to both
directions of the optimiser — a rival-served route needs a larger station
backlog before adding carriages or trains, and sheds carriages sooner when
output falls. The detection reads public station-tile ownership within the
industry's catchment and is computed fresh each time, so it tracks rival
stations being built or demolished. Town passenger and mail routes are
excluded: a rival town station does not intercept production the way a rival
mine station does.

## Industry events and production tracking

The controller now subscribes to the game's industry events. When an
industry closes, every route pair involving it is forgotten and any
operating service whose source or destination died returns to its depot for
sale through the normal retirement path instead of running on to a dead
station. When an industry relevant to coal, ore or wood opens, the matching
manager's no-viable-connection cooldown is cut short so the newcomer is
considered immediately. Separately, each freight service records its pickup
industry's output when the route opens and refreshes it once per game month:
a source that has shrunk must show double the usual station backlog before
the fleet expands, and a grown source may expand at half the usual backlog.
Town passenger routes are unaffected: towns do not close, and their demand
is observed through station cargo directly.

## Oriented freight junctions

Segment paths are stored start-to-goal, and junction candidates walk them
goal-to-start, so a candidate's direction d points from the segment's goal
station towards its start. At a separated junction the diverge lane carries
host traffic travelling -d onto the branch, and the branch's return lane
rejoins the host travelling +d. Branch planning therefore prefers the
orientation that matches the loaded train's own movement: a train leaving the
host segment's goal station (or a farm branch merging towards its
destination) travels +d of the reversed walk, so d=-j.d; a train arriving
over another branch travels goal-ward and diverges, so d=+j.d. Junction
candidates on the host trunk are also ranked by cargo flow: the loaded train
enters through the goal-side merge of the branch serving the pickup, so
junctions on the goal side of that merge rank ahead of junctions whose use
would force a far-end turnaround on every trip. The preferred orientation is
attempted across every junction and site before any mirrored layout is
accepted, and the mirror pass only revisits junctions the preferred pass
rejected before any path search, so a planning call never pays for two full
searches at one junction. Segment records store their goal station tile and
each junction's path position so later branches can compute this. Goods
stations offer both platform mouths (the far one penalised): the far mouth
has the opposite junction handedness, and terminal goods stations host no
future depot, so the preferred orientation finds a compatible approach more
often. The preferred orientation is attempted across every junction and site
before any mirrored layout is accepted, and a mirrored build is logged as a
warning so the line can be identified in AI debug. Branches built before
these rules existed keep their original geometry; the AI never rebuilds
working lines. Freight tests fail on any trunk-served train whose return leg
still touches a trunk-end station (the mis-orientation regression) and warn
on off-trunk return detours.

## Scaling fleet reviews

Steady-state trains now run their full optimiser check once per game day
instead of on every controller pass: depot visits and loading stops last for
days, so a daily sample observes each one. Trains in an active phase
(queued upgrade, replacement, sale, staggered dispatch) keep their exact
per-pass timing, and any transition back to normal observation clears the
daily marker so follow-up work is not delayed. Each review call reads the
game date once and shares it across the fleet loop. In a mature company the
recurring review cost stops growing with every controller pass and instead
scales with fleet size per game day, leaving construction more of the
AI-tick budget. Behaviour — upgrade triggers, retirement timing, dispatch
delays — is unchanged; only the sampling cadence of idle trains changed.

## Coal, then farm expansion

Construction now offers coal the first opportunity on every turn, followed by
farm branches across existing ore networks, then other freight and passengers.
Farms become eligible once the factory is connected; the goods-to-city leg no
longer has to be finished first. Deferred or unavailable farm work yields to
other construction. Existing branch plans and junction recovery remain protected,
and the monthly farm scan and reduced optimiser cadence are unchanged.

## Farms can start a freight network

After coal, eligible farms can now establish their own two-track RIRO network
with a factory, without an ore mine, steel mill or existing factory station.
Existing connected factories are offered farm branches first. New farm backbones
validate station coverage for both grain and livestock, purchase both trains in
the pickup depot before dispatch, and retain junction candidates for expansion.
The next stage is factory goods to a city using the shared-network branch planner.
Failure to find a goods outlet does not prevent the farm connection from starting.

Farm networks are stored alongside ore networks with their own `FARM` type and
use the existing service optimiser and review cadence. `tests/farm_start.py`
checks independent startup, delivery of both cargoes, save/load, cleanup after a
failed second train purchase, and dispatch to the goods-stage planner. The latter
is a scheduling check, not an end-to-end goods-delivery test.

## Factory-facing farm junctions

Farm branches now identify the factory by its recorded station anchor, matching
segment endpoint metadata and the existing steel/goods orientation logic. Using
the industry location instead made a factory-bound branch select the opposite
junction direction and send trains via the original farm. This corrects newly
planned junctions; existing track layouts are not automatically rebuilt.

## Measured round-trip capacity

The optimiser measures pickup departure to the next pickup departure, requiring
a visit to the destination in between. Loading, travel, servicing and delays
therefore contribute to the cycle. It smooths completed samples (75% previous
estimate, 25% new sample) and retains integer timing data in saved service records.
Until measured, a train uses a 30-day cycle. Sampling uses the existing daily
fleet observations, without increasing optimiser frequency.

Monthly throughput is the sum of each same-cargo train's capacity multiplied by
30 divided by its cycle days. Adding/removing wagons and sizing additional trains
use those timings; other cargo trains do not count as available capacity. Waiting
cargo is still targeted for clearance over a month, and platform, congestion and
four-train limits remain. Initial trains on new routes retain demand-based sizing.

## Retired railway cleanup

When a service is sold through the retirement path, the controller queues a
physical survey from its depot and stations. Any remaining vehicle on the
connected railway, or with orders for its stations/depots, prevents demolition.
That includes other cargo services and stopped trains: an active freight network
is retained even if one of its services has been sold. Ownership checks prevent
removal of competitors' assets.

An unused railway is removed in bounded batches, including stations, depot,
signals and rail bridges/tunnels. Level-crossing roads are retained. Cleanup does
not run during pending construction and persists its scan/deletion progress in
saves. Failed removal commands are retried after seven days. Retired freight
network records are removed; retired town connections free their route slots and
receive a one-year rebuilding cooldown. Existing abandoned routes are not swept
automatically: retirement of a train triggers the survey.

`tests/retirement.py` covers real loss-based sales, protection by another stopped
train, resumed cleanup, complete removal (including the bridge fixture), and
route/network bookkeeping on two maps.

## Restored straight-track preference

A* now charges 50 cost units per heading change, against 100 per track tile.
Repeated zigzags therefore cost more than sustained straight or diagonal track.
Diagonal tile steps are evaluated by the rail heading, so a continuous diagonal
is not charged as a series of corners. The same preference applies to terrain
improvement scoring and retained search prefixes.

Turns remain allowed around obstacles. Close-turn penalties remain zero to keep
redundant run-length history out of the search state; existing search budgets
and optimiser frequency are unchanged. New routes use this preference; existing
rails are not rebuilt. `tests/straightness.py` compares flat diagonal searches
with and without the penalty, and checks that unnecessary bends are removed.

## Factory goods priority

Once a farm or steel supply route reaches a factory, its goods-to-city link
gets first construction priority, ahead of new coal, farm and passenger routes.
This bypasses the alternating continuation turn and selects the ready factory
network directly. Existing retry cooldowns still let other work proceed when
the goods connection fails. Goods destinations are considered in descending
population within the existing 140-tile junction range, using distance to break
ties and checking station goods acceptance before choosing a site.

## Train optimisation switch and goods limit

Train optimisation is enabled. Set `TRAIN_OPTIMISATION_ENABLED` at the top of
`optimiser.nut` to `0` to pause it for route-building comparisons, or `1` to
restore it. Initial train dispatch remains active while paused. Restart the AI
or load a game with the updated script to apply a source change.

Goods lines never add a second train through optimisation, including previously
queued expansion work. Their existing train can still gain or lose wagons and
receive engine replacements. Existing extra goods trains in saved games are
not automatically removed. `tests/fleet_limits.py` checks the goods cap alongside
the existing passenger fleet rules.


## Freight station fallback

Freight stations may use the standard two-platform terminus and crossover when
neither RIRO loop orientation fits. Coal and freight backbones no longer reject
a completed route merely because a preferred loop could not be built. Shared
freight branches, including goods-to-city and farm branches, also accept
terminus sites and preserve that choice through save/load. If a saved loop plan
becomes obstructed, the branch retains its standard station instead of abandoning
the whole plan. Cargo coverage, station entrances, depot access and junction
checks still apply.

Run `python3 tests/farm_start.py --terminus` and
`python3 tests/network.py --wood --terminus --seed 42` to force unavailable loops and
check construction, deliveries and save/load with standard stations.


## Compact RIRO footprint

New RIRO stations use three rows across instead of four: two platforms and an
adjacent return track, with no unused row between them. The platform exits
merge inward before turning across both platform rows. A straight tile after
that merge keeps both platform paths usable with 90-degree turns disabled.
This makes the end one tile longer than the earlier shortened-end layout, but
reduces the station-and-loop bounding rectangle from 4 × 9 to 3 × 10 tiles
for four-tile platforms (excluding the unchanged main-line approaches).

Existing stations retain their saved geometry. The live RIRO test asserts the
three-row width and runs trains with an obstruction on the old outer return
row, in both map orientations. It also checks fallback, saved recovery and
cleanup.


## RIRO loop earthworks

The AI can raise or lower clear land to match the station throat before building
a RIRO loop. Planning does not change the map. Earthworks are limited to two
height levels per corner, 64 changed corners and the existing 20,000 internal
cost budget, with cash reserved for construction and rollback. Changes that
would affect existing rail, roads, buildings or water are rejected, retaining
the standard-station fallback. Saved construction journals include the original
heights so failed or interrupted loop construction can restore the land.

`tests/roro.py` exercises raised and lowered loop land, failure after levelling,
saved recovery, compact clearance and train circulation in both orientations.

## Farm-chain construction focus

Construction now tries connected factories' goods outlets first, then farm work,
then coal and the remaining freight/passenger work. A factory cannot receive
additional farm branches until its goods-to-city leg is complete. Existing
services still receive maintenance at the same cadence. Failed or deferred
farm/goods work yields to other construction rather than stopping expansion.
Goods planning skips exhausted station approaches in larger cities and considers
the next city, preserving the preference for population and the search budgets.

## Shared factory hubs and RIRO platform choice

A new farm network first attempts a second farm into the same factory, then
its shared city goods outlet. If the extra supplier cannot currently connect,
goods work proceeds; existing factories remain preferred for further farm
branches before a new factory backbone. This keeps farms and their shared
goods service ahead of coal/passenger construction.

New RIRO layouts remove inward-facing signals between the entrance fan and
platforms. The incoming path signal now reserves through a free platform to
its exit signal, instead of letting a train commit to an occupied platform's
entrance. Platform-exit and return-loop signals remain. Single-track upgrades
apply the same arrangement. Existing built stations are not automatically
resignalled.

## Goods immediately after the first farm

A successful first farm-to-factory route now triggers goods-to-city planning
before further farms. Shared-track goods branches remain preferred. If that
connection fails, a subsequent bounded attempt may build an independent dual-track
goods route, with a separate factory station and its own maintenance depot.
Large nearby cities are tried first; unsuccessful pairs use the usual planning
cooldowns. Existing farm services continue operating, and further farms can
still share the original factory station. The separate service is saved and
optimised with the factory network and retired if its source factory closes.

## Expand completed factories with more farms

After commissioning goods service, farm planning prioritises completed factory
networks over starting other farm backbones. Further farm branches still deliver
to the original factory station, including when goods uses a separate station.
There is no one- or two-farm cap: eligible nearby suppliers continue to be added.
A pending branch or retry cooldown no longer causes a new factory backbone while
the existing completed hub still has eligible suppliers. Other route types may
proceed during the delay. Farms already served by another company-owned network
are excluded from duplicate connections.

## Reliable age renewal

Engine renewal is due at twenty years or the vehicle's maximum lifetime,
whichever comes first. Queued engine work sets a stop-in-depot order for the
next maintenance visit so a busy route planner cannot miss it. After replacement
(or a safe failed attempt), the normal service order and running state are
restored. Capacity-only optimisation remains opportunistic; the ordinary daily
review frequency is unchanged. The age test pauses the optimiser across a depot
visit and verifies holding, saved-state recovery, rollback and renewed service.

## Farm and goods construction failure recovery

Depot construction clears and journals any running signal on its junction tile,
including signals facing the opposite direction. Rollback restores the earliest
signal state for each track rather than an intermediate construction state.
Failed builds no longer consume an otherwise unused junction: unsuccessful
station/side attempts remain recorded separately. Searches that exhaust their
time budget rotate to another junction and defer that approach for thirty days,
instead of repeating it immediately or permanently blacklisting it.

## Explicit goods-to-farms handover

Commissioning a goods outlet queues a saved follow-up task to connect another
farm to that same factory's original receiving station. This attempt takes
precedence over goods work on other networks, coal and passengers. Both shared
and separate-station goods routes trigger it. Temporary waits retain the task;
a factory with no eligible suppliers yields to other work. Further farm
connections continue under the existing completed-factory expansion policy.

## Farm monthly production eligibility

A farm qualifies when grain **or** livestock exceeds 50 units in the last month.
The other cargo may be zero; exactly 50 does not qualify, and the cargoes are not
added together for this threshold. New backbones, additional branches and pending
expansion scans use the same rule. Source station searches use the more productive
cargo so a zero-grain month does not hide an eligible livestock-producing farm.

RIRO station earthworks: freight and goods-city station searches first try sites
that fit the existing terrain. If no RIRO candidate fits, they also consider
levelling the platforms, entrance throat and return loop together. Cuts/fills
are limited to two height levels, 96 changed corners and the existing earthwork
budget; occupied land, roads, rails and water remain protected. Preparation is
journalled before construction, including network branches, so abandoned builds
can restore the original terrain. The ordinary terminus remains a fallback.

Network backbones are retained and commissioned even when no suitable future
junction sites exist. This is logged explicitly; shared-branch planning can
reject unavailable junctions later, and goods can use its separate-line fallback.

New factory-to-city goods outlets build a separate dual-track line immediately,
with signals and two-platform RIRO stations preferred at both ends. Reversing
two-platform stations are the next choice. If no two-platform site fits, the
compact one-train fallback below applies. Normal goods routes never defer their
return track until fleet expansion, because town growth can block its later construction.
Existing goods routes are unchanged; the goods fleet remains limited to its
initial train, with wagon capacity growth as before.

Construction priority is coal first, then farm/factory/goods chains, then iron
ore chains, then passenger routes (mail continues to use passenger routes).
Wood networks are maintained and can expand when those priorities have no work.

Industry competition: new routes skip sources with another company's station
in their producing catchment, instead of halving their ranking. This covers
coal, farms, ore, forests and processed-cargo pickups (steel/goods). Sources are
checked again before construction. Rival-served delivery destinations remain
eligible, existing services are retained, and town competition is unchanged.

Oil wells can supply oil refineries (OIL_ input, GOOD output). Oil is attempted
after ore chains and before passenger routes. Offshore rigs and rival-served
sources are skipped. Routes use the coal-style single-track start, freight
orders, capacity growth, eventual second-track upgrade, maintenance and renewal.
Oil services are saved and restored, and react to industry openings/closures.

New independent routes reselect the best available rail technology before
planning, without requiring the existing fleet to run on it. Selection uses
buildable powered locomotives, excluding wagons; equal speeds prefer the higher
rail-type ID (the newer standard technology). Existing network extensions use
the network depot's rail type and restore the independent construction setting
afterwards. Monthly reviews wait until construction is clear; existing-network
conversion retains its own fleet-compatibility checks.

Compatible upgrades now use a company-wide connected-railway scanner, replacing
the freight-only segment conversion. It covers all train services, including
coal, oil, passengers/mail and disconnected goods outlets. Stations, loops,
junctions, depots and bridge/tunnel endpoints are discovered from actual rail
connections. The scanner handles 128 entries per batch; conversion visits at
most 32 entries per batch, at most once every 20 AI ticks, outside construction
and pathfinding. Depots convert only after all other tiles succeed. Failed tiles
are retried on the next monthly sweep. Primitive scan/progress data survives
save/load, and changes to train orders/fleet restart an in-progress scan.
All engines must remain powered and every wagon compatible with the selected
technology; this does not replace trains for monorail or maglev migration.

Upgrade save compatibility: fleet/order snapshots are integer arrays, not a
concatenated string (OpenTTD limits saved strings to 254 characters). Older
string-based snapshots restart the upgrade scan on load without undoing any
track conversions. Regression coverage includes a fleet exceeding the old
limit, exact order-change detection and save/load of the numeric snapshot.

Upgrade progress no longer restarts when engines are renewed or unrelated
services change: it compares the distinct destinations used by trains on the
current component. A changed route rescans that component without discarding
the rest of the sweep. Saved absolute tick delays reset on load. Maintenance
gets up to eight bounded batches (160 AI ticks) before another route search;
already-current components skip conversion immediately. Unfinished builds defer
only components containing their protected stations/depots, not all railways.


Whole-network technology replacement now supports incompatible rail technologies, including monorail and maglev. A monthly scan selects a newer, faster available type only when every service in the connected component has a suitable engine and cargo wagon. The saved migration job gathers those trains at their own maintenance depots, pauses construction and normal optimisation, and tests the running-track conversion and full replacement budget. Gathering times out after one game year.

Occupied depots cannot be converted while holding incompatible trains, so the migration builds an additional fleet-assembly depot off an unsignalled straight running tile. Original trains remain intact in their original depots while running tracks, stations, bridges and tunnels are converted and complete replacements are assembled. Wagon numbers target the old cargo capacity, subject to the existing platform length. Only after every replacement has valid copied orders are the old trains sold, optimiser/source-service IDs remapped, original depots converted, and the new fleet released. The assembly depot remains connected for later use. Failed work before the sale stage removes new vehicles/depot connections, restores original rail types and releases the old fleet. Save/load preserves partial carriage assembly and conversion progress. Funding, vehicle availability, and space for the assembly depot can defer a migration; compatible in-place upgrades remain available.

Validation: `tests/fleet_upgrade.py` runs passenger and coal services through electric-to-maglev migration in both map orientations on two seeds, injects rollback after partial replacement assembly, reloads saved state mid-consist, verifies service mappings/orders/platform lengths, and observes completed train circuits. Existing compatible-upgrade and route-expansion regression fixtures also pass.

Depot mismatch recovery also runs when the running railway already uses the newest type. It stops/reverses a train stuck at its old depot entrance, saves service/cargo/order data, sells the affected consists, demolishes the empty depot, rebuilds it at the same tile and orientation using the running line's rail type, and builds replacement engines/wagons there. Recovery journals survive a save after sale/depot removal as well as during carriage assembly. Orders are recreated after depot demolition, which otherwise invalidates depot destinations. Normal fleet upgrades now also rebuild their empty original depots and restore replacement orders before release. A mixed running line is not guessed at by this repair, and untracked stock prevents destructive depot work. `tests/depot_recovery.py` reproduces an upgraded maglev line with two electric trains and an old depot, including a train attempting to leave, and checks saved recovery and subsequent service in both orientations/two seeds.

New technology upgrades now reuse the original service depots instead of adding a fleet-assembly depot. Once all trains are gathered and running-track conversion succeeds, the AI journals service records, sells the old consists, rebuilds the existing depots, and purchases their replacements there. Pre-sale conversion failures still roll back; after sale, saved jobs resume depot/vehicle reconstruction. Existing staged upgrade jobs remain loadable. Depot scans also repair missing entry/exit curves on straight main-line junctions, preserving the existing one-way signals. This fixes older assembly depots whose single curve forced departing trains against the lane direction. Existing extra depots are not automatically demolished.

The fleet upgrade fixture now removes one depot curve and verifies its repair, checks that all original signal directions survive, asserts that an upgrade still leaves exactly one depot, and exercises conversion rollback, save/load during replacement construction, and subsequent train circulation in both orientations on two seeds.

Steel mill -> factory continuations now build independent routes, like the factory -> city goods outlet. They use their own pickup/delivery stations and depot, initially one unsignalled running track and one steel train, with normal capacity optimisation thereafter. A successful steel service advances the ore chain to the factory stage so its goods outlet can follow. It does not consume or require ore-line junctions; those old junction candidates are cleared to prevent future farms being sent onto the disconnected ore line. Existing operating steel services are retained. `tests/steel.py` verifies actual ore supply, steel loading/delivery/maintenance, single-track commissioning, save/load and goods continuation eligibility with no available junctions on two seeds.

After the initial coal startup priority, construction rotates through coal, goods, farm, ore/steel, farm, passengers, farm, wood, passengers; oil receives an additional slot after every second round. Each attempted connection consumes its slot even if planning fails; unavailable categories are skipped. Farms therefore retain the largest share without preventing passenger attempts. Ore slots exclude farm networks. The cursor survives save/load, with older saves starting at the beginning of the rotation. Wood has regular slots for both the forest-to-sawmill link and its goods continuation.

Freight network station departures now require three straight tiles instead of twenty, allowing earlier turns around obstacles. `tests/rotation.py` checks the weighted schedule, skipped categories and save/load continuity; expansion and independent steel delivery tests also cover this change. An isolated replay of the 100-year autosave reaches passenger planning; this is not yet a long-term growth benchmark.

Station searches now have a final compact fallback: when the wider station
search cannot find a site at either end, passenger and independent freight
services can use one-platform reversing stations connected by a single
unsignalled line. This is a placement fallback, not a retry after an ordinary
pathfinding failure. The route permanently carries at most one train; carriages
may still grow to platform length, and maintenance and replacement continue.
The saved restriction blocks extra passenger, freight and mail trains, including
deferred second-track upgrades. Station width is saved in construction journals
so cleanup does not remove neighbouring tiles. Compact ore/wood backbones offer
no junction sites; subsequent cargo links use separate routes. Farm backbones
retain their grain and livestock trains and do not use this fallback.

`tests/compact.py` verifies freight commissioning, delivery, maintenance and the
saved fleet cap. `tests/compact_passenger.py` uses physically obstructed second
platforms to verify passenger fallback, circulation and safe station removal.
Both run on two map seeds; the regular RIRO and farm/goods integration fixtures
also cover the unchanged larger layouts.

Wood chains now receive a regular construction slot each round, including their sawmill-to-city continuation. Oil runs once per two rounds. With all categories available, each 19-slot cycle gives farms six attempts, passengers four, coal/goods/ore/wood two each, and oil one. The initial coal startup priority remains. Unavailable work is skipped and rotation progress survives save/load.

Industry closure now immediately requests retirement of affected services,
including added trains and separate steel/goods outlets. New service records
save source and destination industry IDs; older saves use their recorded station
endpoints as a fallback. Closure retirement bypasses ordinary optimisation
timers and the optimisation switch. Events are checked during path searches as
well as the main loop. Trains are directed to stop in a depot and sold with their
wagons; stopped depot trains can be sold immediately. Save/load preserves the
request, including replacement-engine handover. An active railway conversion
finishes safely before its held trains are retired.

Sales queue the existing railway cleanup: unused connected lines, stations and
depots are removed once trains are clear. A connected railway still used by any
other train is retained; this cleanup does not prune individual branches from a
live shared network. `tests/industry_closure.py` checks additional trains, legacy
steel/goods outlet matching, immediate depot diversion, saved retirement and
demolition. Existing loss-making retirement tests cover shared-track protection.

All new route selections use the same inclusive 50–150 Manhattan-tile endpoint
range, including farm expansion, wood, ore, steel and goods chain legs and towns.
The distance is |source x - destination x| + |source y - destination y|, measured
between industry locations or town centres, not station entrances, junctions or
track length. Direct construction requests also reject out-of-range endpoints.
Existing routes are not removed by this rule.

Rail upgrade retries can now complete mixed-type networks without requiring a
technology newer than their newest existing section. Queued carriage and engine
work may be superseded by fleet replacement; active purchases, sales and track
transactions remain protected. Gathering clears service-only depot flags, and
replacement trains do not inherit maintenance stop orders. Initial budgets use
quoted conversion costs with a rollback reserve where available, retaining a
contingency for occupied tiles and the final preflight before conversion.
Deferred upgrades log their component and reason (active work, missing records,
replacement availability, budget, construction or a gathering timeout).

Route failures are logged without creating map signs. Legacy `[VF]` failure
and `[VT search]` planning signs are removed during startup/search cleanup.
Unrelated signs remain untouched. Failure logs distinguish the project time
limit, individual search budget, station-pair limit and recorded build failures.

Terrain work now permits station cuttings/embankments of up to three levels
(96 changed corners, or 160 for a complete RIRO footprint; cost cap 40,000).
Route smoothing allows four levels, 160 changed corners and cost up to 60,000,
with candidate sections up to 16 tiles. Cash and rollback reserves still apply.
A bounded cutting trial runs on the first planned path before construction,
keeping changes only when replanning improves its score. Existing rail, roads,
water, station approaches and reserved footprints remain protected. This improves
a viable path; it does not terraform arbitrary land during every A* expansion.

RIRO fallback reasons are logged without placing signs. Startup cleanup removes
legacy `RIRO:` markers as well as old search/failure signs, preserving unrelated
signs. Detailed loop checks include orientations and failed tile locations.

RIRO construction now uses the same three-level/160-corner/40,000 earthworks
allowance as station planning, subject to the financial limits below. Minor
earthworks may request available loan funds for their cash reserve. Fallback logs distinguish cost cap, cash
reserve, rejected test/command and unmet height targets; logs include amounts,
tiles and command errors. Failed changes still retain rollback protection.

A buildable station site now retains any earthworks planned for its RIRO return
loop, even during the first station-selection pass. These changes are applied
and journalled before platforms or approach tracks are built, so construction
cannot block the loop's own planned cutting. Rollback restores the earlier land.

Intensive earthworks now require a fully repaid company loan and at least
500,000 cash. Before construction they must leave 500,000 plus the estimated
rollback cost available: the initial balance must cover 500,000 plus twice the
estimated work cost. Intensive work never requests a new loan.
Until eligible, all station, RIRO and track earthworks are capped at one height
level, 16 changed corners and 5,000 estimated cost per operation. Optional route
smoothing is skipped entirely until eligible. Existing terrain safety checks and
the normal larger limits remain in force for established companies.
Execution rechecks finances for cached plans; restoring failed work remains
possible regardless of debt. `python3 tests/terrain_finance.py` verifies the
financial boundaries, startup limits, cached-plan rejection, minor construction
and rollback on two maps.

Two-track construction now retries from a retained source-side midpoint when
building the first line or searching for its return line fails. Ground track is
built from source to destination. The retry removes the later journalled pieces,
keeps approximately the first half of the contiguous usable ground track, and
seeds A* at that frontier. The frontier's outgoing piece is removed so its new
heading is free. A tile in the discarded tail is excluded to avoid repeating the
same layout. The return track is then planned against the replacement first line.
This also applies to freight-network branches.

There is one midpoint retry per attempted track pair within its existing time
budget. Fewer than four usable prefix tiles, or an expired budget, skip this
retry. When a contiguous built route includes bridges or tunnels, the retained section
ends at the far end of its last completed structure instead of the midpoint.
The entire prefix, including every earlier structure, is preserved during retry.
Any disconnected structures beyond an incomplete prefix are removed whole. Failed retries still roll back the entire uncommissioned line.
All retained and replacement pieces stay in the saved construction journal, and
pre-existing infrastructure is never added to that removal journal merely for
being reused. `tests/midpoint.py` checks forced return-search failures, actual
construction obstacles, retained rails, alternative tails, bounded failure and
rollback on two seeds in both orientations. Bridge and tunnel fixtures also
check train circuits and preservation of infrastructure above/below the line.

Bridges now stop at the first buildable landing with a legal straight exit,
instead of offering progressively longer spans over clear land. This applies
also when that shortest candidate was already examined: search-state pruning
cannot unlock an unnecessarily long bridge. Narrow-corridor searches defer to
full searches rather than lengthening a crossing to fit their preferred corridor.

Tunnel exits remain determined by OpenTTD's terrain rules. Before offering a
long tunnel, the planner checks whether straight surface rail can reach a nearer
entrance with a shorter valid tunnel exiting within the same hill. When it can,
it defers tunnelling until that entrance. These checks are cached per search and
respect reserved land and the existing length/cost caps. No extra terraforming
is performed to shorten a tunnel.

Freight junctions first try a four-tile crossing (two ramps and the two running
tracks), extending a ramp only when the tighter complete layout is unavailable.
`tests/short_crossings.py` verifies both junction sides, construction/rollback,
and the rejection of a long tunnel when a nearer entrance is usable on a stepped
hill. The bridge fixture asserts minimum spans and checks train circulation over
rail and canal obstacles; the tunnel fixture checks traffic and surface safety.

Retained retry prefixes now carry existing bridge/tunnel transitions into A*
with the correct arrival direction and structure metadata. The far ramp stays
built, so trains must leave it straight. Retained structures remain in the saved
construction journal for final cleanup if the entire connection is abandoned.
`tests/structure_retry.py` checks two bridges; `--early` checks a bridge before
halfway and `--tunnel` checks a tunnel. Each runs on two seeds and verifies the
retry origin, intact prefix, structure metadata and eventual rollback.

## Dual RIRO processing-industry stations

New farm → factory, ore → steel mill, wood → sawmill, and steel → factory
connections first try a shared station with two independent two-platform RIRO
sections. Deliveries use one section; the industry's onward cargo service uses
the other. Pickup and delivery approaches can face opposite directions. The
pickup section is built with the inbound line, and its footprint is reserved
while planning that line. Ordinary RIRO, reversing, and eligible single-platform
fallbacks remain available; farm services still require two trains/platforms.
Dual candidates first try existing terrain, then coordinated levelling of both
sections before falling back. Larger earthworks still require a repaid loan and
sufficient cash; minor work keeps the existing startup limits.

A newly commissioned dual hub gets the next construction turn for its onward
cargo leg. Onward steel/goods legs receive 12,000 AI ticks initially and 16,000
on retries, with 40 search batches and up to 24 station attempts; ordinary new
connections retain their short initial budgets. Hub records and construction recovery journals survive saves. The
outlet reuses the existing pickup platforms, preserves the delivery section,
and restores its idle approach if construction fails. Upgrade and retirement
scans include all platform groups belonging to the shared station, even across
an empty row. Existing stations are not automatically rebuilt as dual hubs.

`python3 tests/dual_station.py` (also with `--vertical`) runs live OpenTTD
checks on two maps for both station axes and pickup facings, shared station IDs, full approach construction, onward platform
reuse, delivery-track protection during rollback, primitive saved state, fallback
retry eligibility, and next-turn continuation priority. The existing
`tests/farm_start.py --goods` checks cargo delivery through the complete chain;
`tests/rotation.py` checks that normal construction scheduling still progresses.

Dual RIRO pickup sections carry a `[VT pickup]` status sign while awaiting an
onward service: waiting, planning, building, retry reason, or separate-station
fallback. Status is saved and restored without duplicate signs. Completion of
the onward service (including a separate-station fallback) removes the sign;
rollback, industry closure and station removal also clear it. These signs are
independent of the disabled pathfinding/fallback diagnostic signs.

## Freight distances and budgets by rail technology

Industry routes use source/destination Manhattan distance, not laid track length.
Normal rail allows 40–125 tiles, electric rail 50–150, monorail 60–225, and
maglev 75–300. These checks cover coal/oil, farm and processing chains, and
industry-to-city goods outlets. Passenger town-pair distances remain 50–150.
New independent routes select the current technology before checking distance;
shared pickups and branches use the rail type of their existing infrastructure.

Freight project time, per-search batches, and station-attempt allowances use
85%, 100%, 150%, and 200% of their existing budgets respectively. The same
multipliers apply to the 12,000/16,000-tick onward-leg budgets. Batch/attempt
counts round up to whole numbers. Passenger planning keeps its existing budgets.
The built-in rail slots are classified explicitly; additional custom rail slots
use the electric-rail baseline. `tests/rail_policy.py` exercises all four types,
boundary distances, coordinate checks, initial/retry/onward budgets and reset
of freight settings before passenger planning.

## Growing a crowded two-platform RIRO station to three platforms

When a train stands still for a week on a station's approach throat while every
platform is occupied, the optimiser flags the station and the builder attempts
to add a third platform. The upgrade always places the new platform on the
side the queued train approaches from, so its one-way approach line can reach
the new mouth: beyond the inner platform row (pure additions, the return loop
untouched) or on the return row (the loop rebuilt one row further out, as in
the manual layout). The switch column may displace one approach signal; the
signal is journalled and restored if the upgrade is rolled back. When the
planned pickup section sits closer to the incoming line than the delivery
section, the two roles are swapped: the route reaches the closest platform
loop and the onward step takes the far section, avoiding double crossings. The new
platform joins the existing station, the mouth gains a PBS and waiting point,
and the roll-through gains an exit signal. The third platform's split shares
the mouth crossover's square, and the platform's far rail wraps around the old
merge corner on clear land to reach the return line. Earthworks follow the
same financial rules as other construction. Upgrades are rate limited per
station, never touch shared dual-hub sections, and every step re-checks world
state so a save between commands resumes or rolls back cleanly.
`python3 tests/platform_upgrade.py` runs live checks on two maps (also with
`--vertical`): a queued third train triggers the growth, the station spans
three platforms, and the new platform is reachable.

### Steel feeds the shared factory input line
When a steel mill's factory already receives grain and livestock on another
chain's input line, the steel leg is no longer built as a second line and
station. The mill becomes a feeder of that line: the branch construction
builds the mill's pickup station and depot, joins the existing input line at
a junction, and one steel train delivers to the same factory station the
grain and livestock trains use. The feeder is tried before the separate
steel line, which remains the fallback when the factory has no farm input
line, when the branch cannot build, or when the mill already feeds the line.
Feeder trains are retired with the mill, and the ore chain continues to its
goods outlet as usual. `python3 tests/steel_feeder.py` verifies the routing,
the shared-square split, the mill feeder bookkeeping and the fallback.


### Additional iron ore mines
Completed ore → steel → goods chains remain eligible for expansion: new ore
mines can branch into the original ore network and deliver to the same steel
mill station. Each new mine gets one ore train and its own pickup depot, using
the existing farm-branch construction, signals and maintenance flow. Production
and distance rank eligible mines; already-served and competitor-served sources
are excluded. Track-type distance limits still apply.

Ore junction candidates survive construction of the independent steel outlet.
Older saves recover candidates from the original ore line. Branches only use
junctions in the receiving station's connected track component, so an ore train
cannot accidentally join a disconnected steel or goods line. If no suitable
junction is available, the network yields to other construction work.


### Additional forests
After completing the forest → sawmill → city chain, the AI can connect more
forests to the original sawmill station through the existing wood network.
Each forest gets one wood train and a pickup depot. Selection, production and
distance ranking, competitor exclusions, retry cooldowns and connected-track
checks match the additional iron ore mine behaviour. Forest ownership is saved
and shared across the wood networks to prevent duplicate connections. Separate
goods outlets are not used as wood-delivery junctions.


### Gradually relaxing industry production requirements
When no untried coal connections or farm chains qualify, their production
threshold drops to 75%, 50%, 25%, then 10% of the original requirement, at most
once every 30 game days. Coal starts at 100 units/month and can eventually accept
10. Farms start above 50 units/month of either grain or livestock and can
ultimately qualify above 5. Each lower tier is searched before another reduction.
Successful candidate selection keeps the current threshold.

The policy survives saving/loading and farm networks share it, including new
networks and additional suppliers to existing factories. Industry scans resume
after the cooldown; cached farm eligibility is refreshed after a reduction.
Ore and wood already accept any positive production, so those cutoffs stay
at one. Oil wells produce orders of magnitude more units than other
industries: their initial cutoff is 100,000 units/month, relaxed by the same
ladder down to 10,000 when nothing viable remains. Distance, competition,
station coverage and construction checks remain in effect.


### Short track detours
Before construction, successful searches receive a bounded local straightening
pass on both tracks. It replaces short sideways kinks with a cheaper buildable
straight or diagonal alignment. Station approaches, reserved tiles, occupied
track pieces, structures and already-built sections are protected. The pass
checks at most 64 alternatives and makes at most four replacements, with a
20-tick time allowance; necessary obstacle detours are retained. Existing routes
are not rebuilt by this change.
