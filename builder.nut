class RouteBuilder
{
    station_platforms=2;
    committed_prefix=false;
    closure_review_day=-1;
    entrance_guidance=true;
    planning_history=null;
    search_batches_limit=40;
    planning_percent=100;
    station_attempt_limit=36;
    station_retry_spacing=0;
    station_attempts=null;
    start_run=3;
    junction_reuse=false;
	platform_length = 4;
	single_first = false;
	reusable_rails = null;
	skip_rail_pieces = null;
	build_journal = null;
	extra_reserved = null;
	search_corridor = null;
	// Legacy fixture fields are inert; SearchPath always runs ordinary A*.
	use_hierarchy = false;
	use_jump_search = false;
	use_aystar = false;
	aystar_trial = false;
	jump_trial = false;
	planning_deadline = 0;
	planning_timed_out = false;
	startup_failures = 0;
	optimiser = null;
	used_towns = null;
	retry_after = null;
	failed_connections = null;
	connected_pairs = null;
	station_evaluations = null;
	station_shortlists = null;
	pending_stations = null;
	retained_prefixes = null;
	reuse_prefixes = false;
	failure_detail = null;
    failure_tile = -1;
	search_failure = "middle";
	route_failure = "middle";
	attempt_failure = "temporary";
	reservation_failure = null;
	optimiser_review_day = -1;

	constructor(platform_length, failed_connections = null, connected_pairs = null)
	{
		this.platform_length = platform_length;
		this.pending_stations = [];
        this.planning_history={};
        this.station_attempts=[];
		this.used_towns = {};
		this.retry_after = {};
		this.failed_connections = failed_connections == null ? {} : clone failed_connections;
		this.connected_pairs = connected_pairs == null ? {} : clone connected_pairs;
		foreach (_key, pair in this.connected_pairs) {
			this.MarkTown(pair[0]);
			this.MarkTown(pair[1]);
		}
	}

    function PlanningBudget()
    {
        local oldest=-1;
        foreach(train,_ in AIVehicleList()) {
            if(AIVehicle.GetVehicleType(train)!=AIVehicle.VT_RAIL ||
                AIVehicle.GetState(train)==AIVehicle.VS_STOPPED || AIVehicle.IsStoppedInDepot(train)) continue;
            if(AIVehicle.GetAge(train)>oldest) oldest=AIVehicle.GetAge(train);
        }
        return this.BudgetForAge(oldest);
    }
    function BudgetForAge(oldest)
    {
        if(oldest<0) {
            local budget=2400+(this.startup_failures/4)*2400;
            return budget>8000 ? 8000 : budget;
        }
        return oldest<2*365 ? 4800 : 8000;
    }
    function DeferredConnection(key)
    {
        return key in this.planning_history && AIDate.GetCurrentDate()<this.planning_history[key].after;
    }
    function LogRouteFailure(source,destination,success)
    {
        if(success) return;
        local reason=this.failure_detail==null ? "No feasible route" : this.failure_detail;
        if(this.planning_deadline!=0 && AIController.GetTick()>=this.planning_deadline)
            reason="Project time budget reached";
        AILog.Info("Route failed at "+source+" towards "+destination+": "+reason+
            "; last failure tile="+this.failure_tile);
    }
	function FinishConnection(key,success)
	{
		if(success) { if(key in this.planning_history) delete this.planning_history[key]; }
		else {
			local count=key in this.planning_history ? this.planning_history[key].count+1 : 1;
			// Short cooldowns: quick probes fail cheaply, and the pair reaches its
			// full-budget search within a season instead of after years.
			// Repeated failures of the same pair escalate to multi-year
			// deferrals: an approach blocked by town layout only changes as
			// the town grows, so annual retries just burn decades.
			local days=count==1 ? 30 : (count==2 ? 60 : (count==3 ? 180 : (count==4 ? 365 : (count==5 ? 730 : (count==6 ? 1460 : 2920)))));
			this.planning_history[key] <- {count=count,after=AIDate.GetCurrentDate()+days};
			AILog.Info("Planning: deferring unsuccessful connection for "+days+" days (attempt "+count+").");
		}
		this.search_batches_limit=40;
        this.planning_percent=100;
	}
    function BeginPlanning(key=null,continuation=false,industry=false)
    {
        this.failure_detail=null;this.failure_tile=-1;
        local budget=this.PlanningBudget();
        local count=key!=null && key in this.planning_history ? this.planning_history[key].count : 0;
        this.search_batches_limit=key==null ? 40 : (count==0 ? 8 : (count==1 ? 16 : 40));
        if(key!=null) {
            local limit=count==0 ? 1200 : (count==1 ? 2400 : budget);
            if(budget==0 || limit<budget) budget=limit;
        }
        this.station_attempt_limit=key==null || count>=2 ? 36 : (count==0 ? 4 : 8);
        this.station_retry_spacing=key==null || count>=2 ? 0 : (count==0 ? 3 : 1);
        if(continuation) {
            budget=count==0 ? 12000 : 16000;
            this.search_batches_limit=40;
            this.station_attempt_limit=24;
            this.station_retry_spacing=1;
            AILog.Info("Planning: extended budget for an existing cargo chain's onward leg.");
        }
        this.planning_percent=industry ? IndustryRailPolicy().budget_percent : 100;
        budget=budget*this.planning_percent/100;
        this.search_batches_limit=(this.search_batches_limit*this.planning_percent+99)/100;
        this.station_attempt_limit=(this.station_attempt_limit*this.planning_percent+99)/100;
        this.station_attempts=[];
        this.planning_timed_out=false;
        this.planning_deadline=budget==0 ? 0 : AIController.GetTick()+budget;
        if(budget>0) AILog.Info("Planning: limiting this connection to "+budget+" AI ticks.");
    }
    function TryStationPair(a,b)
    {
        a=clone a; b=clone b;
        if(!("exit" in a)) a.exit <- this.NearestStationExit(a,b.tile);
        if(!("exit" in b)) b.exit <- this.NearestStationExit(b,a.tile);
        foreach(pair in this.station_attempts) {
            if(("dual" in a)==("dual" in pair[0]) && ("dual" in b)==("dual" in pair[1]) &&
                StationPlatforms(a)==StationPlatforms(pair[0]) && StationPlatforms(b)==StationPlatforms(pair[1]) && a.dir==pair[0].dir && b.dir==pair[1].dir &&
                a.exit[0]-a.exit[1]==pair[0].exit[0]-pair[0].exit[1] &&
                b.exit[0]-b.exit[1]==pair[1].exit[0]-pair[1].exit[1] &&
                AIMap.DistanceManhattan(a.tile,pair[0].tile)<=this.station_retry_spacing &&
                AIMap.DistanceManhattan(b.tile,pair[1].tile)<=this.station_retry_spacing) return false;
        }
        if(this.station_attempts.len()>=this.station_attempt_limit) {
            this.planning_timed_out=true;
            this.failure_detail="Station-pair attempt limit reached";
            AILog.Info("Planning: station-pair attempt limit reached; yielding to another connection.");
            return false;
        }
        this.station_attempts.append([a,b]);
        return true;
    }
    function PlanningExpired()
    {
        if(this.planning_timed_out && this.planning_deadline!=0) return true;
        if(this.planning_deadline==0 || AIController.GetTick()<this.planning_deadline) return false;
        if(!this.planning_timed_out) AILog.Info("Planning: project time budget reached; yielding to another connection.");
        this.planning_timed_out=true;
        return true;
    }

	function ConnectionKey(a, b, kind_a = "town", kind_b = "town")
	{
		local first = kind_a + ":" + a;
		local second = kind_b + ":" + b;
		return first < second ? first + "|" + second : second + "|" + first;
	}

	function ConnectionFailed(a, b, kind_a = "town", kind_b = "town")
	{
		return this.ConnectionKey(a, b, kind_a, kind_b) in this.failed_connections ||
            this.DeferredConnection(this.ConnectionKey(a,b,kind_a,kind_b));
	}

	function RememberFailure(a, b, kind_a = "town", kind_b = "town")
	{
		this.failed_connections[this.ConnectionKey(a, b, kind_a, kind_b)] <- true;
	}

	function TownRouteCount(town_id)
	{
		return town_id in this.used_towns ? this.used_towns[town_id] : 0;
	}

	function ConnectionBuilt(a, b)
	{
		return this.ConnectionKey(a, b) in this.connected_pairs;
	}

	function MarkConnection(a, b)
	{
		if (this.ConnectionBuilt(a, b)) return;
		this.connected_pairs[this.ConnectionKey(a, b)] <- [a, b];
		this.MarkTown(a);
		this.MarkTown(b);
	}

	function RecoverLiveConnections()
	{
		// Recover missing/legacy route memory from our trains' actual station orders.
		foreach (train, _ in AIVehicleList()) {
			if (AIVehicle.GetVehicleType(train) != AIVehicle.VT_RAIL ||
				AIVehicle.GetState(train) == AIVehicle.VS_CRASHED ||
				AIVehicle.GetCapacity(train,PassengerCargo())<=0) continue;
			local towns = [];
			foreach (index in this.StationOrderIndices(train)) {
				local station = AIStation.GetStationID(AIOrder.GetOrderDestination(train, index));
				if (!AIStation.IsValidStation(station)) continue;
				local town = AIStation.GetNearestTown(station);
				if (!AITown.IsValidTown(town)) continue;
				local seen = false;
				foreach (other in towns) if (other == town) seen = true;
				if (!seen) towns.append(town);
			}
			for (local i = 0; i < towns.len(); i++) for (local j = i+1; j < towns.len(); j++)
				this.MarkConnection(towns[i], towns[j]);
		}
	}

	function StationOrderIndices(train)
	{
		local indices = [];
		for (local i = 0; i < AIOrder.GetOrderCount(train); i++)
			if (AIOrder.IsGotoStationOrder(train, i)) indices.append(i);
		return indices;
	}

	function TownIsFree(town_id, limit = 1)
	{
		return this.TownRouteCount(town_id) < limit &&
			(!(town_id in this.retry_after) || AIController.GetTick() >= this.retry_after[town_id]);
	}

	function MarkTown(town_id)
	{
		this.used_towns[town_id] <- this.TownRouteCount(town_id) + 1;
	}

	function TownCentreDistance(tile, dir, center)
	{
		// Use the nearest platform tile, rather than the footprint's anchor corner.
		local size = StationFootprint(dir, this.platform_length, this.station_platforms);
		local dx = AIMap.GetTileX(center) - AIMap.GetTileX(tile);
		local dy = AIMap.GetTileY(center) - AIMap.GetTileY(tile);
		local x = dx < 0 ? -dx : (dx >= size[0] ? dx - size[0] + 1 : 0);
		local y = dy < 0 ? -dy : (dy >= size[1] ? dy - size[1] + 1 : 0);
		return x + y;
	}

	function StationEvaluation(tile, dir, cargo, coverage)
	{
		local key = tile + ":" + dir;
		if (this.station_evaluations != null && key in this.station_evaluations)
			return this.station_evaluations[key];
		local size = StationFootprint(dir, this.platform_length, this.station_platforms);
		local production = 0;
		if (AreaIsBuildable(tile, size[0], size[1]) &&
			AITile.GetCargoAcceptance(tile, cargo, size[0], size[1], coverage) >= 8)
			production = AITile.GetCargoProduction(tile, cargo, size[0], size[1], coverage);
		local result = { production = production, buildable = null, earthworks = {} };
		if (this.station_evaluations != null) this.station_evaluations[key] <- result;
		return result;
	}

	function FacesDestination(tile, dir, center, target)
	{
		local size = StationFootprint(dir, this.platform_length, this.station_platforms);
		// Use the centre of the complete footprint, not its anchor corner.
		local dx = 2 * (AIMap.GetTileX(tile) - AIMap.GetTileX(center)) + size[0] - 1;
		local dy = 2 * (AIMap.GetTileY(tile) - AIMap.GetTileY(center)) + size[1] - 1;
		return dx * (AIMap.GetTileX(target)-AIMap.GetTileX(center)) +
			dy * (AIMap.GetTileY(target)-AIMap.GetTileY(center)) >= 0;
	}

	function NearestStationExit(site, target)
	{
		local exits = StationExits(site.tile, site.dir, this.platform_length);
		return AIMap.DistanceManhattan(exits[0][0], target) <= AIMap.DistanceManhattan(exits[1][0], target) ? exits[0] : exits[1];
	}

	function ExistingTownStationTiles(town)
	{
		local tiles = [];
		local pending = {};
		foreach (site in this.pending_stations) pending[AIStation.GetStationID(site.tile)] <- true;
		foreach (station, _ in AIStationList(AIStation.STATION_TRAIN)) {
			if (station in pending || AIStation.GetNearestTown(station) != town) continue;
			foreach (tile, _ in AITileList_StationType(station, AIStation.STATION_TRAIN)) tiles.append(tile);
		}
		return tiles;
	}

	function StationSpacingScore(site, existing, coverage)
	{
		local separation = 2 * coverage + 1;
		local nearest = separation;
		// Footprint distance: a long station should not appear farther away just
		// because its sign or anchor is at the other end of the platforms.
		foreach (tile in existing) {
			local distance = this.TownCentreDistance(site.tile, site.dir, tile);
			if (distance < nearest) nearest = distance;
		}
		return site.production * (0.25 + 0.75 * nearest / separation);
	}

	function StationFacingWeight(site, target)
	{
		local size=StationFootprint(site.dir, this.platform_length, StationPlatforms(site));
		local dx=Abs(2*(AIMap.GetTileX(target)-AIMap.GetTileX(site.tile))-size[0]+1);
		local dy=Abs(2*(AIMap.GetTileY(target)-AIMap.GetTileY(site.tile))-size[1]+1);
		local dominant=dx>dy ? dx : dy;
		if(dominant==0) return 1.0;
		local along=site.dir==AIRail.RAILTRACK_NE_SW ? dx : dy;
		// A perpendicular platform needs roughly four times the coverage to win.
		// Both axes remain equally attractive for a diagonal destination.
		return 0.25+0.75*along/dominant;
	}

	function FindStationSites(town_id, target, preferred_dir = null, source_site = null, central = true, coverage_bias = true)
	{
		local existing = this.ExistingTownStationTiles(town_id);
		local cache_key = town_id + ":" + target + ":" + preferred_dir + ":" + central + ":" +
			(source_site == null ? "none" : source_site.tile + ":" + source_site.dir);
		foreach (tile in existing) cache_key += ":" + tile;
		if (this.station_shortlists != null && cache_key in this.station_shortlists)
			return this.station_shortlists[cache_key];
		local sites = [];
		local cargo = PassengerCargo();
		local coverage = AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
		local center = AITown.GetLocation(town_id);
		local length = this.platform_length;
		local dirs = [AIRail.RAILTRACK_NE_SW, AIRail.RAILTRACK_NW_SE];

		for (local radius = 0; radius <= 28; radius++) {
            if(this.PlanningExpired()) return [];
			for (local x = -radius; x <= radius; x++) {
				for (local y = -radius; y <= radius; y += (Abs(x) == radius || radius == 0 ? 1 : 2 * radius)) {
					local tx = AIMap.GetTileX(center) + x;
					local ty = AIMap.GetTileY(center) + y;
					if (tx < 0 || ty < 0 || tx >= AIMap.GetMapSizeX() || ty >= AIMap.GetMapSizeY()) continue;
					local tile = AIMap.GetTileIndex(tx, ty);
					if (!AIMap.IsValidTile(tile)) continue;
					if (AITile.GetClosestTown(tile) != town_id) continue;

					foreach (dir in dirs) {
						if (central && !this.FacesDestination(tile, dir, center, target)) continue;

						local cross = dir == AIRail.RAILTRACK_NE_SW ?
							Abs(AIMap.GetTileY(tile) - AIMap.GetTileY(target)) :
							Abs(AIMap.GetTileX(tile) - AIMap.GetTileX(target));
						local center_distance = this.TownCentreDistance(tile, dir, center);
						// Coverage, spacing and facing direction rank together; centre distance breaks ties.
						local priority = 4 * (AIMap.GetMapSizeX() + AIMap.GetMapSizeY()) + 7;
						local score = center_distance * priority + cross * 3 + AIMap.DistanceManhattan(tile, target);

						if (preferred_dir != null && dir != preferred_dir) score += 6;
						local site = { tile = tile, dir = dir, platforms=this.station_platforms, score = score, center_distance = center_distance };
						local evaluation = this.StationEvaluation(tile, dir, cargo, coverage);
						local production = evaluation.production;
						if (production <= 0) continue;
						site.production <- production;
						site.spacing_score <- this.StationSpacingScore(site, existing, coverage);
						site.placement_score <- site.spacing_score*this.StationFacingWeight(site,target);
						if (sites.len() == 8 && (site.placement_score < sites[7].placement_score ||
							(site.placement_score == sites[7].placement_score && score >= sites[7].score))) continue;

						local ok_exit = false;
						foreach (exit in StationExits(tile, dir, length)) {
							if (AIMap.IsValidTile(exit[0]) && AITile.IsBuildable(exit[0])) {
								ok_exit = true;
								break;
							}
						}
						if (!ok_exit) continue;

						if (evaluation.buildable == null) evaluation.buildable = this.CanBuildStation(site);
						if (!evaluation.buildable || (central && !this.CanStationThroat(this.NearestStationExit(site, target), this.PlatformOffset(site)))) {
							local earth_key = central ? this.NearestStationExit(site,target)[0] : -1;
							if (!(earth_key in evaluation.earthworks)) evaluation.earthworks[earth_key] <- this.StationEarthwork(site,target,central);
							local earthwork = evaluation.earthworks[earth_key];
							if (earthwork == null) continue;
							site.earthwork <- earthwork;
						}
						sites.append(site);
						sites.sort(function(a, b) {
							if (a.placement_score != b.placement_score) return a.placement_score > b.placement_score ? -1 : 1;
							return a.score < b.score ? -1 : (a.score > b.score ? 1 : 0);
						});
						if (sites.len() > 8) sites.pop();
					}
				}
			}
			// Scan the full radius: a farther site may cover more passenger producers.
		}
		if (this.station_shortlists != null) this.station_shortlists[cache_key] <- sites;
		return sites;
	}

	function CanReshapeStation(site)
	{
		local test=AITestMode();
		if (AIRail.BuildRailStation(site.tile,site.dir,StationPlatforms(site),this.platform_length,AIStation.STATION_NEW)) return true;
		local error=AIError.GetLastError();
		return error==AIError.ERR_FLAT_LAND_REQUIRED || error==AIError.ERR_LAND_SLOPED_WRONG || error==AIError.ERR_SITE_UNSUITABLE;
	}

	function StationEarthwork(site, target, central = true)
	{
		if (!this.CanReshapeStation(site)) return null;
		local exits = central ? [this.NearestStationExit(site, target)] : StationExits(site.tile, site.dir, this.platform_length);
		local best = null;
		local best_cost = 100000;
		foreach (exit in exits) {
			local tiles = this.StationTiles(site);
			local step = exit[0] - exit[1];
			local offset = this.PlatformOffset(site);
			local valid = true;
			// Include both platforms, the X junction and the first tile beyond it.
			foreach (lane in [0, offset]) for (local i=0; i<4; i++) {
				local tile = exit[0] + lane + i*step;
				if (!AIMap.IsValidTile(tile) || AIMap.DistanceManhattan(exit[0]+lane,tile)!=i) valid=false;
				tiles.append(tile);
			}
			if (!valid) continue;
			local corners = {};
			local heights = [];
			local geometry = PairedTerrain();
			foreach (tile in tiles) {
				if (!AITile.IsBuildable(tile) || AITile.IsWaterTile(tile)) { valid=false; break; }
				foreach (corner in geometry.Corners(tile)) if (!(corner in corners)) {
					if (!AIMap.IsValidTile(corner)) { valid=false; break; }
					corners[corner] <- true;
					heights.append(AITile.GetCornerHeight(corner,AITile.CORNER_N));
				}
			}
			if (!valid) continue;
			heights.sort();
			local median = heights[heights.len()/2];
			foreach (height in [median, median+1, median-1, median+2, median-2]) {
				if (height<1 || Abs(height-heights[0])>3 || Abs(height-heights[heights.len()-1])>3) continue;
				local terrain = PairedTerrain(3,96,40000);
				local ok = true;
				foreach (corner,_ in corners) if (!terrain.SetHeight(corner,height)) { ok=false; break; }
				if (!ok || terrain.targets.len()==0) continue;
				local cost = 0;
				foreach (corner,h in terrain.targets) cost += Abs(h-AITile.GetCornerHeight(corner,AITile.CORNER_N));
				if (cost < best_cost) { best_cost=cost; best={ targets=clone terrain.targets, exit=exit }; }
			}
		}
		return best;
	}

    // Try the existing terrain first, then level the complete RIRO footprint
    // before any station/rail construction can prevent corner changes.
    function RiroSite(site, exit, reshape = true)
    {
        local candidate=clone site;
        candidate.exit <- exit;
        local off=this.PlatformOffset(site);
        local entrance={signals=[[exit[0],exit[1]],[exit[0]+off,exit[1]+off]]};
        local lane=this.LeftOutboundLane(exit);
        local ordinary=this.CanBuildStation(site) && this.CanStationThroat(exit,off);
        if(StationPlatforms(site)==1) {candidate.loop <- null;return ordinary ? candidate : null;}
        candidate.loop <- ordinary ? RollThroughStation().PlanFlexible(entrance,lane,this.platform_length) : null;
        if(candidate.loop!=null) {
            // A buildable platform can still need a cutting beside it. Carry
            // the loop's earthworks into station preparation, before platforms
            // and approaches prevent changes to their shared corners.
            if(candidate.loop.terrain!=null && candidate.loop.terrain.targets.len()>0)
                candidate.earthwork <- {targets=clone candidate.loop.terrain.targets,exit=exit,riro=true};
            return candidate;
        }
        if(!reshape) return ordinary ? candidate : null;
        if(!this.CanReshapeStation(site)) return ordinary ? candidate : null;
        local best=null,best_cost=100000;
        foreach(mirror in [false,true]) {
            local loop=RollThroughStation();
            loop.Plan(entrance,lane,this.platform_length,mirror,false);
            loop.mirrored=mirror;
            local tiles=this.StationTiles(site),step=exit[0]-exit[1];
            foreach(offset in [0,off]) for(local n=0;n<4;n++) tiles.append(exit[0]+offset+n*step);
            local overlaps=false;
            foreach(piece in loop.pieces) foreach(platform in this.StationTiles(site))
                if(piece[1]==platform) overlaps=true;
            if(overlaps) continue;
            foreach(piece in loop.pieces) tiles.append(piece[1]);
            tiles.append(loop.junction);
            local corners={},heights=[],valid=true,geometry=PairedTerrain();
            foreach(piece in loop.pieces) if(!AIMap.IsValidTile(piece[1]) ||
                AIMap.DistanceManhattan(piece[0],piece[1])!=1 ||
                AIMap.DistanceManhattan(piece[1],piece[2])!=1) valid=false;
            if(!valid) continue;
            foreach(tile in tiles) {
                if(!AIMap.IsValidTile(tile) || !AITile.IsBuildable(tile) || AITile.IsWaterTile(tile)) {valid=false;break;}
                foreach(corner in geometry.Corners(tile)) if(!(corner in corners)) {
                    if(!AIMap.IsValidTile(corner)) {valid=false;break;}
                    corners[corner] <- true;
                    heights.append(AITile.GetCornerHeight(corner,AITile.CORNER_N));
                }
            }
            if(!valid || heights.len()==0) continue;
            heights.sort();
            local median=heights[heights.len()/2];
            foreach(height in [median,median+1,median-1]) {
                local terrain=PairedTerrain(3,160,40000),ok=true,cost=0;
                foreach(corner,_ in corners) {
                    if(!terrain.SetHeight(corner,height)) {ok=false;break;}
                    terrain.desired[corner] <- height;
                }
                if(!ok || terrain.targets.len()==0) continue;
                foreach(corner,h in terrain.targets) cost+=Abs(h-AITile.GetCornerHeight(corner,AITile.CORNER_N));
                if(cost>=best_cost) continue;
                best_cost=cost;best=clone candidate;
                best.loop=loop;
                best.earthwork <- {targets=clone terrain.targets,exit=exit,riro=true};
            }
        }
        return best!=null ? best : (ordinary ? candidate : null);
    }

	function PrepareStation(site, pending)
	{
		if (!("earthwork" in site)) return this.CanBuildStation(site);
		if (!this.CanReshapeStation(site)) return false;
		local terrain = PairedTerrain(3,("dual" in site.earthwork) ? 320 : ("riro" in site.earthwork) ? 160 : 96,("dual" in site.earthwork) ? 60000 : 40000);
		// Revalidate the cached plan against current land and nearby infrastructure.
        foreach (corner,height in site.earthwork.targets) {
            if(height<1 || Abs(height-AITile.GetCornerHeight(corner,AITile.CORNER_N))>terrain.max_change ||
                (height!=AITile.GetCornerHeight(corner,AITile.CORNER_N) && !terrain.Safe(corner))) return false;
            terrain.targets[corner] <- height;
        }
        if(terrain.targets.len()>terrain.max_corners) return false;
		if (terrain.targets.len()>0) {
			// Persist originals before the first command can suspend the AI.
			local original = {};
			foreach (corner,_ in terrain.targets) original[corner] <- AITile.GetCornerHeight(corner,AITile.CORNER_N);
			pending.earthwork_original <- original;
			EnsureMoney(120000);
			if (!terrain.Apply()) return false;
			AILog.Info("Station earthworks completed: changed corners=" + terrain.targets.len());
		}
		return this.CanBuildStation(site) && this.CanStationThroat(site.earthwork.exit,this.PlatformOffset(site));
	}

    function IsPrebuiltTile(tile)
    {
        foreach(site in this.pending_stations) if("primary_recovery" in site && site.primary_recovery.upgrade!=null)
            foreach(piece in site.primary_recovery.upgrade.pieces) if(piece[1]==tile) return true;
        return false;
    }

	function CanStationThroat(exit, offset)
	{
		local step = exit[0] - exit[1];
		local test = AITestMode();
		foreach (lane in [0, offset]) {
			for (local i = 0; i < 3; i++) {
				local tile = exit[0] + lane + i * step;
				if (!AIMap.IsValidTile(tile) || !AIMap.IsValidTile(tile + step) ||
                    AIMap.DistanceManhattan(tile, tile + step) != 1) return false;
                local existing=this.IsPrebuiltTile(tile) && AIRail.AreTilesConnected(tile-step,tile,tile+step) &&
                    AITile.GetOwner(tile)==AICompany.ResolveCompanyID(AICompany.COMPANY_SELF);
                if(!existing && (!AITile.IsBuildable(tile) || !AIRail.BuildRail(tile-step,tile,tile+step))) return false;
			}
		}
		if(offset==0) return true;
		foreach (direction in [step, -step]) {
			local a = exit[0] + step;
			if (!AIRail.BuildRail(a - direction, a, a + offset) ||
				!AIRail.BuildRail(a, a + offset, a + offset + direction)) return false;
		}
		return true;
	}

	function CanBuildStation(site)
	{
        if("hub_existing" in site) return this.VerifyStation(site);
		local test = AITestMode();
		if (!AIRail.BuildRailStation(site.tile, site.dir, StationPlatforms(site), this.platform_length, AIStation.STATION_NEW)) return false;
		foreach (exit in StationExits(site.tile, site.dir, this.platform_length))
			if (this.CanStationThroat(exit, this.PlatformOffset(site))) return true;
		return false;
	}

	function BuildStation(site)
	{
        if("hub_existing" in site) return this.VerifyStation(site);
		EnsureMoney(50000);
		return AIRail.BuildRailStation(site.tile, site.dir, StationPlatforms(site), this.platform_length, AIStation.STATION_NEW);
	}

	function StationTiles(site)
	{
		local tiles = [];
		local size = StationFootprint(site.dir, this.platform_length, StationPlatforms(site));
		for (local x = 0; x < size[0]; x++)
			for (local y = 0; y < size[1]; y++) tiles.append(site.tile + AIMap.GetTileIndex(x, y));
		return tiles;
	}

	function PlatformOffset(site)
	{
		return StationPlatforms(site)==1 ? 0 : (site.dir == AIRail.RAILTRACK_NE_SW ? AIMap.GetMapSizeX() : 1);
	}

	function StationDistance(site_a, site_b)
	{
		// Exact Manhattan distance between the two rectangular footprints.
		local a = StationFootprint(site_a.dir, this.platform_length, StationPlatforms(site_a));
		local b = StationFootprint(site_b.dir, this.platform_length, StationPlatforms(site_b));
		local ax = AIMap.GetTileX(site_a.tile), ay = AIMap.GetTileY(site_a.tile);
		local bx = AIMap.GetTileX(site_b.tile), by = AIMap.GetTileY(site_b.tile);
		local dx = ax > bx ? ax - (bx+b[0]-1) : bx - (ax+a[0]-1);
		local dy = ay > by ? ay - (by+b[1]-1) : by - (ay+a[1]-1);
		return (dx > 0 ? dx : 0) + (dy > 0 ? dy : 0);
	}

	function PathTiles(path)
	{
		local tiles = [];
		while (path != null) { tiles.append(path.GetTile()); path = path.GetParent(); }
		return tiles;
	}

	function TrackReservations(path, start, goal)
	{
		local tiles = [goal[1]];
		foreach (tile in this.PathTiles(path)) tiles.append(tile);
		tiles.append(start[1]);
		local occupied = {};
		for (local i = 1; i < tiles.len()-1; i++) {
			if (IsStructureSpan(tiles[i-1], tiles[i]) || IsStructureSpan(tiles[i], tiles[i+1])) occupied[tiles[i]] <- 255;
			else occupied[tiles[i]] <- RailPiece(tiles[i-1], tiles[i], tiles[i+1]);
			if (IsStructureSpan(tiles[i], tiles[i+1])) {
				local distance = AIMap.DistanceManhattan(tiles[i], tiles[i+1]);
				local step = (tiles[i+1]-tiles[i])/distance;
				for (local j=1; j<distance; j++) occupied[tiles[i]+j*step] <- 255;
			}
		}
		return occupied;
	}

	function ClearSearchSigns()
	{
		local prefix = "[VT search] ";
		// The owned-sign list also recovers signs left by an interrupted search.
		foreach (id, _ in AISignList()) {
			local name = AISign.GetName(id);
			if ((name.len() >= prefix.len() && name.slice(0, prefix.len()) == prefix) ||
                (name.len()>=5 && name.slice(0,5)=="[VF] ") ||
                (name.len()>=6 && name.slice(0,6)=="RIRO: ")) AISign.RemoveSign(id);
		}
	}

	function SearchSign(tile, label)
	{
		// Keep legacy sign cleanup for saved games, but create no planning signs.
		return -1;
	}

    function SearchPath(start, goal, reserved, preferred = null, batches = 40, occupied = null)
    {
        return this.SearchPathMode(start,goal,reserved,preferred,batches,occupied);
    }

    function SearchBatchBudget(batches,fast=false)
    {
        local requested=((fast ? 2 : batches)*this.planning_percent+99)/100;
        return requested<this.search_batches_limit ? requested : this.search_batches_limit;
    }
    function SearchPathMode(start, goal, reserved, preferred = null, batches = 40, occupied = null)
	{
		this.search_failure = "middle";
		if (this.retained_prefixes == null) this.retained_prefixes = {};
		local prefix_key = start[0] + ":" + start[1];
		if (!AIMap.IsValidTile(start[0]) || !AIMap.IsValidTile(goal[0])) return null;
		foreach (tile in reserved) if (tile == start[0] || tile == goal[0]) return null;
		this.ClearSearchSigns();
		local track = preferred == null ? "Track 1" : "Track 2";
		local start_sign = this.SearchSign(start[0], track + " start");
		this.SearchSign(goal[0], track + " target");
		local current_sign = -1;
		// For the second track, try its narrow corridor first, then the full search.
		local checks = {};
		foreach (fast in (preferred == null ? [false] : [true, false])) {
			local stage = track + (fast ? " narrow corridor" : " full search");
			local started = AIController.GetTick();
			AILog.Info("Pathfinder: " + stage + ", start=" + start[0] + ", target=" + goal[0]);
			if (AISign.IsValidSign(start_sign)) AISign.SetName(start_sign, "[VT search] " + (preferred == null ? "T1 full" : (fast ? "T2 narrow" : "T2 full")));
			local pf = RailPathFinder();
            pf._entrance_guidance=this.entrance_guidance;
			pf._hierarchy=this.search_corridor;
            pf._start_run=this.start_run;
            pf._jump=false;
            pf._aystar=false;
            pf._reusable=this.reusable_rails;
            pf._junction_reuse=this.junction_reuse;
            pf._virtual_pieces=this.skip_rail_pieces;
			pf.InitializePath([start], [goal], reserved, preferred, occupied, fast, checks);
			if (this.reuse_prefixes && prefix_key in this.retained_prefixes) {
				if (pf.SeedPrefix(this.retained_prefixes[prefix_key])) {
					AILog.Info("Continuing from retained track prefix: " + this.retained_prefixes[prefix_key].len() + " tiles, " + stage);
				} else {
					if(this.committed_prefix) return null;
                    AILog.Info("Retained prefix no longer fits; replanning from the same origin station.");
					pf.InitializePath([start], [goal], reserved, preferred, occupied, fast, {});
				}
			}
			local path = false;
			local budget=this.SearchBatchBudget(batches,fast);
			for (local batch = 0; batch < budget && path == false; batch++) {
                if(this.PlanningExpired()) {this.failure_tile=pf._last_tile;return null;}
				path = pf.FindPath(200);
				// Sample progress every 1,000 examined states, rather than every tile.
				if (path == false && batch % 5 == 0) {
					if (AISign.IsValidSign(current_sign)) AISign.RemoveSign(current_sign);
					current_sign = this.SearchSign(pf._last_tile, (preferred == null ? "T1: " : "T2: ") + pf._expanded + " states");
					AILog.Info("Pathfinder progress: " + stage + ", states=" + pf._expanded +
						", queued=" + pf._open.Count() + ", rejected rail tests=" + pf._rail_failures +
						", elapsed ticks=" + (AIController.GetTick()-started));
				}
				// The main loop reviews the fleet every few ticks; while a long
				// planning call blocks that loop, catch depot visits once a day.
                if(IndustryClosureController!=null && AIEventController.IsEventWaiting()) IndustryClosureController.HandleEvents();
                if(IndustryClosureController!=null && AIDate.GetCurrentDate()!=this.closure_review_day) {
                    this.closure_review_day=AIDate.GetCurrentDate();
                    IndustryClosureController.ReviewIndustryClosures();
                }
				if (this.optimiser != null && path == false &&
					AIDate.GetCurrentDate() != this.optimiser_review_day) {
					this.optimiser_review_day = AIDate.GetCurrentDate();
					this.optimiser.Review();
				}
				if (path == false) AIController.Sleep(1);
			}
			if(this.jump_trial) AILog.Info("Jump planner: intermediate steps="+pf._jump_steps+", expanded states="+pf._expanded);
			local outcome = path == false ? "search budget reached" : (path == null ? "no path in search area" : "path found");
			AILog.Info("Pathfinder: " + stage + ": " + outcome + ", states=" + pf._expanded +
				", elapsed ticks=" + (AIController.GetTick()-started));
			if (path != null && path != false) {
                if(!this.committed_prefix && !this.PlanningExpired()) path=pf.StraightenPath(path);
				if (!(prefix_key in this.retained_prefixes)) {
					local prefix = pf.HalfPrefix();
					if (prefix != null) this.retained_prefixes[prefix_key] <- prefix;
				}
				this.ClearSearchSigns(); return path;
			}
			if (!fast) {
				this.search_failure = pf._nearest_goal <= 6 ? "target" :
					(path == null && pf._spread <= 6 ? "start" : "middle");
				if (this.search_failure == "target" && !(prefix_key in this.retained_prefixes)) {
					local prefix = pf.HalfPrefix();
					if (prefix != null) this.retained_prefixes[prefix_key] <- prefix;
				}
                this.failure_tile=pf._last_tile;
                this.failure_detail=path==false ? "Search budget reached" : "No path near "+this.search_failure;
				AILog.Info("Failure location: " + this.search_failure + ", nearest target=" + pf._nearest_goal +
					", search spread=" + pf._spread);
			}
		}
		this.ClearSearchSigns();
		return null;
	}

	function LeftOutboundLane(exit)
	{
		// With OpenTTD's isometric axes, +Y is left of +X travel and
		// +X is left of -Y travel. Platform 1 is offset along that axis.
		local step = exit[0] - exit[1];
		return step == 1 || step == -AIMap.GetMapSizeX() ? 1 : 0;
	}

	function CompleteRailPlan(path, path2, start, goal, start2, goal2, reserved, outbound)
	{
		local entrances = [];
		local entrance_a = this.StationEntrance(start, start2, path, path2);
		local entrance_b = this.StationEntrance(goal, goal2, path, path2);
		if (entrance_a == null || entrance_b == null) return null;
		entrances.append(entrance_a);
		entrances.append(entrance_b);
		local depot_reserved = clone reserved;
		local return_path = outbound == 0 ? path2 : path;
		local outbound_path = outbound == 0 ? path : path2;
		foreach (tile in this.PathTiles(outbound_path)) depot_reserved.append(tile);
		local depot_site = this.DepotSite(return_path, depot_reserved, entrance_a);
		if (depot_site == null) return null;
		local quality = this.PathQuality(path, start, goal);
		local quality2 = this.PathQuality(path2, start2, goal2);
		if (quality.bends == 999 || quality2.bends == 999) return null;
		quality.score += quality2.score;
		return { path = path, start = start, goal = goal, depot_site = depot_site, quality = quality,
				secondary = { path = path2, start = start2, goal = goal2 }, entrances = entrances, outbound = outbound, line_signals = [] };
	}

    function UndoFirstLine()
    {
        foreach(site in this.pending_stations) if("primary_recovery" in site) {
            if(!RestoreSingleUpgrade(site.primary_recovery)) return false;
            delete site.primary_recovery;
        }
        return true;
    }
    // One bounded cutting trial before rails make the land unmodifiable.
    function SmoothFirstPath(path,start,goal,reserved,batches)
    {
        if(!IntensiveEarthworksAllowed()) return path;
        if(this.PlanningExpired()) return path;
        local tiles=this.PathTiles(path);tiles.reverse();
        for(local k=1;k<tiles.len();k++) if(IsStructureSpan(tiles[k-1],tiles[k])) return path;
        local protected=clone reserved;
        foreach(exit in [start,goal]) for(local n=0;n<5;n++) protected.append(exit[0]+n*(exit[0]-exit[1]));
        local best=null,gain=0;
        for(local i=5;i<tiles.len()-7;i++) foreach(span in [4,8,12,16]) {
            local j=i+span;if(j>=tiles.len()-5) continue;
            local height=AITile.GetMaxHeight(tiles[i]);
            if(AITile.GetSlope(tiles[i])!=AITile.SLOPE_FLAT ||
                AITile.GetSlope(tiles[j])!=AITile.SLOPE_FLAT || AITile.GetMaxHeight(tiles[j])!=height) continue;
            local benefit=0;
            for(local k=i+1;k<j;k++) benefit+=Abs(AITile.GetMaxHeight(tiles[k])-height);
            if(benefit<=gain) continue;
            local terrain=PairedTerrain(4,160,60000);terrain.Protect(protected);
            local ok=true;
            for(local k=i;k<=j && ok;k++) foreach(corner in terrain.Corners(tiles[k])) {
                if(!terrain.SetHeight(corner,height)) {ok=false;break;}
                terrain.desired[corner] <- height;
            }
            if(ok && terrain.targets.len()>0) {best=terrain;gain=benefit;}
        }
        if(best==null || this.PlanningExpired()) return path;
        local before=this.PathQuality(path,start,goal).score;
        this.RememberRouteEarthwork(best);
        if(!best.Apply()) return path;
        this.retained_prefixes={};this.reuse_prefixes=false;
        local improved=this.SearchPath(start,goal,reserved,null,batches);
        if(improved!=null && this.PathQuality(improved,start,goal).score<before) {
            AILog.Info("First-line cutting retained: changed corners="+best.targets.len());
            return improved;
        }
        if(best.Restore()) return path;
        return improved!=null ? improved : path;
    }
    function BuildFirstLine(path,start,goal,keep_on_failure=false)
    {
        if(this.pending_stations.len()==0 || !this.UndoFirstLine()) return false;
        local recovery={upgrade={pieces=[],structures=[],removed=[],signals=[]}};
        this.pending_stations[0].primary_recovery <- recovery;
        this.build_journal=recovery.upgrade;
        local built=this.BuildPath({path=path,start=start,goal=goal});
        this.build_journal=null;
        if(!built) {if(!keep_on_failure) this.UndoFirstLine();return false;}
        AILog.Info("First track built; now planning the return track.");
        return true;
    }

    // Keep journalled source-side rail through the last completed structure. Never split a structure or
    // remove pre-existing infrastructure. Journals remain live during commands.
    function RetryFromMidpoint(path,start,goal,reserved,batches)
    {
        if(this.PlanningExpired() || this.pending_stations.len()==0 ||
            !("primary_recovery" in this.pending_stations[0])) return null;
        local journal=this.pending_stations[0].primary_recovery.upgrade;
        local tiles=this.PathTiles(path);tiles.reverse();
        local usable=0,last_structure=-1;
        for(local i=0;i<tiles.len()-1;i++) {
            local before=i==0 ? start[1] : tiles[i-1];
            if(IsStructureSpan(tiles[i],tiles[i+1])) {
                if(BuiltRailSpanKind(tiles[i],tiles[i+1])==null) break;
                last_structure=i+1;usable=i+2;i++;
                continue;
            }
            if(!AIRail.AreTilesConnected(before,tiles[i],tiles[i+1])) break;
            usable=i+1;
        }
        // Retain through the last completed structure, even beyond halfway.
        // Its far ramp remains built and enforces a straight departure.
        local end=last_structure>=0 ? last_structure+1 : tiles.len()/2;
        if(last_structure<0 && end>usable) end=usable;
        if(end<4 || end>=tiles.len()) return null;
        local prefix=tiles.slice(0,end),keep={};
        for(local i=0;i<(last_structure>=0 ? end : end-1);i++) keep[tiles[i]] <- true;
        for(local i=journal.pieces.len()-1;i>=0;i--) {
            local p=journal.pieces[i];
            if(p[1] in keep) continue;
            if(AIRail.AreTilesConnected(p[0],p[1],p[2]) && !AIRail.RemoveRail(p[0],p[1],p[2])) return null;
            journal.pieces.remove(i);
        }
        // Structures beyond the contiguous built prefix are removed whole;
        // retained spans stay in the original save/rollback journal.
        for(local i=journal.structures.len()-1;i>=0;i--) {
            local span=journal.structures[i];
            if(span[0] in keep && span[1] in keep) continue;
            local tail={upgrade={pieces=[],structures=[span],removed=[],signals=[]}};
            if(!RestoreSingleUpgrade(tail)) return null;
            journal.structures.remove(i);
        }
        local retry_reserved=clone reserved;
        // Choose the diversion only within the discarded tail, never the prefix.
        local diversion_index=end+(tiles.len()-end)/2;
        local diversion=tiles[diversion_index];
        if(AIMap.DistanceManhattan(diversion,goal[0])>3) retry_reserved.append(diversion);
        local old_prefixes=this.retained_prefixes,old_reuse=this.reuse_prefixes;
        local old_rails=this.reusable_rails,old_committed=this.committed_prefix;
        this.retained_prefixes={};this.retained_prefixes[start[0]+":"+start[1]] <- prefix;
        this.reuse_prefixes=true;this.committed_prefix=true;
        this.reusable_rails=old_rails==null ? {} : clone old_rails;
        foreach(tile,_ in keep) this.reusable_rails[tile] <- true;
        AILog.Info("Route retry: retaining "+keep.len()+" source-side track tiles; replanning from "+(last_structure>=0 ? "the last structure exit." : "the midpoint."));
        local replacement=this.SearchPath(start,goal,retry_reserved,null,batches);
        this.retained_prefixes=old_prefixes;this.reuse_prefixes=old_reuse;
        this.reusable_rails=old_rails;this.committed_prefix=old_committed;
        if(replacement==null) return null;
        this.build_journal=journal;
        local built=this.BuildPath({path=replacement,start=start,goal=goal});
        this.build_journal=null;
        return built ? replacement : null;
    }

    function BuildTrackPair(path,start,goal,start2,goal2,reserved,second_reserved,batches)
    {
        local built=this.BuildFirstLine(path,start,goal,true);
        local path2=built ? this.SearchPath(start2,goal2,second_reserved,this.PathTiles(path),batches,
            this.TrackReservations(path,start,goal)) : null;
        if(path2!=null) return {path=path,path2=path2};
        if(!this.PlanningExpired()) {
            local retry=this.RetryFromMidpoint(path,start,goal,reserved,batches);
            if(retry!=null) {
                path=retry;
                path2=this.SearchPath(start2,goal2,second_reserved,this.PathTiles(path),batches,
                    this.TrackReservations(path,start,goal));
                if(path2!=null) return {path=path,path2=path2};
            }
        }
        this.UndoFirstLine();
        return null;
    }

    function FindPathBetween(site_a, site_b, batches = 40)
    {
        this.search_corridor=null;
        return this.FindPathInArea(site_a,site_b,batches);
    }

    function FindPathInArea(site_a, site_b, batches = 40)
	{
        if(StationPlatforms(site_a)==1 || StationPlatforms(site_b)==1) return PlanPermanentSingleTrack(this,site_a,site_b,batches);
        if(this.single_first) return PlanSingleTrack(this,site_a,site_b,batches);
		this.route_failure = "middle";
		local failures = [];
		local length = this.platform_length;
		local starts = StationExits(site_a.tile, site_a.dir, length);
		local goals = StationExits(site_b.tile, site_b.dir, length);
		if ("exit" in site_a) starts=[site_a.exit];
		if ("exit" in site_b) goals=[site_b.exit];
		local exits = [];
		foreach (start in starts) foreach (goal in goals) {
			if (AIMap.IsValidTile(start[0]) && AIMap.IsValidTile(goal[0]))
				exits.append({ start = start, goal = goal, distance = AIMap.DistanceManhattan(start[0], goal[0]),
					facing = (StationExitFacesTarget(site_a,start,site_b.tile,length) ? 1:0) + (StationExitFacesTarget(site_b,goal,site_a.tile,length) ? 1:0) });
		}
		exits.sort(function(a, b) { if(a.facing!=b.facing) return a.facing>b.facing ? -1:1; return a.distance < b.distance ? -1 : (a.distance > b.distance ? 1 : 0); });
		foreach (pair in exits) {
            if(this.PlanningExpired()) return null;
			local start = pair.start;
			local goal = pair.goal;
			if (this.reuse_prefixes && !((start[0]+":"+start[1]) in this.retained_prefixes)) continue;
			local outbound = this.LeftOutboundLane(start);
			if (outbound == this.LeftOutboundLane(goal)) continue;
			if (!this.CanStationThroat(start, this.PlatformOffset(site_a))) { failures.append("start"); continue; }
			if (!this.CanStationThroat(goal, this.PlatformOffset(site_b))) { failures.append("target"); continue; }
			local reserved = [];
			foreach (site in [site_a, site_b]) foreach (tile in this.StationTiles(site)) reserved.append(tile);
			if(this.extra_reserved!=null) foreach(tile in this.extra_reserved) reserved.append(tile);

            local offset_a = this.PlatformOffset(site_a);
            local offset_b = this.PlatformOffset(site_b);
            local start2 = [start[0] + offset_a, start[1] + offset_a];
            local goal2 = [goal[0] + offset_b, goal[1] + offset_b];

			local path = this.SearchPath(start, goal, reserved, null, batches);
			if (path == null) {
				if (this.search_failure == "target") { this.route_failure = "target"; return null; }
				failures.append(this.search_failure); continue;
			}
            path=this.SmoothFirstPath(path,start,goal,reserved,batches);
            local pair_tracks=this.BuildTrackPair(path,start,goal,start2,goal2,reserved,reserved,batches);
            if(pair_tracks==null) {
                if(this.search_failure=="target") {this.route_failure="target";return null;}
                failures.append(this.search_failure);continue;
            }
            path=pair_tracks.path;
            local path2=pair_tracks.path2;
			failures.append("middle"); // Later junction/depot failures do not identify a bad endpoint.
			local completed=this.CompleteRailPlan(path,path2,start,goal,start2,goal2,reserved,outbound);
            if(completed!=null) {completed.first_built <- true;return completed;}
            if(!this.UndoFirstLine()) return null;
		}
		// Conflicting endpoint evidence is inconclusive; do not blame either station.
		if (failures.len() > 0) {
			this.route_failure = failures[0];
			foreach (failure in failures) if (failure != this.route_failure) { this.route_failure = "middle"; break; }
		}
		return null;
	}

	function RememberRouteEarthwork(terrain)
	{
		if (this.pending_stations.len()==0) return;
		local record=this.pending_stations[0];
		if (!("earthwork_original" in record)) record.earthwork_original <- {};
		foreach (corner,_ in terrain.targets) if (!(corner in record.earthwork_original))
			record.earthwork_original[corner] <- AITile.GetCornerHeight(corner,AITile.CORNER_N);
	}

	function SmoothRouteTerrain(found, site_a, site_b)
	{
		local tiles=this.PathTiles(found.path); tiles.reverse();
		local protected_tiles=this.extra_reserved==null ? [] : clone this.extra_reserved;
		foreach (site in [site_a,site_b]) foreach(tile in this.StationTiles(site)) protected_tiles.append(tile);
		foreach (entrance in found.entrances) foreach (signal in entrance.signals) {
			local step=signal[0]-signal[1];
			for(local i=0;i<5;i++) protected_tiles.append(signal[0]+i*step);
		}
		foreach(tile in [found.depot_site.depot,found.depot_site.front,found.depot_site.before,found.depot_site.after]) protected_tiles.append(tile);
		local handed=this.LeftOutboundLane(found.start)==1 ? 1 : -1;
		local w=AIMap.GetMapSizeX();
		local best=null, best_gain=0;
		local secondary={};
		foreach(tile in this.PathTiles(found.secondary.path)) secondary[tile] <- true;
		// Test short straight shortcuts and level cuttings, without terraforming
		// during A*. Only the most promising patch gets a construction/replan trial.
		for(local i=5;i<tiles.len()-7;i++) foreach(span in [2,3,4,6,8,10,12,16]) {
			local j=i+span;
			if(j>=tiles.len()-5) continue;
			local a=tiles[i], b=tiles[j];
			local distance=AIMap.DistanceManhattan(a,b);
			if(distance<2 || distance>16) continue;
			if(AITile.GetSlope(a)!=AITile.SLOPE_FLAT || AITile.GetSlope(b)!=AITile.SLOPE_FLAT || AITile.GetMaxHeight(a)!=AITile.GetMaxHeight(b)) continue;
			local gain=(span-distance)*100;
			for(local k=i+1;k<=j;k++) gain+=Abs(AITile.GetMaxHeight(tiles[k])-AITile.GetMaxHeight(tiles[k-1]))*55;
			local height=AITile.GetMaxHeight(a);
			local corridor=[];
			local axis=AIMap.GetTileX(a)==AIMap.GetTileX(b) || AIMap.GetTileY(a)==AIMap.GetTileY(b);
			// Diagonal rails alternate grid steps and may share opposite pieces
			// on one tile. Include that tile as well as the neighbouring lane.
			for(local k=0;k<=(axis ? distance : span);k++) {
				local tile=axis ? a+k*((b-a)/distance) : tiles[i+k];
				local step=axis ? (b-a)/distance : tiles[i+k]-tiles[i+k-1];
				local offset=(step==1 ? w : (step==-1 ? -w : (step==w ? -1 : 1)))*handed;
				foreach(t in [tile,tile+offset]) {
					corridor.append(t);
					if(AIMap.IsValidTile(t) && !(t in secondary)) {
						local hill=AITile.GetMaxHeight(t)-height;
						if(hill>0) gain+=hill*55;
					}
				}
			}
			if(gain<=best_gain) continue;
			local terrain=PairedTerrain(4,160,60000); terrain.Protect(protected_tiles);
			local ok=true;
			foreach(tile in corridor) {
				if(!AIMap.IsValidTile(tile) || !AITile.IsBuildable(tile) || AITile.IsWaterTile(tile)) { ok=false; break; }
				foreach(corner in terrain.Corners(tile)) if(!terrain.SetHeight(corner,height)) { ok=false; break; }
				if(!ok) break;
			}
			if(ok && terrain.targets.len()>0 && gain>best_gain) { best=terrain; best_gain=gain; }
		}
		if(best==null) return found;
		local before=found.quality.score;
		this.RememberRouteEarthwork(best);
		local applied=best.Apply();
		this.retained_prefixes={}; this.reuse_prefixes=false;
		local candidate=applied?this.FindPathBetween(site_a,site_b,40):null;
		this.retained_prefixes={}; this.reuse_prefixes=false;
		if(applied && candidate!=null && candidate.quality.score<before) {
			AILog.Info("Route smoothing retained: score="+before+" -> "+candidate.quality.score+", changed corners="+best.targets.len());
			return candidate;
		}
		// Undo the trial when possible. If the earthwork cannot be restored
		// (cash, town growth or slope rules blocked the undo), keep it: the
		// terrain is already smoothed for rail, so continue on it rather than
		// abandoning the connection.
		if(best.Restore()) return found;
		AILog.Info("Route smoothing: earthwork restore failed; keeping the terrain and the adjusted route.");
		return candidate!=null?candidate:found;
	}

	// Improve an already viable route, so earthworks have a useful baseline.
	function ImproveTerrain(found, site_a, site_b)
	{
        if(!IntensiveEarthworksAllowed()) return found;
        if("permanent_single" in found) return found;
        if("first_built" in found) return found; // Preserve the constructed first line.
        // Earthworks must not invalidate unbuilt bridge ramps or tunnel portals.
		foreach (line in [found, found.secondary]) {
            if("stubs" in line) continue;
			local tiles = this.PathTiles(line.path);
			for (local i=1; i<tiles.len(); i++) if (IsStructureSpan(tiles[i-1], tiles[i])) return found;
		}
        found=this.SmoothRouteTerrain(found,site_a,site_b);
        if(found!=null && "single" in found) return found;
		if(found==null) return null;
		// A smoother replacement may now use a bridge or tunnel; preserve it.
		foreach(line in [found,found.secondary]) {
			local tiles=this.PathTiles(line.path);
			for(local i=1;i<tiles.len();i++) if(IsStructureSpan(tiles[i-1],tiles[i])) return found;
		}
		local terrain = PairedTerrain(4,160,60000);
		local original_quality=this.PathQuality(found.secondary.path,found.secondary.start,found.secondary.goal).score;
		local primary = this.PathTiles(found.path);
		primary.reverse();
		local protected_tiles = clone primary;
		if(this.extra_reserved!=null) foreach(tile in this.extra_reserved) protected_tiles.append(tile);
		foreach (site in [site_a, site_b]) foreach (tile in this.StationTiles(site)) protected_tiles.append(tile);
		foreach (entrance in found.entrances) foreach (signal in entrance.signals) {
			local step = signal[0] - signal[1];
			for (local i = 0; i < 5; i++) protected_tiles.append(signal[0] + i * step);
		}
		foreach (tile in [found.depot_site.depot, found.depot_site.front,
			found.depot_site.before, found.depot_site.after]) protected_tiles.append(tile);
		terrain.Protect(protected_tiles);
		local handed = this.LeftOutboundLane(found.start) == 1 ? 1 : -1;
		local width = AIMap.GetMapSizeX();
		local pairs = [];
		for (local i = 5; i < primary.len() - 5; i++) {
			local step = primary[i] - primary[i-1];
			if (primary[i+1] - primary[i] != step) continue;
			local offset = (step == 1 ? width : (step == -1 ? -width : (step == width ? -1 : 1))) * handed;
			local tile = primary[i];
			local adjacent = tile + offset;
			if (!AIMap.IsValidTile(adjacent) || AIMap.DistanceManhattan(tile, adjacent) != 1) continue;
			pairs.append([tile, adjacent, step]);
			terrain.Match(tile, adjacent);
		}
		local before = terrain.Matched(pairs, this.PathTiles(found.secondary.path));
		this.RememberRouteEarthwork(terrain);
		if (!terrain.Apply()) {
			// Partial earthwork that could not be completed or restored: the
			// original route usually still builds on the adjusted terrain.
			if (terrain.restore_failed) AILog.Info("Route smoothing: earthwork could not be restored; continuing on the adjusted terrain.");
			return found;
		}
		local reserved = [];
		foreach (site in [site_a, site_b]) foreach (tile in this.StationTiles(site)) reserved.append(tile);
		if(this.extra_reserved!=null) foreach(tile in this.extra_reserved) reserved.append(tile);
		local path = this.SearchPath(found.secondary.start, found.secondary.goal, reserved, primary, 40, this.TrackReservations(found.path, found.start, found.goal));
		local new_quality=path==null ? null : this.PathQuality(path,found.secondary.start,found.secondary.goal);
		if (path != null && (new_quality.score<original_quality ||
			(terrain.Matched(pairs,this.PathTiles(path))>before && new_quality.score<=original_quality))) {
			local a = this.StationEntrance(found.start, found.secondary.start, found.path, path);
			local b = this.StationEntrance(found.goal, found.secondary.goal, found.path, path);
			local depot_reserved = this.extra_reserved==null ? [] : clone this.extra_reserved;
			foreach (site in [site_a, site_b]) foreach (tile in this.StationTiles(site)) depot_reserved.append(tile);
			foreach (tile in this.PathTiles(found.outbound == 0 ? found.path : path)) depot_reserved.append(tile);
			local depot = this.DepotSite(found.outbound == 0 ? path : found.path, depot_reserved, a);
			local quality = this.PathQuality(path, found.secondary.start, found.secondary.goal);
			if (a != null && b != null && depot != null && quality.bends != 999) {
				found.secondary.path = path;
				found.entrances = [a, b];
				found.depot_site = depot;
				found.quality = this.PathQuality(found.path, found.start, found.goal);
				found.quality.score += quality.score;
				AILog.Info("Paired earthworks retained: matching adjacent track tiles=" + before + " -> " +
					terrain.Matched(pairs, this.PathTiles(path)) + ", changed corners=" + terrain.targets.len());
				return found;
			}
		}
		// A failed optimisation should leave the original viable route usable;
		// if the earthwork cannot be undone, keep the terrain and the route.
		if (!terrain.Restore()) {
			AILog.Info("Route smoothing: earthwork restore failed; keeping the adjusted terrain.");
		}
		return found;
	}

	function PathQuality(path, start, goal)
	{
		local structures=PathStructures(path);
		local tiles = [goal[1]];
		while (path != null) { tiles.append(path.GetTile()); path = path.GetParent(); }
		tiles.append(start[1]);
		local pf = RailPathFinder();
		local heading = pf._Heading(tiles[0], tiles[1]);
		local bends = 0;
		local straight = 2;
		local penalty = 0;
		for (local i = 1; i < tiles.len(); i++) {
			local key=StructureKey(tiles[i-1],tiles[i]);
			penalty += pf.HeightCost(tiles[i-1],tiles[i],key in structures ? structures[key] : null);
			local next_heading = i == tiles.len() - 1 ? pf._Heading(tiles[i-1], tiles[i]) : pf._Heading(tiles[i-1], tiles[i+1]);
			local dot=heading[0] * next_heading[0] + heading[1] * next_heading[1];
            if (dot<0 || (dot==0 && pf._forbid_right_angles))
				return { bends = 999, tiles = tiles.len() - 2, score = 2147483647 };
			if (heading[0] != next_heading[0] || heading[1] != next_heading[1]) {
				bends++;
				penalty += pf.cost.turn + (2 - straight) * pf.cost.close_turn;
				straight = 0;
			} else if (straight < 2) {
				straight++;
			}
			heading = next_heading;
		}
		return { bends = bends, tiles = tiles.len() - 2, score = (tiles.len() - 2) * pf.cost.tile + penalty };
	}

	function BuildPath(found)
	{
        if("stubs" in found) return RailPiecesBuild(found.stubs);
		local structures=PathStructures(found.path);
		local tunnel_starts=PathTunnelStarts(found.path);
		// The finder returns goal -> start. Include station tiles as anchors so
		// BuildRail also constructs BOTH outside approach tiles.
		local tiles = [found.goal[1]];
		local path = found.path;
		while (path != null) {
			tiles.append(path.GetTile());
			path = path.GetParent();
		}
		tiles.append(found.start[1]);
		local end = tiles.len() - 1;
		if (tiles[1] - tiles[0] != tiles[2] - tiles[1] ||
			tiles[end-1] - tiles[end-2] != tiles[end] - tiles[end-1]) {
			AILog.Warning("Station approach is not straight; cancelling route.");
			return false;
		}
		AILog.Info("Straight station approaches verified at both ends.");
        // Build from the source so a failed construction leaves a usable prefix.
        tiles.reverse();
		for (local i=1; i<tiles.len()-2; i++) if (IsStructureSpan(tiles[i], tiles[i+1])) {
			if (structures[StructureKey(tiles[i],tiles[i+1])]=="tunnel") {
				local start=tunnel_starts[StructureKey(tiles[i],tiles[i+1])];
				local end=start==tiles[i] ? tiles[i+1] : tiles[i];
                if(AITunnel.IsTunnelTile(start) && AITunnel.GetOtherTunnelEnd(start)==end) continue;
				local cost=RailTunnelCost(start,end);
				if(cost<0 || !EnsureMoney(cost+80000)) return false;
                if(this.build_journal!=null) this.build_journal.structures.append([start,end,"tunnel"]);
                if(!AITunnel.BuildTunnel(AIVehicle.VT_RAIL,start)) return false;
				AILog.Info("Rail tunnel built: "+tiles[i]+" -> "+tiles[i+1]);
				continue;
			}
            if(AIBridge.IsBridgeTile(tiles[i]) && AIBridge.GetOtherBridgeEnd(tiles[i])==tiles[i+1]) continue;
			local bridge = SuitableRailBridge(tiles[i], tiles[i+1]);
			if (bridge == -1) return false;
			EnsureMoney(AIBridge.GetPrice(bridge, AIMap.DistanceManhattan(tiles[i],tiles[i+1])+1) + 20000);
			if(this.build_journal!=null) this.build_journal.structures.append([tiles[i],tiles[i+1],"bridge"]);
			if (!AIBridge.BuildBridge(AIVehicle.VT_RAIL, bridge, tiles[i], tiles[i+1])) return false;
			AILog.Info("Rail bridge built: " + tiles[i] + " -> " + tiles[i+1]);
		}
		for (local i = 1; i < tiles.len() - 1; i++) {
			if (IsStructureSpan(tiles[i-1], tiles[i]) || IsStructureSpan(tiles[i], tiles[i+1])) continue;
			EnsureMoney(20000);
            local triple=[tiles[i-1],tiles[i],tiles[i+1]];
            if(this.skip_rail_pieces!=null && RailTripleKey(triple) in this.skip_rail_pieces) continue;
            if(this.build_journal!=null && !AIRail.AreTilesConnected(triple[0],triple[1],triple[2])) this.build_journal.pieces.append(triple);
			if (!AIRail.AreTilesConnected(tiles[i - 1], tiles[i], tiles[i + 1]) &&
				!AIRail.BuildRail(tiles[i - 1], tiles[i], tiles[i + 1])) {
				AILog.Warning("Track construction failed at " + tiles[i] + ": " + AIError.GetLastErrorString());
				return false;
			}
		}
		// Never commission a route with a missing or incorrectly oriented piece.
		for (local i = 1; i < tiles.len() - 1; i++) {
			if (IsStructureSpan(tiles[i], tiles[i+1])) {
				if(structures[StructureKey(tiles[i],tiles[i+1])]=="tunnel") {
					if(!AITunnel.IsTunnelTile(tiles[i]) || AITunnel.GetOtherTunnelEnd(tiles[i])!=tiles[i+1]) return false;
				} else if (!AIBridge.IsBridgeTile(tiles[i]) || AIBridge.GetOtherBridgeEnd(tiles[i]) != tiles[i+1]) return false;
			} else if (!IsStructureSpan(tiles[i-1], tiles[i]) &&
                !(this.skip_rail_pieces!=null && RailTripleKey([tiles[i-1],tiles[i],tiles[i+1]]) in this.skip_rail_pieces) &&
				!AIRail.AreTilesConnected(tiles[i - 1], tiles[i], tiles[i + 1])) return false;
		}
		return true;
	}

	function CanBuildDepot(site)
	{
		local test = AITestMode();
		return AIRail.BuildRailDepot(site.depot, site.front) &&
			AIRail.BuildRail(site.before, site.front, site.depot) &&
			AIRail.BuildRail(site.after, site.front, site.depot) &&
			(("approach" in site && site.approach) || AIRail.BuildRail(site.depot, site.front, site.across));
	}

	function DepotSite(path, reserved, entrance)
    {
        if(entrance==null) return null;
        local tiles=this.PathTiles(path),occupied={},cross=entrance.crosses.len()>0 ? entrance.crosses[0] : {a=entrance.signals[0][0],b=entrance.signals[0][0]},anchor=-1;
        foreach(t in reserved) occupied[t] <- true;
        foreach(i,t in tiles) {occupied[t] <- true;if(t==cross.a || t==cross.b) anchor=i;}
        if(anchor<0) return null;
        local candidates=[],distances=[0];
        for(local k=1;k<tiles.len();k++) distances.append(distances[k-1]+AIMap.DistanceManhattan(tiles[k-1],tiles[k]));
        for(local i=4;i<tiles.len()-4;i++) {
            local d=tiles[i]-tiles[i-1];
            if(AIMap.DistanceManhattan(tiles[i],tiles[i-1])!=1 || tiles[i+1]-tiles[i]!=d ||
                tiles[i-1]-tiles[i-2]!=d || tiles[i+2]-tiles[i+1]!=d) continue;
            local distance=Abs(distances[i]-distances[anchor]);
            if(distance<5) continue;
            candidates.append({index=i,d=d,distance=distance,score=Abs(distance-15)+(distance>=10 && distance<=20?0:1000)});
        }
        candidates.sort(function(a,b){return a.score<b.score?-1:a.score>b.score?1:0;});
        foreach(c in candidates) {
            local i=c.index,front=tiles[i],side=Abs(c.d)==1?AIMap.GetMapSizeX():1;
            if(AITile.GetSlope(front)!=AITile.SLOPE_FLAT || AIRail.IsLevelCrossingTile(tiles[i-1]) || AIRail.IsLevelCrossingTile(tiles[i+1])) continue;
            foreach(offset in [side,-side]) {
                local depot=front+offset;
                if(!AIMap.IsValidTile(depot) || AIMap.DistanceManhattan(depot,front)!=1 || depot in occupied || !AITile.IsBuildable(depot)) continue;
                local site={depot=depot,front=front,before=tiles[i-1],after=tiles[i+1],across=tiles[i-1],
                    index=i,route_length=tiles.len(),approach=true,distance=c.distance};
                if(this.CanBuildDepot(site)) return site;
            }
        }
        return null;
    }

	function BuildDepot(site)
	{
		EnsureMoney(30000);
		if (!AIRail.BuildRailDepot(site.depot, site.front)) return AIMap.TILE_INVALID;
		local first = AIRail.BuildRail(site.before, site.front, site.depot);
		local second = first && AIRail.BuildRail(site.after, site.front, site.depot);
		// Preserve the extra crossing connection for legacy saved depot sites.
		local across = second && (("approach" in site && site.approach) || AIRail.BuildRail(site.depot, site.front, site.across));
		if (!across || !AIRail.AreTilesConnected(site.depot, site.front, site.across) ||
			!AIRail.AreTilesConnected(site.before, site.front, site.depot) ||
			!AIRail.AreTilesConnected(site.after, site.front, site.depot) ||
			!AIRail.AreTilesConnected(site.before, site.front, site.after)) {
			if (first) AIRail.RemoveRail(site.before, site.front, site.depot);
			if (second) AIRail.RemoveRail(site.after, site.front, site.depot);
			if (across && !("approach" in site && site.approach)) AIRail.RemoveRail(site.depot, site.front, site.across);
			AITile.DemolishTile(site.depot);
			return AIMap.TILE_INVALID;
		}
		AILog.Info("Approach depot verified: Route index="+site.index+", route length="+site.route_length);
		return site.depot;
	}

	function StationEntrance(exit, exit2, path, path2)
	{
		local first = {};
		local second = {};
		foreach (tile in this.PathTiles(path)) first[tile] <- true;
		foreach (tile in this.PathTiles(path2)) second[tile] <- true;
		local step = exit[0] - exit[1];
		for (local i = 0; i < 3; i++) {
			if (!(exit[0] + i * step in first) || !(exit2[0] + i * step in second)) return null;
		}
		local crosses = [];
		// Both opposite diagonals occupy the same pair of tiles, forming an X.
		foreach (direction in [step, -step]) {
			local a = exit[0] + step;
			local b = exit2[0] + step;
			local cross = { from = a - direction, a = a, b = b, to = b + direction, step = direction };
			if (!this.CanBuildCrossover(cross)) return null;
			crosses.append(cross);
		}
		return { crosses = crosses, signals = [[exit[0], exit[1]], [exit2[0], exit2[1]]] };
	}

	function BuildStationEntrances(found)
	{
        if("permanent_single" in found) return true;
		foreach (entrance in found.entrances) {
			foreach (cross in entrance.crosses) if (!this.BuildCrossover(cross)) {AILog.Warning("Station crossover failed at "+cross.a+": "+AIError.GetLastErrorString());return false;}
			if (entrance.crosses[0].a != entrance.crosses[1].a || entrance.crosses[0].b != entrance.crosses[1].b) return false;
			// Verify both diagonals still exist after adding the overlapping pieces.
			foreach (cross in entrance.crosses) {
				if (!AIRail.AreTilesConnected(cross.from, cross.a, cross.b) ||
					!AIRail.AreTilesConnected(cross.a, cross.b, cross.to)) return false;
			}
			foreach (signal in entrance.signals) {
                if("single" in found) continue;
				if (!AIRail.BuildSignal(signal[0], signal[1], AIRail.SIGNALTYPE_PBS) ||
					AIRail.GetSignalType(signal[0], signal[1]) != AIRail.SIGNALTYPE_PBS) {AILog.Warning("Station signal failed at "+signal[0]+": "+AIError.GetLastErrorString());return false;}
			}
		}
		AILog.Info("Overlapping X crossovers verified at both stations.");
		AILog.Info("permanent_single" in found ? "Single-platform line commissioned; fleet permanently limited to one train." : "single" in found ? "Single-track station entrances verified without signals." : "Station entrances verified: two crossovers and four platform path signals.");
		return true;
	}

	function BuildPreferredStations(found)
	{
        if("permanent_single" in found) {
            foreach(entrance in found.entrances) RiroFallbackSign(entrance.signals[0][1],"Single-platform fallback");
            return;
        }
		// Prefer through platforms where the complete loop fits. Each end can
		// independently retain the terminus without sacrificing town coverage.
		foreach(index, entrance in found.entrances) {
			local site=StationSiteFromEntrance(entrance,this.platform_length);
			local target=StationSiteFromEntrance(found.entrances[1-index],this.platform_length);
			if(!StationExitFacesTarget(site,entrance.signals[0],target.tile,this.platform_length)) {
				RiroFallbackSign(site.tile,"Faces away from target");
                AILog.Info("Station: retaining terminus; RIRO entrance would face away from destination.");
				continue;
			}
			local lane=index==0 ? found.outbound : 1-found.outbound;
			local planner=RollThroughStation();
            local loop=null,mirror=null;
            foreach(pending in this.pending_stations) if(pending.tile==site.tile) {
                if("dual" in pending) mirror=pending.dual.mirror;
                if("fixed_mirror" in pending) mirror=pending.fixed_mirror;
            }
            if(mirror!=null) {
                if(planner.Plan(entrance,lane,this.platform_length,mirror)) loop=planner;
            } else loop=planner.PlanFlexible(entrance,lane,this.platform_length);
			if(loop==null) { RiroFallbackSign(site.tile,planner.failure_reason);AILog.Info("RIRO checks: "+planner.failure_detail); AILog.Info("Station " + (index==0 ? "A" : "B") + ": retaining terminus; through loop did not fit on either side."); continue; }
			local recovery={pieces=[],signals=[],removed=[]};
			{
				// Journal only integer arrays, before construction can suspend.
				foreach(pending in this.pending_stations) if(pending.tile==site.tile)
					pending.loop_recovery <- recovery;
			}
			if(loop.Build(recovery,!("single" in found))) {
				entrance.roro <- loop;
                RiroFallbackSign(site.tile);
				AILog.Info("Station " + (index==0 ? "A" : "B") + ": roll-in roll-out loop built" + (loop.mirrored?" (mirrored)":"") + ".");
			} else {RiroFallbackSign(site.tile,loop.failure_reason);AILog.Info("RIRO build: "+loop.failure_detail);}
		}
	}

	function AddOneWaySignal(found, tiles, i)
	{
		local tile = tiles[i];
		if (AIRail.IsLevelCrossingTile(tile) || AIBridge.IsBridgeTile(tile) || AITunnel.IsTunnelTile(tile)) return false;
		local tracks = AIRail.GetRailTracks(tile);
		// Never put a waiting point on the station crossover or depot junction.
		if (tracks == 0 || ((tracks & (tracks - 1)) != 0 && !ParallelRailPieces(tracks))) return false;
		if (!(this.build_journal==null ? AIRail.BuildSignal(tile,tiles[i-1],AIRail.SIGNALTYPE_PBS_ONEWAY) : JournalSignal(this.build_journal,tile,tiles[i-1],AIRail.SIGNALTYPE_PBS_ONEWAY))) return false;
		found.line_signals.append([tile, tiles[i-1], tiles[i+1]]);
		return AIRail.GetSignalType(tile, tiles[i-1]) == AIRail.SIGNALTYPE_PBS_ONEWAY &&
			AIRail.GetSignalType(tile, tiles[i+1]) == AIRail.SIGNALTYPE_NONE;
	}

	function BuildLineSignals(found)
	{
        if("single" in found) return true;
		local lanes = [found, found.secondary];
		local spacing = this.platform_length + 1;
		local depot_signalled = false;
		for (local lane = 0; lane < 2; lane++) {
			local line = lanes[lane];
			local path = this.PathTiles(line.path);
			local outbound = lane == found.outbound;
			if (outbound) path.reverse();
			local tiles = [outbound ? line.start[1] : line.goal[1]];
			foreach (tile in path) tiles.append(tile);
			tiles.append(outbound ? line.goal[1] : line.start[1]);
			// Station anchor=0, platform approach=1, X crossover=2.
			// Put the outbound signal immediately after the X, at tile 3.
			local first = 3;
			local last = tiles.len() - 4;
			local required = {};
			required[first] <- true;
			required[last] <- true;
			if (!outbound) {
				local junction = null;
				foreach (index, tile in tiles) if (tile == found.depot_site.front) junction = index;
				// Approach depots need one-way signals on both sides. Older
				// crossover sites retain their existing station-side PBS.
                if(junction==null) return false;
                required[junction-1] <- true;
                if("approach" in found.depot_site && found.depot_site.approach) {
                    if(junction-1<first || junction+1>last) return false;
                    required[junction+1] <- true;
                } else if(AIRail.GetSignalType(tiles[junction+1],tiles[junction+2])!=AIRail.SIGNALTYPE_PBS) return false;
			}
			local previous = first;
			for (local i = first; i <= last; i++) {
				local mandatory = i in required;
				if (mandatory || (i - previous >= spacing && i < last - 1)) {
					if (this.AddOneWaySignal(found, tiles, i)) previous = i;
					else if (mandatory) return false;
				}
			}
			AILog.Info("Immediate post-crossover departure signal verified on left-hand track.");
			if (!outbound) depot_signalled = true;
		}
		if (!depot_signalled) return false;
		AILog.Info("Depot approaches verified: signals on both sides of the junction.");
		AILog.Info("Left-hand one-way running signals verified: count=" + found.line_signals.len() + ", spacing=" + spacing);
		return true;
	}

	function CanBuildCrossover(cross)
	{
		local test = AITestMode();
		return AIRail.BuildRail(cross.from, cross.a, cross.b) && AIRail.BuildRail(cross.a, cross.b, cross.to);
	}

	function BuildCrossover(cross)
	{
		EnsureMoney(20000);
		if (!AIRail.AreTilesConnected(cross.from, cross.a, cross.b) && !AIRail.BuildRail(cross.from, cross.a, cross.b)) return false;
		if (!AIRail.AreTilesConnected(cross.a, cross.b, cross.to) && !AIRail.BuildRail(cross.a, cross.b, cross.to)) return false;
		return AIRail.AreTilesConnected(cross.from, cross.a, cross.b) &&
			AIRail.AreTilesConnected(cross.a, cross.b, cross.to) &&
			AIRail.AreTilesConnected(cross.a - cross.step, cross.a, cross.a + cross.step) &&
			AIRail.AreTilesConnected(cross.b - cross.step, cross.b, cross.b + cross.step);
	}

	function VerifyStation(site)
	{
		local id = AIStation.GetStationID(site.tile);
		foreach (tile in this.StationTiles(site)) {
			if (!AIRail.IsRailStationTile(tile) || AIStation.GetStationID(tile) != id ||
				AIRail.GetRailStationDirection(tile) != site.dir) return false;
		}
		return true;
	}

	function RemoveStation(site)
	{
        if("hub_existing" in site) return;
		local size = StationFootprint(site.dir, this.platform_length, StationPlatforms(site));
		if (!AIRail.RemoveRailStationTileRectangle(site.tile, site.tile + AIMap.GetTileIndex(size[0]-1, size[1]-1), false))
			AILog.Warning("Could not remove unfinished station: " + AIError.GetLastErrorString());
	}

	function CleanupRoute(found, site_a, site_b)
	{
		if("depot_site" in found) {
			local depot=found.depot_site;
			foreach(other in [depot.before,depot.after,depot.across])
				if(AIRail.AreTilesConnected(depot.depot,depot.front,other)) AIRail.RemoveRail(depot.depot,depot.front,other);
		}
		foreach(entrance in found.entrances) if("roro" in entrance) entrance.roro.Restore();
		foreach (signal in found.line_signals) {
			if (AIRail.GetSignalType(signal[0], signal[1]) != AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(signal[0], signal[1]);
		}
		foreach (entrance in found.entrances) {
			foreach (signal in entrance.signals) {
				if (AIRail.GetSignalType(signal[0], signal[1]) != AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(signal[0], signal[1]);
			}
			foreach (cross in entrance.crosses) {
				if (AIRail.AreTilesConnected(cross.from, cross.a, cross.b)) AIRail.RemoveRail(cross.from, cross.a, cross.b);
				if (AIRail.AreTilesConnected(cross.a, cross.b, cross.to)) AIRail.RemoveRail(cross.a, cross.b, cross.to);
			}
		}
		foreach (line in [found, found.secondary]) {
            if("stubs" in line) {
                foreach(p in line.stubs) if(AIRail.AreTilesConnected(p[0],p[1],p[2])) AIRail.RemoveRail(p[0],p[1],p[2]);
                continue;
            }
			local tiles = [line.goal[1]];
			foreach (tile in this.PathTiles(line.path)) tiles.append(tile);
			tiles.append(line.start[1]);
			for (local i = 1; i < tiles.len() - 1; i++) {
				if (IsStructureSpan(tiles[i], tiles[i+1])) {
					if(AITunnel.IsTunnelTile(tiles[i]) && AITunnel.GetOtherTunnelEnd(tiles[i])==tiles[i+1] &&
						AITile.GetOwner(tiles[i])==AICompany.ResolveCompanyID(AICompany.COMPANY_SELF)) AITunnel.RemoveTunnel(tiles[i]);
					else if (AIBridge.IsBridgeTile(tiles[i]) && AIBridge.GetOtherBridgeEnd(tiles[i]) == tiles[i+1] &&
						AITile.GetOwner(tiles[i]) == AICompany.ResolveCompanyID(AICompany.COMPANY_SELF)) AIBridge.RemoveBridge(tiles[i]);
				} else if (!IsStructureSpan(tiles[i-1], tiles[i]) && AIRail.AreTilesConnected(tiles[i-1], tiles[i], tiles[i+1]))
					AIRail.RemoveRail(tiles[i-1], tiles[i], tiles[i+1]);
			}
		}
		this.RemoveStation(site_a);
		this.RemoveStation(site_b);
	}

	function ReleasePendingStations(keep = null)
	{
		local remaining = [];
		local failed = false;
		foreach (site in this.pending_stations) {
			local retain = false;
			if (keep != null) foreach (candidate in keep) if (site.tile == candidate.tile && site.dir == candidate.dir) retain = true;
			if (retain) { remaining.append(site); continue; }
			if("dual_access" in site) {
                DualPickupStatus(site.dual_access);
                if(!RestoreDualAccess(site.dual_access)) {remaining.append(site);failed=true;continue;}
            }
            if ("loop_recovery" in site) {
				local loop=RollThroughStation();
				loop.built=site.loop_recovery.pieces;
				loop.changed_signals=site.loop_recovery.signals;
				if("removed" in site.loop_recovery) loop.removed=site.loop_recovery.removed;
				if("terrain_original" in site.loop_recovery) loop.terrain_original=site.loop_recovery.terrain_original;
				if(!loop.Restore()) { remaining.append(site);failed=true;continue; }
			}
            if("primary_recovery" in site && !RestoreSingleUpgrade(site.primary_recovery)) {
                remaining.append(site);failed=true;continue;
            }
            if("hub_existing" in site) continue;
			local owned = false;
			foreach (tile in this.StationTiles(site)) if (AIRail.IsRailStationTile(tile) &&
				AITile.GetOwner(tile) == AICompany.ResolveCompanyID(AICompany.COMPANY_SELF)) owned = true;
			if (owned) this.RemoveStation(site);
			local remains = false;
			foreach (tile in this.StationTiles(site)) if (AIRail.IsRailStationTile(tile) &&
				AITile.GetOwner(tile) == AICompany.ResolveCompanyID(AICompany.COMPANY_SELF)) {
				remains = true; break;
			}
			if (!remains && "earthwork_original" in site) {
				local terrain = PairedTerrain();
				terrain.original = site.earthwork_original;
				if (!terrain.Restore()) remains = true;
			}
			if (remains) { remaining.append(site); failed=true; }
		}
		this.pending_stations = remaining;
		return !failed;
	}

    function BuildPlannedStations(a, b)
    {
        // Revalidate after planning: another company may now occupy a footprint.
        if(!this.CanBuildStation(a) || !this.CanBuildStation(b)) return false;
        foreach(site in [a,b]) if(!this.BuildStation(site)) return false;
        foreach(site in [a,b]) if("dual" in site) {
            local hub=site.dual,pickup=hub.pickup;
            if(!AIRail.BuildRailStation(pickup.tile,pickup.dir,2,this.platform_length,AIStation.GetStationID(site.tile))) return false;
            foreach(pending in this.pending_stations) if(pending.tile==pickup.tile) pending.dual_access <- hub;
            if(!BuildDualAccess(this,hub)) return false;
            DualPickupStatus(hub,"Waiting for route");
        }
        return this.VerifyStation(a) && this.VerifyStation(b);
    }

	function ReserveStations(a, b)
	{
        this.failure_detail="Station footprint unavailable";
		this.reservation_failure = null;
		if (!this.ReleasePendingStations([a, b])) return false;
		foreach (site in [a, b]) {
			local retained = false;
			foreach (pending in this.pending_stations) if (pending.tile == site.tile && pending.dir == site.dir) retained = true;
			if (retained && this.CanBuildStation(site)) continue;
            if("hub_existing" in site) {
                if(!this.VerifyStation(site)) return false;
                this.pending_stations.append(clone site);continue;
            }
			// Never register an existing station as our temporary construction.
			local size = StationFootprint(site.dir, this.platform_length, StationPlatforms(site));
			if (!AreaIsBuildable(site.tile,size[0],size[1])) { this.reservation_failure=site.tile+":"+site.dir; return false; }
			// Save the footprint and earthwork originals before construction can suspend.
			local pending = clone site;
			this.pending_stations.append(pending);
			if (!this.PrepareStation(site,pending)) {
				this.reservation_failure = site.tile+":"+site.dir;
				if (!this.ReleasePendingStations(site==b ? [a] : null)) this.reservation_failure=null;
				return false;
			}
		}
        foreach(site in [a,b]) if("dual" in site) {
            local pickup=site.dual.pickup;
            if(!this.CanBuildStation(pickup)) return false;
            this.pending_stations.append(clone pickup);
        }
        this.failure_detail="No feasible track layout";
		AILog.Info("Station footprints prepared for planning; construction deferred.");
		return true;
	}

    function ConnectTowns(town_a,town_b,competition_guard=null)
    {
        if(!RouteEndpointsAllowed(AITown.GetLocation(town_a),AITown.GetLocation(town_b))) return null;
        local key=this.ConnectionKey(town_a,town_b);
        if(this.ConnectionFailed(town_a,town_b)) return null;
        if(!this.ReleasePendingStations()) return null;
        RailTypeReview();
        this.BeginPlanning(key);
        local result=this.ConnectTownsWithinBudget(town_a,town_b,competition_guard);
        this.LogRouteFailure(AITown.GetLocation(town_a),AITown.GetName(town_b),result!=null);
        this.FinishConnection(key,result!=null);
        if(result==null) this.startup_failures++; else this.startup_failures=0;
        this.planning_deadline=0;
        return result;
    }

    function ConnectTownsWithinBudget(town_a, town_b, competition_guard = null)
	{
		if (!this.ReleasePendingStations()) return null;
		this.RecoverLiveConnections();
		if (this.ConnectionFailed(town_a, town_b) || this.ConnectionBuilt(town_a, town_b)) return null;
		local result = null;
		local no_paths = 0;
		foreach (reverse in [false, true]) {
			local source = reverse ? town_b : town_a;
			local target = reverse ? town_a : town_b;
			local guard = competition_guard;
			if (reverse && guard != null) guard = { controller=guard.controller, count_a=guard.count_b, count_b=guard.count_a };
			this.ClearSearchSigns();
			this.SearchSign(AITown.GetLocation(source), "Choosing station A");
			this.SearchSign(AITown.GetLocation(target), "Choosing station B");
			this.attempt_failure = "temporary";
			result = this.PlanReservedRoute(source, target, guard);
			this.retained_prefixes = null;
			this.reuse_prefixes = false;
			this.ClearSearchSigns();
			this.station_evaluations = null;
			this.station_shortlists = null;
			if (result != null) { this.pending_stations = []; return result; }
			if (!this.ReleasePendingStations()) return null;
			if(this.planning_timed_out) {
                foreach(town in [town_a,town_b]) this.retry_after[town] <- AIController.GetTick()+1500;
                return null;
            }
            if (this.attempt_failure == "cancelled") return null;
			if (this.attempt_failure == "no_path") no_paths++;
			if (!reverse) AILog.Info("Connection failed; swapping source and destination for one reverse attempt.");
		}
		if (no_paths == 2 && this.search_batches_limit>=40) {
			this.RememberFailure(town_a, town_b);
			foreach (town in [town_a, town_b]) if (town in this.retry_after) delete this.retry_after[town];
			AILog.Warning("No route found in either direction; remembering failed connection " + town_a + " <-> " + town_b + ".");
		}
		return null;
	}

	function PlanReservedRoute(town_a, town_b, competition_guard = null)
	{
		// Passenger and mail routes are always two-track; a coal connection
		// sharing this builder may have left single-first set.
		this.single_first = false;
		this.RecoverLiveConnections();
		if (this.ConnectionFailed(town_a, town_b) || this.ConnectionBuilt(town_a, town_b)) return null;
		local planning_started = AIController.GetTick();
		this.retained_prefixes = {};
		this.reuse_prefixes = false;
		local locked_origin = null;
		this.station_evaluations = {};
		this.station_shortlists = {};
		local searched = {};
		local rejected_sites = {};
		local reservation_failed = false;
        local missing_station=false;
		// Construction failures may be temporary; no-path failures are remembered below.
		foreach (town in [town_a, town_b]) {
			this.retry_after[town] <- AIController.GetTick() + 1500;
		}
		local found = null;
		local site_a = null;
		local site_b = null;
		// Try destination-facing sites at both towns first, preserving coverage ranking.
		// Other sides remain available in the fallback passes.
		foreach (pass in [2, 1, 0]) {
			local central = pass != 0;
			if (found != null) break;
			AILog.Info(central ? "Station search: destination-facing sides first." : "Station search: allowing other sides as fallback.");
			local fixed_target = null;
			local candidates = locked_origin != null ? [locked_origin] : this.FindStationSites(town_a, AITown.GetLocation(town_b), null, null, central, pass != 0);
			if (candidates.len() == 0) {this.failure_detail="No source station site";missing_station=true;continue;}
			for (local i = 0; found == null && i < candidates.len(); i++) {
				if (locked_origin == null && pass > 0 && AIController.GetTick() - planning_started > (central ? 2400 : 4000)) break;
				local candidate_a = candidates[i];
				if (locked_origin == null) this.retained_prefixes = {};
				local destinations = fixed_target != null ? [fixed_target] : this.FindStationSites(town_b, candidate_a.tile, candidate_a.dir, candidate_a, central, pass != 0);
				if(destinations.len()==0) {missing_station=true;this.failure_detail="No destination station site";}
				local destination_limit = locked_origin != null ? destinations.len() : 2;
				for (local j = 0; found == null && j < destination_limit && j < destinations.len(); j++) {
					if (locked_origin == null && pass > 0 && AIController.GetTick() - planning_started > (central ? 2400 : 4000)) break;
					if(this.PlanningExpired()) return null;
					local candidate_b = destinations[j];
					local budget = 40; // Fully test each proposed pair before relocating it.
					local key = candidate_a.tile + ":" + candidate_a.dir + ":" + candidate_b.tile + ":" + candidate_b.dir;
					// A larger fallback budget remains a genuinely new attempt.
					if (key in searched && searched[key] >= budget) continue;
					searched[key] <- budget;
					local a_key=candidate_a.tile+":"+candidate_a.dir;
					local b_key=candidate_b.tile+":"+candidate_b.dir;
					if (a_key in rejected_sites) break;
					if (b_key in rejected_sites) continue;
                    if(!this.TryStationPair(candidate_a,candidate_b)) {
                        if(this.PlanningExpired()) return null;
                        continue;
                    }
					if (!this.ReserveStations(candidate_a, candidate_b)) {
						reservation_failed=true;
						if (this.reservation_failure==null) return null;
						if (!this.ReleasePendingStations([candidate_a])) return null;
						rejected_sites[this.reservation_failure] <- true;
						if (this.reservation_failure==a_key) break;
						continue;
					}
					local route = this.FindPathBetween(candidate_a, candidate_b, budget);
					if(this.PlanningExpired()) return null;
					if (route == null && this.route_failure == "start" && locked_origin == null) {
						fixed_target = candidate_b;
						AILog.Info("Keeping target station; trying another origin near the start blockage.");
						break;
					}
					if (route == null && (this.route_failure == "target" || locked_origin != null)) {
						locked_origin = candidate_a;
						this.reuse_prefixes = this.retained_prefixes.len() > 0;
						fixed_target = null;
						if (destinations.len() == 1) {
							destinations = this.FindStationSites(town_b, candidate_a.tile, candidate_a.dir, candidate_a, central, pass != 0);
							j = -1;
						}
						destination_limit = destinations.len();
						AILog.Info("Origin locked; keeping the first half of the explored route and trying another target.");
					}
					if (route != null) {
						found = route;
						site_a = candidate_a;
						site_b = candidate_b;
					}
				}
				if (locked_origin != null) break;
			}
		}

		// Never retain planning snapshots across construction or another route attempt.
		this.station_evaluations = null;
		this.station_shortlists = null;
		if (found == null) {
            if(missing_station && this.station_platforms==2 && !this.PlanningExpired()) {
                AILog.Info("Station fallback: trying one platform and a permanent one-train line.");
                this.station_platforms=1;
                local fallback=this.PlanReservedRoute(town_a,town_b,competition_guard);
                this.station_platforms=2;
                return fallback;
            }
			this.attempt_failure = reservation_failed ? "temporary" : "no_path";
			return null;
		}
		if (!this.CanBuildStation(site_a) || !this.CanBuildStation(site_b)) return null;
		found = this.ImproveTerrain(found, site_a, site_b);
		if (found == null) return null;
		AILog.Info("Planning completed in " + (AIController.GetTick() - planning_started) + " AI ticks.");
		AILog.Info("Selected route: tiles=" + found.quality.tiles + ", bends=" + found.quality.bends);
		AILog.Info("Route distances: towns=" + AIMap.DistanceManhattan(AITown.GetLocation(town_a), AITown.GetLocation(town_b)) +
			", stations=" + this.StationDistance(site_a, site_b));
		AILog.Info("Station passenger production coverage: A=" + site_a.production + ", B=" + site_b.production);
		AILog.Info("Station distances from town centres: A=" + site_a.center_distance + ", B=" + site_b.center_distance);
		if (competition_guard != null &&
			(competition_guard.controller.CompetingStationCount(town_a, true) > competition_guard.count_a ||
			competition_guard.controller.CompetingStationCount(town_b, true) > competition_guard.count_b)) {
			this.attempt_failure = "cancelled";this.failure_detail="Rival station appeared";
			AILog.Info("A rival added a station during planning; choosing another route.");
			return null;
		}
		AILog.Info("Route planned; building stations, rail and a depot.");
		this.failure_detail="Station build failed";
        if (!this.BuildPlannedStations(site_a,site_b)) return null;
        this.failure_detail="Track build failed";

		if (!this.VerifyStation(site_a) || !this.VerifyStation(site_b) ||
			!this.BuildPath(found) || !this.BuildPath(found.secondary) ||
			!this.BuildStationEntrances(found)) {
			this.CleanupRoute(found, site_a, site_b);
			return null;
		}
		local depot = this.BuildDepot(found.depot_site);
		if (depot == AIMap.TILE_INVALID) {
			this.failure_detail="Depot build failed";
            AILog.Warning("Could not build a depot.");
			this.CleanupRoute(found, site_a, site_b);
			return null;
		}

		if (!this.BuildLineSignals(found)) {
			this.failure_detail="Signal build failed";
            AILog.Warning("Could not complete one-way signals; cancelling route.");
			AIRail.RemoveRail(found.depot_site.before, found.depot_site.front, depot);
			AIRail.RemoveRail(found.depot_site.after, found.depot_site.front, depot);
			AIRail.RemoveRail(depot, found.depot_site.front, found.depot_site.across);
			AITile.DemolishTile(depot);
			this.CleanupRoute(found, site_a, site_b);
			return null;
		}

		this.BuildPreferredStations(found);
		AILog.Info("permanent_single" in found ? "Single-platform line commissioned; fleet permanently limited to one train." : "single" in found ? "Single main line commissioned without signals; two-platform stations retained." : "Two platforms and two connected tracks verified; station crossovers provide depot access.");
		this.MarkConnection(town_a, town_b);

		return {
			station_a = site_a.tile,
			station_b = site_b.tile,
			depot = depot,
            single_route = SaveSingleRoute(this,found,site_a,site_b)
		};
	}
}
