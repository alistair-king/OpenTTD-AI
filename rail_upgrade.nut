// Complete connected railways, scanned in bounded batches outside pathfinding.
ActiveRailUpgrade <- null;
class RailwayUpgrades
{
    state=null;
    owners=null;
    function Bind(owners) {this.owners=owners;ActiveRailUpgrade=this;}
    function Busy() {return this.state.job!=null && "migration" in this.state.job;}
    function Holds(id) {
        if(!this.Busy()) return false;
        foreach(e in this.state.job.migration.trains) if(e.old==id || e.fresh==id) return true;
        return false;
    }
    constructor(saved=null) {
        this.state=saved==null?{month=-1,seeds=[],seen={},job=null,next_tick=0}:saved;
        // AI ticks restart when loading; never retain an old absolute throttle.
        this.state.next_tick=0;
        // Older saves used a fleet-sized string. Restart only the scan when
        // loading it; already converted infrastructure remains untouched.
        if(this.state.job!=null && (!("fleet" in this.state.job) || typeof this.state.job.fleet!="array")) {
            this.state.job=null;this.state.seeds=[];this.state.seen={};this.state.month=-1;
        }
    }
    function Save() {return this.state;}
    function TrainUses(id,job,stations)
    {
        if(AIVehicle.GetLocation(id) in job.seen) return true;
        for(local i=0;i<AIOrder.GetOrderCount(id);i++) {
            local tile=AIOrder.GetOrderDestination(id,i);
            if(tile in job.seen) return true;
            if(AIMap.IsValidTile(tile) && AITile.IsStationTile(tile) && AIStation.GetStationID(tile) in stations) return true;
        }
        return false;
    }
    function ChooseType(job)
    {
        local stations={},trains=[];
        foreach(p in job.tiles) if(p.kind=="station") stations[p.station] <- true;
        foreach(id,_ in AIVehicleList()) if(AIVehicle.GetVehicleType(id)==AIVehicle.VT_RAIL && this.TrainUses(id,job,stations)) trains.append(id);
        if(trains.len()==0) return -1;
        local best=-1,speed=-1,speeds={};
        foreach(type,_ in AIRailTypeList()) {
            local ok=true;
            foreach(id in trains) for(local i=0;i<AIVehicle.GetNumWagons(id);i++) {
                local engine=AIVehicle.GetWagonEngineType(id,i);
                if(engine<0 || !AIEngine.CanRunOnRail(engine,type) ||
                    (!AIEngine.IsWagon(engine) && !AIEngine.HasPowerOnRail(engine,type))) {ok=false;break;}
            }
            local candidate=BestEngineSpeedOnRail(type);speeds[type] <- candidate;
            if(!ok) continue;
            if(candidate>0 && (candidate>speed || (candidate==speed && type>best))) {best=type;speed=candidate;}
        }
        // Never downgrade a newer section just because its faster engine retired.
        foreach(p in job.tiles) {
            local type=AIRail.GetRailType(p.tile);
            if(type in speeds && (speeds[type]>speed || (speeds[type]==speed && type>best))) return -1;
        }
        return best;
    }
    // Runtime owners are deliberately not saved; jobs contain only primitive data.
    function Owner(id) {
        if(this.owners!=null) foreach(o in this.owners) if(id in o.optimiser.trains) return o;
        return null;
    }
    function DeferMigration(job,reason)
    {
        AILog.Info("Rail upgrade: deferred component at "+job.front[0]+": "+reason);
        return false;
    }
    function MigrationTarget(type,speeds,existing)
    {
        local changed=false;
        foreach(old,_ in existing) {
            if(old==type) continue;
            local old_speed=old in speeds?speeds[old]:0;
            if(speeds[type]<old_speed || (speeds[type]==old_speed && type<old)) return false;
            changed=true;
        }
        return changed; // Allow finishing a mixed network, but never downgrade it.
    }
    function PrepareMigration(job)
    {
        if(this.owners==null) return false;
        local stations={},ids=[];
        foreach(p in job.tiles) if(p.kind=="station") stations[p.station] <- true;
        foreach(id,_ in AIVehicleList()) if(AIVehicle.GetVehicleType(id)==AIVehicle.VT_RAIL && this.TrainUses(id,job,stations)) {
            local o=this.Owner(id);
            if(o==null) return this.DeferMigration(job,"train "+id+" has no optimisation record");
            local r=o.optimiser.trains[id];
            // Queued work has not bought rolling stock: fleet replacement can
            // safely supersede it. Active transactions and sales must finish.
            if((r.phase!="observe" && r.phase!="pending" && r.phase!="engine") || r.replacement>=0 ||
                (r.single_route!=null && r.single_route.upgrade!=null))
                return this.DeferMigration(job,"train "+id+" has active work ("+r.phase+")");
            ids.append(id);
        }
        if(ids.len()==0) return false;
        local previous=AIRail.GetCurrentRailType(),best=-1,speed=-1,plans=null;
        local speeds={},existing={};
        foreach(type,_ in AIRailTypeList()) speeds[type] <- BestEngineSpeedOnRail(type);
        foreach(p in job.tiles) existing[AIRail.GetRailType(p.tile)] <- true;
        foreach(type,candidate in speeds) {
            if(!this.MigrationTarget(type,speeds,existing) || candidate<speed || (candidate==speed && type<=best)) continue;
            AIRail.SetCurrentRailType(type);
            local entries=[],ok=true;
            foreach(id in ids) {
                local r=this.Owner(id).optimiser.trains[id],buyer=TrainBuyer(r.cargo);
                local engine=buyer.BestEngine(),wagon=buyer.BestWagon();
                if(engine<0 || wagon<0) {ok=false;break;}
                local capacity=AIVehicle.GetCapacity(id,r.cargo),cap=AIEngine.GetCapacity(wagon);
                if(cap<=0) {ok=false;break;}
                local count=(capacity+cap-1)/cap;
                if(count<1) count=1;
                entries.append({old=id,fresh=-1,engine=engine,wagon=wagon,count=count,cargo=r.cargo,
                    depot=r.depot,max_length=r.max_length,orders=[],sent=false,committed=false,
                    built=false,attached=0,pending_wagon=-1});
            }
            if(ok) {best=type;speed=candidate;plans=entries;}
        }
        AIRail.SetCurrentRailType(previous);
        if(best<0) {
            local newer=false;
            foreach(type,_ in speeds) if(this.MigrationTarget(type,speeds,existing)) newer=true;
            return newer ? this.DeferMigration(job,"no replacement engine/wagon combination for every cargo") : false;
        }
        local budget=50000;
        foreach(e in plans) {
            budget+=AIEngine.GetPrice(e.engine)+e.count*AIEngine.GetPrice(e.wagon);
            for(local i=0;i<AIOrder.GetOrderCount(e.old);i++)
                e.orders.append([AIOrder.GetOrderDestination(e.old,i),AIOrder.GetOrderFlags(e.old,i)]);
        }
        foreach(p in job.tiles) {
            p.original_type <- AIRail.GetRailType(p.tile);
            if(p.original_type==best) continue;
            // Price clear tiles directly; occupied tiles retain a contingency.
            // Keep a rollback reserve. Preflight after gathering remains mandatory.
            local quoted=false,cost=0;
            {local test=AITestMode();local accounting=AIAccounting();
                quoted=AIRail.ConvertRailType(p.tile,p.tile,best);cost=accounting.GetCosts();}
            budget+=quoted ? (cost>0 ? cost*3 : 0) : 2000;
        }
        if(!EnsureMoney(budget) || AICompany.GetBankBalance(AICompany.COMPANY_SELF)<budget)
            return this.DeferMigration(job,"replacement budget "+budget+", available "+AICompany.GetBankBalance(AICompany.COMPANY_SELF));
        job.type=best;
        job.migration <- {reuse_depots=true,phase="gather",trains=plans,index=0,deadline=AIDate.GetCurrentDate()+365,budget=budget};
        AILog.Info("Rail upgrade: gathering "+plans.len()+" trains for complete network conversion to "+AIRail.GetName(best)+".");
        return true;
    }
    // Recover a completed running line with an old depot/fleet left behind.
    // This target may already be the newest available type: it is a repair,
    // not another technology upgrade.
    function PrepareDepotRecovery(job)
    {
        if(this.owners==null) return false;
        local target=-1,depots={},entries=[],stations={};
        foreach(p in job.tiles) {
            if(p.kind=="depot") {depots[p.tile] <- p;continue;}
            local type=AIRail.GetRailType(p.tile);
            if(target<0) target=type;
            if(type!=target) return false; // Do not guess across a mixed running line.
            if(p.kind=="station") stations[p.station] <- true;
        }
        if(target<0) return false;
        local previous=AIRail.GetCurrentRailType();AIRail.SetCurrentRailType(target);
        local ok=true,budget=100000;
        foreach(id,_ in AIVehicleList()) {
            if(AIVehicle.GetVehicleType(id)!=AIVehicle.VT_RAIL || !this.TrainUses(id,job,stations)) continue;
            local owner=this.Owner(id);
            if(owner==null) {ok=false;break;}
            local r=owner.optimiser.trains[id];
            if(!(r.depot in depots)) {ok=false;break;}
            local needs=AIRail.GetRailType(r.depot)!=target || !AIEngine.HasPowerOnRail(AIVehicle.GetEngineType(id),target);
            if(!needs) continue;
            if(r.replacement>=0 || r.phase=="sell" || r.phase=="sell_route" ||
                (r.single_route!=null && r.single_route.upgrade!=null)) {ok=false;break;}
            local buyer=TrainBuyer(r.cargo),engine=buyer.BestEngine(),wagon=buyer.BestWagon();
            if(engine<0 || wagon<0 || AIEngine.GetCapacity(wagon)<=0) {ok=false;break;}
            local cap=AIEngine.GetCapacity(wagon),count=(AIVehicle.GetCapacity(id,r.cargo)+cap-1)/cap;
            if(count<1) count=1;
            local oi=-1;foreach(i,o in this.owners) if(o==owner) {oi=i;break;}
            local orders=[];
            for(local i=0;i<AIOrder.GetOrderCount(id);i++) orders.append([AIOrder.GetOrderDestination(id,i),
                AIOrder.GetOrderFlags(id,i)&(AIOrder.IsGotoDepotOrder(id,i)?~AIOrder.OF_STOP_IN_DEPOT:-1)]);
            entries.append({old=id,fresh=-1,engine=engine,wagon=wagon,count=count,cargo=r.cargo,
                depot=r.depot,max_length=r.max_length,orders=orders,sent=false,turned=false,
                committed=false,built=false,attached=0,pending_wagon=-1,sold=false,
                owner_index=oi,record=clone r,service=("services" in owner && owner.services!=null && id in owner.services)?clone owner.services[id]:null});
            budget+=AIEngine.GetPrice(engine)+count*AIEngine.GetPrice(wagon);
        }
        AIRail.SetCurrentRailType(previous);
        if(!ok || entries.len()==0 || !EnsureMoney(budget) || AICompany.GetBankBalance(AICompany.COMPANY_SELF)<budget) return false;
        local selected={},sites=[];
        foreach(e in entries) if(!(e.depot in selected)) {selected[e.depot] <- true;sites.append(clone depots[e.depot]);}
        // Do not dismantle a depot containing untracked rolling stock.
        foreach(site in sites) foreach(id,_ in AIVehicleList_Depot(site.tile)) {
            local known=false;foreach(e in entries) if(e.old==id) known=true;
            if(!known) return false;
        }
        job.type=target;
        job.migration <- {direct=true,phase="recover_gather",trains=entries,depots=sites,deadline=AIDate.GetCurrentDate()+90};
        AILog.Warning("Rail upgrade: recovering "+entries.len()+" trains from mismatched depots; rebuilding depots as "+AIRail.GetName(target)+".");
        return true;
    }
    function RepairDepotConnections(site)
    {
        if(!AIRail.IsRailDepotTile(site.tile) || !AIRail.IsRailTile(site.front)) return;
        local tracks=AIRail.GetRailTracks(site.front),w=AIMap.GetMapSizeX();
        local axis=Abs(site.tile-site.front)==1?w:1;
        local straight=axis==1?AIRail.RAILTRACK_NE_SW:AIRail.RAILTRACK_NW_SE;
        if((tracks&straight)==0) return;
        local previous=AIRail.GetCurrentRailType();AIRail.SetCurrentRailType(AIRail.GetRailType(site.front));
        // Entry and exit need opposite curves. The former assembly depot had
        // only one, so its exit could face against the lane's one-way signals.
        foreach(d in [-axis,axis]) if(!AIRail.AreTilesConnected(site.front+d,site.front,site.tile)) {
            local ok=false;{local test=AITestMode();ok=AIRail.BuildRail(site.front+d,site.front,site.tile);}
            if(ok) AIRail.BuildRail(site.front+d,site.front,site.tile);
        }
        AIRail.SetCurrentRailType(previous);
    }
    function RebuildDepot(site,type)
    {
        if(AIRail.IsRailDepotTile(site.tile)) {
            if(AIRail.GetRailType(site.tile)==type) return true;
            if(!AITile.DemolishTile(site.tile)) return false;
        }
        local previous=AIRail.GetCurrentRailType();AIRail.SetCurrentRailType(type);
        local ok=AIRail.BuildRailDepot(site.tile,site.front);
        AIRail.SetCurrentRailType(previous);return ok;
    }
    function DepotRecoveryStep(job)
    {
        local m=job.migration;
        if(m.phase=="recover_gather") {
            local ready=true;
            foreach(e in m.trains) {
                if(!AIVehicle.IsValidVehicle(e.old)) {m.deadline=0;ready=false;continue;}
                if(AIVehicle.IsStoppedInDepot(e.old) && AIVehicle.GetLocation(e.old)==e.depot) continue;
                ready=false;
                if(!e.sent) for(local i=0;i<e.orders.len();i++) if(AIOrder.IsGotoDepotOrder(e.old,i) && e.orders[i][0]==e.depot) {
                    if(AIOrder.SetOrderFlags(e.old,i,(e.orders[i][1]&~AIOrder.OF_SERVICE_IF_NEEDED)|AIOrder.OF_STOP_IN_DEPOT) && AIOrder.SkipToOrder(e.old,i)) e.sent=true;
                    break;
                }
                if(AIVehicle.IsInDepot(e.old)) {
                    AIVehicle.StartStopVehicle(e.old);
                } else if(!e.turned && AIVehicle.GetCurrentSpeed(e.old)==0 &&
                    AIMap.DistanceManhattan(AIVehicle.GetLocation(e.old),e.depot)<=1) {
                    // A partly emerged engine must back fully into its old depot
                    // before OpenTTD permits selling the consist.
                    e.turned=AIVehicle.ReverseVehicle(e.old);
                    if(AIVehicle.GetState(e.old)==AIVehicle.VS_STOPPED) AIVehicle.StartStopVehicle(e.old);
                }
            }
            if(!ready) {
                if(AIDate.GetCurrentDate()>m.deadline) {
                    foreach(e in m.trains) if(AIVehicle.IsValidVehicle(e.old)) this.RestoreOrders(e.old,e.orders);
                    AILog.Warning("Rail upgrade: depot recovery deferred; train could not return fully inside its depot.");
                    this.state.job=null;
                }
                return;
            }
            m.phase="recover_sell";return;
        }
        if(m.phase=="recover_sell") {
            // Sell all old consists before buying any, because OpenTTD can
            // reuse their vehicle IDs for the replacements.
            foreach(e in m.trains) if(!e.sold) {
                if(AIVehicle.IsValidVehicle(e.old) && !AIVehicle.SellVehicle(e.old)) return;
                local owner=this.owners[e.owner_index];
                if(e.old in owner.optimiser.trains) delete owner.optimiser.trains[e.old];
                if("services" in owner && owner.services!=null && e.old in owner.services) delete owner.services[e.old];
                e.sold=true;return;
            }
            m.phase="recover_depots";return;
        }
        if(m.phase=="recover_depots") {
            foreach(site in m.depots) if(!this.RebuildDepot(site,job.type)) return;
            m.phase="recover_build";return;
        }
        if(m.phase=="recover_build") {
            foreach(e in m.trains) if(!e.built) {
                if(!AIVehicle.IsValidVehicle(e.fresh)) {
                    e.fresh=AIVehicle.BuildVehicle(e.depot,e.engine);return;
                }
                if(e.attached<e.count) {
                    if(!AIVehicle.IsValidVehicle(e.pending_wagon)) {e.pending_wagon=AIVehicle.BuildVehicle(e.depot,e.wagon);return;}
                    if(AIVehicle.GetLength(e.fresh)+AIVehicle.GetLength(e.pending_wagon)>e.max_length) {
                        if(!AIVehicle.SellVehicle(e.pending_wagon)) return;
                        e.pending_wagon=-1;e.count=e.attached;return;
                    }
                    if(!AIVehicle.MoveWagon(e.pending_wagon,0,e.fresh,AIVehicle.GetNumWagons(e.fresh)-1)) return;
                    e.pending_wagon=-1;e.attached++;return;
                }
                if(e.attached==0 || AIVehicle.GetCapacity(e.fresh,e.cargo)<=0) return;
                // Recreate orders from saved values; the old vehicle is gone.
                local i=AIOrder.GetOrderCount(e.fresh);
                if(i<e.orders.len()) {AIOrder.AppendOrder(e.fresh,e.orders[i][0],e.orders[i][1]);return;}
                local owner=this.owners[e.owner_index],r=e.record;
                r.phase="observe";r.replacement=-1;r.loss_years=0;r.observed_day=0;
                r.review_after=AIDate.GetCurrentDate()+90;r.last_station=AIStation.STATION_INVALID;
                r.trip_days <- 0;r.trip_departed <- -1;r.trip_destination <- false;r.trip_loading <- false;r.trip_observed <- -1;
                owner.optimiser.trains[e.fresh] <- r;
                if(e.service!=null) owner.services[e.fresh] <- e.service;
                e.built=true;return;
            }
            foreach(e in m.trains) if(AIVehicle.IsStoppedInDepot(e.fresh) && !AIVehicle.StartStopVehicle(e.fresh)) return;
            AILog.Info("Rail upgrade: depot recovery complete; replacement trains released from rebuilt depots.");
            this.state.job=null;
        }
    }
    function StageDepot(job)
    {
        local previous=AIRail.GetCurrentRailType();AIRail.SetCurrentRailType(job.type);
        local result=null,w=AIMap.GetMapSizeX();
        foreach(p in job.tiles) {
            if(p.kind!="rail") continue;
            // Avoid changing existing signals or junctions. A side depot joins
            // a plain running tile; the component is empty before construction.
            if(p.tracks!=AIRail.RAILTRACK_NE_SW && p.tracks!=AIRail.RAILTRACK_NW_SE) continue;
            local axis=p.tracks==AIRail.RAILTRACK_NE_SW?1:w,side=axis==1?w:1;
            if(AIRail.GetSignalType(p.tile,p.tile+axis)!=AIRail.SIGNALTYPE_NONE ||
                AIRail.GetSignalType(p.tile,p.tile-axis)!=AIRail.SIGNALTYPE_NONE) continue;
            foreach(d in [side,-side]) {
                local tile=p.tile+d;
                if(!AIMap.IsValidTile(tile) || AIMap.DistanceManhattan(tile,p.tile)!=1 || !AITile.IsBuildable(tile)) continue;
                local ok=false;
                {local test=AITestMode();ok=AIRail.BuildRailDepot(tile,p.tile);}
                if(ok) {result={tile=tile,front=p.tile,prev=p.tile-axis,original=p.tracks,built=false,connected=false};break;}
            }
            if(result!=null) break;
        }
        AIRail.SetCurrentRailType(previous);return result;
    }
    function RecreateOrders(entry)
    {
        // Depot demolition turns its orders into invalid orders, even if the
        // depot is rebuilt immediately. Recreate from the saved destinations.
        if(!("orders_cleared" in entry)) {
            if(AIOrder.GetOrderCount(entry.fresh)>0) {AIOrder.RemoveOrder(entry.fresh,0);return false;}
            entry.orders_cleared <- true;
        }
        local i=AIOrder.GetOrderCount(entry.fresh);
        if(i<entry.orders.len()) {AIOrder.AppendOrder(entry.fresh,entry.orders[i][0],entry.orders[i][1]);return false;}
        return true;
    }
    function RestoreOrders(id,orders)
    {
        if(AIOrder.GetOrderCount(id)!=orders.len()) return false;
        for(local i=0;i<orders.len();i++) if(!AIOrder.SetOrderFlags(id,i,orders[i][1])) return false;
        return true;
    }
    function MigrationStep(job)
    {
        local m=job.migration;
        if("direct" in m && m.direct) {this.DepotRecoveryStep(job);return;}
        if(m.phase=="gather") {
            local ready=true;
            foreach(e in m.trains) {
                if(!AIVehicle.IsValidVehicle(e.old)) {m.phase="rollback";m.index=0;return;}
                if(!e.sent) {
                    // Use the service's own depot, avoiding repeated toggle commands.
                    for(local i=0;i<e.orders.len();i++) if(AIOrder.IsGotoDepotOrder(e.old,i) && e.orders[i][0]==e.depot) {
                        if(AIOrder.SetOrderFlags(e.old,i,(e.orders[i][1]&~AIOrder.OF_SERVICE_IF_NEEDED)|AIOrder.OF_STOP_IN_DEPOT) &&
                            AIOrder.SkipToOrder(e.old,i)) e.sent=true;
                        break;
                    }
                }
                if(!AIVehicle.IsStoppedInDepot(e.old) || AIVehicle.GetLocation(e.old)!=e.depot) ready=false;
            }
            if(!ready) {
                if(AIDate.GetCurrentDate()>m.deadline) {
                    AILog.Warning("Rail upgrade: gathering timed out; a train could not reach its depot.");
                    m.phase="rollback";m.index=0;
                }
                return;
            }
            // Keep occupied old depots until the replacement fleet is ready.
            // Stage the new fleet in a separate depot on this same component.
            // Old saved jobs retain their staged transaction; new upgrades
            // reuse the existing service depots and their signalled approaches.
            if(!("reuse_depots" in m)) {
                local stage=this.StageDepot(job);
                if(stage==null) {m.phase="rollback";m.index=0;return;}
                m.stage <- stage;
            }
            local cost=0,ok=true;
            {local test=AITestMode();local accounting=AIAccounting();
                foreach(p in job.tiles) if(p.kind!="depot" && AIRail.GetRailType(p.tile)!=job.type &&
                    !AIRail.ConvertRailType(p.tile,p.tile,job.type)) {ok=false;break;}
                cost=accounting.GetCosts()*3;} // Include funds to undo conversion if needed.
            foreach(e in m.trains) cost+=AIEngine.GetPrice(e.engine)+e.count*AIEngine.GetPrice(e.wagon);
            if(!ok || !EnsureMoney(cost+50000) || AICompany.GetBankBalance(AICompany.COMPANY_SELF)<cost+50000) {
                AILog.Warning("Rail upgrade: conversion preflight or replacement budget failed; keeping the original fleet.");
                m.phase="rollback";m.index=0;return;
            }
            m.phase="convert";m.index=0;return;
        }
        if(m.phase=="convert" || m.phase=="rollback") {
            local rollback=m.phase=="rollback";
            if(rollback) foreach(e in m.trains) if(AIVehicle.IsValidVehicle(e.pending_wagon)) {
                if(!AIVehicle.SellVehicle(e.pending_wagon)) return;
                e.pending_wagon=-1;
            }
            if(rollback) foreach(e in m.trains) if(AIVehicle.IsValidVehicle(e.fresh)) {
                if(!AIVehicle.SellVehicle(e.fresh)) return;
                e.fresh=-1;
            }
            if(rollback && "stage" in m && m.stage.built) {
                local p=m.stage;
                if(AIRail.IsRailDepotTile(p.tile) && !AITile.DemolishTile(p.tile)) return;
                if(p.connected && (AIRail.GetRailTracks(p.front)&RailPiece(p.prev,p.front,p.tile))!=0 &&
                    !AIRail.RemoveRail(p.prev,p.front,p.tile)) return;
                p.built=false;p.connected=false;
            }
            local count=0;
            while(m.index<job.tiles.len() && count++<32) {
                local p=job.tiles[m.index],type=rollback?p.original_type:job.type;
                if((!rollback && p.kind=="depot") || (rollback && !RailwayRetirement().Rail(p.tile))) {m.index++;continue;}
                if(AIRail.GetRailType(p.tile)!=type && !AIRail.ConvertRailType(p.tile,p.tile,type)) {
                    if(!rollback) {m.phase="rollback";m.index=0;}
                    return;
                }
                m.index++;
            }
            if(m.index<job.tiles.len()) return;
            if(rollback) {
                foreach(e in m.trains) if(AIVehicle.IsValidVehicle(e.old)) {
                    if(!this.RestoreOrders(e.old,e.orders)) return;
                    if(AIVehicle.IsStoppedInDepot(e.old) && !AIVehicle.StartStopVehicle(e.old)) return;
                }
                AILog.Warning("Rail upgrade: deferred; original tracks and trains restored.");
                this.state.job=null;return;
            }
            if("reuse_depots" in m) {
                local sites=[];foreach(p in job.tiles) if(p.kind=="depot") sites.append(clone p);
                foreach(e in m.trains) {
                    local owner=this.Owner(e.old),oi=-1;
                    foreach(i,o in this.owners) if(o==owner) {oi=i;break;}
                    // Queued engine work may have armed a depot stop. The new
                    // engine has completed that work and must resume normal service.
                    for(local i=0;i<e.orders.len();i++) if(AIOrder.IsGotoDepotOrder(e.old,i))
                        e.orders[i][1]=e.orders[i][1]&~AIOrder.OF_STOP_IN_DEPOT;
                    e.owner_index <- oi;e.record <- clone owner.optimiser.trains[e.old];
                    e.service <- ("services" in owner && owner.services!=null && e.old in owner.services)?clone owner.services[e.old]:null;
                    e.sold <- false;
                }
                m.depots <- sites;m.direct <- true;m.phase="recover_sell";
                return;
            }
            m.phase="build";return;
        }
        if(m.phase=="build") {
            local stage=m.stage;
            if(!stage.built) {
                local previous=AIRail.GetCurrentRailType();AIRail.SetCurrentRailType(job.type);
                stage.built=AIRail.BuildRailDepot(stage.tile,stage.front);
                AIRail.SetCurrentRailType(previous);
                if(!stage.built) {m.phase="rollback";m.index=0;}
                return;
            }
            if(!stage.connected) {
                local previous=AIRail.GetCurrentRailType();AIRail.SetCurrentRailType(job.type);
                stage.connected=AIRail.BuildRail(stage.prev,stage.front,stage.tile);
                AIRail.SetCurrentRailType(previous);
                if(!stage.connected) {m.phase="rollback";m.index=0;}
                return;
            }
            foreach(e in m.trains) if(!e.built) {
                // Each purchase/attachment is journalled separately for save/load.
                if(e.fresh<0) {
                    e.fresh=AIVehicle.BuildVehicle(m.stage.tile,e.engine);
                    if(!AIVehicle.IsValidVehicle(e.fresh)) {m.phase="rollback";m.index=0;}
                    return;
                }
                if(e.attached<e.count) {
                    if(e.pending_wagon<0) {
                        e.pending_wagon=AIVehicle.BuildVehicle(m.stage.tile,e.wagon);
                        if(!AIVehicle.IsValidVehicle(e.pending_wagon)) {m.phase="rollback";m.index=0;}
                        return;
                    }
                    if(AIVehicle.GetLength(e.fresh)+AIVehicle.GetLength(e.pending_wagon)>e.max_length) {
                        if(!AIVehicle.SellVehicle(e.pending_wagon)) return;
                        e.pending_wagon=-1;e.count=e.attached;return;
                    }
                    if(!AIVehicle.MoveWagon(e.pending_wagon,0,e.fresh,AIVehicle.GetNumWagons(e.fresh)-1)) {
                        m.phase="rollback";m.index=0;return;
                    }
                    e.pending_wagon=-1;e.attached++;return;
                }
                local ok=e.attached>0 && AIVehicle.GetCapacity(e.fresh,e.cargo)>0 &&
                    AIVehicle.GetLength(e.fresh)<=e.max_length &&
                    AIOrder.CopyOrders(e.fresh,e.old) && this.RestoreOrders(e.fresh,e.orders);
                if(!ok) {m.phase="rollback";m.index=0;} else e.built=true;
                return;
            }
            m.phase="commit";return;
        }
        if(m.phase=="commit") {
            foreach(e in m.trains) if(!e.committed) {
                local owner=this.Owner(e.old);
                if(owner==null) return;
                if(AIVehicle.IsValidVehicle(e.old) && !AIVehicle.SellVehicle(e.old)) return;
                local r=owner.optimiser.trains[e.old];
                r.phase="observe";r.replacement=-1;r.loss_years=0;r.observed_day=0;
                r.review_after=AIDate.GetCurrentDate()+90;r.last_station=AIStation.STATION_INVALID;
                r.trip_days <- 0;r.trip_departed <- -1;r.trip_destination <- false;
                r.trip_loading <- false;r.trip_observed <- -1;
                owner.optimiser.trains[e.fresh] <- r;delete owner.optimiser.trains[e.old];
                if("services" in owner && owner.services!=null && e.old in owner.services) {
                    owner.services[e.fresh] <- owner.services[e.old];delete owner.services[e.old];
                }
                e.committed=true;return;
            }
            // Empty original depots can now be converted; never release a
            // replacement onto a component with an old depot still in service.
            foreach(p in job.tiles) if(p.kind=="depot" && AIRail.GetRailType(p.tile)!=job.type &&
                !this.RebuildDepot(p,job.type)) return;
            m.phase="restart";return;
        }
        if(m.phase=="restart") {
            foreach(e in m.trains) if(!this.RecreateOrders(e)) return;
            if("stage" in m) this.RepairDepotConnections(m.stage);
            // Release only after every service record points at its new consist.
            foreach(e in m.trains) if(AIVehicle.IsStoppedInDepot(e.fresh) && !AIVehicle.StartStopVehicle(e.fresh)) return;
            AILog.Info("Rail upgrade: replaced "+m.trains.len()+" complete trains and reopened network using "+AIRail.GetName(job.type)+".");
            this.state.job=null;
        }
    }
    function RunningReady(job,scanner)
    {
        foreach(p in job.tiles) if(p.kind!="depot" && scanner.Rail(p.tile) && AIRail.GetRailType(p.tile)!=job.type) return false;
        return true;
    }
    function FleetSignature()
    {
        // Save numbers, not one concatenated string: OpenTTD limits each
        // saved string to 254 characters. Include counts to delimit orders.
        local signature=[];
        foreach(id,_ in AIVehicleList()) if(AIVehicle.GetVehicleType(id)==AIVehicle.VT_RAIL) {
            local count=AIOrder.GetOrderCount(id);
            signature.append(id);signature.append(count);
            for(local i=0;i<count;i++) signature.append(AIOrder.GetOrderDestination(id,i));
        }
        return signature;
    }
    function SameFleet(a,b)
    {
        if(typeof a!="array" || typeof b!="array" || a.len()!=b.len()) return false;
        for(local i=0;i<a.len();i++) if(a[i]!=b[i]) return false;
        return true;
    }
    function RouteSignature(job)
    {
        // Engine renewal and unrelated routes must not restart this scan.
        // Track the distinct destinations of trains using this component.
        local stations={},destinations={};
        foreach(p in job.tiles) if(p.kind=="station") stations[p.station] <- true;
        foreach(id,_ in AIVehicleList()) if(AIVehicle.GetVehicleType(id)==AIVehicle.VT_RAIL && this.TrainUses(id,job,stations))
            for(local i=0;i<AIOrder.GetOrderCount(id);i++) destinations[AIOrder.GetOrderDestination(id,i)] <- true;
        local signature=[];foreach(tile,_ in destinations) signature.append(tile);
        signature.sort();return signature;
    }
    function RunBatch(blocked=null)
    {
        // Give maintenance a bounded slice before another long route search.
        // No sleeps and no extra optimiser reviews inside pathfinding.
        local deadline=AIController.GetTick()+160;
        for(local i=0;i<8 && AIController.GetTick()<deadline;i++) this.Step(true,blocked);
    }
    function Step(force=false,blocked=null)
    {
        if(!force && AIController.GetTick()<this.state.next_tick) return;
        this.state.next_tick=AIController.GetTick()+20;
        local scanner=RailwayRetirement(),s=this.state;
        if(s.job==null) {
            if(s.seeds.len()==0) {
                local month=AIDate.GetYear(AIDate.GetCurrentDate())*12+AIDate.GetMonth(AIDate.GetCurrentDate());
                if(s.month==month) return;
                s.month=month;s.seen={};
                foreach(id,_ in AIVehicleList()) if(AIVehicle.GetVehicleType(id)==AIVehicle.VT_RAIL)
                    for(local i=0;i<AIOrder.GetOrderCount(id);i++) {
                        local tile=AIOrder.GetOrderDestination(id,i);
                        if(scanner.Rail(tile)) s.seeds.append(tile);
                    }
            }
            while(s.seeds.len()>0) {
                local tile=s.seeds.pop();
                if(tile in s.seen || !scanner.Rail(tile)) continue;
                s.job={fleet=[],front=[tile],seen={},tiles=[],scan=0,ready=false,index=0,type=-1,converted=0,failed=0,phase=0};
                break;
            }
            if(s.job==null) return;
        }
        local job=s.job;
        if("migration" in job) {this.MigrationStep(job);return;}
        if(!job.ready) {scanner.Scan(job);return;}
        if(blocked!=null) foreach(tile in blocked) if(tile in job.seen) {
            foreach(t,_ in job.seen) s.seen[t] <- true;
            this.DeferMigration(job,"construction is still using this component");
            s.job=null;return; // Defer this component, not the whole company.
        }
        foreach(p in job.tiles) if(p.kind=="depot") this.RepairDepotConnections(p);
        local signature=this.RouteSignature(job);
        if(!("route_snapshot" in job)) {job.fleet=signature;job.route_snapshot <- true;}
        else if(!this.SameFleet(job.fleet,signature)) {
            // Only this component needs rescanning; retain the rest of the sweep.
            local seed=job.front[0];
            s.job={fleet=[],front=[seed],seen={},tiles=[],scan=0,ready=false,index=0,type=-1,converted=0,failed=0,phase=0};
            return;
        }
        if(job.type<0) {
            foreach(tile,_ in job.seen) s.seen[tile] <- true;
            if(this.PrepareDepotRecovery(job) || this.PrepareMigration(job)) return;
            job.type=this.ChooseType(job);
            if(job.type<0) {s.job=null;return;}
            local needs_work=false;
            foreach(p in job.tiles) if(scanner.Rail(p.tile) && AIRail.GetRailType(p.tile)!=job.type) {needs_work=true;break;}
            if(!needs_work) {s.job=null;return;}
        }
        // Recheck fleet compatibility across save/load, purchases and renewals.
        if(this.ChooseType(job)!=job.type) {s.job=null;return;}
        if(job.phase==1 && !this.RunningReady(job,scanner)) {job.failed++;job.index=job.tiles.len();}
        local count=0;
        while(job.index<job.tiles.len() && count++<32) {
            local p=job.tiles[job.index++];
            if(!scanner.Rail(p.tile)) continue;
            // Depots are last: never offer a new electric engine before its
            // full route, including stations and bridge/tunnel ends, is ready.
            if((p.kind=="depot")!=(job.phase==1)) continue;
            if(AIRail.GetRailType(p.tile)==job.type) continue;
            local cost=0,ok=false;
            {local test=AITestMode();local accounting=AIAccounting();
                ok=AIRail.ConvertRailType(p.tile,p.tile,job.type);cost=accounting.GetCosts();}
            if(!ok || !EnsureMoney(cost+10000) || !AIRail.ConvertRailType(p.tile,p.tile,job.type)) {job.failed++;continue;}
            job.converted++;
        }
        if(job.index<job.tiles.len()) return;
        if(job.phase==0 && job.failed==0) {
            if(this.RunningReady(job,scanner)) {job.phase=1;job.index=0;return;}
            job.failed++;
        }
        if(job.converted>0 || job.failed>0) AILog.Info("Rail upgrade: "+AIRail.GetName(job.type)+", converted="+job.converted+
            ", pending="+job.failed+"; complete-route scan includes stations, loops, junctions and depots.");
        // Failed tiles are retried on the next monthly sweep, never mistaken
        // for completion because another tile already has the desired type.
        s.job=null;
    }
}
