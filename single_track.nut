// Single main line first; primitive route metadata supports a later, recoverable upgrade.
function RailTripleKey(p) { return p[1]+":"+RailPiece(p[0],p[1],p[2]); }
function PackRailPath(path)
{
    local nodes=[];
    while(path!=null) { nodes.append([path.GetTile(),path.GetStructure()]); path=path.GetParent(); }
    return nodes;
}
function UnpackRailPath(nodes)
{
    local path=null;
    for(local i=nodes.len()-1;i>=0;i--) path=VibePath(nodes[i][0],path,nodes[i][1]);
    return path;
}
function RailPiecesBuild(pieces)
{
    foreach(p in pieces) if(!AIRail.AreTilesConnected(p[0],p[1],p[2]) && !AIRail.BuildRail(p[0],p[1],p[2])) return false;
    return true;
}
function PlanSingleTrack(b,a,z,batches)
{
    local starts="exit" in a ? [a.exit] : StationExits(a.tile,a.dir,b.platform_length);
    local goals="exit" in z ? [z.exit] : StationExits(z.tile,z.dir,b.platform_length);
    local pairs=[];
    foreach(start in starts) foreach(goal in goals) {
        if(b.LeftOutboundLane(start)==b.LeftOutboundLane(goal)) continue;
        pairs.append({start=start,goal=goal,distance=AIMap.DistanceManhattan(start[0],goal[0]),
            facing=(StationExitFacesTarget(a,start,z.tile,b.platform_length)?1:0)+(StationExitFacesTarget(z,goal,a.tile,b.platform_length)?1:0)});
    }
    pairs.sort(function(a,b) { if(a.facing!=b.facing) return a.facing>b.facing?-1:1; return a.distance<b.distance?-1:(a.distance>b.distance?1:0); });
    foreach(pair in pairs) {
        if(b.PlanningExpired()) return null;
        local start=pair.start,goal=pair.goal;
        if(!b.CanStationThroat(start,b.PlatformOffset(a)) || !b.CanStationThroat(goal,b.PlatformOffset(z))) continue;
        local start2=[start[0]+b.PlatformOffset(a),start[1]+b.PlatformOffset(a)];
        local goal2=[goal[0]+b.PlatformOffset(z),goal[1]+b.PlatformOffset(z)];
        // Build the future station-A arrival lane first so its depot remains
        // accessible when the return line is added and signals become one-way.
        if(b.LeftOutboundLane(start)==0) {
            local swap=start;start=start2;start2=swap;
            swap=goal;goal=goal2;goal2=swap;
        }
        local reserved=b.extra_reserved==null?[]:clone b.extra_reserved;
        foreach(site in [a,z]) foreach(tile in b.StationTiles(site)) reserved.append(tile);
        local stubs=[],merges=[],stub_nodes=[];
        foreach(ends in [[start,start2],[goal,goal2]]) {
            local e=ends[0][0],q=ends[1][0],s=ends[0][0]-ends[0][1];
            for(local i=0;i<4;i++) { reserved.append(q+i*s); if(i<3) stub_nodes.append([q+i*s,null]); }
            stubs.append([q-s,q,q+s]); stubs.append([q,q+s,q+2*s]);
            merges.append([q+s,q+2*s,e+2*s]); merges.append([q+2*s,e+2*s,e+3*s]);
        }
        local allowed=true;
        { local test=AITestMode(); foreach(p in merges) if(!AIRail.BuildRail(p[0],p[1],p[2])) {allowed=false; break;} }
        if(!allowed) continue;
        local outbound=1;
        local depot_reserved=clone reserved;
        local path=b.SearchPath(start,goal,reserved,null,batches);
        if(path==null) { b.route_failure=b.search_failure; continue; }
        local stub_path=UnpackRailPath(stub_nodes);
        local ea=b.StationEntrance(start,start2,path,stub_path), ez=b.StationEntrance(goal,goal2,path,stub_path);
        if(ea==null || ez==null) continue;
        local depot=b.DepotSite(path,depot_reserved,ea);
        if(depot==null) {b.route_failure="start";continue;}
        local pieces=clone stubs; foreach(p in merges) pieces.append(p);
        AILog.Info("Single-track planner: one main line found; return track deferred until fleet expansion.");
        return {single=true,path=path,start=start,goal=goal,outbound=outbound,quality=b.PathQuality(path,start,goal),
            secondary={path=stub_path,start=start2,goal=goal2,stubs=pieces},entrances=[ea,ez],depot_site=depot,line_signals=[],merges=merges};
    }
    return null;
}
// A compact terminus has no crossing, parallel stub or future second lane.
function PlanPermanentSingleTrack(b,a,z,batches)
{
    local starts="exit" in a ? [a.exit] : StationExits(a.tile,a.dir,b.platform_length);
    local goals="exit" in z ? [z.exit] : StationExits(z.tile,z.dir,b.platform_length);
    foreach(start in starts) foreach(goal in goals) {
        if(b.PlanningExpired()) return null;
        if(!b.CanStationThroat(start,0) || !b.CanStationThroat(goal,0)) continue;
        local reserved=[];
        foreach(site in [a,z]) foreach(tile in b.StationTiles(site)) reserved.append(tile);
        local path=b.SearchPath(start,goal,reserved,null,batches);
        if(path==null) continue;
        local entrances=[{crosses=[],signals=[start]},{crosses=[],signals=[goal]}];
        local depot=b.DepotSite(path,reserved,entrances[0]);
        if(depot==null) continue;
        return {single=true,permanent_single=true,path=path,start=start,goal=goal,outbound=0,
            quality=b.PathQuality(path,start,goal),secondary={path=null,start=start,goal=goal,stubs=[]},
            entrances=entrances,depot_site=depot,line_signals=[],merges=[]};
    }
    return null;
}
function SaveSingleRoute(b,found,a,z)
{
    if(!("single" in found)) return null;
    if("permanent_single" in found) return {permanent=true,dual=false,upgrade=null,platform_length=b.platform_length};
    local loops=[],skip={},reserved=[];
    foreach(e in found.entrances) if("roro" in e) {
        foreach(s in e.roro.signals) loops.append(clone s);
        foreach(p in e.roro.remove) skip[RailTripleKey(p)] <- true;
        foreach(p in e.roro.pieces) if(p[1]!=e.roro.junction) reserved.append(p[1]);
    }
    local entrances=[];
    foreach(e in found.entrances) entrances.append({crosses=e.crosses,signals=e.signals});
    return {dual=false,platform_length=b.platform_length,primary=PackRailPath(found.path),start=found.start,goal=found.goal,
        start2=found.secondary.start,goal2=found.secondary.goal,outbound=found.outbound,
        depot_site=clone found.depot_site,entrances=entrances,merges=found.merges,stubs=found.secondary.stubs,
        sites=[{tile=a.tile,dir=a.dir},{tile=z.tile,dir=z.dir}],loop_signals=loops,skip=skip,reserved=reserved,upgrade=null};
}
function JournalSignal(j,tile,front,type)
{
    local back=tile+(tile-front);
    local old_front=AIRail.GetSignalType(tile,front),old_back=AIRail.GetSignalType(tile,back);
    if(old_front==type && ((type!=AIRail.SIGNALTYPE_PBS_ONEWAY && type!=AIRail.SIGNALTYPE_NONE) || old_back==AIRail.SIGNALTYPE_NONE)) return true;
    j.signals.append([tile,front,back,old_front,old_back]);
    if(old_front!=AIRail.SIGNALTYPE_NONE) { if(!AIRail.RemoveSignal(tile,front)) return false; }
    else if(old_back!=AIRail.SIGNALTYPE_NONE) { if(!AIRail.RemoveSignal(tile,back)) return false; }
    return type==AIRail.SIGNALTYPE_NONE || AIRail.BuildSignal(tile,front,type);
}
function RestoreSingleUpgrade(data)
{
    local j=data.upgrade;
    if(j==null) return true;
    // Remove signals before restoring bidirectional access. Keep train stopped on any failure.
    for(local i=j.signals.len()-1;i>=0;i--) {
        local s=j.signals[i];
        if(AIRail.GetSignalType(s[0],s[1])!=AIRail.SIGNALTYPE_NONE && !AIRail.RemoveSignal(s[0],s[1])) return false;
        if(AIRail.GetSignalType(s[0],s[2])!=AIRail.SIGNALTYPE_NONE && !AIRail.RemoveSignal(s[0],s[2])) return false;
        if(s[3]!=AIRail.SIGNALTYPE_NONE && !AIRail.BuildSignal(s[0],s[1],s[3])) return false;
        if(s[4]!=AIRail.SIGNALTYPE_NONE && !AIRail.BuildSignal(s[0],s[2],s[4])) return false;
        j.signals.pop();
    }
    for(local i=j.pieces.len()-1;i>=0;i--) {
        local p=j.pieces[i];
        if(AIRail.AreTilesConnected(p[0],p[1],p[2]) && !AIRail.RemoveRail(p[0],p[1],p[2])) return false;
        j.pieces.pop();
    }
    for(local i=j.structures.len()-1;i>=0;i--) {
        local p=j.structures[i];
        if(p[2]=="tunnel") {
            if(AITunnel.IsTunnelTile(p[0]) && AITunnel.GetOtherTunnelEnd(p[0])==p[1] && !AITunnel.RemoveTunnel(p[0])) return false;
        } else if(AIBridge.IsBridgeTile(p[0]) && AIBridge.GetOtherBridgeEnd(p[0])==p[1] && !AIBridge.RemoveBridge(p[0])) return false;
        j.structures.pop();
    }
    if(!RailPiecesBuild(j.removed)) return false;
    data.upgrade=null;
    return true;
}
function UpgradeSingleRoute(train,record)
{
    local data=record.single_route;
    if(data!=null && "permanent" in data && data.permanent) return false;
    if(data==null || data.dual) return true;
    if(!AIVehicle.IsStoppedInDepot(train) || AIVehicle.GetLocation(train)!=record.depot) return false;
    if(!RestoreSingleUpgrade(data)) return false;
    local b=RouteBuilder("platform_length" in data ? data.platform_length : record.max_length/16);
    b.use_hierarchy=false; b.single_first=false;
    b.use_jump_search=false;
    b.use_aystar=false;
    local previous_type=AIRail.GetCurrentRailType();
    AIRail.SetCurrentRailType(AIRail.GetRailType(record.depot));
    local primary=UnpackRailPath(data.primary);
    local reserved=clone data.reserved;
    reserved.append(record.depot);
    foreach(site in data.sites) foreach(tile in b.StationTiles(site)) reserved.append(tile);
    b.reusable_rails={};
    foreach(ends in [data.start2,data.goal2]) {
        local step=ends[0]-ends[1];
        for(local i=0;i<3;i++) b.reusable_rails[ends[0]+i*step] <- true;
    }
    b.skip_rail_pieces=data.skip;
    b.planning_deadline=AIController.GetTick()+4800;
    AILog.Info("Single-track upgrade: train held in depot while searching for return line.");
    local path=b.SearchPath(data.start2,data.goal2,reserved,b.PathTiles(primary),40,b.TrackReservations(primary,data.start,data.goal));
    b.planning_deadline=0;
    if(path==null) {
        AIRail.SetCurrentRailType(previous_type);
        AILog.Info("Single-track upgrade: no return line found; keeping one train.");
        return false;
    }
    local found={path=primary,start=data.start,goal=data.goal,secondary={path=path,start=data.start2,goal=data.goal2},
        entrances=data.entrances,outbound=data.outbound,depot_site=data.depot_site,line_signals=[]};
    data.upgrade={pieces=[],structures=[],removed=[],signals=[]};
    b.build_journal=data.upgrade;
    local ok=b.BuildPath(found.secondary);
    if(ok) foreach(p in data.merges) {
        data.upgrade.removed.append(p);
        if(AIRail.AreTilesConnected(p[0],p[1],p[2]) && !AIRail.RemoveRail(p[0],p[1],p[2])) {ok=false;break;}
    }
    if(ok) foreach(e in data.entrances) foreach(s in e.signals)
        if(!JournalSignal(data.upgrade,s[0],s[1],AIRail.SIGNALTYPE_PBS)) ok=false;
    if(ok) ok=b.BuildLineSignals(found);
    if(ok) foreach(s in data.loop_signals) if(!JournalSignal(data.upgrade,s[0],s[1],s.len()>2?s[2]:AIRail.SIGNALTYPE_PBS_ONEWAY)) {ok=false;break;}
    if(ok) {
        data.dual=true; data.upgrade=null;
        AILog.Info("Single-track upgrade complete: two separate tracks and one-way signals; another train is now permitted.");
    } else {
        RestoreSingleUpgrade(data);
        AILog.Warning("Single-track upgrade failed; restoring original route before releasing train.");
    }
    AIRail.SetCurrentRailType(previous_type);
    return ok;
}
