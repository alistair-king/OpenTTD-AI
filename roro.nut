// Optional through-platform loop on the outbound side of a terminus throat.
// The old X becomes an entrance fan and an independent return curve.
class RollThroughStation
{
    failure_reason="Loop does not fit";
    failure_tile=-1;
    failure_detail="";
    function Fail(reason,tile) {
        this.failure_reason=reason;this.failure_tile=tile;
        this.failure_detail=reason+" at "+tile;
        return false;
    }
    pieces = null;
    signals = null;
    built = null;
    changed_signals = null;
    remove = null;
    removed = null;
    mirrored = false;
    junction = null;
    terrain = null;
    terrain_original = null;
    constructor() { this.pieces=[]; this.signals=[]; this.built=[]; this.changed_signals=[]; this.remove=[]; this.removed=[]; this.mirrored=false; this.terrain_original={}; }

    function AddPath(tiles)
    {
        for(local i=1;i<tiles.len()-1;i++) this.pieces.append([tiles[i-1],tiles[i],tiles[i+1]]);
    }

    // Plan on the preferred side; if the loop does not fit there, retry with
    // the geometry mirrored to the opposite platform row before giving up.
    function PlanFlexible(entrance, lane, length)
    {
        local loop = RollThroughStation();
        if (loop.Plan(entrance, lane, length)) return loop;
        local first=loop.failure_detail;
        loop = RollThroughStation();
        if (loop.Plan(entrance, lane, length, true)) {
            loop.mirrored = true;
            return loop;
        }
        this.failure_reason=loop.failure_reason;
        this.failure_tile=loop.failure_tile;
        this.failure_detail="first side: "+first+"; mirrored side: "+loop.failure_detail;
        return null;
    }

    function Plan(entrance, lane, length, mirror = false, prepare = true)
    {
        local near=entrance.signals[lane];
        local other=entrance.signals[1-lane];
        local origin=near[1];
        local forward=near[1]-near[0];
        local side=near[1]-other[1];
        // Mirrored: wrap the return loop around the opposite platform row.
        if(mirror) side=-side;
        // Merge towards the inner platform before turning across both rows.
        // This leaves the return track directly beside the outer platform,
        // eliminating the unused row in the previous four-row footprint.
        this.AddPath([origin+(length-1)*forward,origin+length*forward,
            origin+(length+1)*forward,origin+(length+1)*forward-side,
            origin+(length+2)*forward-side]);
        this.AddPath([origin-side+(length-1)*forward,origin-side+length*forward,
            origin-side+(length+1)*forward,origin-side+(length+2)*forward]);
        local loop=[origin+(length+1)*forward-side,origin+(length+2)*forward-side,
            origin+(length+3)*forward-side,origin+(length+3)*forward,
            origin+(length+3)*forward+side];
        for(local u=length+2;u>=-2;u--) loop.append(origin+u*forward+side);
        loop.append(origin-2*forward);
        loop.append(origin-3*forward);
        this.AddPath(loop);
        foreach(endpoint in [near,other]) {
            // No waiting point after the fan: reserve through an available platform.
            this.signals.append([endpoint[0],endpoint[0]-forward,AIRail.SIGNALTYPE_NONE]);
            this.signals.append([endpoint[1]+length*forward,endpoint[1]+(length-1)*forward]);
        }
        // The loop's return side can hold a train clear of the platform exits.
        this.signals.append([origin+side,origin+forward+side]);
        // Signal the return straight after the compact turn.
        this.signals.append([origin+(length+1)*forward+side,origin+(length+2)*forward+side]);
        local junction=origin-2*forward;
        this.junction=junction;
        local incoming=junction-side;
        // Keep incoming -> both platforms, but disconnect the return curve
        // from the entrance fan. Opposite corner pieces can share this tile
        // without forming a crossing or a junction.
        this.remove.append([junction-forward,junction,junction+forward]);
        this.remove.append([incoming,junction,junction-forward]);
        this.remove.append([junction,incoming,incoming+forward]);
        return !prepare || this.PrepareTerrain();
    }

    // Read-only planning. Match the existing throat height, changing only
    // clear land; PairedTerrain rejects changes beside roads, rail or water.
    function PrepareTerrain()
    {
        this.terrain=PairedTerrain(3,160,40000);
        local height=AITile.GetCornerHeight(this.junction,AITile.CORNER_N);
        if(AITile.GetSlope(this.junction)!=AITile.SLOPE_FLAT) return this.Fail("Entrance not flat",this.junction);
        foreach(piece in this.pieces) {
            local tile=piece[1];
            if(!AIMap.IsValidTile(tile) || AIMap.DistanceManhattan(piece[0],tile)!=1 ||
                AIMap.DistanceManhattan(tile,piece[2])!=1) return this.Fail("Invalid loop geometry",tile);
            // A crossover or earlier construction step may already contain
            // this exact piece. Reuse owned matching rail, never foreign track.
            local existing=AITile.GetOwner(tile)==AICompany.ResolveCompanyID(AICompany.COMPANY_SELF) &&
                AIRail.IsRailTile(tile) && AIRail.AreTilesConnected(piece[0],tile,piece[2]);
            if(tile!=this.junction && !existing && (!AITile.IsBuildable(tile) || AITile.IsWaterTile(tile))) return this.Fail("Loop tile obstructed",tile);
            foreach(corner in this.terrain.Corners(tile)) {
                if(!this.terrain.SetHeight(corner,height)) return this.Fail("Terrain unsafe or limit",corner);
                this.terrain.desired[corner] <- height;
            }
            // Sloping tiles are checked by the real rail build after levelling.
            if(AITile.GetSlope(tile)==AITile.SLOPE_FLAT &&
                AITile.GetCornerHeight(tile,AITile.CORNER_N)==height) {
                local test=AITestMode();
                if(!existing && !AIRail.BuildRail(piece[0],tile,piece[2])) return this.Fail("Rail layout rejected",tile);
            }
        }
        return true;
    }

    function Restore()
    {
        foreach(signal in this.changed_signals) {
            if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_NONE)
                AIRail.RemoveSignal(signal[0],signal[1]);
            if(signal[2]!=AIRail.SIGNALTYPE_NONE) AIRail.BuildSignal(signal[0],signal[1],signal[2]);
            if(signal[3]!=AIRail.SIGNALTYPE_NONE) AIRail.BuildSignal(signal[0],signal[4],signal[3]);
        }
        for(local i=this.built.len()-1;i>=0;i--) {
            local p=this.built[i];
            if(AIRail.AreTilesConnected(p[0],p[1],p[2])) AIRail.RemoveRail(p[0],p[1],p[2]);
        }
        foreach(p in this.removed) if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) AIRail.BuildRail(p[0],p[1],p[2]);
        this.built.resize(0); this.changed_signals.resize(0); this.removed.resize(0);
        local earthwork=PairedTerrain();
        earthwork.original=this.terrain_original;
        if(!earthwork.Restore()) return false;
        this.terrain_original.clear();
        return true;
    }

    function Build(recovery = null, add_signals = true)
    {
        if(recovery!=null) {
            this.built=recovery.pieces; this.changed_signals=recovery.signals;
            if(!("removed" in recovery)) recovery.removed <- [];
            this.removed=recovery.removed;
            if(!("terrain_original" in recovery)) recovery.terrain_original <- {};
            this.terrain_original=recovery.terrain_original;
        }
        if(!EnsureMoney(40000)) return this.Fail("Insufficient funds",this.junction);
        if(!this.PrepareTerrain()) return false;
        if(this.terrain.targets.len()>0) {
            // Apply fills this shared, saved journal before its first mutation.
            this.terrain.original=this.terrain_original;
            if(!this.terrain.Apply()) {
                this.Fail(this.terrain.failure_reason,this.junction);
                this.failure_detail+="; "+this.terrain.failure_detail;
                this.Restore();return false;
            }
            AILog.Info("RIRO: levelled loop land to throat height; changed corners="+this.terrain.targets.len());
        }
        foreach(p in this.pieces) {
            if(AIRail.AreTilesConnected(p[0],p[1],p[2])) continue;
            this.built.append(p);
            if(!AIRail.BuildRail(p[0],p[1],p[2])) { this.Fail("Rail build failed",p[1]); this.Restore(); return false; }
        }
        foreach(p in this.remove) {
            if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) continue;
            this.removed.append(p);
            if(!AIRail.RemoveRail(p[0],p[1],p[2])) { this.Fail("Crossover removal failed",p[1]); this.Restore(); return false; }
        }
        if(!ParallelRailPieces(AIRail.GetRailTracks(this.junction))) { this.Fail("Return track not separate",this.junction); this.Restore(); return false; }
        foreach(signal in this.signals) {
            if(!add_signals) continue;
            local tile=signal[0], front=signal[1], back=tile+(tile-front);
            local old_front=AIRail.GetSignalType(tile,front), old_back=AIRail.GetSignalType(tile,back);
            this.changed_signals.append([tile,front,old_front,old_back,back]);
            if(old_front!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(tile,front);
            else if(old_back!=AIRail.SIGNALTYPE_NONE) AIRail.RemoveSignal(tile,back);
            local type=signal.len()>2?signal[2]:AIRail.SIGNALTYPE_PBS_ONEWAY;
            if((type!=AIRail.SIGNALTYPE_NONE && !AIRail.BuildSignal(tile,front,type)) ||
                AIRail.GetSignalType(tile,back)!=AIRail.SIGNALTYPE_NONE) { this.Fail("Signal placement failed",tile); this.Restore(); return false; }
        }
        foreach(p in this.pieces) if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) { this.Fail("Loop connection missing",p[1]); this.Restore(); return false; }
        AILog.Info("RIRO: separate entrance fan and return track verified.");
        return true;
    }
}
