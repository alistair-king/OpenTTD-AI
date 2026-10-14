require("util.nut");
require("pathfinder.nut");
require("paired_pathfinder.nut");
require("hierarchy.nut");
require("terrain.nut");
require("builder.nut");
require("roro.nut");
require("single_track.nut");
require("trains.nut");
require("retirement_cleanup.nut");
require("rail_upgrade.nut");
require("optimiser.nut");
require("coal.nut");
require("junction.nut");
require("network.nut");
require("dual_station.nut");
require("platform_upgrade.nut");

class OpenTTDAI extends AIController
{
	builder = null;
    rail_upgrades=null;loaded_rail_upgrades=null;
    construction_cursor=0;
    loaded_planning_history=null;
    loaded_retirements=null;
	oil = null;
	loaded_oil = null;
	coal = null;
	loaded_coal = null;
    network = null;
    wood_network = null;
    loaded_wood_network = null;
    wood_next = false;
    loaded_network = null;
    network_next = true;
	coal_turn = 0;
	continuation_turn = true;
	rail_review_month = null;
	pairs_quiet_until = 0;
	last_recover_day = -1;
	iron = null;
	loaded_iron = null;
	iron_next = true;
	buyer = null;
	optimiser = null;
	loaded_services = null;
	loaded_pending_stations = null;
	routes = 0;
	loaded_failures = null;
	loaded_connections = null;
	competition_cache = null;
	population_threshold = null;
	last_loan_repayment_year = -1;
}

function OpenTTDAI::Start()
{
	this.Sleep(1 + AIBase.RandRange(150));
	this.SetCompanyName();
    ::IndustryClosureController=this;
	// The optimiser owns renewal and tracks the new vehicle ID itself.
	AICompany.SetAutoRenewStatus(false);
	AILog.Info("OpenTTDAI is looking for passenger work.");

	if (!PickRailType()) {
		AILog.Error("No rail type is available.");
		return;
	}

	local cargo = PassengerCargo();
	if (cargo == 0xFF) {
		AILog.Error("No passenger cargo on this map.");
		return;
	}

	::RetiredRailways=RailwayRetirement(this.loaded_retirements);
    this.rail_upgrades=RailwayUpgrades(this.loaded_rail_upgrades);
	this.builder = RouteBuilder(AIController.GetSetting("platform_length"), this.loaded_failures, this.loaded_connections);
	if(this.loaded_planning_history!=null) this.builder.planning_history=this.loaded_planning_history;
	// Town routes are two-track from the start: deferred return-line upgrades
	// kept failing once town growth blocked the second path.
	this.builder.single_first = false;
	this.builder.use_hierarchy = false;
	this.builder.use_jump_search = false;
	this.builder.use_aystar = false;
	if (this.loaded_pending_stations != null) this.builder.pending_stations = this.loaded_pending_stations;
	this.builder.ReleasePendingStations();
	this.builder.ClearSearchSigns();
	this.buyer = TrainBuyer(cargo);
	this.optimiser = ServiceOptimiser(this.buyer, this.loaded_services);
	this.builder.optimiser = this.optimiser;
	this.coal = CoalRoutes(this.builder,this.loaded_coal);
	this.iron = CoalRoutes(this.builder,this.loaded_iron,"IORE");
	this.oil = CoalRoutes(this.builder,this.loaded_oil,"OIL_");
	this.iron.passenger_optimiser=this.oil;
	this.oil.passenger_optimiser=this.optimiser;
	this.network=FreightNetworks(this.builder.platform_length,this.loaded_network);
    this.wood_network=FreightNetworks(this.builder.platform_length,this.loaded_wood_network,"WOOD");
    this.network.passenger_optimiser=this.wood_network;
    this.wood_network.passenger_optimiser=this.iron;
    this.coal.passenger_optimiser=this.network;
	this.builder.optimiser=this.coal;
	// Construction borrows as needed; loading a game must not undo repayments.

	local next_build = 0;
	while (true) {
        local upgrade_owners=[this,this.coal,this.iron,this.oil];
        foreach(manager in [this.network,this.wood_network]) foreach(n in manager.networks) upgrade_owners.append(n);
        this.rail_upgrades.Bind(upgrade_owners);
        this.HandleEvents();
        this.ReviewIndustryClosures();
        if(this.rail_upgrades.Busy()) {this.rail_upgrades.RunBatch();this.Sleep(5);continue;}
		this.coal.Review();
		this.ReviewLoan();
		local month = AIDate.GetYear(AIDate.GetCurrentDate()) * 12 + AIDate.GetMonth(AIDate.GetCurrentDate());
        // Do not remove infrastructure during an unfinished construction transaction.
        local pending=this.builder.pending_stations.len()>0,upgrade_blocked=[];
        foreach(site in this.builder.pending_stations) upgrade_blocked.append(site.tile);
        foreach(manager in [this.network,this.wood_network]) if(manager!=null)
            foreach(n in manager.networks) if(n.builder.pending_stations.len()>0 || n.state.transaction!=null ||
                ("plan" in n.state && n.state.plan!=null)) {
                pending=true;
                upgrade_blocked.append(n.state.depot);
                foreach(site in n.state.stations) upgrade_blocked.append(site.tile);
                foreach(site in n.builder.pending_stations) upgrade_blocked.append(site.tile);
            }
        if(!pending) {
            if(this.rail_review_month!=month) {this.rail_review_month=month;RailTypeReview();}
            local cleaning=RetiredRailways.Step();
            this.FinishRetirements();
            if(cleaning) {this.Sleep(5);continue;}
        }
        this.rail_upgrades.RunBatch(upgrade_blocked);
		if (!this.rail_upgrades.Busy() && AIController.GetTick() >= next_build) {
			this.TryBuildRoute();
			next_build = AIController.GetTick() + 10;
		}
		this.Sleep(5);
	}
}

function OpenTTDAI::ReviewLoan()
{
	local year = AIDate.GetYear(AIDate.GetCurrentDate());
	if (year <= this.last_loan_repayment_year) return false;
	if (!RepaySurplusLoan()) return false;
	this.last_loan_repayment_year = year;
	return true;
}

function OpenTTDAI::Save()
{
	local failed = this.builder == null ? this.loaded_failures : this.builder.failed_connections;
	local connected = this.builder == null ? this.loaded_connections : this.builder.connected_pairs;
	return { construction_cursor=this.construction_cursor, rail_upgrades=this.rail_upgrades==null?this.loaded_rail_upgrades:this.rail_upgrades.Save(), oil=this.oil==null?this.loaded_oil:this.oil.Save(), retirements=RetiredRailways==null?this.loaded_retirements:RetiredRailways.Save(), planning_history=this.builder==null?this.loaded_planning_history:this.builder.planning_history, continuation_turn=this.continuation_turn, coal_turn=this.coal_turn, wood_network=this.wood_network==null?this.loaded_wood_network:this.wood_network.Save(), wood_next=this.wood_next, network=this.network==null?this.loaded_network:this.network.Save(), network_next=this.network_next, iron = this.iron==null ? this.loaded_iron : this.iron.Save(), iron_next = this.iron_next, coal = this.coal==null ? this.loaded_coal : this.coal.Save(), last_loan_repayment_year = this.last_loan_repayment_year, population_threshold = this.population_threshold, pending_stations = SavedStationReservations(this.builder == null ? this.loaded_pending_stations : this.builder.pending_stations), routes = this.routes, failed_connections = failed == null ? {} : clone failed,
		connected_pairs = connected == null ? {} : clone connected,
		services = this.optimiser == null ? this.loaded_services : this.optimiser.Save() };
}

function OpenTTDAI::Load(version, data)
{
    this.construction_cursor=("construction_cursor" in data && typeof data.construction_cursor=="integer" && data.construction_cursor>=0)?data.construction_cursor%this.ConstructionRotation().len():0;
	this.loaded_retirements="retirements" in data ? data.retirements : null;
	this.loaded_planning_history="planning_history" in data ? data.planning_history : null;
	this.loaded_rail_upgrades="rail_upgrades" in data?data.rail_upgrades:null;
	this.loaded_oil = "oil" in data ? data.oil : null;
	this.loaded_coal = "coal" in data ? data.coal : null;
    this.coal_turn="coal_turn" in data?data.coal_turn:0;
    this.continuation_turn="continuation_turn" in data?data.continuation_turn:true;
    this.loaded_wood_network="wood_network" in data?data.wood_network:null;
    this.wood_next="wood_next" in data?data.wood_next:false;
    this.loaded_network="network" in data?data.network:null;
    this.network_next="network_next" in data?data.network_next:true;
	this.loaded_iron = "iron" in data ? data.iron : null;
	this.iron_next = "iron_next" in data ? data.iron_next : true;
	this.last_loan_repayment_year = "last_loan_repayment_year" in data && typeof data.last_loan_repayment_year == "integer" ? data.last_loan_repayment_year : -1;
	this.population_threshold = "population_threshold" in data && typeof data.population_threshold == "integer" ? data.population_threshold : null;
	if (this.population_threshold != null && this.population_threshold < 50) this.population_threshold = 50;
	this.loaded_pending_stations = "pending_stations" in data ? data.pending_stations : null;
	this.loaded_services = "services" in data ? data.services : null;
	this.loaded_connections = "connected_pairs" in data ? clone data.connected_pairs : {};
	this.loaded_failures = "failed_connections" in data ? clone data.failed_connections : {};
	if ("routes" in data) this.routes = data.routes;
}

function OpenTTDAI::SetCompanyName()
{
	if (!AICompany.SetName("OpenTTDAI")) {
		local i = 2;
		while (!AICompany.SetName("OpenTTDAI #" + i) && i < 255) {
			i++;
		}
	}
	AICompany.SetPresidentName("V. Ibe");
}

function OpenTTDAI::ReviewIndustryClosures()
{
    foreach(owner in [this,this.coal,this.iron,this.oil])
        if(owner!=null && owner.optimiser!=null) owner.optimiser.ReviewClosures();
    foreach(manager in [this.network,this.wood_network]) if(manager!=null)
        foreach(network in manager.networks) network.optimiser.ReviewClosures();
}

function OpenTTDAI::HandleEvents()
{
	while (AIEventController.IsEventWaiting()) {
		local event = AIEventController.GetNextEvent();
		if (event == null) break;
		switch (event.GetEventType()) {
			case AIEvent.ET_VEHICLE_CRASHED:
				AILog.Warning("A train crashed. Time to build more carefully.");
				break;
			case AIEvent.ET_VEHICLE_LOST:
				AILog.Warning("A train is lost.");
				break;
			case AIEvent.ET_INDUSTRY_CLOSE: {
				local industry = AIEventIndustryClose.Convert(event).GetIndustryID();
				AILog.Info("An industry closed.");
				if(this.oil!=null) this.oil.OnIndustryClosed(industry);
                if (this.coal != null && ("OnIndustryClosed" in this.coal)) this.coal.OnIndustryClosed(industry);
				if (this.iron != null && ("OnIndustryClosed" in this.iron)) this.iron.OnIndustryClosed(industry);
				if (this.network != null && ("OnIndustryClosed" in this.network)) this.network.OnIndustryClosed(industry);
				if (this.wood_network != null && ("OnIndustryClosed" in this.wood_network)) this.wood_network.OnIndustryClosed(industry);
				break;
			}
			case AIEvent.ET_INDUSTRY_OPEN: {
				local industry = AIEventIndustryOpen.Convert(event).GetIndustryID();
				if(this.oil!=null) this.oil.OnIndustryOpened(industry);
                if (this.coal != null && ("OnIndustryOpened" in this.coal)) this.coal.OnIndustryOpened(industry);
				if (this.iron != null && ("OnIndustryOpened" in this.iron)) this.iron.OnIndustryOpened(industry);
				if (this.network != null && ("OnIndustryOpened" in this.network)) this.network.OnIndustryOpened(industry);
				if (this.wood_network != null && ("OnIndustryOpened" in this.wood_network)) this.wood_network.OnIndustryOpened(industry);
				break;
			}
		}
	}
}

function OpenTTDAI::ConstructionRotation()
{
    // Wood gets a regular turn each round; oil only once per two rounds.
    return ["coal","goods","farm","ore","farm","passengers","farm","wood","passengers",
            "coal","goods","farm","ore","farm","passengers","farm","wood","passengers","oil"];
}

function OpenTTDAI::TryBuildRoute()
{
    // The first coal service still gets startup priority. Afterwards a failed
    // high-priority attempt spends its slot, not everybody else's next turn.
    if(this.coal!=null && !this.coal.StartupComplete()) {
        if(this.coal.TryBuild()) return;
        if(!this.coal.YieldsStartup()) return;
    }
    // Give a newly commissioned dual hub the very next construction turn.
    foreach(manager in [this.network,this.wood_network]) if(manager!=null && "networks" in manager)
        foreach(network in manager.networks) if("dual_priority" in network.state && network.state.dual_priority) {
            network.state.dual_priority=false;
            if(network.NeedsContinuation() && network.TryBuild()) return;
        }
    local rotation=this.ConstructionRotation();
    local tried={};
    for(local i=0;i<rotation.len();i++) {
        local kind=rotation[this.construction_cursor];
        this.construction_cursor=(this.construction_cursor+1)%rotation.len();
        if(kind in tried) continue;
        tried[kind] <- true;
        if(this.TryConstructionKind(kind)) return;
    }
}

function OpenTTDAI::TryConstructionKind(kind)
{
    if(kind=="coal") return this.coal!=null && this.coal.TryBuild();
    if(kind=="wood") return this.wood_network!=null && this.wood_network.TryBuild();
    if(kind=="oil") return this.oil!=null && this.oil.TryBuild();
    if(kind=="passengers") return this.TryPassengerRoute();
    if(this.network==null) return false;
    if(kind=="goods") return "TryFactoryGoods" in this.network && this.network.TryFactoryGoods();
    if(kind=="farm") {
        if("TryPostGoodsFarms" in this.network && this.network.TryPostGoodsFarms()) return true;
        return "TryBuildFarm" in this.network && this.network.TryBuildFarm();
    }
    if(kind=="ore") return "TryBuildOre" in this.network?this.network.TryBuildOre():this.network.TryBuild();
    return false;
}

function OpenTTDAI::TryPassengerRoute()
{
    local max_routes = AIController.GetSetting("max_routes");
    if(max_routes>0 && this.routes>=max_routes) return false;

	// A token delay keeps simultaneous AIs from picking identical pairs without
	// idling most of the schedule.
	this.Sleep(1 + AIBase.RandRange(5));
	local pair = this.PickTownPair();
	if (pair == null) {
		// Every candidate is deferred or cooled down; log once per game day.
		if (AIController.GetTick() >= this.pairs_quiet_until) {
			AILog.Info("No more town pairs look viable right now.");
			this.pairs_quiet_until = AIController.GetTick() + 74;
		}
		return false;
	}

	AILog.Info("Planning rail: " + AITown.GetName(pair[0]) + " <-> " + AITown.GetName(pair[1]));
	local count_a = this.CompetingStationCount(pair[0], true);
	local count_b = this.CompetingStationCount(pair[1], true);
	local guard = { controller = this, count_a = count_a, count_b = count_b };
	local route = this.builder.ConnectTowns(pair[0], pair[1], guard);
	if (route == null) return true;

	// Size the first consist from the pickup town's catchment production.
	local platform_wagons = AIController.GetSetting("platform_length") - 1;
	if (platform_wagons < 2) platform_wagons = 2;
	local wagons = this.buyer.SizedWagons(MonthlyCargoDemand(PassengerCargo(), null, route.station_a), platform_wagons);
	AILog.Info("Passenger route: first train sized to " + wagons + " wagons from catchment demand.");
	local train = this.buyer.BuildPassengerTrain(route.depot, route.station_a, route.station_b, wagons);
	if (train >= 0) {
		this.optimiser.Register(train, route, AIController.GetSetting("platform_length"));
		this.routes++;
	}
    return true;
}

// Rival station APIs are ownership-restricted: inspect public tile information.
function OpenTTDAI::CompetingStationCount(town, fresh = false)
{
	if (this.competition_cache == null) this.competition_cache = {};
	local now = AIDate.GetCurrentDate();
	if (!fresh && town in this.competition_cache && now < this.competition_cache[town].expires)
		return this.competition_cache[town].count;
	local centre = AITown.GetLocation(town);
	local cx = AIMap.GetTileX(centre);
	local cy = AIMap.GetTileY(centre);
	local self = AICompany.ResolveCompanyID(AICompany.COMPANY_SELF);
	local cargo = PassengerCargo();
	local stations = {};
	// Bounded scan around towns, refreshed every seven game days.
	for (local dx = -20; dx <= 20; dx++) {
		for (local dy = -20; dy <= 20; dy++) {
			local x = cx + dx, y = cy + dy;
			if (x < 0 || y < 0 || x >= AIMap.GetMapSizeX() || y >= AIMap.GetMapSizeY()) continue;
			local tile = AIMap.GetTileIndex(x, y);
			if (!AITile.IsStationTile(tile)) continue;
			local owner = AITile.GetOwner(tile);
			if (owner == self || AICompany.ResolveCompanyID(owner) == AICompany.COMPANY_INVALID ||
				AITile.GetClosestTown(tile) != town) continue;
			// Conservative coverage estimate, also suitable for nearby road stops.
			if (cargo != 0xFF && AITile.GetCargoProduction(tile, cargo, 1, 1, 3) > 0) stations[AIStation.GetStationID(tile)] <- true;
		}
	}
	this.competition_cache[town] <- { count = stations.len(), expires = now + 7 };
	return stations.len();
}

function OpenTTDAI::HasCompetingStation(town)
{
	return this.CompetingStationCount(town) > 0;
}

function OpenTTDAI::CompetitionWeight(town, population, typical)
{
	// Even large cities have limited demand: each distinct rival station matters.
	return 1.0 / (1.0 + 9.0 * this.CompetingStationCount(town));
}

// A bounded terrain estimate, not a route search: hills and water are soft costs.
function OpenTTDAI::TownPairTerrainCost(a, b, height_a, height_b)
{
	local ax = AIMap.GetTileX(a), ay = AIMap.GetTileY(a);
	local bx = AIMap.GetTileX(b), by = AIMap.GetTileY(b);
	local previous_height = height_a;
	local climb = 0;
	local water = 0;
	for (local i = 1; i <= 8; i++) {
		local tile = AIMap.GetTileIndex(ax + (bx-ax)*i/8, ay + (by-ay)*i/8);
		local height = i == 8 ? height_b : AITile.GetCornerHeight(tile, AITile.CORNER_N);
		climb += Abs(height - previous_height);
		previous_height = height;
		if (i < 8 && AITile.IsWaterTile(tile)) water++;
	}
	// Endpoint elevation is already priced separately; charge only extra rises/falls.
	return 6 * (climb - Abs(height_b-height_a)) + 8 * water;
}

function OpenTTDAI::PickTownPair()
{
	// Order recovery is a safety net for lost bookkeeping, not needed every
	// attempt; saved connections already cover the normal case.
	local today = AIDate.GetCurrentDate();
	if (today != this.last_recover_day) {
		this.last_recover_day = today;
		this.builder.RecoverLiveConnections();
	}
	if (this.population_threshold == null)
		this.population_threshold = AIController.GetSetting("min_town_population");
	while (true) {
		local pair = this.PickTownPairAtPopulation(this.population_threshold);
		if (pair != null || this.population_threshold <= 50) return pair;
		local previous = this.population_threshold;
		this.population_threshold = previous / 2;
		if (this.population_threshold < 50) this.population_threshold = 50;
		AILog.Info("No eligible town pairs at population " + previous +
			"; lowering minimum population to " + this.population_threshold + ".");
	}
}

function OpenTTDAI::PickTownPairAtPopulation(min_pop)
{
	local towns = AITownList();
	towns.Valuate(AITown.GetPopulation);
	towns.KeepAboveValue(min_pop - 1);
	towns.Sort(AIList.SORT_BY_VALUE, false);

	local populations = [];
	foreach (_town, population in towns) populations.append(population);
	if (populations.len() < 2) return null;
	populations.sort();
	local typical = (populations[(populations.len() - 1) / 2] + populations[populations.len() / 2]) / 2;
	local ids = [];
	local heights = {};
	local competition = {};
	local locations = {};
	local counts = {};
	foreach (town_id, _pop in towns) {
		if (this.builder.TownIsFree(town_id, TownRouteLimit(_pop, typical))) {
			ids.append(town_id);
			locations[town_id] <- AITown.GetLocation(town_id);
			counts[town_id] <- this.builder.TownRouteCount(town_id);
			heights[town_id] <- AITile.GetCornerHeight(locations[town_id], AITile.CORNER_N);
		}
	}
	if (ids.len() < 2) return null;

	local best = null;
	local best_score = 0;
	local best_priority = -1;
	for (local i = 0; i < ids.len(); i++) {
		for (local j = i + 1; j < ids.len(); j++) {
			if (this.builder.ConnectionFailed(ids[i], ids[j]) || this.builder.ConnectionBuilt(ids[i], ids[j])) continue;
			local dist = AIMap.DistanceManhattan(locations[ids[i]], locations[ids[j]]);
			if (!RouteDistanceAllowed(dist)) continue;
			local height_difference = Abs(heights[ids[i]] - heights[ids[j]]);
			// Each height level counts like ten extra tiles when ranking towns.
			// This is a preference, not a ban on routes between different heights.
			local population_a = towns.GetValue(ids[i]).tofloat();
			local population_b = towns.GetValue(ids[j]).tofloat();
			local large_a = population_a >= typical;
			local large_b = population_b >= typical;
			local unserved_large = (large_a && counts[ids[i]] == 0) ||
				(large_b && counts[ids[j]] == 0);
			// Priority tiers cannot be outweighed by a cheaper small-town route.
			local priority = large_a && large_b ? (unserved_large ? 3 : 2) : (unserved_large ? 1 : 0);
			local served = counts[ids[i]] + counts[ids[j]];
			local demand = (population_a * population_a + population_b * population_b) / (1 + served);
			local effort = dist + 10 * height_difference;
			local variation = (75 + AIBase.RandRange(51)) / 100.0;
			local score = demand * variation / effort;
			// Further penalties only reduce this upper bound. Avoid work on losers.
			if (priority < best_priority || (priority == best_priority && score <= best_score)) continue;
			effort += this.TownPairTerrainCost(locations[ids[i]], locations[ids[j]], heights[ids[i]], heights[ids[j]]);
			score = demand * variation / effort;
			if (priority == best_priority && score <= best_score) continue;
			foreach (town in [ids[i], ids[j]]) {
				if (!(town in competition)) competition[town] <- this.CompetitionWeight(town, towns.GetValue(town), typical);
				score *= competition[town];
				if (priority == best_priority && score <= best_score) break;
			}
			if (priority > best_priority || (priority == best_priority && score > best_score)) {
				best_priority = priority;
				best_score = score;
				best = [ids[i], ids[j]];
			}
		}
	}
	return best;
}

function OpenTTDAI::FinishRetirements()
{
    foreach(job in RetiredRailways.completed) {
        if(job.towns.len()==2) {
            local key=this.builder.ConnectionKey(job.towns[0],job.towns[1]);
            if(key in this.builder.connected_pairs) {
                delete this.builder.connected_pairs[key];
                if(this.routes>0) this.routes--;
                this.builder.planning_history[key] <- {count=4,after=AIDate.GetCurrentDate()+365};
                this.builder.used_towns={};
                foreach(_,pair in this.builder.connected_pairs) foreach(t in pair) this.builder.MarkTown(t);
            }
        }
        foreach(manager in [this.network,this.wood_network]) if(manager!=null) {
            for(local i=manager.networks.len()-1;i>=0;i--) {
                local n=manager.networks[i];
                if(!(n.state.depot in job.seen)) continue;
                local live=false;foreach(id,_ in n.optimiser.trains) if(AIVehicle.IsValidVehicle(id)) live=true;
                if(!live) manager.networks.remove(i);
            }
        }
    }
    RetiredRailways.completed=[];
}
