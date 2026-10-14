function Abs(n)
{
	return n < 0 ? -n : n;
}

function PassengerCargo()
{
	local cargos = AICargoList();
	cargos.Valuate(AICargo.HasCargoClass, AICargo.CC_PASSENGERS);
	cargos.KeepValue(1);
	if (cargos.Count() == 0) return 0xFF;
	return cargos.Begin();
}

// Detect another company's station inside an industry's producing catchment.
// Station tile ownership is public even for rival companies. Computed fresh:
// the scan is small, and caching went stale whenever rival stations changed.
function RivalIndustryStation(industry)
{
	if(industry<0 || !AIIndustry.IsValidIndustry(industry)) return false;
	if(AIIndustry.GetAmountOfStationsAround(industry)<=0) return false;
	local self=AICompany.ResolveCompanyID(AICompany.COMPANY_SELF);
	local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
	foreach(tile,_ in AITileList_IndustryProducing(industry,radius)) {
		if(!AITile.IsStationTile(tile)) continue;
		local owner=AITile.GetOwner(tile);
		if(owner!=self && AICompany.ResolveCompanyID(owner)!=AICompany.COMPANY_INVALID) return true;
	}
	return false;
}

function EnsureMoney(amount)
{
	local self = AICompany.COMPANY_SELF;
	if (AICompany.GetBankBalance(self) >= amount) return true;

	local interval = AICompany.GetLoanInterval();
	if (interval <= 0) return false;

	local need = amount - AICompany.GetBankBalance(self);
	local extra = ((need / interval) + 1) * interval;
	local target = AICompany.GetLoanAmount() + extra;
	local max_loan = AICompany.GetMaxLoanAmount();
	if (target > max_loan) target = max_loan;
	return AICompany.SetLoanAmount(target);
}

// Loan commands use fixed increments. Round the remaining half down so the
// last increment is paid off instead of leaving a permanent small balance.
function RepaySurplusLoan()
{
	local loan = AICompany.GetLoanAmount();
	if (loan <= 0 || AICompany.GetBankBalance(AICompany.COMPANY_SELF) / 2 < loan) return false;
	local interval = AICompany.GetLoanInterval();
	if (interval <= 0) return false;
	local remaining = (loan / 2 / interval) * interval;
	if (!AICompany.SetLoanAmount(remaining)) return false;
	AILog.Info("Finance: repaid " + (loan - remaining) + "; outstanding loan=" + remaining + ".");
	return true;
}

// True when every rail vehicle in the company's fleet - engines and wagons -
// can run on the given rail type. A type passing this check is a compatible
// upgrade: track can be converted and construction switched without touching
// a single train. Base changes (monorail, maglev) fail it by design.
function FleetCanRunOnRail(type)
{
	foreach (vehicle, _ in AIVehicleList()) {
		if (AIVehicle.GetVehicleType(vehicle) != AIVehicle.VT_RAIL) continue;
		if (!AIEngine.CanRunOnRail(AIVehicle.GetEngineType(vehicle), type)) return false;
		for (local i = 1; i < AIVehicle.GetNumWagons(vehicle); i++) {
			local wagon = AIVehicle.GetWagonEngineType(vehicle, i);
			if (wagon != -1 && !AIEngine.CanRunOnRail(wagon, type)) return false;
		}
	}
	return true;
}

// The fastest speed any buildable engine can achieve on the given rail type.
// Rail-type max speed alone is a poor proxy: many train sets give every type
// the same type-level speed, with the real gains coming from which engines
// (steam vs diesel vs electric) the type supports.
function BestEngineSpeedOnRail(type)
{
	local engines = AIEngineList(AIVehicle.VT_RAIL);
	engines.Valuate(AIEngine.IsBuildable);
	engines.KeepValue(1);
	engines.Valuate(AIEngine.CanRunOnRail, type);
	engines.KeepValue(1);
	engines.Valuate(AIEngine.HasPowerOnRail, type);
	engines.KeepValue(1);
	engines.Valuate(AIEngine.IsWagon);
	engines.KeepValue(0);
	engines.Valuate(AIEngine.GetMaxSpeed);
	local best = 0;
	foreach (engine, speed in engines) if (speed > best) best = speed;
	return best;
}

// Independent new routes may use newer technology even while legacy trains
// remain on their old routes. Existing-network work selects its own rail type.
function RailTypeReview()
{
    local previous=AIRail.GetCurrentRailType();
    if(!PickRailType() || AIRail.GetCurrentRailType()==previous) return false;
    AILog.Info("Rail type: new independent routes will use " + AIRail.GetName(AIRail.GetCurrentRailType()) + ".");
    return true;
}

// Monthly cargo demand for sizing a new consist: an industry's output last
// month (halved when a rival station serves it), or the catchment production
// around a station tile for town cargoes.
function MonthlyCargoDemand(cargo, industry, tile)
{
	local radius = AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
	if (industry != null && industry >= 0 && AIIndustry.IsValidIndustry(industry)) {
		local demand = AIIndustry.GetLastMonthProduction(industry, cargo);
		if (RivalIndustryStation(industry)) demand /= 2;
		return demand;
	}
	if (tile != null && AIMap.IsValidTile(tile))
		return AITile.GetCargoProduction(tile, cargo, 1, 1, radius);
	return 0;
}

function PickRailType()
{
	// Pick by the fastest buildable engine each type supports: many train
	// sets leave the type-level speed at zero and phase the real gains into
	// which engines the type carries.
	local types = AIRailTypeList();
	if (types.Count() == 0) return false;
	local best = -1, best_speed = -1;
	foreach (type, _ in types) {
		local speed = BestEngineSpeedOnRail(type);
		if (speed>0 && (speed > best_speed || (speed==best_speed && type>best))) { best_speed = speed; best = type; }
	}
	if (best < 0) return false;
	AIRail.SetCurrentRailType(best);
	return true;
}

function AreaIsBuildable(tile, width, height)
{
	if (!AIMap.IsValidTile(tile)) return false;
	if (AIMap.GetTileX(tile) + width > AIMap.GetMapSizeX() ||
		AIMap.GetTileY(tile) + height > AIMap.GetMapSizeY()) return false;
	for (local x = 0; x < width; x++) {
		for (local y = 0; y < height; y++) {
			local t = tile + AIMap.GetTileIndex(x, y);
			if (!AIMap.IsValidTile(t) || !AITile.IsBuildable(t)) return false;
		}
	}
	return true;
}

function StationPlatforms(site) { return "platforms" in site ? site.platforms : 2; }

function StationFootprint(dir, length, platforms = 2)
{
	if (dir == AIRail.RAILTRACK_NE_SW) {
		return [length, platforms];
	}
	return [platforms, length];
}

function StationExits(tile, dir, length)
{
	if (dir == AIRail.RAILTRACK_NE_SW) {
		return [
			[tile + AIMap.GetTileIndex(-1, 0), tile],
			[tile + AIMap.GetTileIndex(length, 0), tile + AIMap.GetTileIndex(length - 1, 0)]
		];
	}
	return [
		[tile + AIMap.GetTileIndex(0, -1), tile],
		[tile + AIMap.GetTileIndex(0, length), tile + AIMap.GetTileIndex(0, length - 1)]
	];
}


function TownRouteLimit(population, typical_population)
{
	// A hub must be at least twice the median eligible town and have 1,000 people.
	local threshold = typical_population * 2;
	if (threshold < 1000) threshold = 1000;
	local limit = 1 + population / threshold;
	return limit > 4 ? 4 : limit;
}

// Identify one physical rail piece from its two neighbouring tiles.
function RailPiece(from, tile, to)
{
	local a = from - tile;
	local b = to - tile;
	local w = AIMap.GetMapSizeX();
	if (a > b) { local swap = a; a = b; b = swap; }
	if (a == -1 && b == 1) return AIRail.RAILTRACK_NE_SW;
	if (a == -w && b == w) return AIRail.RAILTRACK_NW_SE;
	if (a == -w && b == -1) return AIRail.RAILTRACK_NW_NE;
	if (a == 1 && b == w) return AIRail.RAILTRACK_SW_SE;
	if (a == -w && b == 1) return AIRail.RAILTRACK_NW_SW;
	if (a == -1 && b == w) return AIRail.RAILTRACK_NE_SE;
	return 0;
}

function ParallelRailPieces(tracks)
{
	return tracks == (AIRail.RAILTRACK_NW_NE | AIRail.RAILTRACK_SW_SE) ||
		tracks == (AIRail.RAILTRACK_NW_SW | AIRail.RAILTRACK_NE_SE);
}

// Bridge length includes both ramps. Test the command before accepting a span.
function SuitableRailBridge(start, end)
{
	local length = AIMap.DistanceManhattan(start, end) + 1;
	local bridges = AIBridgeList();
	bridges.Valuate(AIBridge.GetMaxSpeed);
	bridges.Sort(AIList.SORT_BY_VALUE, false);
	local test = AITestMode();
	foreach (bridge, _ in bridges) {
		if (AIBridge.GetMinLength(bridge) <= length && AIBridge.GetMaxLength(bridge) >= length &&
			AIBridge.BuildBridge(AIVehicle.VT_RAIL, bridge, start, end)) return bridge;
	}
	return -1;
}

// Only reuse complete structures belonging to this company and rail type.
function BuiltRailSpanKind(a,b)
{
    if(!AIMap.IsValidTile(a) || !AIMap.IsValidTile(b) ||
        AITile.GetOwner(a)!=AICompany.ResolveCompanyID(AICompany.COMPANY_SELF) ||
        AITile.GetOwner(b)!=AICompany.ResolveCompanyID(AICompany.COMPANY_SELF) ||
        AIRail.GetRailType(a)!=AIRail.GetCurrentRailType() || AIRail.GetRailType(b)!=AIRail.GetCurrentRailType()) return null;
    if(AIBridge.IsBridgeTile(a) && AIBridge.GetOtherBridgeEnd(a)==b) return "bridge";
    if(AITunnel.IsTunnelTile(a) && AITunnel.GetOtherTunnelEnd(a)==b) return "tunnel";
    return null;
}

function IsStructureSpan(a, b)
{
	return AIMap.DistanceManhattan(a, b) > 1;
}

// Persist only the station/terrain information needed by startup rollback.
// Planning scores are floats, which OpenTTD's AI save serializer rejects.
function SavedStationReservations(stations)
{
	local saved = [];
	if (stations == null) return saved;
	foreach (site in stations) {
		local record = { tile=site.tile, dir=site.dir, platforms=StationPlatforms(site) };
        if("primary_recovery" in site) record.primary_recovery <- site.primary_recovery;
        if("hub_existing" in site) record.hub_existing <- true;
        if("dual_access" in site) record.dual_access <- site.dual_access;
		if ("earthwork_original" in site) record.earthwork_original <- clone site.earthwork_original;
		if ("loop_recovery" in site) {
			record.loop_recovery <- {pieces=[],signals=[],removed=[]};
            if("terrain_original" in site.loop_recovery) record.loop_recovery.terrain_original <- clone site.loop_recovery.terrain_original;
			foreach(piece in site.loop_recovery.pieces) record.loop_recovery.pieces.append(clone piece);
			foreach(signal in site.loop_recovery.signals) record.loop_recovery.signals.append(clone signal);
			if("removed" in site.loop_recovery) foreach(piece in site.loop_recovery.removed) record.loop_recovery.removed.append(clone piece);
		}
		saved.append(record);
	}
	return saved;
}

function StructureKey(a,b) { return a<b ? a+":"+b : b+":"+a; }

function PathStructures(path)
{
	local spans={};
	while(path!=null && path.GetParent()!=null) {
		if(IsStructureSpan(path.GetTile(),path.GetParent().GetTile()))
			spans[StructureKey(path.GetTile(),path.GetParent().GetTile())] <- path.GetStructure()=="tunnel" ? "tunnel" : "bridge";
		path=path.GetParent();
	}
	return spans;
}

function RailTunnelCost(start,end)
{
	if(!AIMap.IsValidTile(start) || !AIMap.IsValidTile(end) ||
		!AITile.IsBuildable(start) || !AITile.IsBuildable(end) || AITunnel.GetOtherTunnelEnd(start)!=end) return -1;
	local test=AITestMode();
	local accounting=AIAccounting();
	if(!AITunnel.BuildTunnel(AIVehicle.VT_RAIL,start)) return -1;
	local cost=accounting.GetCosts();
	return cost<=60000 ? cost : -1;
}

function PathTunnelStarts(path)
{
	local starts={};
	while(path!=null && path.GetParent()!=null) {
		if(path.GetStructure()=="tunnel") starts[StructureKey(path.GetTile(),path.GetParent().GetTile())] <- path.GetParent().GetTile();
		path=path.GetParent();
	}
	return starts;
}

// Test the station mouth against the destination, using the full footprint centre.
function StationExitFacesTarget(site, exit, target, length)
{
	local size=StationFootprint(site.dir,length);
	local dx=2*AIMap.GetTileX(target)-(2*AIMap.GetTileX(site.tile)+size[0]-1);
	local dy=2*AIMap.GetTileY(target)-(2*AIMap.GetTileY(site.tile)+size[1]-1);
	local sx=AIMap.GetTileX(exit[0])-AIMap.GetTileX(exit[1]);
	local sy=AIMap.GetTileY(exit[0])-AIMap.GetTileY(exit[1]);
	return dx*sx+dy*sy>=0;
}

function StationSiteFromEntrance(entrance,length)
{
	local first=entrance.signals[0][1], second=entrance.signals[1][1];
	local forward=first-entrance.signals[0][0];
	local tile=first;
	foreach(corner in [second,first+(length-1)*forward,second+(length-1)*forward]) if(corner<tile) tile=corner;
	return {tile=tile,dir=Abs(forward)==1 ? AIRail.RAILTRACK_NE_SW : AIRail.RAILTRACK_NW_SE};
}

// Lists can outlive industries while the AI yields to the game. Keep null
// distinct from a valid empty output list (e.g. a power station).
function IndustryOutputs(industry)
{
    if(!AIIndustry.IsValidIndustry(industry)) return null;
    return AIIndustryType.GetProducedCargo(AIIndustry.GetIndustryType(industry));
}

// Eligibility measures endpoint coordinates, never rail length or a junction spur.
function RouteDistanceAllowed(distance)
{
    return distance >= 50 && distance <= 150;
}

function RouteEndpointsAllowed(source, destination)
{
    return AIMap.IsValidTile(source) && AIMap.IsValidTile(destination) &&
        RouteDistanceAllowed(AIMap.DistanceManhattan(source, destination));
}

// Log fallback reasons and remove legacy markers without creating new signs.
function RiroFallbackSign(tile,reason=null)
{
    if(!AIMap.IsValidTile(tile)) return;
    foreach(id,_ in AISignList()) {
        local name=AISign.GetName(id);
        if(AISign.GetLocation(id)==tile && name.len()>=6 && name.slice(0,6)=="RIRO: ") AISign.RemoveSign(id);
    }
    if(reason==null) return;
    AILog.Info("RIRO fallback at "+tile+": "+reason);
}

// OpenTTD's built-in rail slots: rail, electric, monorail, maglev.
// Additional NewGRF slots use the unchanged baseline rather than guessing a tier.
function IndustryRailPolicy(type=null)
{
    if(type==null) type=AIRail.GetCurrentRailType();
    if(type==0) return {minimum=40,maximum=125,budget_percent=85};
    if(type==2) return {minimum=60,maximum=225,budget_percent=150};
    if(type==3) return {minimum=75,maximum=300,budget_percent=200};
    return {minimum=50,maximum=150,budget_percent=100};
}
function IndustryDistanceAllowed(distance,type=null)
{
    local policy=IndustryRailPolicy(type);
    return distance>=policy.minimum && distance<=policy.maximum;
}
function IndustryEndpointsAllowed(source,destination,type=null)
{
    return AIMap.IsValidTile(source) && AIMap.IsValidTile(destination) &&
        IndustryDistanceAllowed(AIMap.DistanceManhattan(source,destination),type);
}

// Exhaustion expands the candidate pool gradually, never permitting zero output.
function IndustryProductionPolicy() {return {percent=100,next_relax=0};}
function IndustryProductionMinimum(policy,base)
{
    local value=(base*policy.percent+99)/100;
    return value<1?1:value;
}
function RelaxIndustryProduction(policy,name)
{
    local today=AIDate.GetCurrentDate();
    if(policy.percent<=10 || today<policy.next_relax) return false;
    policy.percent=policy.percent>25?policy.percent-25:10;
    policy.next_relax=today+30;
    AILog.Info(name+": candidates exhausted; production requirement reduced to "+policy.percent+"% of its original threshold.");
    return true;
}
