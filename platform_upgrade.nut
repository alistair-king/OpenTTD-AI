// Grows a full two-platform RIRO station to three platforms when trains queue
// at its entrance. The outer return track row becomes the new platform and the
// return loop is rebuilt one row further out, mirroring the manual layout.
// All journals are primitive arrays so an interrupted upgrade survives saves.

StationExpansionCooldown <- {};

// Transient journal for route objects without saved state; a save during a
// standalone-route upgrade loses the journal, and the rollback-free rebuild
// steps simply restart from the current world state.
StationExpansionJournal <- {expansion_plan=null, recovery=null};

function RiroSelf(tile)
{
    return AITile.GetOwner(tile)==AICompany.ResolveCompanyID(AICompany.COMPANY_SELF);
}

// True when every planned piece already exists exactly as owned rail.
function RiroLoopMatches(pieces)
{
    foreach(piece in pieces)
        if(!RiroSelf(piece[1]) || !AIRail.IsRailTile(piece[1]) ||
            !AIRail.AreTilesConnected(piece[0],piece[1],piece[2])) return false;
    return true;
}

// A train stopped for days on the line beside a station throat is waiting
// for a platform. The last line signal can sit several tiles short of the
// mouth, so scan a window along both approach rows.
function IsStationApproachTile(tile,station,length)
{
    if(!AIRail.IsRailStationTile(station) || !RiroSelf(station)) return false;
    local dir=AIRail.GetRailStationDirection(station);
    local id=AIStation.GetStationID(station);
    local fx=dir==AIRail.RAILTRACK_NE_SW ? 1 : AIMap.GetMapSizeX();
    local off=dir==AIRail.RAILTRACK_NE_SW ? AIMap.GetMapSizeX() : 1;
    local platforms=1;
    for(local row=1;row<3;row++) {
        local full=true;
        for(local i=0;i<length;i++) {
            local t=station+i*fx+row*off;
            if(!AIRail.IsRailStationTile(t) || AIStation.GetStationID(t)!=id) {full=false;break;}
        }
        if(full) platforms=row+1; else break;
    }
    if(platforms<2) return false;
    for(local k=0;k<7;k++) foreach(row in [0,off])
        if(tile==station-fx-k*fx+row || tile==station+length*fx+k*fx+row) return true;
    return false;
}

// Recognise an existing two-platform RIRO by re-planning its loop and matching
// every piece against the physical rails. Pins mouth, lane and mirror.
function RiroIdentify(b,tile)
{
    if(!AIRail.IsRailStationTile(tile) || !RiroSelf(tile)) return null;
    local dir=AIRail.GetRailStationDirection(tile);
    local id=AIStation.GetStationID(tile);
    local L=b.platform_length;
    local fx=dir==AIRail.RAILTRACK_NE_SW ? 1 : AIMap.GetMapSizeX();
    local off=dir==AIRail.RAILTRACK_NE_SW ? AIMap.GetMapSizeX() : 1;
    for(local i=0;i<L;i++) {
        if(!AIRail.IsRailStationTile(tile+i*fx) || AIStation.GetStationID(tile+i*fx)!=id) return null;
        if(!AIRail.IsRailStationTile(tile+i*fx+off) || AIStation.GetStationID(tile+i*fx+off)!=id) return null;
        // A station that already spans three rows on either side is done.
        if(AIRail.IsRailStationTile(tile+i*fx+2*off) && AIStation.GetStationID(tile+i*fx+2*off)==id) return null;
        if(AIRail.IsRailStationTile(tile+i*fx-off) && AIStation.GetStationID(tile+i*fx-off)==id) return null;
    }
    foreach(exit in StationExits(tile,dir,L)) foreach(lane in [0,1]) foreach(mirror in [false,true]) {
        local entrance={signals=[[exit[0],exit[1]],[exit[0]+off,exit[1]+off]]};
        local planner=RollThroughStation();
        if(!planner.Plan(entrance,lane,L,mirror,false)) continue;
        if(!RiroLoopMatches(planner.pieces)) continue;
        return {tile=tile,dir=dir,length=L,off=off,exit=exit,lane=lane,mirror=mirror,
            entrance=entrance,plan=planner,
            origin=entrance.signals[lane][1],
            forward=entrance.signals[lane][1]-entrance.signals[lane][0],
            side=(entrance.signals[lane][1]-entrance.signals[1-lane][1])*(mirror?-1:1),
            junction=entrance.signals[lane][1]-2*(entrance.signals[lane][1]-entrance.signals[lane][0])};
    }
    return null;
}

function RiroPathPieces(tiles)
{
    local pieces=[];
    for(local i=1;i<tiles.len()-1;i++) pieces.append([tiles[i-1],tiles[i],tiles[i+1]]);
    return pieces;
}

// Prepare the switch column: any signals on it are journalled and removed
// (a one-way facing the platform would forbid the turn, and OpenTTD refuses
// to add a rail bit under a signal), then both switch curves are validated
// in test mode. Returns false and restores the signals when the column
// cannot take the switch.
function RiroTrySwitchColumn(col,forward,side,piece1,piece2,plan)
{
    if(!AIMap.IsValidTile(col) || !AIMap.IsValidTile(col+side)) return false;
    if(AIRail.IsRailTile(col) && RiroSelf(col)) {
        // A shared square (the crossover column) intentionally carries two
        // bits; the test build below decides whether the turn still fits.
    } else if(!AITile.IsBuildable(col) || AITile.IsWaterTile(col)) return false;
    foreach(d in [forward,-forward]) {
        local type=AIRail.GetSignalType(col,col+d);
        if(type!=AIRail.SIGNALTYPE_NONE) {
            plan.remove_signals.append([col,col+d]);
            plan.restore_signals.append([col,col+d,type]);
            AIRail.RemoveSignal(col,col+d);
        }
    }
    local test=AITestMode();
    if(AIRail.BuildRail(piece1[0],piece1[1],piece1[2]) &&
        AIRail.BuildRail(piece2[0],piece2[1],piece2[2])) return true;
    foreach(s in plan.restore_signals)
        if(AIRail.GetSignalType(s[0],s[1])==AIRail.SIGNALTYPE_NONE) AIRail.BuildSignal(s[0],s[1],s[2]);
    plan.restore_signals.clear();
    plan.remove_signals.clear();
    return false;
}

// Read-only apart from reversible signal moves. The third platform goes on
// the side the queued train approaches from, so its one-way approach line
// can actually reach the new mouth: beyond the inner platform row (pure
// additions, the loop untouched) when the queue waits there, or on the
// return row (the loop rebuilt one row further out) when it queues beside
// the loop.
function RiroThirdPlan(b,id,wait_tile)
{
    local origin=id.origin,forward=id.forward,side=id.side,L=id.length;
    local inner=origin-side;
    local on_inner=false,on_outer=false;
    for(local k=0;k<7;k++) {
        local out=(1+k)*forward;
        if(wait_tile==inner-out || wait_tile==inner-side-out) on_inner=true;
        if(wait_tile==origin-out || wait_tile==origin+side-out) on_outer=true;
    }
    local pieces=[],remove=[],signals=[],remove_signals=[],restore_signals=[],station=0;
    if(on_inner || !on_outer) {
        // Beyond the inner row: the switch hangs off the inner row's throat
        // on the same square as the mouth crossover, and the new platform
        // rolls through and swings around the old merge corner to reach the
        // return row on clear land.
        local far=[origin+(L-1)*forward-2*side];
        for(local u=L;u<=L+3;u++) far.append(origin+u*forward-2*side);
        far.append(origin+(L+4)*forward-2*side);
        far.append(origin+(L+4)*forward-side);
        far.append(origin+(L+4)*forward);
        far.append(origin+(L+4)*forward+side);
        far.append(origin+(L+3)*forward+side);
        foreach(p in RiroPathPieces(far)) pieces.append(p);
        local switch_plan=null;
        for(local d=2;d<=6;d++) {
            local col=inner-d*forward;
            local plan={remove_signals=[],restore_signals=[]};
            if(d==2) {
                // The same square as the mouth crossover: its registration is
                // dead (the RIRO build severed the fan), so clear it and let
                // both splits share the column.
                AIRail.RemoveRail(col+forward,col,col+side);
                AIRail.RemoveRail(col,col+side,col+side-forward);
            }
            if(!RiroTrySwitchColumn(col,forward,-side,
                [col-forward,col,col-side],[col,col-side,col+forward-side],plan)) continue;
            local mouth=[col-side];
            for(local j=1;j<d;j++) mouth.append(col+j*forward-side);
            mouth.append(origin-2*side);
            local plan2={pieces=[[col-forward,col,col-side],[col,col-side,col+forward-side]]};
            foreach(p in RiroPathPieces(mouth)) plan2.pieces.append(p);
            switch_plan=plan2;
            foreach(s in plan.remove_signals) remove_signals.append(s);
            foreach(s in plan.restore_signals) restore_signals.append(s);
            break;
        }
        if(switch_plan==null) return {reason="No free throat column for the platform switch"};
        foreach(p in switch_plan.pieces) pieces.append(p);
        signals.append([origin-forward-2*side,origin-2*side,AIRail.SIGNALTYPE_PBS]);
        signals.append([origin-forward-2*side,origin-2*forward-2*side,AIRail.SIGNALTYPE_NONE]);
        signals.append([origin+L*forward-2*side,origin+(L-1)*forward-2*side]);
        station=origin+(L-1)*forward-2*side;
    } else {
        // On the return row: free the outer return track for the new platform
        // and rebuild the return loop one row further out, reusing the kept
        // final curve into the entrance junction.
        local old_outer={};
        for(local u=-3;u<=L+4;u++) old_outer[origin+u*forward+side] <- true;
        foreach(piece in id.plan.pieces) if(piece[1] in old_outer) remove.append(piece);
        if(remove.len()==0) return {reason="Return row not recognised"};
        local tiles=[origin+(L-1)*forward+side];
        for(local u=L;u<=L+3;u++) tiles.append(origin+u*forward+side);
        tiles.append(origin+(L+3)*forward+2*side);
        for(local u=L+2;u>=-2;u--) tiles.append(origin+u*forward+2*side);
        tiles.append(origin-2*forward+side);
        pieces.append([origin+(L+3)*forward,origin+(L+3)*forward+side,origin+(L+3)*forward+2*side]);
        foreach(p in RiroPathPieces(tiles)) pieces.append(p);
        local switch_plan=null;
        for(local d=3;d<=6;d++) {
            local col=origin-d*forward;
            local plan={remove_signals=[],restore_signals=[]};
            if(!RiroTrySwitchColumn(col,forward,side,
                [col-forward,col,col+side],[col,col+side,col-forward+side],plan)) continue;
            local mouth=[col+side];
            for(local j=d-1;j>=1;j--) mouth.append(origin-j*forward+side);
            mouth.append(origin+side);
            local plan2={pieces=[[col-forward,col,col+side],[col,col+side,col-forward+side]]};
            foreach(p in RiroPathPieces(mouth)) plan2.pieces.append(p);
            switch_plan=plan2;
            foreach(s in plan.remove_signals) remove_signals.append(s);
            foreach(s in plan.restore_signals) restore_signals.append(s);
            break;
        }
        if(switch_plan==null) return {reason="No free throat column for the platform switch"};
        foreach(p in switch_plan.pieces) pieces.append(p);
        signals.append([origin-forward+side,origin+side,AIRail.SIGNALTYPE_PBS]);
        signals.append([origin-forward+side,origin-2*forward+side,AIRail.SIGNALTYPE_NONE]);
        signals.append([origin+side+L*forward,origin+side+(L-1)*forward]);
        // The return keeps its waiting point and post-turn signal, one row out.
        signals.append([origin+2*side,origin+forward+2*side]);
        signals.append([origin+(L+1)*forward+2*side,origin+(L+2)*forward+2*side]);
        remove_signals.append([origin+side,origin+forward+side]);
        remove_signals.append([origin+(L+1)*forward+side,origin+(L+2)*forward+side]);
        station=origin+(L-1)*forward+side;
    }
    // New tiles must be clear land or our own rail; the platform row must not
    // carry foreign infrastructure.
    foreach(piece in pieces) {
        local t=piece[1];
        if(!AIMap.IsValidTile(t) || AITile.IsWaterTile(t)) return {reason="New loop tile blocked"};
        if(RiroSelf(t) && AIRail.IsRailTile(t)) continue;
        if(!AITile.IsBuildable(t) || AITile.HasTransportType(t,AITile.TRANSPORT_ROAD)) return {reason="New loop tile occupied"};
    }
    for(local u=0;u<L;u++) {
        local t=station+u*forward;
        if(!AIMap.IsValidTile(t) || AITile.IsWaterTile(t)) return {reason="New platform tile blocked"};
        if(RiroSelf(t) && (AIRail.IsRailTile(t) || AIRail.IsRailStationTile(t))) continue;
        if(!AITile.IsBuildable(t) || AITile.HasTransportType(t,AITile.TRANSPORT_ROAD) ||
            AITile.HasTransportType(t,AITile.TRANSPORT_RAIL)) return {reason="New platform tile occupied"};
    }
    return {pieces=pieces,remove=remove,signals=signals,remove_signals=remove_signals,
        restore_signals=restore_signals,station=station,reason=null};
}

// Plan the earthworks for the new loop tiles at the existing throat height.
// Every planned tile is levelled, including tiles that already carry track on
// a slope: the switch needs a flat base before its curves can connect.
// Returns the planner instance, or null when the land cannot match.
function RiroThirdTerrain(id,pieces)
{
    local junction=id.junction;
    if(!AIMap.IsValidTile(junction) || AITile.GetSlope(junction)!=AITile.SLOPE_FLAT) return null;
    local height=AITile.GetCornerHeight(junction,AITile.CORNER_N);
    local terrain=PairedTerrain(3,160,40000);
    foreach(piece in pieces) {
        local tile=piece[1];
        if(!AIMap.IsValidTile(tile)) return null;
        foreach(corner in terrain.Corners(tile))
            if(!terrain.SetHeight(corner,height)) return null;
    }
    return terrain;
}

// Execute (or resume) the upgrade. Every step re-checks world state, so a
// save between commands resumes cleanly, and any failure rolls the whole
// upgrade back through the journal.
function RiroThirdBuild(b,id,plan,journal)
{
    if(!("recovery" in journal) || journal.recovery==null) {
        // Journal integers before the first command can suspend the AI.
        local recovery={pieces=[],signals=[],removed=[],terrain_original={},station_done=false};
        foreach(p in plan.pieces) recovery.pieces.append(p);
        foreach(p in plan.remove) recovery.removed.append(p);
        foreach(s in plan.signals) recovery.signals.append([s[0],s[1],AIRail.SIGNALTYPE_NONE,AIRail.SIGNALTYPE_NONE,s[1]+ (s[1]-s[0])]);
        journal.recovery=recovery;
    }
    local recovery=journal.recovery;

    if(!EnsureMoney(60000)) {AILog.Warning("RIRO platform upgrade: insufficient funds.");return false;}

    foreach(s in plan.remove_signals)
        if(AIRail.GetSignalType(s[0],s[1])!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(s[0],s[1]);
    foreach(p in plan.remove) {
        if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) continue;
        if(!AIRail.RemoveRail(p[0],p[1],p[2])) {
            AILog.Warning("RIRO platform upgrade: return track removal failed at "+p[1]+": "+AIError.GetLastErrorString());
            RiroThirdRollback(id,plan,journal);return false;
        }
    }

    local terrain=RiroThirdTerrain(id,plan.pieces);
    if(terrain==null) {
        AILog.Warning("RIRO platform upgrade: loop terrain does not match the throat height.");
        RiroThirdRollback(id,plan,journal);return false;
    }
    if(terrain.targets.len()>0) {
        if(recovery.terrain_original.len()==0) {
            foreach(corner,_ in terrain.targets)
                recovery.terrain_original[corner] <- AITile.GetCornerHeight(corner,AITile.CORNER_N);
        }
        terrain.original=recovery.terrain_original;
        if(!terrain.Apply()) {
            AILog.Warning("RIRO platform upgrade: "+terrain.failure_detail);
            RiroThirdRollback(id,plan,journal);return false;
        }
    }

    foreach(p in plan.pieces) {
        if(AIRail.AreTilesConnected(p[0],p[1],p[2])) continue;
        if(!AIRail.BuildRail(p[0],p[1],p[2])) {
            AILog.Warning("RIRO platform upgrade: rail build failed at "+p[1]+": "+AIError.GetLastErrorString());
            RiroThirdRollback(id,plan,journal);return false;
        }
    }
    if(!recovery.station_done && !AIRail.IsRailStationTile(plan.station)) {
        if(!AIRail.BuildRailStation(plan.station,id.dir,1,id.length,AIStation.STATION_JOIN_ADJACENT)) {
            AILog.Warning("RIRO platform upgrade: station row failed: "+AIError.GetLastErrorString());
            RiroThirdRollback(id,plan,journal);return false;
        }
        recovery.station_done=true;
    }
    foreach(s in plan.signals) {
        local front=s[1],back=s[1]+(s[1]-s[0]);
        local type=s.len()>2 ? s[2] : AIRail.SIGNALTYPE_PBS_ONEWAY;
        // NONE marks a waiting point: no signal may face the platform here.
        if(type==AIRail.SIGNALTYPE_NONE) {
            if(AIRail.GetSignalType(s[0],front)!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(s[0],front);
            else if(AIRail.GetSignalType(s[0],back)!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(s[0],back);
            continue;
        }
        if(AIRail.GetSignalType(s[0],front)==type) continue;
        local old_front=AIRail.GetSignalType(s[0],front),old_back=AIRail.GetSignalType(s[0],back);
        if(old_front!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(s[0],front);
        else if(old_back!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(s[0],back);
        if(!AIRail.BuildSignal(s[0],front,type)) {
            AILog.Warning("RIRO platform upgrade: signal failed at "+s[0]+": "+AIError.GetLastErrorString());
            RiroThirdRollback(id,plan,journal);return false;
        }
    }
    foreach(p in plan.pieces)
        if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) {
            AILog.Warning("RIRO platform upgrade: loop connection missing at "+p[1]);
            RiroThirdRollback(id,plan,journal);return false;
        }
    journal.recovery=null;
    AILog.Info("RIRO: third platform added; return track rebuilt one row further out.");
    return true;
}

function RiroThirdRollback(id,plan,journal)
{
    local recovery=journal.recovery;
    if(recovery==null) return;
    foreach(s in recovery.signals) {
        if(AIRail.GetSignalType(s[0],s[1])!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(s[0],s[1]);
        if(s[2]!=AIRail.SIGNALTYPE_NONE) AIRail.BuildSignal(s[0],s[1],s[2]);
    }
    for(local i=recovery.pieces.len()-1;i>=0;i--) {
        local p=recovery.pieces[i];
        if(AIRail.AreTilesConnected(p[0],p[1],p[2])) AIRail.RemoveRail(p[0],p[1],p[2]);
    }
    foreach(p in recovery.removed)
        if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) AIRail.BuildRail(p[0],p[1],p[2]);
    // Put back any approach signal the switch column displaced.
    if("restore_signals" in plan) foreach(s in plan.restore_signals)
        if(AIRail.GetSignalType(s[0],s[1])==AIRail.SIGNALTYPE_NONE) AIRail.BuildSignal(s[0],s[1],s[2]);
    local earthwork=PairedTerrain();
    earthwork.original=recovery.terrain_original;
    if(!earthwork.Restore()) AILog.Warning("RIRO platform upgrade: could not fully restore terrain.");
    journal.recovery=null;
}

// Called after each optimiser review with the stations trains were observed
// queueing at. Upgrades at most one station per call; a failed plan cools
// down for a season. Hub sections are never touched.
function ExpandBlockedStations(b,optimiser,skip,journal)
{
    if(!("expansion_plan" in journal)) journal.expansion_plan <- null;
    if(!("recovery" in journal)) journal.recovery <- null;
    if(journal.recovery!=null && journal.expansion_plan!=null) {
        // Resume an interrupted upgrade before starting anything new.
        RiroThirdBuild(b,journal.expansion_plan.id,journal.expansion_plan,journal);
        return;
    }
    if(optimiser.blocked_stations.len()==0) return;
    local today=AIDate.GetCurrentDate();
    foreach(tile,wait in optimiser.blocked_stations) {
        if(skip!=null && tile in skip) continue;
        if(tile in StationExpansionCooldown && today<StationExpansionCooldown[tile]) continue;
        local id=RiroIdentify(b,tile);
        if(id==null) {StationExpansionCooldown[tile] <- today+180;continue;}
        local plan=RiroThirdPlan(b,id,wait);
        if(plan.reason!=null || RiroThirdTerrain(id,plan.pieces)==null) {
            AILog.Info("RIRO: station "+tile+" cannot take a third platform"+
                (plan.reason!=null ? ": "+plan.reason : " (terrain)"));
            // The switch scan may already have moved approach signals aside.
            if("restore_signals" in plan) foreach(s in plan.restore_signals)
                if(AIRail.GetSignalType(s[0],s[1])==AIRail.SIGNALTYPE_NONE) AIRail.BuildSignal(s[0],s[1],s[2]);
            StationExpansionCooldown[tile] <- today+180;
            continue;
        }
        AILog.Info("RIRO: train queued at station "+tile+" while all platforms were busy; adding a third platform.");
        journal.expansion_plan <- {id={tile=id.tile,dir=id.dir,length=id.length,off=id.off,exit=id.exit,
            lane=id.lane,mirror=id.mirror,entrance=id.entrance,origin=id.origin,forward=id.forward,
            side=id.side,junction=id.junction},pieces=plan.pieces,remove=plan.remove,
            signals=plan.signals,remove_signals=plan.remove_signals,station=plan.station,
            restore_signals=("restore_signals" in plan ? plan.restore_signals : []),reason=null};
        if(RiroThirdBuild(b,journal.expansion_plan.id,journal.expansion_plan,journal)) {
            StationExpansionCooldown[tile] <- today+365;
        } else StationExpansionCooldown[tile] <- today+180;
        return;
    }
}
