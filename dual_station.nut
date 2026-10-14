// Two isolated RIRO sections sharing a station ID. Saved hub data is primitive.
function DualSectionTiles(b,site,loop)
{
    local occupied={};
    foreach(tile in b.StationTiles(site)) occupied[tile] <- true;
    foreach(p in loop.pieces) foreach(tile in p) occupied[tile] <- true;
    local off=b.PlatformOffset(site),step=site.exit[0]-site.exit[1];
    foreach(lane in [0,off]) for(local i=0;i<4;i++) occupied[site.exit[0]+lane+i*step] <- true;
    return occupied;
}
function PlanDualStation(b,site,target,reshape=false,from_tile=null)
{
    if(StationPlatforms(site)!=2) return null;
    if(!reshape && (site.loop==null || "earthwork" in site)) return null;
    if(reshape) {
        site=clone site;
        local loop=RollThroughStation();
        loop.Plan(DualEntrance(b,site),b.LeftOutboundLane(site.exit),b.platform_length,false,false);
        site.loop=loop;
    }
    local occupied=DualSectionTiles(b,site,site.loop),off=b.PlatformOffset(site);
    // The pickup section keeps its exit for the hub's lifetime, so a fit that
    // faces the onward target must outrank any facing-away fit, whatever the
    // gap. Falling back to the opposite mouth of one gap used to commission
    // hubs whose pickup pointed straight past the intended destination.
    local phases=[[],[]];
    foreach(gap in [3,-3,4,-4]) {
        // Stop exploring, but retain the best layout already found below.
        if(b.PlanningExpired()) break;
        local pickup={tile=site.tile+gap*off,dir=site.dir,platforms=2};
        if(!AIMap.IsValidTile(pickup.tile) || AIMap.DistanceManhattan(site.tile,pickup.tile)!=Abs(gap)) continue;
        local exits=StationExits(pickup.tile,pickup.dir,b.platform_length);
        if(AIMap.DistanceManhattan(exits[0][0],target)>AIMap.DistanceManhattan(exits[1][0],target)) exits.reverse();
        foreach(index,exit in exits) {
            local candidate=null;
            if(reshape) {
                candidate=clone pickup;candidate.exit <- exit;
                local loop=RollThroughStation();
                loop.Plan(DualEntrance(b,candidate),b.LeftOutboundLane(exit),b.platform_length,false,false);
                candidate.loop <- loop;
            } else candidate=b.RiroSite(pickup,exit,false);
            if(candidate==null || candidate.loop==null || (!reshape && "earthwork" in candidate)) continue;
            local other=DualSectionTiles(b,candidate,candidate.loop),overlap=false;
            foreach(tile,_ in other) if(tile in occupied) {overlap=true;break;}
            if(overlap) continue;
            local plan={candidate=candidate,other=other,exit=exit,other_exit=exits[1-index]};
            if(reshape) {
                local earthwork=DualEarthwork(occupied,other,site.exit);
                if(earthwork==null) continue;
                plan.earthwork <- earthwork;
            }
            phases[index].append(plan);
        }
    }
    foreach(phase in phases) foreach(plan in phase) {
        local result=RiroDualResult(b,site,plan);
        // The initial route connects to the delivery loop. When the planned
        // pickup section sits closer to the incoming line, swap the roles so
        // the route reaches the closest loop and the onward step takes the
        // far section.
        if(from_tile!=null && AIMap.DistanceManhattan(from_tile,plan.candidate.tile)<
            AIMap.DistanceManhattan(from_tile,site.tile)) {
            local swapped=RiroDualSwapped(b,site,plan,reshape);
            if(swapped!=null) return swapped;
        }
        return result;
    }
    return null;
}
function RiroDualResult(b,site,plan)
{
    local result=clone site;
    if("earthwork" in plan) result.earthwork <- plan.earthwork;
    result.dual <- {pickup={tile=plan.candidate.tile,dir=plan.candidate.dir,platforms=2,
        exit=clone plan.exit,mirror=plan.candidate.loop.mirrored},delivery=site.tile,
        mirror=site.loop.mirrored,reserved=[],delivery_reserved=[],access=null,used=false};
    foreach(tile,_ in plan.other) result.dual.reserved.append(tile);
    foreach(tile,_ in DualSectionTiles(b,site,site.loop)) result.dual.delivery_reserved.append(tile);
    return result;
}
// Swapped roles: the planned pickup section becomes the delivery (re-planned
// with the mouth facing the incoming line) and the original row becomes the
// pickup (facing the onward target). Returns null when either re-plan does
// not fit the existing terrain.
function RiroDualSwapped(b,site,plan,reshape)
{
    local L=b.platform_length,cand2=null,site2=null,onward=null;
    foreach(e in StationExits(site.tile,site.dir,L)) if(e[0]!=site.exit[0]) onward=e;
    if(onward==null) return null;
    if(reshape) {
        cand2=clone plan.candidate;
        cand2.exit=plan.other_exit;
        local loop=RollThroughStation();
        loop.Plan(DualEntrance(b,cand2),b.LeftOutboundLane(cand2.exit),L,false,false);
        cand2.loop=loop;
        site2=clone site;
        site2.exit=onward;
        local loop2=RollThroughStation();
        loop2.Plan(DualEntrance(b,site2),b.LeftOutboundLane(site2.exit),L,false,false);
        site2.loop=loop2;
    } else {
        cand2=b.RiroSite(plan.candidate,plan.other_exit,false);
        site2=b.RiroSite(site,onward,false);
    }
    if(cand2==null || cand2.loop==null || site2==null || site2.loop==null) return null;
    if(!reshape && (("earthwork" in cand2) || ("earthwork" in site2))) return null;
    local delivery_tiles=DualSectionTiles(b,cand2,cand2.loop);
    local pickup_tiles=DualSectionTiles(b,site2,site2.loop);
    foreach(tile,_ in pickup_tiles) if(tile in delivery_tiles) return null;
    local result=clone cand2;
    if("earthwork" in plan) {
        result.earthwork <- plan.earthwork;
        result.earthwork.exit=cand2.exit;
    }
    result.dual <- {pickup={tile=site2.tile,dir=site2.dir,platforms=2,exit=clone site2.exit,
        mirror=site2.loop.mirrored},delivery=cand2.tile,mirror=cand2.loop.mirrored,
        reserved=[],delivery_reserved=[],access=null,used=false};
    foreach(tile,_ in pickup_tiles) result.dual.reserved.append(tile);
    foreach(tile,_ in delivery_tiles) result.dual.delivery_reserved.append(tile);
    return result;
}
function DualEntrance(b,site)
{
    local exit=site.exit,off=b.PlatformOffset(site),step=exit[0]-exit[1];
    local entrance={signals=[[exit[0],exit[1]],[exit[0]+off,exit[1]+off]],crosses=[]};
    foreach(d in [step,-step]) {
        local a=exit[0]+step,z=a+off;
        entrance.crosses.append({from=a-d,a=a,b=z,to=z+d,step=d});
    }
    return entrance;
}
function RestoreDualAccess(hub)
{
    if(hub.access==null) return true;
    local data=hub.access,loop=RollThroughStation();
    loop.built=data.loop.pieces;loop.changed_signals=data.loop.signals;loop.removed=data.loop.removed;
    if("terrain_original" in data.loop) loop.terrain_original=data.loop.terrain_original;
    if(!loop.Restore() || !RestoreSingleUpgrade(data.base)) return false;
    hub.access=null;
    return true;
}
function BuildDualAccess(b,hub)
{
    if(hub.access!=null) {
        if("complete" in hub.access && hub.access.complete) return true;
        if(!RestoreDualAccess(hub)) return false;
    }
    local site=hub.pickup,entrance=DualEntrance(b,site),step=site.exit[0]-site.exit[1];
    hub.access={base={upgrade={pieces=[],structures=[],removed=[],signals=[]}},loop={pieces=[],signals=[],removed=[]}};
    local journal=hub.access.base.upgrade;
    foreach(signal in entrance.signals) for(local i=0;i<3;i++) {
        local tile=signal[0]+i*step,p=[tile-step,tile,tile+step];
        if(AIRail.AreTilesConnected(p[0],p[1],p[2])) continue;
        journal.pieces.append(p);
        if(!AIRail.BuildRail(p[0],p[1],p[2])) return false;
    }
    foreach(c in entrance.crosses) foreach(p in [[c.from,c.a,c.b],[c.a,c.b,c.to]]) {
        if(AIRail.AreTilesConnected(p[0],p[1],p[2])) continue;
        journal.pieces.append(p);
        if(!AIRail.BuildRail(p[0],p[1],p[2])) return false;
    }
    local loop=RollThroughStation();
    if(!loop.Plan(entrance,b.LeftOutboundLane(site.exit),b.platform_length,site.mirror) || !loop.Build(hub.access.loop)) return false;
    hub.access.complete <- true;
    return true;
}
function DualPickupSites(b,hub,target)
{
    if(hub==null || hub.used || !AIRail.IsRailStationTile(hub.pickup.tile) ||
        AITile.GetOwner(hub.pickup.tile)!=AICompany.ResolveCompanyID(AICompany.COMPANY_SELF)) return [];
    local site=clone hub.pickup;site.hub_existing <- true;
    if(!b.VerifyStation(site)) return [];
    // Its orientation was chosen for the next cargo destination when commissioned.
    local loop=RollThroughStation();
    if(!loop.Plan(DualEntrance(b,site),b.LeftOutboundLane(site.exit),b.platform_length,site.mirror)) return [];
    site.loop <- loop;site.fixed_mirror <- site.mirror;
    return [site];
}

// Level both platform groups and their complete approaches as one plan, before
// either group is built. Separate plans could change each other's shared corners.
function DualEarthwork(delivery,pickup,exit)
{
    local corners={},heights=[],geometry=PairedTerrain();
    foreach(section in [delivery,pickup]) foreach(tile,_ in section) {
        if(!AIMap.IsValidTile(tile) || !AITile.IsBuildable(tile) || AITile.IsWaterTile(tile)) return null;
        foreach(corner in geometry.Corners(tile)) if(!(corner in corners)) {
            if(!AIMap.IsValidTile(corner)) return null;
            corners[corner] <- true;heights.append(AITile.GetCornerHeight(corner,AITile.CORNER_N));
        }
    }
    if(heights.len()==0) return null;
    heights.sort();local median=heights[heights.len()/2],best=null,best_cost=1000000;
    foreach(height in [median,median+1,median-1]) {
        if(height<1) continue;
        local terrain=PairedTerrain(3,320,60000),valid=true,cost=0;
        foreach(corner,_ in corners) {
            if(!terrain.SetHeight(corner,height)) {valid=false;break;}
            terrain.desired[corner] <- height;
        }
        if(!valid) continue;
        // Propagated slope changes must not contradict the level footprint.
        foreach(corner,_ in corners) if(terrain.Height(corner)!=height) {valid=false;break;}
        if(!valid) continue;
        foreach(corner,h in terrain.targets) cost+=Abs(h-AITile.GetCornerHeight(corner,AITile.CORNER_N));
        if(cost<best_cost) {best_cost=cost;best={targets=clone terrain.targets,exit=exit,riro=true,dual=true};}
    }
    return best;
}

// Short, persistent status on the unused half; separate from transient search signs.
function DualPickupStatus(hub,status=null)
{
    local prefix="[VT pickup] ",tile=hub.pickup.tile,sign=-1;
    hub.pickup_status <- status;
    foreach(id,_ in AISignList()) {
        local name=AISign.GetName(id);
        if(AISign.GetLocation(id)!=tile || name.len()<prefix.len() || name.slice(0,prefix.len())!=prefix) continue;
        if(status==null || sign!=-1) AISign.RemoveSign(id);
        else sign=id;
    }
    if(status==null) return;
    local name=prefix+status;
    // API 14 compatibility limits sign names to 30 characters.
    if(name.len()>30) name=name.slice(0,30);
    if(sign!=-1) {if(AISign.GetName(sign)!=name) AISign.SetName(sign,name);}
    else if(AIRail.IsRailStationTile(tile)) {
        local id=AISign.BuildSign(tile,name);
        if(!AISign.IsValidSign(id)) AILog.Warning("Pickup status sign failed: "+AIError.GetLastErrorString());
    }
}
