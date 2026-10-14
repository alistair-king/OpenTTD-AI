// Saved, bounded cleanup jobs. Run only from the controller, never inside A*.
RetiredRailways <- null;
class RailwayRetirement
{
    jobs=null;
    completed=null;
    constructor(saved=null) {
        this.jobs=saved==null?[]:(typeof saved=="array"?saved:saved.jobs);
        this.completed=saved!=null && typeof saved=="table" ? saved.completed : [];
    }
    function Save() {return {jobs=this.jobs,completed=this.completed};}
    function Queue(record)
    {
        foreach(job in this.jobs) if(job.depot==record.depot) return;
        local seeds=[record.depot];
        foreach(st in [record.station_a,record.station_b])
            if(AIStation.IsValidStation(st)) seeds.append(AIStation.GetLocation(st));
        local towns=[];
        if((!("network" in record) || !record.network) && "cargo" in record &&
            (AICargo.HasCargoClass(record.cargo,AICargo.CC_PASSENGERS) || AICargo.HasCargoClass(record.cargo,AICargo.CC_MAIL)))
            foreach(st in [record.station_a,record.station_b]) if(AIStation.IsValidStation(st))
                towns.append(AITile.GetClosestTown(AIStation.GetLocation(st)));
        this.jobs.append({towns=towns,retry=0,depot=record.depot,front=seeds,seen={},tiles=[],scan=0,remove=0,ready=false});
    }
    function Rail(tile)
    {
        return AIMap.IsValidTile(tile) && AITile.GetOwner(tile)==AICompany.ResolveCompanyID(AICompany.COMPANY_SELF) &&
            AITile.HasTransportType(tile,AITile.TRANSPORT_RAIL);
    }
    function Snapshot(tile)
    {
        if(!this.Rail(tile)) return null;
        if(AIRail.IsRailDepotTile(tile)) return {tile=tile,kind="depot",front=AIRail.GetRailDepotFrontTile(tile)};
        if(AIRail.IsRailStationTile(tile)) return {tile=tile,kind="station",station=AIStation.GetStationID(tile),tracks=AIRail.GetRailStationDirection(tile)};
        if(AITunnel.IsTunnelTile(tile)) return {tile=tile,kind="tunnel",other=AITunnel.GetOtherTunnelEnd(tile)};
        if(AIBridge.IsBridgeTile(tile)) return {tile=tile,kind="bridge",other=AIBridge.GetOtherBridgeEnd(tile)};
        if(AIRail.IsRailTile(tile)) return {tile=tile,kind="rail",tracks=AIRail.GetRailTracks(tile)};
        return null;
    }
    function Ports(p)
    {
        local w=AIMap.GetMapSizeX();
        if(p.kind=="depot") return [p.front-p.tile];
        if(p.kind=="bridge" || p.kind=="tunnel") {
            local d=AIMap.GetTileX(p.tile)==AIMap.GetTileX(p.other)?w:1;
            return [p.other>p.tile?-d:d];
        }
        local out=[];
        foreach(d in [-1,1,-w,w]) {
            foreach(e in [-1,1,-w,w]) if(d!=e && (p.tracks&RailPiece(p.tile+d,p.tile,p.tile+e))!=0) {
                out.append(d);break;
            }
        }
        return out;
    }
    function Scan(job)
    {
        local count=0;
        while(job.scan<job.front.len() && count++<128) {
            local tile=job.front[job.scan++];
            if(tile in job.seen) continue;
            local p=this.Snapshot(tile);if(p==null) continue;
            job.seen[tile] <- true;job.tiles.append(p);
            if(p.kind=="bridge" || p.kind=="tunnel") job.front.append(p.other);
            foreach(d in this.Ports(p)) {
                local next=tile+d;
                if(!AIMap.IsValidTile(next) || AIMap.DistanceManhattan(tile,next)!=1) continue;
                local q=this.Snapshot(next);if(q==null) continue;
                foreach(e in this.Ports(q)) if(e==-d) {job.front.append(next);break;}
            }
            // Shared dual stations can have disconnected platform groups. Scan
            // both for retirement and upgrades, once per station per job.
            if(p.kind=="station") {
                if(!("stations" in job)) job.stations <- {};
                if(!(p.station in job.stations)) {
                    job.stations[p.station] <- true;
                    foreach(next,_ in AITileList_StationType(p.station,AIStation.STATION_TRAIN)) job.front.append(next);
                }
            }
        }
        job.ready=job.scan>=job.front.len();
    }
    function InUse(job)
    {
        local stations={};
        foreach(p in job.tiles) if(p.kind=="station") stations[p.station] <- true;
        foreach(id,_ in AIVehicleList()) {
            if(AIVehicle.GetLocation(id) in job.seen) return true;
            for(local i=0;i<AIOrder.GetOrderCount(id);i++) {
                local tile=AIOrder.GetOrderDestination(id,i);
                if(tile in job.seen) return true;
                if(AIMap.IsValidTile(tile) && AITile.IsStationTile(tile) && AIStation.GetStationID(tile) in stations) return true;
            }
        }
        return false;
    }
    function Remove(p)
    {
        local now=this.Snapshot(p.tile);
        if(now==null || now.kind!=p.kind) return true;
        if(p.kind=="station") {
            if(now.station!=p.station) return true;
            return AIRail.RemoveRailStationTileRectangle(p.tile,p.tile,false);
        }
        if(p.kind=="depot") return now.front!=p.front || AITile.DemolishTile(p.tile);
        if(p.kind=="bridge") return now.other!=p.other || AIBridge.RemoveBridge(p.tile);
        if(p.kind=="tunnel") return now.other!=p.other || AITunnel.RemoveTunnel(p.tile);
        // Remove rail only, preserving roads at level crossings.
        foreach(bit in [AIRail.RAILTRACK_NE_SW,AIRail.RAILTRACK_NW_SE,AIRail.RAILTRACK_NW_NE,
            AIRail.RAILTRACK_SW_SE,AIRail.RAILTRACK_NW_SW,AIRail.RAILTRACK_NE_SE])
            if((p.tracks&now.tracks&bit)!=0 && !AIRail.RemoveRailTrack(p.tile,bit)) return false;
        return true;
    }
    function Step()
    {
        if(this.jobs.len()==0) return false;
        local job=this.jobs[0];
        if(job.retry>AIDate.GetCurrentDate()) return false;
        if(!job.ready) {this.Scan(job);return true;}
        // Shared mail/freight services, and stopped trains, all protect rails.
        if(this.InUse(job)) {this.jobs.remove(0);return false;}
        local count=0;
        while(job.remove<job.tiles.len() && count++<24) {
            if(!this.Remove(job.tiles[job.remove])) {job.retry=AIDate.GetCurrentDate()+7;return false;}
            job.remove++;
        }
        if(job.remove>=job.tiles.len()) {
            AILog.Info("Retirement: removed unused railway, stations and depots ("+job.tiles.len()+" tiles).");
            this.completed.append(job);
            this.jobs.remove(0);
        }
        return true;
    }
}
