IndustryClosureController <- null;

// Observe real departures and resize trains during their existing depot order.
// Route-building comparison switch: 0 pauses train optimisation; 1 enables it.
const TRAIN_OPTIMISATION_ENABLED = 1;

class ServiceOptimiser
{
	trains = null;
	buyer = null;
	// Stations where a train was recently observed queueing for a platform.
	blocked_stations = null;

	constructor(buyer, saved = null)
	{
		this.buyer = buyer;
		this.trains = {};
		if (saved != null) foreach (train, record in saved) {
			this.trains[train] <- clone record;
            if(!("single_route" in this.trains[train])) this.trains[train].single_route <- null;
			this.trains[train].last_station = AIStation.STATION_INVALID;
			this.trains[train].last_tile <- AIMap.TILE_INVALID;
			this.trains[train].stationary_since <- AIDate.GetCurrentDate();
			if (!("expand_after" in this.trains[train])) this.trains[train].expand_after <- 0;
			if (!("engine_check_after" in this.trains[train])) {
				this.trains[train].engine_check_after <- 0;
				this.trains[train].replacement <- -1;
				this.trains[train].engine_capacity <- 0;
			}
			if (!("dispatch_after" in this.trains[train])) this.trains[train].dispatch_after <- 0;
			if (!("fleet_after" in this.trains[train])) this.trains[train].fleet_after <- 0;
			if (!("profit_year" in this.trains[train])) {
				this.trains[train].profit_year <- AIDate.GetYear(AIDate.GetCurrentDate());
				this.trains[train].loss_years <- 0;
			}
			if (!("observed_day" in this.trains[train])) this.trains[train].observed_day <- 0;
		}
		this.blocked_stations = {};
	}

	function Save()
	{
		local saved = {};
		foreach (train, record in this.trains) saved[train] <- clone record;
		return saved;
	}

	function Register(train, route, platform_length)
	{
		this.trains[train] <- { cargo = this.buyer.cargo, depot = route.depot, station_a = AIStation.GetStationID(route.station_a),
			station_b = AIStation.GetStationID(route.station_b),
            source_industry=("source_industry" in route?route.source_industry:-1),
            target_industry=("target_industry" in route?route.target_industry:-1), single_route = "single_route" in route ? route.single_route : null, max_length = platform_length * 16,
			review_after = AIDate.GetCurrentDate() + 90, last_station = AIStation.STATION_INVALID,
			engine_check_after = 0, replacement = -1, engine_capacity = 0,
			last_tile = AIMap.TILE_INVALID, stationary_since = 0, expand_after = 0,
			phase = "observe", dispatch_after = 0, flags = 0, capacity_before = 0, fleet_after = 0,
			profit_year = AIDate.GetYear(AIDate.GetCurrentDate()), loss_years = 0, observed_day = 0 };
	}

    function InitTrip(record)
    {
        if(!("trip_days" in record)) record.trip_days <- 0;
        if(!("trip_departed" in record)) record.trip_departed <- -1;
        if(!("trip_destination" in record)) record.trip_destination <- false;
        if(!("trip_loading" in record)) record.trip_loading <- false;
        if(!("trip_observed" in record)) record.trip_observed <- -1;
    }
    function TripSample(record,today,station,running)
    {
        this.InitTrip(record);
        if(record.trip_observed==today) return;
        record.trip_observed=today;
        if(station==record.station_b && record.trip_departed>=0) record.trip_destination=true;
        if(station==record.station_a) record.trip_loading=true;
        else if(running && record.trip_loading) {
            if(record.trip_departed>=0 && record.trip_destination && today>record.trip_departed) {
                local days=today-record.trip_departed;
                record.trip_days=record.trip_days>0 ? (3*record.trip_days+days+2)/4 : days;
            }
            record.trip_departed=today;
            record.trip_destination=false;
            record.trip_loading=false;
        }
    }
    function TripDays(record)
    {
        return "trip_days" in record && record.trip_days>0 ? record.trip_days : 30;
    }
    // Sum actual same-cargo capacities, adjusted for each train's measured
    // cycle. Mail and other farm cargoes cannot carry this cargo's demand.
    function MonthlyCapacity(record,cargo)
    {
        local total=0;
        foreach(id,service in this.trains) if(this.SameRoute(service,record) &&
            this.BuyerFor(service).cargo==cargo && AIVehicle.IsValidVehicle(id))
            total+=AIVehicle.GetCapacity(id,cargo)*30/this.TripDays(service);
        return total;
    }
    function SameRoute(a,b)
    {
        return a.depot==b.depot && ((a.station_a==b.station_a && a.station_b==b.station_b) ||
            (a.station_a==b.station_b && a.station_b==b.station_a));
    }
    function BuyerFor(record)
    {
        return "cargo" in record && record.cargo!=this.buyer.cargo ? TrainBuyer(record.cargo) : this.buyer;
    }

    function ExpansionBuyer(record)
    {
        local current=this.BuyerFor(record);
        if(!AICargo.HasCargoClass(current.cargo,AICargo.CC_PASSENGERS)) return current;
        if(!AIStation.IsValidStation(record.station_a) || !AIStation.IsValidStation(record.station_b)) return current;
        local accepts_a=AICargoList_StationAccepting(record.station_a);
        local accepts_b=AICargoList_StationAccepting(record.station_b);
        foreach(cargo,_ in AICargoList()) {
            if(!AICargo.HasCargoClass(cargo,AICargo.CC_MAIL) ||
                !accepts_a.HasItem(cargo) || !accepts_b.HasItem(cargo)) continue;
            local served=false;
            foreach(id,service in this.trains)
                if(this.SameRoute(service,record) && AIVehicle.IsValidVehicle(id) &&
                    AICargo.HasCargoClass(this.BuyerFor(service).cargo,AICargo.CC_MAIL)) served=true;
            if(served) return current;
            local mail_buyer=TrainBuyer(cargo);
            if(mail_buyer.BestEngine()>=0 && mail_buyer.BestWagon()>=0) return mail_buyer;
        }
        return current;
    }

	// A passenger route whose two stations can both receive mail, with no
	// mail train on it yet (ExpansionBuyer returns the mail buyer only then),
	// and with mail actually waiting or being produced there.
	function MailTrainWanted(record)
	{
        if(record.single_route!=null && "permanent" in record.single_route && record.single_route.permanent) return false;
		local buyer=this.ExpansionBuyer(record);
		if(!AICargo.HasCargoClass(buyer.cargo,AICargo.CC_MAIL)) return false;
		if(!AIStation.IsValidStation(record.station_a) || !AIStation.IsValidStation(record.station_b)) return false;
		local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
		foreach(station in [record.station_a,record.station_b]) {
			if(AIStation.GetCargoWaiting(station,buyer.cargo)>0) return true;
			if(AITile.GetCargoProduction(AIStation.GetLocation(station),buyer.cargo,1,1,radius)>0) return true;
		}
		return false;
	}

    function PriorityCityMail(record)
    {
        if(!AICargo.HasCargoClass(this.BuyerFor(record).cargo,AICargo.CC_PASSENGERS)) return false;
        local priority=false;
        foreach(station in [record.station_a,record.station_b])
            if(AIStation.IsValidStation(station) && BusCityRailPriority(AITile.GetClosestTown(AIStation.GetLocation(station)))>0)
                priority=true;
        return priority && this.MailTrainWanted(record);
    }

	function RouteReady(record)
	{
		foreach (_train, service in this.trains) {
			if (!this.SameRoute(service,record)) continue;
			if (service.fleet_after > AIDate.GetCurrentDate() || service.phase == "pending") return false;
		}
		return true;
	}

	function FleetCount(record)
	{
		local count=0;
		foreach(train,service in this.trains) if(this.SameRoute(service,record) && AIVehicle.IsValidVehicle(train)) count++;
		return count;
	}

	// Monthly demand for the route: a freight source's output last month, or
	// the pickup station's catchment production for town passenger and mail
	// routes (towns have no industry record).
	function DemandEstimate(train, record, cargo = null)
	{
		cargo = cargo != null ? cargo : this.BuyerFor(record).cargo;
		if("source_industry" in record && AIIndustry.IsValidIndustry(record.source_industry)) {
			local demand=AIIndustry.GetLastMonthProduction(record.source_industry,cargo);
			// Another company's station at the source is assumed to take half
			// of the output, so only the remainder feeds fleet sizing. Town
			// routes are excluded: rival town stations do not intercept
			// production the way a rival mine station does.
			if(RivalIndustryStation(record.source_industry)) demand/=2;
			return demand;
		}
		if(!AIStation.IsValidStation(record.station_a)) return 0;
		local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
		return AITile.GetCargoProduction(AIStation.GetLocation(record.station_a),cargo,1,1,radius);
	}

	function WagonCapacity(record)
	{
		local wagon=this.BuyerFor(record).BestWagon();
		return wagon<0?0:AIEngine.GetCapacity(wagon);
	}

    // Convert the monthly throughput deficit into capacity to add to this
    // train. Backlog is targeted for clearance over the next month.
	function ExpansionShortfall(train, record)
	{
		local demand=this.DemandEstimate(train,record);
		if(demand<=0) return 0;
		local cargo=this.BuyerFor(record).cargo;
		local backlog=AIStation.IsValidStation(record.station_a)?AIStation.GetCargoWaiting(record.station_a,cargo):0;
		local covered=this.MonthlyCapacity(record,cargo);
		local shortfall=demand+backlog-covered;
		return shortfall>0?(shortfall*this.TripDays(record)+29)/30:0;
	}

	// True when production has fallen well below what the fleet provides:
	// after shedding one carriage the route must still cover demand and any
	// waiting cargo with a quarter headroom, so month-to-month production
	// noise cannot cause removal and re-adding to oscillate.
	function ReductionCandidate(train, record)
	{
		local demand=this.DemandEstimate(train,record);
		if(demand<=0) return false; // A dead route is the retirement path's job.
		local cargo=this.BuyerFor(record).cargo;
		local wagon=this.WagonCapacity(record);
		if(wagon<=0) return false;
		if(AIVehicle.GetNumWagons(train)<=4) return false; // Keep the standard three-wagon minimum.
		local backlog=AIStation.IsValidStation(record.station_a)?AIStation.GetCargoWaiting(record.station_a,cargo):0;
		local covered=this.MonthlyCapacity(record,cargo);
		return covered-(wagon*30+this.TripDays(record)-1)/this.TripDays(record)>=(demand+backlog)*5/4;
	}

	function ObserveMovement(train, record)
	{
		local tile=AIVehicle.GetLocation(train);
		if(AIVehicle.GetState(train)!=AIVehicle.VS_RUNNING || tile!=record.last_tile)
			record.stationary_since=AIDate.GetCurrentDate();
		record.last_tile=tile;
	}

	function CanExpandFleet(train, record)
	{
        if(record.single_route!=null && "permanent" in record.single_route && record.single_route.permanent) return false;
		// Goods lines keep their initial train; capacity may grow via wagons only.
		if (AICargo.GetCargoLabel(this.BuyerFor(record).cargo) == "GOOD") return false;
		local count=this.FleetCount(record);
        if(count>=4) return false;
		local today=AIDate.GetCurrentDate();
        if("network" in record && record.network) foreach(id,service in this.trains)
            if(id!=train && "network" in service && service.network && AIVehicle.IsValidVehicle(id) &&
                AIVehicle.GetState(id)==AIVehicle.VS_RUNNING && today-service.stationary_since>=7) return false;
		foreach(id,service in this.trains) if(this.SameRoute(service,record) && AIVehicle.IsValidVehicle(id)) {
			if(service.expand_after>today || service.phase=="dispatch") return false;
			// Exclude loading and depot stops; a stationary running train is
			// evidence of a blocked line or station approach, not unmet demand.
			if(id!=train && AIVehicle.GetState(id)==AIVehicle.VS_RUNNING && today-service.stationary_since>=7) return false;
		}
		if(count<=1) return true; // Keep the first additional train responsive.
		local required=AIVehicle.GetCapacity(train,this.BuyerFor(record).cargo)*count;
		// A source that shrank since the route opened must prove a larger
		// backlog before the fleet grows; a grown source may expand sooner.
		if("production_level" in record && "production_baseline" in record && record.production_baseline>0) {
			if(record.production_level<record.production_baseline) required*=2;
			else if(record.production_level>record.production_baseline) required=(required+1)/2;
		}
		foreach(station in [record.station_a,record.station_b])
			if(AIStation.IsValidStation(station) && AIStation.GetCargoWaiting(station,this.BuyerFor(record).cargo)>=required) return true;
		return false;
	}

	function Queue(train, record, engine = false)
	{
		if (AIOrder.GetOrderCount(train) != 3 || !AIOrder.IsGotoDepotOrder(train, 2) ||
			AIOrder.GetOrderDestination(train, 2) != record.depot) return false;
		local flags = AIOrder.GetOrderFlags(train, 2);
        record.flags = flags & ~AIOrder.OF_STOP_IN_DEPOT;
        record.capacity_before = AIVehicle.GetCapacity(train, this.BuyerFor(record).cargo);
        // Capacity work catches a normal visit; engine work arms a depot stop
        // below so a busy planner cannot repeatedly miss the replacement.
        record.phase = engine ? "engine" : "pending";
		if (engine && TrainNeedsRenewal(train)) AILog.Info("Optimiser: train " + train + " reached its renewal age; replacement queued for its next depot visit.");
		else if (engine) AILog.Info("Optimiser: train " + train + " at least five years old with reliability below 66%; newer, more powerful engine queued for next service.");
		else AILog.Info("Optimiser: train " + train + " departed full with cargo waiting; capacity upgrade queued for its next depot visit.");
		// Queued work needs live observations; clear the daily sample marker.
		record.observed_day = 0;
		return true;
	}

	function UpdateProfitHistory(record, year, profit, age)
	{
		if (year <= record.profit_year) return;
		// Missing years cannot establish a consecutive streak. Ignore partial
		// first-year results; profit and break-even years reset the streak.
		if (year != record.profit_year + 1) record.loss_years = 0;
		if (age >= 366 && profit < 0) record.loss_years++;
		else record.loss_years = 0;
		record.profit_year = year;
	}

	function ReviewProfit(train, record, year)
	{
		if (year > record.profit_year)
			this.UpdateProfitHistory(record, year, AIVehicle.GetProfitLastYear(train), AIVehicle.GetAge(train));
		return AIVehicle.GetAge(train) > 5 * 365 && record.loss_years >= 3 && AIVehicle.GetProfitThisYear(train) <= 0;
	}

	// Used when the route's reason to exist disappears (a closed industry):
	// retirement proceeds through the normal depot-return path.
	function ForceSale(train)
	{
		if (!(train in this.trains)) return false;
		local record = this.trains[train];
        if("industry_closed" in record && record.industry_closed) return true;
		record.industry_closed <- true;
        if(ActiveRailUpgrade!=null && ActiveRailUpgrade.Holds(train)) {
            foreach(entry in ActiveRailUpgrade.state.job.migration.trains)
                if((entry.old==train || entry.fresh==train) && "record" in entry) entry.record.industry_closed <- true;
            return true;
        }
		record.phase = "sell_route";
		AILog.Info("Optimiser: train " + train + " serves a closed industry; returning to depot for sale.");
        if(AIVehicle.IsValidVehicle(train) && !AIVehicle.IsStoppedInDepot(train) && record.replacement<0 &&
            (record.single_route==null || record.single_route.upgrade==null)) this.Retire(train,record);
		return true;
	}

    function ReviewClosures()
    {
        local removed=[],replacements=[];
        foreach(train,record in this.trains) {
            if(!("industry_closed" in record) || !record.industry_closed) continue;
            if(ActiveRailUpgrade!=null && ActiveRailUpgrade.Holds(train)) continue;
            if(!AIVehicle.IsValidVehicle(train)) {
                if(record.replacement>=0 && AIVehicle.IsValidVehicle(record.replacement)) {
                    local successor=clone record;successor.replacement=-1;successor.phase="sell_route";
                    replacements.append([record.replacement,successor]);
                }
                removed.append(train);continue;
            }
            // Finish any journaled track restoration before removing its train.
            if(record.single_route!=null && record.single_route.upgrade!=null && !RestoreSingleUpgrade(record.single_route)) continue;
            if(record.replacement>=0 && AIVehicle.IsValidVehicle(record.replacement)) {
                if(!AIVehicle.IsStoppedInDepot(record.replacement) || !AIVehicle.SellVehicle(record.replacement)) continue;
                record.replacement=-1;
            }
            if(record.phase!="sell") record.phase="sell_route";
            if(this.Retire(train,record)) removed.append(train);
        }
        foreach(train in removed) delete this.trains[train];
        foreach(entry in replacements) this.trains[entry[0]] <- entry[1];
    }

	function Retire(train, record)
	{
        if("industry_closed" in record && record.industry_closed && AIVehicle.IsInDepot(train) && !AIVehicle.IsStoppedInDepot(train))
            AIVehicle.StartStopVehicle(train);
		if (AIVehicle.IsStoppedInDepot(train)) {
            // Queue before the command can suspend/save. A still-live train
            // protects the network if selling fails or a save interrupts it.
            if(RetiredRailways!=null) RetiredRailways.Queue(record);
			if (!AIVehicle.SellVehicle(train)) return false;
			AILog.Info("Optimiser: sold retired train " + train + " and its carriages in the depot.");
			return true;
		}
		if (record.phase == "sell_route") {
            for(local order=0;order<AIOrder.GetOrderCount(train);order++) {
                if(!AIOrder.IsGotoDepotOrder(train,order) || AIOrder.GetOrderDestination(train,order)!=record.depot) continue;
                local flags=AIOrder.GetOrderFlags(train,order);
                local wanted=(flags & ~AIOrder.OF_SERVICE_IF_NEEDED) | AIOrder.OF_STOP_IN_DEPOT;
                if((flags==wanted || AIOrder.SetOrderFlags(train,order,wanted)) &&
                    (AIOrder.ResolveOrderPosition(train,AIOrder.ORDER_CURRENT)==order || AIOrder.SkipToOrder(train,order))) {
                    record.phase="sell";
                    if(AIVehicle.GetState(train)==AIVehicle.VS_STOPPED) AIVehicle.StartStopVehicle(train);
                }
                return false;
            }
            if(AIVehicle.SendVehicleToDepot(train)) record.phase="sell";
		}
		return false;
	}

	function Review()
	{
        this.ReviewClosures();
		// One date pair per review: the per-train loop must not issue its own
		// date queries.
		local today = AIDate.GetCurrentDate();
		local year = AIDate.GetYear(today);
		local removed = [];
		local additions = [];
		this.blocked_stations = {};
		foreach (train, record in this.trains) {
            if(ActiveRailUpgrade!=null && ActiveRailUpgrade.Holds(train)) continue;
            if("industry_closed" in record && record.industry_closed) continue;
			// Dispatch is also used by initial farm trains; keep it and completion
			// of an already finished depot operation running during the experiment.
			// All other optimisation (including saved queued work) is paused.
			if (!TRAIN_OPTIMISATION_ENABLED && record.phase != "dispatch" && record.phase != "resume") continue;
			// Steady-state trains run their full check once per game day; the
			// frequent loop then only walks tables. Depot visits and loading
			// stops last for days, so a daily sample observes each one.
			if (record.phase == "observe" && "observed_day" in record && record.observed_day == today) continue;
			if (!AIVehicle.IsValidVehicle(train)) {
				// A save may occur just after selling the old engine.
				if (record.replacement >= 0 && AIVehicle.IsValidVehicle(record.replacement)) {
					local service = clone record;
					service.phase = "resume";
					service.replacement = -1;
					additions.append([record.replacement, service]);
				}
				removed.append(train); continue;
			}
			if(record.single_route!=null && record.single_route.upgrade!=null) {
                if(!AIVehicle.IsStoppedInDepot(train) || !RestoreSingleUpgrade(record.single_route)) continue;
            }
			if (record.phase == "observe") record.observed_day = today;
            this.ObserveMovement(train,record);
            // A train holding still for a week on a station throat is queued
            // for a platform; remember the station so the builder can grow it.
            if(today-record.stationary_since>=7 && !AIVehicle.IsStoppedInDepot(train)) {
                local location=AIVehicle.GetLocation(train),platform_length=record.max_length/16;
                foreach(station in [record.station_a,record.station_b]) {
                    if(!AIStation.IsValidStation(station)) continue;
                    local anchor=AIStation.GetLocation(station);
                    if(!(anchor in this.blocked_stations) &&
                        IsStationApproachTile(location,anchor,platform_length))
                        this.blocked_stations[anchor] <- location;
                }
            }
            this.InitTrip(record);
            if(record.trip_observed!=today) {
                local state=AIVehicle.GetState(train);
                local station=state==AIVehicle.VS_AT_STATION ? AIStation.GetStationID(AIVehicle.GetLocation(train)) : AIStation.STATION_INVALID;
                this.TripSample(record,today,station,state==AIVehicle.VS_RUNNING);
            }
			if (record.phase == "dispatch") {
				if (today < record.dispatch_after) continue;
				if (!AIVehicle.IsStoppedInDepot(train) || AIVehicle.StartStopVehicle(train)) {
					record.phase = "observe";
					record.observed_day = 0;
					record.review_after = today + 90;
					AILog.Info("Optimiser: delayed train " + train + " released from depot.");
				}
				continue;
			}
			if (!TRAIN_OPTIMISATION_ENABLED && record.phase == "resume") {
				if (!AIVehicle.IsStoppedInDepot(train) ||
					(AIOrder.SetOrderFlags(train, 2, record.flags & ~AIOrder.OF_STOP_IN_DEPOT) && AIVehicle.StartStopVehicle(train))) {
					record.phase = "observe";
					record.observed_day = 0;
				}
				continue;
			}
			if (record.phase != "sell" && record.phase != "sell_route" && record.replacement < 0 && this.ReviewProfit(train, record, year)) {
				record.phase = "sell_route";
				AILog.Info("Optimiser: train " + train + " is over five years old with " + record.loss_years +
					" consecutive losing years; returning to depot for sale.");
			}
			if (record.phase == "sell" || record.phase == "sell_route") {
				if (this.Retire(train, record)) removed.append(train);
				continue;
			}
            if ((record.phase=="observe" || record.phase=="pending") && TrainNeedsRenewal(train)) {
                if(record.phase=="pending") record.phase="engine";
                else this.Queue(train,record,true);
            }
			if ((record.phase == "observe" || record.phase == "pending") && AIVehicle.GetAge(train) >= 5 * 365 &&
				AIVehicle.GetReliability(train) < 66 &&
				today >= record.engine_check_after) {
				record.engine_check_after = AIDate.GetCurrentDate() + 30;
				if (this.BuyerFor(record).NewerPowerfulEngine(train, record.depot) >= 0) {
					if (record.phase == "pending") record.phase = "engine";
					else this.Queue(train, record, true);
				}
			}
			if (record.phase != "observe") {
				// Recover if a save occurred between restarting and recording completion.
				if (record.phase == "resume" && !AIVehicle.IsStoppedInDepot(train)) {
					record.phase = "observe";
					record.observed_day = 0;
					record.review_after = today + 30;
					record.last_station = AIStation.STATION_INVALID;
					continue;
				}
                if(record.phase=="pending" || record.phase=="engine") {
                    record.flags = record.flags & ~AIOrder.OF_STOP_IN_DEPOT;
                    // Engine work must survive missed observations during construction.
                    // Capacity-only work remains opportunistic and does not hold trains.
                    local depot_flags=record.phase=="engine" ? record.flags|AIOrder.OF_STOP_IN_DEPOT : record.flags;
                    if(AIOrder.GetOrderCount(train)==3 && AIOrder.IsGotoDepotOrder(train,2) &&
                        AIOrder.GetOrderFlags(train,2)!=depot_flags)
                        AIOrder.SetOrderFlags(train,2,depot_flags);
                    if(AIVehicle.IsInDepot(train) && AIVehicle.GetLocation(train)==record.depot &&
                        !AIVehicle.IsStoppedInDepot(train)) AIVehicle.StartStopVehicle(train);
                }
				if (AIVehicle.IsStoppedInDepot(train) && AIVehicle.GetLocation(train) == record.depot) {
					if (record.phase == "engine") {
						local replacement = this.BuyerFor(record).ReplaceEngine(train, record);
						if (replacement >= 0) {
							local service = clone record;
							service.phase = "resume";
							service.replacement = -1;
							service.loss_years = 0;
							service.profit_year = AIDate.GetYear(AIDate.GetCurrentDate());
							service.engine_check_after = AIDate.GetCurrentDate() + 30;
							additions.append([replacement, service]);
							removed.append(train);
							continue;
						}
						if (record.replacement >= 0) continue;
						record.phase = "resume";
					}
					if (record.phase == "pending") {
						if (record.fleet_after <= today && AIVehicle.GetCapacity(train, this.BuyerFor(record).cargo) <= record.capacity_before) {
							// Add every carriage the computed shortfall needs in
							// one visit; a second train is queued when the
							// platform is exhausted but demand remains.
							local shortfall=this.ExpansionShortfall(train,record);
							local wagon=this.WagonCapacity(record);
							local wanted=(shortfall>0 && wagon>0)?(shortfall+wagon-1)/wagon:0;
							local added=0;
							local platform_full=false;
							while(added<wanted) {
								local result=this.BuyerFor(record).AddCargoCarriage(train, record.depot, record.max_length);
								if(result==true) { added++; continue; }
								platform_full=result==-1;
								break;
							}
							local result=platform_full?-1:0;
							local mail_wanted=this.MailTrainWanted(record);
							if (result == 0 && this.ReductionCandidate(train, record)) {
								// Production has dropped below the fleet's capacity:
								// shed one rearmost carriage per depot visit until
								// capacity matches demand again.
								local last=AIVehicle.GetNumWagons(train)-1;
								if (AIVehicle.SellWagon(train, last))
									AILog.Info("Optimiser: removed one carriage from train " + train +
										"; production no longer needs the capacity.");
							}
							// A second train is added when the platform is full
							// with demand remaining, or when the route itself
							// wants a dedicated mail train.
							if ((result == -1 || mail_wanted) && this.CanExpandFleet(train,record) && UpgradeSingleRoute(train,record)) {
								// Reserve the route before purchasing so several crowded trains
								// cannot each immediately add another full consist.
								foreach (_id, service in this.trains) if (this.SameRoute(service,record))
									service.fleet_after = AIDate.GetCurrentDate() + 90;
								local expansion_buyer=this.ExpansionBuyer(record);
                                // Size the new consist from the route demand
                                // shared across the enlarged fleet.
                                local clone_cargo=expansion_buyer.cargo;
                                local wagon_buyer=clone_cargo==this.buyer.cargo?this.buyer:TrainBuyer(clone_cargo);
                                local wagon=wagon_buyer.BestWagon();
                                local wagon_cap=wagon<0?0:AIEngine.GetCapacity(wagon);
                                local clone_demand=this.DemandEstimate(train,record,clone_cargo);
                                local max_wagons=record.max_length/16-1;
                                local fleet_now=0;
                                foreach(id,r in this.trains) if(this.SameRoute(r,record) &&
                                    this.BuyerFor(r).cargo==clone_cargo && AIVehicle.IsValidVehicle(id)) fleet_now++;
                                local trip_days=clone_cargo==this.BuyerFor(record).cargo ? this.TripDays(record) : 30;
                                local clone_wagons=expansion_buyer.SizedWagons((clone_demand*trip_days+30*(fleet_now+1)-1)/(30*(fleet_now+1)),max_wagons>2?max_wagons-1:3);
                                AILog.Info("Optimiser: new train sized to "+clone_wagons+" wagons from demand "+clone_demand+" units/month.");
                                local extra = expansion_buyer.ClonePassengerTrain(train, record.depot, record.max_length, record.flags, clone_wagons);
								if (extra >= 0) {
									local fleet=this.FleetCount(record)+1;
									local next_expansion=AIDate.GetCurrentDate()+90*fleet*fleet;
									foreach(id,existing in this.trains) if(this.SameRoute(existing,record)) existing.expand_after=next_expansion;
									AILog.Info("Optimiser: route now has "+fleet+" trains; next fleet expansion review in "+(90*fleet*fleet)+" days, subject to backlog and congestion.");
									local service = clone record;
									service.cargo <- expansion_buyer.cargo;
                                    service.trip_days <- trip_days;
                                    service.trip_departed <- -1;
                                    service.trip_destination <- false;
                                    service.trip_loading <- false;
                                    service.trip_observed <- -1;
                                    service.phase = "dispatch";
									service.dispatch_after = AIDate.GetCurrentDate() + 15 + AIBase.RandRange(16);
									service.review_after = AIDate.GetCurrentDate() + 90;
									service.last_station = AIStation.STATION_INVALID;
									service.profit_year = AIDate.GetYear(AIDate.GetCurrentDate());
									service.loss_years = 0;
									additions.append([extra, service]);
								}
							}
						}
						if(record.single_route!=null && record.single_route.upgrade!=null) continue;
						record.phase = "resume";
					}
					if (AIOrder.SetOrderFlags(train, 2, record.flags & ~AIOrder.OF_STOP_IN_DEPOT) && AIVehicle.StartStopVehicle(train)) {
						record.phase = "observe";
						record.observed_day = 0;
						record.review_after = today + 30;
						record.last_station = AIStation.STATION_INVALID;
						AILog.Info("Optimiser: train " + train + " resumed its service.");
					}
				}
				continue;
			}
			if (AIVehicle.GetState(train) == AIVehicle.VS_AT_STATION) {
				local station = AIStation.GetStationID(AIVehicle.GetLocation(train));
				if (station == record.station_a || station == record.station_b) record.last_station = station;
			} else if (AIVehicle.GetState(train) == AIVehicle.VS_RUNNING && (today >= record.review_after || this.PriorityCityMail(record)) &&
				this.RouteReady(record) && AIVehicle.GetCapacity(train, this.BuyerFor(record).cargo) > 0) {
				local expand=this.ExpansionShortfall(train,record) > 0;
				local reduce=this.ReductionCandidate(train,record);
				local mail=this.MailTrainWanted(record);
				// Demand computed from production justifies resizing even when
				// no full departure was observed.
				if ((expand && (AIVehicle.GetLength(train) < record.max_length || this.CanExpandFleet(train,record))) || reduce || mail)
					this.Queue(train, record);
			} else if (AIVehicle.GetState(train) == AIVehicle.VS_RUNNING && record.last_station != AIStation.STATION_INVALID) {
				local station = record.last_station;
				record.last_station = AIStation.STATION_INVALID;
				local capacity = AIVehicle.GetCapacity(train, this.BuyerFor(record).cargo);
				if ((today >= record.review_after || this.PriorityCityMail(record)) && AIStation.IsValidStation(station) &&
					capacity > 0 && AIVehicle.GetCargoLoad(train, this.BuyerFor(record).cargo) >= capacity &&
					AIStation.GetCargoWaiting(station, this.BuyerFor(record).cargo) > 0 && this.RouteReady(record))
					this.Queue(train, record);
			}
		}
		foreach (train in removed) delete this.trains[train];
		foreach (addition in additions) this.trains[addition[0]] <- addition[1];
	}
}
