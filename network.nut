// Shared freight infrastructure; only primitive network data is saved.
function NetworkSegment(f)
{
    local segment={a=PackRailPath(f.path),z=PackRailPath(f.secondary.path),
        start=f.start,goal=f.goal,start2=f.secondary.start,goal2=f.secondary.goal,outbound=f.outbound};
    if("grade" in f) segment.grade <- f.grade;
    if("permanent_single" in f) segment.permanent_single <- true;
    return segment;
}
// Restore junction geometry before its old signals: extra crossing pieces can
// make a previously valid signal unsuitable. Every phase remains saveable.
function RestoreNetworkUpgrade(data)
{
    if(!("original_signals" in data)) {
        if(data.upgrade==null) return true;
        foreach(s in data.upgrade.signals) {
            foreach(front in [s[1],s[2]])
                if(AIRail.GetSignalType(s[0],front)!=AIRail.SIGNALTYPE_NONE && !AIRail.RemoveSignal(s[0],front)) return false;
        }
        // A tile can be signalled, then cleared again for a depot in one build.
        // Restore only its first (pre-construction) state, not intermediate signals.
        local originals=[],seen={};
        foreach(s in data.upgrade.signals) {
            local key=s[0]+":"+(s[1]<s[2]?s[1]:s[2]);
            if(key in seen) continue;
            seen[key] <- true;originals.append(s);
        }
        data.original_signals <- originals;
        data.upgrade.signals=[];
    }
    if(!RestoreSingleUpgrade(data)) return false;
    while(data.original_signals.len()>0) {
        local s=data.original_signals.top();
        // Older saved journals may contain intermediate signals on removed track.
        if(!AIRail.IsRailTile(s[0])) {data.original_signals.pop();continue;}
        if(s[3]!=AIRail.SIGNALTYPE_NONE && AIRail.GetSignalType(s[0],s[1])!=s[3] && !AIRail.BuildSignal(s[0],s[1],s[3])) return false;
        if(s[4]!=AIRail.SIGNALTYPE_NONE && AIRail.GetSignalType(s[0],s[2])!=s[4] && !AIRail.BuildSignal(s[0],s[2],s[4])) return false;
        data.original_signals.pop();
    }
    return true;
}
class NetworkBackbone extends CoalRoutes
{
    completed=null; network=null;
    single_first=false;
    // A usable backbone earns revenue even when no future junction fits.
    // CoalRoutes accepts it; branch planning handles the lack of junctions later.
    function ServiceBuilt(found,a,z,train)
    {
        this.completed={segment=NetworkSegment(found),mine={tile=a.tile,dir=a.dir,platforms=StationPlatforms(a)},mill={tile=z.tile,dir=z.dir,platforms=StationPlatforms(z)},
            train=train,depot=this.services[train].depot};
        // Branch orientation needs to know which end of each segment serves the cargo.
        this.completed.segment.goal_station <- z.tile;
        if("dual" in z) this.completed.dual <- z.dual;
    }
}
// A farm can seed a network without any ore or steel infrastructure.
class FarmBackbone extends NetworkBackbone
{
    allow_single_station=false; // Grain and livestock require two trains.
    function Sites(industry,target,loading)
    {
        local label=loading && AIIndustry.GetLastMonthProduction(industry,FreightCargo("LVST"))>AIIndustry.GetLastMonthProduction(industry,FreightCargo("GRAI")) ? "LVST":"GRAI";
        local helper=CoalRoutes(this.builder,null,label);
        local candidates=helper.Sites(industry,target,loading),result=[];
        local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
        foreach(site in candidates) {
            if(loading) {
                if(this.network.FarmSiteCargoes(site,true)) result.append(site);
                continue;
            }
            local size=StationFootprint(site.dir,this.builder.platform_length),ok=true;
            foreach(c in this.network.FarmCargoes()) {
                local amount=loading ? AITile.GetCargoProduction(site.tile,c,size[0],size[1],radius) :
                    AITile.GetCargoAcceptance(site.tile,c,size[0],size[1],radius);
                if(amount<(loading?1:8)) ok=false;
            }
            if(ok) result.append(site);
        }
        return result;
    }
    function BuyInitialTrain(depot,a,z,source)
    {
        this.network.state.bootstrap <- [];
        foreach(c in this.network.FarmCargoes()) {
            local train=this.network.BuyBranchTrain(c,depot,a,z,source);
            if(train<0) {
                foreach(id in this.network.state.bootstrap) if(AIVehicle.IsValidVehicle(id)) AIVehicle.SellVehicle(id);
                this.network.state.bootstrap=[];
                return -1;
            }
            this.network.state.bootstrap.append(train);
        }
        return this.network.state.bootstrap[0];
    }
}
// A goods outlet need not share the factory's inbound tracks or station.
class FactoryGoodsRoute extends CoalRoutes
{
    continuation=true;
    network=null;
    // Reserve both running lines before town growth blocks the return route.
    single_first=false;
    function DestinationIsIndustry() {return false;}
    function DestinationValid(target) {return AITown.IsValidTown(target);}
    function DestinationLocation(target) {return AITown.GetLocation(target);}
    function ConnectionPlanKey(source,target) {return "factory-goods:"+source+":"+target;}
    function Sites(endpoint,target,loading)
    {
        local candidates=loading ? CoalRoutes(this.builder,null,"GOOD").Sites(endpoint,target,true) :
            this.network.CitySites(endpoint,target);
        return candidates; // RIRO first, then reversing terminus, then compact fallback.
    }
    function ServiceBuilt(found,a,z,train)
    {
        local record=this.optimiser.trains[train];
        record.network <- true;
        this.network.optimiser.trains[train] <- record;
        this.network.state.goods_outlet <- {source=a.tile,destination=z.tile,depot=record.depot};
        // Track it for maintenance, but do not advertise junctions on a disconnected line.
        local segment=NetworkSegment(found);segment.goal_station <- z.tile;
        this.network.state.segments.append(segment);
        this.network.state.stations.append({tile=z.tile,dir=z.dir,platforms=StationPlatforms(z)});
        this.network.state.stage=this.network.LastStage();
        this.network.state.goods_standalone <- false;
        this.network.QueueFarmExpansion();
        AILog.Info(this.source_hub!=null ? "Factory goods: shared pickup section and city service commissioned." : "Factory goods: separate factory station and city service commissioned.");
    }
}
// Steel is an independent mill -> factory service, just like the goods outlet.
class SteelRoute extends CoalRoutes
{
    continuation=true;
    network=null;
    single_first=true;
    function ConnectionPlanKey(source,target) {return "mill-steel:"+source+":"+target;}
    function ServiceBuilt(found,a,z,train)
    {
        local record=this.optimiser.trains[train];
        record.network <- true;
        this.network.optimiser.trains[train] <- record;
        this.network.state.steel_outlet <- {source=a.tile,destination=z.tile,depot=record.depot};
        if("dual" in z) {
            if(!("hubs" in this.network.state)) this.network.state.hubs <- {};
            this.network.state.hubs[this.services[train].target] <- z.dual;
            this.network.state.dual_priority <- true;
        }
        // Ore-line junctions cannot deliver farm traffic to this separate factory.
        // Keep ore junctions; branch selection filters by connected component.
        local segment=NetworkSegment(found);segment.goal_station <- z.tile;
        // Maintenance knows this line, but its track is not joined to the ore line.
        this.network.state.segments.append(segment);
        this.network.state.stations.append({tile=z.tile,dir=z.dir,platforms=StationPlatforms(z)});
        this.network.state.stage=2;
        this.network.state.retry=0;
        AILog.Info(this.source_hub!=null ? "Steel: shared mill pickup section and factory service commissioned; goods outlet is next." : "Steel: separate mill station and factory service commissioned; goods outlet is next.");
    }
}
class FreightNetwork
{
    builder=null; optimiser=null; passenger_optimiser=null; state=null;
    source_label="IORE"; excluded_sources=null; retry_deferred=false;
    production_month=null; detour_check_day=null;
    convert_month=null;
    // Sibling networks of the same manager, for cross-network delivery
    // (steel feeding a factory input line built by the farm chain). Never
    // saved; the manager re-wires the reference after loading.
    siblings=null;
    // A farm qualifies for a branch when it produces at least this much of
    // either grain or livestock. Farms start well below other industries, so
    // this is deliberately low (the standard freight test is far higher).
    farm_min_production=50;
    constructor(length,saved=null,label="IORE")
    {
        this.source_label=saved!=null && "source_label" in saved ? saved.source_label : label;
        this.builder=RouteBuilder(length); this.builder.single_first=false;
        // Preserve shared-network geometry: the stronger goal heuristic can
        // choose a first line that makes its paired return/branch harder to fit.
        this.builder.entrance_guidance=false;
        if(saved!=null && "planning_history" in saved) this.builder.planning_history=saved.planning_history;
        this.builder.start_run=3;
        this.builder.use_hierarchy=false; this.builder.use_aystar=false;
        this.state=saved==null ? {chain=null,segments=[],stations=[],junctions=[],stage=0,depot=-1,
            failed={},transaction=null,held=[],retry=0} : saved.state;
        if(!("production_policy" in this.state)) this.state.production_policy <- IndustryProductionPolicy();
        this.production_month=null;
        this.optimiser=ServiceOptimiser(TrainBuyer(FreightCargo(this.source_label=="FARM"?"GRAI":this.source_label)),saved==null?null:saved.trains);
        if(!("hold_since" in this.state)) this.state.hold_since <- -1;
        if(!("post_goods_farms" in this.state))
            this.state.post_goods_farms <- (this.source_label=="FARM" || this.source_label=="IORE") && this.state.stage>=this.LastStage();
        if(saved!=null && "pending" in saved) {
            this.builder.pending_stations=saved.pending;
            if(!("plan" in this.state) || this.state.plan==null) this.builder.ReleasePendingStations();
        }
    }
    function Save() { return {planning_history=this.builder.planning_history,source_label=this.source_label,state=this.state,trains=this.optimiser.Save(),pending=SavedStationReservations(this.builder.pending_stations)}; }
    function Review()
    {
        if("hubs" in this.state) foreach(industry,hub in this.state.hubs) {
            local status="pickup_status" in hub ? hub.pickup_status : "Waiting for route";
            local completed=this.state.chain!=null && (this.source_label=="IORE" && industry==this.state.chain.mill ?
                this.state.stage>=2 : this.state.stage>=this.LastStage());
            if(completed || hub.used || !AIIndustry.IsValidIndustry(industry) || !AIRail.IsRailStationTile(hub.pickup.tile)) status=null;
            DualPickupStatus(hub,status);
        }
        if(this.state.transaction==null && "plan" in this.state && this.state.plan!=null &&
            this.state.hold_since>=0 && AIDate.GetCurrentDate()-this.state.hold_since>=180)
            this.AbortDepotWait();
        if(this.state.transaction==null && (!("plan" in this.state) || this.state.plan==null) && this.state.held.len()>0) this.ResumeHeld();
        if(this.state.transaction==null && this.state.held.len()==0) {
            this.UpdateProductionNotes();
            this.optimiser.Review();
            // A train queued on a station throat means the station has
            // outgrown its platforms. Shared dual-hub sections are excluded:
            // their footprints belong to the hub's pickup and delivery sides.
            local skip={};
            if("hubs" in this.state) foreach(_,hub in this.state.hubs) {
                foreach(t in hub.reserved) skip[t] <- true;
                foreach(t in hub.delivery_reserved) skip[t] <- true;
                skip[hub.pickup.tile] <- true;
            }
            ExpandBlockedStations(this.builder,this.optimiser,skip,this.state);
            this.ObserveDetours();
        }
        if(this.passenger_optimiser!=null) this.passenger_optimiser.Review();
    }
    // The fastest rail type every vehicle on this network can run on. Scoped
    // to this network's own fleet; independent new routes choose separately.
    function NetworkRailType()
    {
        local best=-1,best_speed=-1;
        foreach(type,_ in AIRailTypeList()) {
            local ok=true;
            foreach(id,_ in this.optimiser.trains) {
                if(!AIVehicle.IsValidVehicle(id)) continue;
                if(!AIEngine.CanRunOnRail(AIVehicle.GetEngineType(id),type)) {ok=false;break;}
                for(local i=1;i<AIVehicle.GetNumWagons(id);i++) {
                    local wagon=AIVehicle.GetWagonEngineType(id,i);
                    if(wagon!=-1 && !AIEngine.CanRunOnRail(wagon,type)) {ok=false;break;}
                }
                if(!ok) break;
            }
            if(!ok) continue;
            local speed=BestEngineSpeedOnRail(type);
            if(speed>best_speed){best_speed=speed;best=type;}
        }
        return best;
    }
    // Once per game day: an empty train touching a backbone-end station that
    // is not its pickup is running a mirrored branch junction. The service
    // keeps working via the far-end turnaround, but the line is named so it
    // can be rebuilt when space allows.
    function ObserveDetours()
    {
        local today=AIDate.GetCurrentDate();
        if(today==this.detour_check_day) return;
        this.detour_check_day=today;
        if(this.state.stations.len()<2) return;
        local ends={};
        ends[AIStation.GetStationID(this.state.stations[0].tile)] <- true;
        ends[AIStation.GetStationID(this.state.stations[1].tile)] <- true;
        foreach(id,record in this.optimiser.trains) {
            if(!AIVehicle.IsValidVehicle(id)) continue;
            local st=AIStation.GetStationID(AIVehicle.GetLocation(id));
            if(st==AIStation.STATION_INVALID) continue;
            if(AIVehicle.GetCargoLoad(id,this.optimiser.BuyerFor(record).cargo)>0 ||
                st==record.station_a || st==record.station_b) {
                if("detour_seen" in record) delete record.detour_seen; continue;
            }
            if((st in ends) && !("detour_seen" in record && record.detour_seen)) {
                record.detour_seen <- true;
                AILog.Warning("Freight network: train " + id + " returns to " +
                    AIStation.GetName(record.station_a) + " via a far-end turnaround; its branch junction is mirrored.");
            }
        }
    }
    function Produces(industry,cargo)
    {
        local outputs=IndustryOutputs(industry);
        if(outputs==null) return false;
        foreach(c,_ in outputs) if(c==cargo) return true;
        return false;
    }
    function OnIndustryOpened(industry)
    {
        // A newcomer can complete an otherwise unbuildable chain; re-check now.
        if(this.state.stage==0 && this.state.retry>AIDate.GetCurrentDate()) this.state.retry=AIDate.GetCurrentDate();
    }
    function OnIndustryClosed(industry)
    {
        foreach(id,record in this.optimiser.trains)
            if(("source_industry" in record && record.source_industry==industry) ||
                ("target_industry" in record && record.target_industry==industry)) this.optimiser.ForceSale(id);
        if(this.state.chain==null) return;
        local dead={};
        if(this.state.chain.mine==industry && this.state.stations.len()>0)
            dead[AIStation.GetStationID(this.state.stations[0].tile)] <- true;
        if(this.state.chain.mill==industry && this.state.stations.len()>1)
            dead[AIStation.GetStationID(this.state.stations[1].tile)] <- true;
        if("factory" in this.state.chain && this.state.chain.factory==industry && this.state.stations.len()>this.FactoryIndex())
            dead[AIStation.GetStationID(this.state.stations[this.FactoryIndex()].tile)] <- true;
        foreach(field in ["mines","forests","mills"]) if(field in this.state && industry in this.state[field])
            dead[AIStation.GetStationID(this.state[field][industry].tile)] <- true;
        if("farms" in this.state && industry in this.state.farms)
            dead[AIStation.GetStationID(this.state.farms[industry].tile)] <- true;
        // Legacy separate outlets have their own station, outside the chain's
        // original inbound footprint. Match those endpoints as well.
        if("steel_outlet" in this.state) {
            if(this.state.chain.mill==industry) dead[AIStation.GetStationID(this.state.steel_outlet.source)] <- true;
            if("factory" in this.state.chain && this.state.chain.factory==industry)
                dead[AIStation.GetStationID(this.state.steel_outlet.destination)] <- true;
        }
        if("goods_outlet" in this.state &&
            (("factory" in this.state.chain ? this.state.chain.factory : this.state.chain.mill)==industry))
            dead[AIStation.GetStationID(this.state.goods_outlet.source)] <- true;
        if(AIStation.STATION_INVALID in dead) delete dead[AIStation.STATION_INVALID];
        foreach(id,record in this.optimiser.trains)
            if(("target_industry" in record && record.target_industry==industry) || record.station_a in dead || record.station_b in dead ||
                ("source_industry" in record && record.source_industry==industry)) this.optimiser.ForceSale(id);
    }
    function UpdateProductionNotes()
    {
        local today=AIDate.GetCurrentDate();
        local month=AIDate.GetYear(today)*12+AIDate.GetMonth(today);
        if(month==this.production_month) return;
        this.production_month=month;
        foreach(id,record in this.optimiser.trains) {
            if(!("source_industry" in record) || !AIIndustry.IsValidIndustry(record.source_industry)) continue;
            local level=AIIndustry.GetLastMonthProduction(record.source_industry,record.cargo);
            if("production_level" in record) record.production_level=level; else record.production_level <- level;
            if(!("production_baseline" in record)) record.production_baseline <- level;
        }
    }
    function FactoryIndex() {return this.source_label=="FARM"?1:2;}
    function FarmCargoes() { return [FreightCargo("GRAI"),FreightCargo("LVST")]; }
    function FarmSiteCargoes(site,loading)
    {
        // Farms start with far lower output than other industries, so the
        // standard test is halved for them: half the acceptance level, and
        // only one of the two cargoes (grain or livestock) needs to qualify.
        local size=StationFootprint(site.dir,this.builder.platform_length);
        local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
        local best=0;
        foreach(cargo in this.FarmCargoes()) {
            if(cargo<0) continue;
            local value=loading ?
                AITile.GetCargoProduction(site.tile,cargo,size[0],size[1],radius) :
                AITile.GetCargoAcceptance(site.tile,cargo,size[0],size[1],radius);
            if(value>best) best=value;
        }
        return best>=(loading?1:4);
    }
    function FarmProductionEligible(grain,livestock)
    {
        local minimum=IndustryProductionMinimum(this.state.production_policy,this.farm_min_production);
        return grain>minimum || livestock>minimum;
    }
    function TryFarm()
    {
        if((this.source_label!="IORE" && this.source_label!="FARM") || this.state.stage<this.FactoryIndex() || !this.FarmSiteCargoes(this.state.stations[this.FactoryIndex()],false)) return false;
        if(!("farms" in this.state)) this.state.farms <- {};
        local cargoes=this.FarmCargoes(),factory=this.state.chain.factory;
        foreach(c in cargoes) {local buyer=TrainBuyer(c);if(buyer.BestEngine()<0 || buyer.BestWagon()<0) return false;}
        local choices=[];
        foreach(industry,_ in AIIndustryList()) {
            if(industry in this.state.farms || (this.excluded_sources!=null && industry in this.excluded_sources)) continue;
            local grain=AIIndustry.GetLastMonthProduction(industry,cargoes[0]);
            local livestock=AIIndustry.GetLastMonthProduction(industry,cargoes[1]);
            // Either cargo must exceed the current cutoff; combined-production ranking
            // still favours mixed farms.
            if(!this.FarmProductionEligible(grain,livestock) || RivalIndustryStation(industry)) continue;
            local distance=AIMap.DistanceManhattan(AIIndustry.GetLocation(industry),AIIndustry.GetLocation(factory));
            if(!IndustryDistanceAllowed(distance,AIRail.GetRailType(this.state.depot))) continue;
            local key="farm:"+industry;
            if(this.FailedChoice(key)) continue;
            choices.append({industry=industry,score=(grain+livestock)*1000/(distance+1)});
        }
        choices.sort(function(a,b){return a.score>b.score?-1:a.score<b.score?1:0;});
        if(choices.len()==0) return false;
        local farm=choices[0].industry;
        AILog.Info("Freight network: planning farm grain and livestock -> existing factory.");
        if(!this.BuildBranch(farm,true,cargoes[0],true)) {
            if(this.builder.planning_timed_out) this.state.retry=AIDate.GetCurrentDate()+7;
            else this.state.failed["farm:"+farm] <- true;
        }
        return true;
    }
    // Reuse the factory for additional farms. Never replace
    // an in-progress goods plan or interfere with junction recovery.
    function TryBuildFarm()
    {
        if(this.source_label=="FARM" && this.state.stage==0) return this.TryBuild();
        if((this.source_label!="IORE" && this.source_label!="FARM") || this.state.stage<this.FactoryIndex()) return false;
        if(this.state.transaction!=null || this.state.held.len()>0 ||
            ("plan" in this.state && this.state.plan!=null)) {
            if("plan" in this.state && this.state.plan!=null && "farm" in this.state.plan)
                return this.TryBuild();
            return false;
        }
        if(!this.FarmExpansionPending() || !this.builder.ReleasePendingStations()) return false;
        return this.TryFarm();
    }
    // Incoming branches share the receiving station, not the separate onward
    // outlet. Steel feeders deliver onto a factory's existing grain/livestock
    // input line instead of building a second line and station.
    function IsSteelFeeder(cargo) {return cargo!=null && cargo>=0 && cargo==FreightCargo("STEL");}
    function IsRawFeeder(cargo) {return cargo!=null && cargo>=0 && (cargo==FreightCargo("IORE") || cargo==FreightCargo("WOOD"));}
    function FeederSources(cargo) {return cargo==FreightCargo("WOOD")?"forests":cargo==FreightCargo("IORE")?"mines":this.IsSteelFeeder(cargo)?"mills":"farms";}
    function FeederStationIndex(cargo) {return this.IsRawFeeder(cargo) ? 1 : this.FactoryIndex();}
    function FeederIndustry(cargo) {return this.IsRawFeeder(cargo) ? this.state.chain.mill : this.state.chain.factory;}
    function FeederKey(source,cargo) {return this.IsRawFeeder(cargo) ? (cargo==FreightCargo("WOOD")?"wood-feed:":"ore-feed:")+this.state.chain.mill+":"+source : this.IsSteelFeeder(cargo) ? "steel-feed:"+source : "farm:"+source;}
    function FeederCargoes(cargo) {return this.IsRawFeeder(cargo) || this.IsSteelFeeder(cargo) ? [cargo] : this.FarmCargoes();}
    function FeederSiteValid(site,cargo,loading)
    {
        if(!this.IsRawFeeder(cargo) && !this.IsSteelFeeder(cargo)) return this.FarmSiteCargoes(site,loading);
        if(!loading && !AIRail.IsRailStationTile(site.tile)) return false;
        local size=StationFootprint(site.dir,this.builder.platform_length,StationPlatforms(site));
        return loading ? AITile.GetCargoProduction(site.tile,cargo,size[0],size[1],AIStation.GetCoverageRadius(AIStation.STATION_TRAIN))>0 :
            AITile.GetCargoAcceptance(site.tile,cargo,size[0],size[1],AIStation.GetCoverageRadius(AIStation.STATION_TRAIN))>=8;
    }
    function SegmentRoot(index)
    {
        local seen={};
        while(index>=0 && index<this.state.segments.len() && !(index in seen)) {
            seen[index] <- true;
            local segment=this.state.segments[index];
            if(!("parent_segment" in segment)) return index;
            index=segment.parent_segment;
        }
        return -1;
    }
    function StationRoot(tile)
    {
        foreach(index,segment in this.state.segments)
            if("goal_station" in segment && segment.goal_station==tile) return this.SegmentRoot(index);
        return -1;
    }
    function RestoreOreJunctions()
    {
        // Older versions discarded these when commissioning the separate steel line.
        if("ore_junctions_restored" in this.state) return;
        this.state.ore_junctions_restored <- true;
        if(this.state.segments.len()==0) return;
        local known={};
        foreach(j in this.state.junctions) known[j.tile] <- true;
        foreach(j in this.JunctionCandidates(this.state.segments[0])) {
            if(j.tile in known) continue;
            j.segment=0;
            this.state.junctions.append(j);
        }
    }
    function TryOreFeeder() {return this.source_label=="IORE" && this.TryIndustryFeeder();}
    function TryIndustryFeeder()
    {
        if((this.source_label!="IORE" && this.source_label!="WOOD") || this.state.stage<1 || this.state.chain==null ||
            !AIIndustry.IsValidIndustry(this.state.chain.mill) || AIDate.GetCurrentDate()<this.state.retry) return false;
        if(this.state.transaction!=null || this.state.held.len()>0 || ("plan" in this.state && this.state.plan!=null)) return false;
        local cargo=FreightCargo(this.source_label),field=this.FeederSources(cargo);
        if(!this.FeederSiteValid(this.state.stations[1],cargo,false)) return false;
        if(this.source_label=="IORE") this.RestoreOreJunctions();
        local available=false;
        foreach(j in this.state.junctions) if(!j.used && this.SegmentRoot(j.segment)==0) available=true;
        if(!available) return false;
        if(!(field in this.state)) this.state[field] <- {};
        local choices=[];
        foreach(mine,_ in AIIndustryList()) {
            if(mine==this.state.chain.mine || mine in this.state[field] || (this.excluded_sources!=null && mine in this.excluded_sources)) continue;
            local production=AIIndustry.GetLastMonthProduction(mine,cargo);
            if(production<=0 || RivalIndustryStation(mine)) continue;
            local key=this.FeederKey(mine,cargo);
            if(key in this.state.failed && (typeof this.state.failed[key]=="bool" || AIDate.GetCurrentDate()<this.state.failed[key])) continue;
            local distance=AIMap.DistanceManhattan(AIIndustry.GetLocation(mine),AIIndustry.GetLocation(this.state.chain.mill));
            if(!IndustryDistanceAllowed(distance,AIRail.GetRailType(this.state.depot))) continue;
            choices.append({source=mine,score=production*1000/(distance+1)});
        }
        choices.sort(function(a,b){return a.score>b.score?-1:a.score<b.score?1:0;});
        if(choices.len()==0) return false;
        local mine=choices[0].source;
        AILog.Info(this.source_label=="WOOD" ? "Freight network: planning additional forest -> existing sawmill station." :
            "Freight network: planning additional iron ore mine -> existing steel mill station.");
        if(!this.BuildBranch(mine,true,cargo,true)) {
            this.state.failed[this.FeederKey(mine,cargo)] <- AIDate.GetCurrentDate()+(this.builder.planning_timed_out?30:365);
            this.state.retry=AIDate.GetCurrentDate()+7;
        }
        return true;
    }
    function LastStage() { return this.source_label=="IORE" ? 3 : 2; }
    function FailedChoice(key)
    {
        if(!(key in this.state.failed)) return false;
        local failure=this.state.failed[key];
        return typeof failure=="bool" ? failure : !this.retry_deferred || AIDate.GetCurrentDate()<failure;
    }
    function PickWoodChain()
    {
        local wood=FreightCargo("WOOD"),goods=FreightCargo("GOOD");
        if(wood<0 || goods<0) return null;
        local forests=[],sawmills=[],production={};
        foreach(i,_ in AIIndustryList()) {
            local monthly=AIIndustry.GetLastMonthProduction(i,wood);
            if(monthly>0 && !RivalIndustryStation(i)) {
                forests.append(i);
                production[i] <- monthly;
            }
            // Select by cargo conversion; tropical lumber mills do not produce goods.
            if(AIIndustry.IsCargoAccepted(i,wood)==AIIndustry.CAS_ACCEPTED && this.Produces(i,goods)) sawmills.append(i);
        }
        local best=null,score=-1;
        foreach(f in forests) foreach(m in sawmills) {
            if(this.excluded_sources!=null && f in this.excluded_sources) continue;
            if(this.builder.DeferredConnection("industry:"+wood+":"+f+":"+m)) continue;
            local distance=AIMap.DistanceManhattan(AIIndustry.GetLocation(f),AIIndustry.GetLocation(m));
            if(!IndustryDistanceAllowed(distance)) continue;
            foreach(t,_ in AITownList()) {
                local centre=AITown.GetLocation(t),last=AIMap.DistanceManhattan(AIIndustry.GetLocation(m),centre);
                if(!IndustryDistanceAllowed(last) || AITile.GetCargoAcceptance(centre,goods,1,1,6)<8) continue;
                local key=f+":"+m+":"+t;
                if(this.FailedChoice(key)) continue;
                // Bus cities take priority; larger cities rank within each group.
                local value=production[f]*1000/(distance+last)*(1.0+AITown.GetPopulation(t).tofloat()/2000.0);
                if(CityDestinationBetter(t,value,best==null?-1:best.city,score)) {score=value;best={mine=f,mill=m,city=t,key=key};}
            }
        }
        return best;
    }
    function PickChain()
    {
        RailTypeReview();
        this.retry_deferred=false;
        local choice=this.PickFreshChain();
        if(choice==null) {
            this.retry_deferred=true;
            choice=this.PickFreshChain();
        }
        this.retry_deferred=false;
        if(choice==null && this.source_label=="FARM") RelaxIndustryProduction(this.state.production_policy,"Farms");
        return choice;
    }
    function PickFarmChain()
    {
        local cargoes=this.FarmCargoes(),goods=FreightCargo("GOOD");
        if(cargoes[0]<0 || cargoes[1]<0 || goods<0) return null;
        local best=null,score=-1;
        foreach(farm,_ in AIIndustryList()) {
            if(this.excluded_sources!=null && farm in this.excluded_sources) continue;
            local grain=AIIndustry.GetLastMonthProduction(farm,cargoes[0]);
            local stock=AIIndustry.GetLastMonthProduction(farm,cargoes[1]);
            if(!this.FarmProductionEligible(grain,stock) || RivalIndustryStation(farm)) continue;
            local demand=grain+stock;
            foreach(factory,_ in AIIndustryList()) {
                if(!this.Produces(factory,goods) ||
                    AIIndustry.IsCargoAccepted(factory,cargoes[0])!=AIIndustry.CAS_ACCEPTED ||
                    AIIndustry.IsCargoAccepted(factory,cargoes[1])!=AIIndustry.CAS_ACCEPTED) continue;
                local distance=AIMap.DistanceManhattan(AIIndustry.GetLocation(farm),AIIndustry.GetLocation(factory));
                local key="farm-start:"+farm+":"+factory;
                if(!IndustryDistanceAllowed(distance) || this.FailedChoice(key) ||
                    this.builder.DeferredConnection("industry:"+cargoes[0]+":"+farm+":"+factory)) continue;
                // The destination city must accept goods: sample the town
                // centre at the standard coverage radius, prefer larger cities,
                // and keep it within the goods-leg distance band.
                local city=-1,city_score=-1.0;
                foreach(t,_ in AITownList()) {
                    local loc=AITown.GetLocation(t),g=AIMap.DistanceManhattan(AIIndustry.GetLocation(factory),loc);
                    if(!IndustryDistanceAllowed(g) || AITile.GetCargoAcceptance(loc,goods,1,1,6)<8) continue;
                    local value=(1.0+AITown.GetPopulation(t).tofloat()/2000.0)/g;
                    if(CityDestinationBetter(t,value,city,city_score)) {city_score=value;city=t;}
                }
                if(city<0) continue;
                local value=demand*1000/(distance+1)*city_score;
                if(CityDestinationBetter(city,value,best==null?-1:best.city,score)) {score=value;best={mine=farm,mill=factory,factory=factory,city=city,key=key};}
            }
        }
        return best;
    }
    function PickFreshChain()
    {
        if(this.source_label=="FARM") return this.PickFarmChain();
        if(this.source_label=="WOOD") return this.PickWoodChain();
        local ore=FreightCargo("IORE"),steel=FreightCargo("STEL"),goods=FreightCargo("GOOD");
        if(ore<0 || steel<0 || goods<0) return null;
        local mines=[],mills=[],factories=[];
        foreach(i,_ in AIIndustryList()) {
            if(AIIndustry.GetLastMonthProduction(i,ore)>0 && !RivalIndustryStation(i)) mines.append(i);
            if(AIIndustry.IsCargoAccepted(i,ore)==AIIndustry.CAS_ACCEPTED && this.Produces(i,steel)) mills.append(i);
            if(AIIndustry.IsCargoAccepted(i,steel)==AIIndustry.CAS_ACCEPTED && this.Produces(i,goods)) factories.append(i);
        }
        local best=null,score=-1,production={};
        foreach(m in mines) production[m] <- AIIndustry.GetLastMonthProduction(m,ore);
        foreach(m in mines) foreach(s in mills) {
            if(this.excluded_sources!=null && m in this.excluded_sources) continue;
            if(this.builder.DeferredConnection("industry:"+ore+":"+m+":"+s)) continue;
            local d=AIMap.DistanceManhattan(AIIndustry.GetLocation(m),AIIndustry.GetLocation(s));
            if(!IndustryDistanceAllowed(d)) continue;
            foreach(f in factories) {
                local e=AIMap.DistanceManhattan(AIIndustry.GetLocation(s),AIIndustry.GetLocation(f));
                if(!IndustryDistanceAllowed(e)) continue;
                foreach(t,_ in AITownList()) {
                    local loc=AITown.GetLocation(t),g=AIMap.DistanceManhattan(AIIndustry.GetLocation(f),loc);
                    if(!IndustryDistanceAllowed(g) || AITile.GetCargoAcceptance(loc,goods,1,1,6)<8) continue;
                    local key=m+":"+s+":"+f+":"+t;
                    if(this.FailedChoice(key)) continue;
                    // Bus cities take priority; larger cities rank within each group.
                    local value=production[m]*1000/(d+e+g)*(1.0+AITown.GetPopulation(t).tofloat()/2000.0);
                    if(CityDestinationBetter(t,value,best==null?-1:best.city,score)) {score=value;best={mine=m,mill=s,factory=f,city=t,key=key};}
                }
            }
        }
        return best;
    }
    function JunctionCandidates(segment)
    {
        local candidates=[];
        if("permanent_single" in segment) return candidates;
        local a=this.builder.PathTiles(UnpackRailPath(segment.a)); a.reverse();
        local other={}; foreach(t in this.builder.PathTiles(UnpackRailPath(segment.z))) other[t] <- true;
        for(local i=10;i<a.len()-10;i++) {
            local d=a[i+1]-a[i],off=Abs(d)==1?AIMap.GetMapSizeX():1;
            foreach(side in [off,-off]) {
                local valid=true;
                for(local k=-8;k<=8;k++) {
                    local t=a[i]+k*d;
                    if(a[i+k]!=t || !(t+side in other)) {valid=false;break;}
                    foreach(tile in [t,t+side]) if(!AIRail.IsRailTile(tile) ||
                        AITile.GetSlope(tile)!=AITile.SLOPE_FLAT ||
                        AIRail.GetRailTracks(tile)!=RailPiece(tile-d,tile,tile+d)) valid=false;
                }
                if(!valid) continue;
                local first=side>0?a[i]:a[i]+side;
                local outgoing=(side>0 ? segment.outbound==0 : segment.outbound==1);
                candidates.append({segment=this.state.segments.len(),at=i,tile=first,side=off,d=d,forward=outgoing?d:-d,used=false});
                break;
            }
        }
        return candidates;
    }
    function RecordSegment(segment)
    {
        local candidates=this.JunctionCandidates(segment);
        if(candidates.len()==0)
            AILog.Info("Freight network: retaining usable route with no future junction sites; shared-track expansion may need a separate route.");
        foreach(candidate in candidates) this.state.junctions.append(candidate);
        this.state.segments.append(segment);
    }
    function CitySites(town,target)
    {
        local sites=this.CitySiteCandidates(town,target,false);
        foreach(site in sites) if(site.loop!=null) return sites;
        if(this.builder.PlanningExpired()) return sites;
        local reshaped=this.CitySiteCandidates(town,target,true);
        return reshaped.len()>0 ? reshaped : sites;
    }
    function CitySiteCandidates(town,target,reshape)
    {
        local out=[],cargo=FreightCargo("GOOD"),centre=AITown.GetLocation(town),w=AIMap.GetMapSizeX();
        // Screen at the same radius the post-build acceptance check uses, so
        // sites cannot pass this scan and still be built and rolled back.
        local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
        for(local x=-12;x<=12;x++) for(local y=-12;y<=12;y++) {
            if(this.builder.PlanningExpired()) return [];
            local tx=AIMap.GetTileX(centre)+x,ty=AIMap.GetTileY(centre)+y;
            if(tx<2 || ty<2 || tx>=w-8 || ty>=AIMap.GetMapSizeY()-8) continue;
            local tile=AIMap.GetTileIndex(tx,ty);
            foreach(dir in [AIRail.RAILTRACK_NE_SW,AIRail.RAILTRACK_NW_SE]) {
                local size=StationFootprint(dir,this.builder.platform_length,this.builder.station_platforms);
                if(!AreaIsBuildable(tile,size[0],size[1]) || AITile.GetCargoAcceptance(tile,cargo,size[0],size[1],radius)<8) continue;
                foreach(exit in StationExits(tile,dir,this.builder.platform_length)) {
                    local site=this.builder.RiroSite({tile=tile,dir=dir,platforms=this.builder.station_platforms},exit,reshape);
                    if(site==null) continue;
                    // Both station mouths are offered, the far one penalised: a
                    // goods station is a terminal stage and hosts no future
                    // depot, and the far mouth has the opposite junction
                    // handedness — letting the preferred branch orientation
                    // find a compatible approach.
                    site.score <- Abs(x)+Abs(y)+
                        (StationExitFacesTarget(site,exit,target,this.builder.platform_length) ? 0 : 10000);
                    out.append(site);
                }
            }
        }
        // Keep facing and far-mouth candidates in separate quotas: the far
        // mouth's opposite junction handedness is the only compatible
        // approach for the preferred orientation on some maps, and a plain
        // top-N cut would drop every one of them.
        out.sort(function(a,b){
            local fa=(a.score>=10000)?1:0,fb=(b.score>=10000)?1:0;
            if(fa!=fb) return fa<fb?-1:1;
            if((a.loop==null)!=(b.loop==null)) return a.loop!=null ? -1 : 1;
            if(("earthwork" in a)!=("earthwork" in b)) return ("earthwork" in a) ? 1 : -1;
            return a.score<b.score?-1:a.score>b.score?1:0;
        });
        local kept=[],kept_facing=0,kept_far=0;
        foreach(site in out) {
            local far=site.score>=10000;
            if(!far) {
                if(kept_facing>=6) continue;
                kept_facing++;
            } else {
                if(kept_far>=3) continue;
                kept_far++;
            }
            kept.append(site);
        }
        return kept;
    }
    function ResumeHeld()
    {
        local remaining=[];
        foreach(id in this.state.held) if(AIVehicle.IsValidVehicle(id)) {
            local ok=true;
            // Cancel our temporary depot instruction before releasing a travelling train.
            if(!AIOrder.IsCurrentOrderPartOfOrderList(id) && AIOrder.IsGotoDepotOrder(id,AIOrder.ORDER_CURRENT))
                ok=AIVehicle.SendVehicleToDepot(id);
            if(AIVehicle.IsStoppedInDepot(id)) ok=AIVehicle.StartStopVehicle(id) && ok;
            if(!ok) remaining.append(id);
        }
        this.state.held=remaining;
        if(remaining.len()==0) this.state.hold_since=-1;
        return remaining.len()==0;
    }
    function AbortDepotWait()
    {
        if(this.state.transaction!=null) return false; // Never reopen a partly modified junction.
        AILog.Warning("Freight network: depot wait exceeded 180 days; cancelling extension and releasing trains.");
        this.state.plan <- null;
        this.state.retry=AIDate.GetCurrentDate()+90;
        this.builder.ReleasePendingStations();
        return this.ResumeHeld();
    }
    function Recover()
    {
        local tx=this.state.transaction;
        if(tx==null) return this.ResumeHeld();
        if("trains" in tx) foreach(train in tx.trains)
            if(AIVehicle.IsValidVehicle(train) && !AIVehicle.SellVehicle(train)) return false;
        if("train" in tx && AIVehicle.IsValidVehicle(tx.train) && !AIVehicle.SellVehicle(tx.train)) return false;
        if("loop" in tx) {
            // Use the resumable journal restorer: keep trains held if any undo fails.
            if(!("loop_upgrade" in tx)) {
                local signals=[];
                foreach(s in tx.loop.signals) signals.append([s[0],s[1],s[4],s[2],s[3]]);
                tx.loop_upgrade <- {upgrade={pieces=tx.loop.pieces,structures=[],removed=tx.loop.removed,signals=signals}};
            }
            if(!RestoreNetworkUpgrade(tx.loop_upgrade)) return false;
            if("terrain_original" in tx.loop) {
                local terrain=PairedTerrain();terrain.original=tx.loop.terrain_original;
                if(!terrain.Restore()) return false;
            }
            delete tx.loop;
        }
        if(!RestoreNetworkUpgrade(tx)) {AILog.Warning("Network rollback pending: "+AIError.GetLastErrorString());return false;}
        if("depot" in tx && AIRail.IsRailDepotTile(tx.depot) && !AITile.DemolishTile(tx.depot)) return false;
        if(AIRail.IsRailStationTile(tx.station.tile)) this.builder.RemoveStation(tx.station);
        if(AIRail.IsRailStationTile(tx.station.tile)) return false;
        if("earthwork_original" in tx) {
            local terrain=PairedTerrain();terrain.original=tx.earthwork_original;
            if(!terrain.Restore()) return false;
        }
        this.state.transaction=null;
        return this.ResumeHeld();
    }
    function RequestDepot(id) {return AIVehicle.SendVehicleToDepot(id);}
    function Hold()
    {
        if(this.state.hold_since<0) this.state.hold_since=AIDate.GetCurrentDate();
        if(AIDate.GetCurrentDate()-this.state.hold_since>=180) {this.AbortDepotWait();return false;}
        local ready=true;
        foreach(id,r in this.optimiser.trains) {
            if(!AIVehicle.IsValidVehicle(id)) continue;
            local held=false;foreach(v in this.state.held) if(v==id) held=true;
            if(AIVehicle.IsStoppedInDepot(id)) {if(!held) this.state.held.append(id);continue;}
            ready=false;
            // Do not toggle a successful temporary order off. Failed requests remain retryable.
            if(!held && this.RequestDepot(id)) this.state.held.append(id);
        }
        return ready;
    }
    function QueueFarmExpansion()
    {
        if(this.source_label!="FARM" && this.source_label!="IORE") return;
        this.state.post_goods_farms <- true;
        this.state.farm_scan <- 0;
        this.state.retry=0;
        AILog.Info("Factory goods operating: next construction task is more farms into the original factory station.");
    }
    function NeedsFactoryGoods()
    {
        if(this.source_label!="IORE" && this.source_label!="FARM") return false;
        if(this.state.stage!=this.FactoryIndex() || this.state.chain==null ||
            !("factory" in this.state.chain) || !AIIndustry.IsValidIndustry(this.state.chain.factory)) return false;
        return this.NeedsContinuation();
    }
    function NeedsContinuation()
    {
        // Finish or recover a started extension before opening unrelated routes.
        if(this.state.transaction!=null || this.state.held.len()>0 ||
            ("plan" in this.state && this.state.plan!=null)) return true;
        if(this.state.stage>=this.LastStage())
            return this.FarmExpansionPending(); // Farm branches outrank new routes.
        return this.state.stage>0 && this.state.stage<this.LastStage() &&
            AIDate.GetCurrentDate()>=this.state.retry;
    }
    // True while an unconnected, eligible farm remains near the factory: the
    // farm-to-factory-to-city chain keeps priority over unrelated routes. The
    // industry scan is gated to once per game month.
    function FarmExpansionPending(include_deferred=false)
    {
        if(!include_deferred && this.state.retry>AIDate.GetCurrentDate()) return false;
        // Only the ore chain has a factory; wood chains (forest -> sawmill ->
        // city) have none and never take farm branches.
        local factory=this.state.chain!=null && ("factory" in this.state.chain) ?
            this.state.chain.factory : null;
        if(factory==null || !AIIndustry.IsValidIndustry(factory) ||
            this.state.stations.len()<=this.FactoryIndex()) return false;
        local today=AIDate.GetCurrentDate();
        if(!("farm_scan" in this.state) || today>=this.state.farm_scan || !("farm_scan_percent" in this.state) || this.state.farm_scan_percent!=this.state.production_policy.percent) {
            this.state.farm_scan <- today+30;
            this.state.farm_scan_percent <- this.state.production_policy.percent;
            local accepted=this.FarmSiteCargoes(this.state.stations[this.FactoryIndex()],false);
            local cargoes=this.FarmCargoes(),count=0;
            local farms=("farms" in this.state)?this.state.farms:{};
            if(accepted) foreach(industry,_ in AIIndustryList()) {
                if(industry in farms || (this.excluded_sources!=null && industry in this.excluded_sources)) continue;
                // Either cargo can meet the current production requirement.
                if(!this.FarmProductionEligible(AIIndustry.GetLastMonthProduction(industry,cargoes[0]),
                    AIIndustry.GetLastMonthProduction(industry,cargoes[1]))) continue;
                if(!IndustryEndpointsAllowed(AIIndustry.GetLocation(industry),
                    AIIndustry.GetLocation(factory),AIRail.GetRailType(this.state.depot))) continue;
                if(this.FailedChoice("farm:"+industry) || RivalIndustryStation(industry)) continue;
                count++;
            }
            this.state.farm_candidates <- count;
        }
        return ("farm_candidates" in this.state) && this.state.farm_candidates>0;
    }
    function TryBuild()
    {
        local previous=AIRail.GetCurrentRailType();
        if(this.state.stage>0 && AIRail.IsRailDepotTile(this.state.depot))
            AIRail.SetCurrentRailType(AIRail.GetRailType(this.state.depot));
        local result=false;
        try { result=this.TryBuildOnRail(); }
        catch(error) { AIRail.SetCurrentRailType(previous);throw error; }
        AIRail.SetCurrentRailType(previous);
        return result;
    }
    function TryBuildOnRail()
    {
        if(this.state.stage==0 && "bootstrap" in this.state && this.state.bootstrap.len()>0) {
            foreach(id in this.state.bootstrap) if(AIVehicle.IsValidVehicle(id) && !AIVehicle.SellVehicle(id)) return false;
            this.state.bootstrap=[];
        }
        if(this.state.transaction!=null) {this.Recover(); return false;}
        if((!("plan" in this.state) || this.state.plan==null) && !this.builder.ReleasePendingStations()) return false;
        if(this.state.held.len()>0 && (!("plan" in this.state) || this.state.plan==null)) {this.ResumeHeld();return false;}
        if("plan" in this.state && this.state.plan!=null) {
            if(!this.Hold()) return false;
            local p=this.state.plan,seg=p.segment;
            if(!("grade" in seg)) {this.state.plan=null;this.ResumeHeld();return true;}
            local f={path=UnpackRailPath(seg.a),secondary={path=UnpackRailPath(seg.z),start=seg.start2,goal=seg.goal2},
                start=seg.start,goal=seg.goal,outbound=seg.outbound,entrances=[p.entrance],line_signals=[]};
            if("grade" in seg) f.grade <- seg.grade;
            local loop=null,fallback_reason="No viable loop site";
            if("loop" in p && p.loop!=null) {
                loop=RollThroughStation();
                loop.pieces=p.loop.pieces;loop.signals=p.loop.signals;loop.remove=p.loop.remove;loop.junction=p.loop.junction;
                // Re-plan safe earthworks against the current map before building.
                if(!loop.PrepareTerrain()) {
                    AILog.Info("Freight network: planned RIRO loop no longer fits; falling back to standard terminus.");
                    fallback_reason=loop.failure_reason;
                    loop=null;
                }
            }
            local site={tile=p.site.tile,dir=p.site.dir,loop=loop,fallback_reason=fallback_reason};
            local built=this.ConstructBranch(f,site,this.state.junctions[p.junction],p.cargo,"farm" in p?p.farm:null);
            this.state.plan=null;
            if(this.state.transaction==null) this.ResumeHeld();
            if(!built) {
                this.builder.ReleasePendingStations();
                // A construct that failed after planning is poisoned for this
                // site: retrying the identical branch repeats the identical
                // failure forever.
                if("farm" in p) this.state.failed[this.FeederKey(p.farm,p.cargo)] <- AIDate.GetCurrentDate()+365;
                else if(p.cargo==FreightCargo("GOOD")) this.state.goods_standalone <- true;
                // The failed station/side attempt is already in branch_tried.
                // Do not consume an unused junction when construction rolls back;
                // other farms or city approaches can still use it.
                this.state.retry=AIDate.GetCurrentDate()+90;
            }
            return true;
        }
        if(AIDate.GetCurrentDate()<this.state.retry) return false;
        if(this.state.stage==0) {
            local chain=this.PickChain();
            if(chain==null) {this.state.retry=AIDate.GetCurrentDate()+(this.source_label=="FARM"?30:365);return false;}
            local trunk=this.source_label=="FARM" ? FarmBackbone(this.builder,null,"GRAI") : NetworkBackbone(this.builder,null,this.source_label);
            trunk.network=this;
            trunk.dual_next_target=this.source_label=="IORE" ? AIIndustry.GetLocation(chain.factory) : AITown.GetLocation(chain.city);
            if(this.source_label=="FARM") trunk.freight_name="Farm";

            local labels=this.source_label=="FARM" ? ["GRAI","LVST"] : this.source_label=="WOOD" ? ["WOOD","GOOD"] : ["IORE","STEL","GOOD"];
            foreach(label in labels) {
                local c=FreightCargo(label);
                local buyer=TrainBuyer(c);
                if(buyer.BestEngine()<0 || buyer.BestWagon()<0) return false;
            }
            AILog.Info(this.source_label=="FARM" ? "Freight network: planning independent farm -> factory network." : this.source_label=="WOOD" ? "Freight network: planning forest -> sawmill -> city chain." :
                "Freight network: planning complete ore -> steel -> goods -> city chain.");
            this.state.failed[chain.key] <- true;
            if(!trunk.Connect(chain.mine,chain.mill)) {
                if(this.builder.planning_timed_out) this.state.failed[chain.key]=AIDate.GetCurrentDate()+180;
                return true;
            }
            local built=trunk.completed;
            if("dual" in built) {
                if(!("hubs" in this.state)) this.state.hubs <- {};
                this.state.hubs[chain.mill] <- built.dual;
                this.state.dual_priority <- true;
            }
            this.state.chain=chain; this.state.depot=built.depot;
            this.state.stations=[built.mine,built.mill]; this.RecordSegment(built.segment);
            if("permanent_single" in built.segment) this.state.goods_standalone <- true;
            this.optimiser.Register(built.train,trunk.services[built.train],this.builder.platform_length);
            this.optimiser.trains[built.train].network <- true;
            if(this.source_label=="FARM") {
                local cargoes=this.FarmCargoes();
                foreach(index,id in this.state.bootstrap) {
                    if(id!=built.train) this.optimiser.Register(id,trunk.services[built.train],this.builder.platform_length);
                    local record=this.optimiser.trains[id];
                    record.cargo=cargoes[index];record.network <- true;
                    record.source_industry <- chain.mine;
                    record.production_baseline <- AIIndustry.GetLastMonthProduction(chain.mine,cargoes[index]);
                    record.production_level <- record.production_baseline;
                    record.phase="dispatch";
                }
                this.state.farms <- {};
                this.state.farms[chain.mine] <- {tile=built.mine.tile,dir=built.mine.dir,depot=built.depot};
                this.state.bootstrap=[];
            }
            this.state.stage=1;
            AILog.Info("Freight network: "+("permanent_single" in built.segment?"one-train ":"two-track ")+this.source_label+" backbone commissioned; junction candidates="+this.state.junctions.len());
            return true;
        }
        if(this.state.stage>=this.LastStage()) return this.TryIndustryFeeder() || this.TryFarm();
        local chain=this.state.chain,steel=this.source_label=="IORE" && this.state.stage==1;
        local source=this.state.stage==1?chain.mill:chain.factory,cargo=FreightCargo(steel?"STEL":"GOOD");
        if(!AIIndustry.IsValidIndustry(source) || RivalIndustryStation(source)) return false;
        // Build the next link as soon as its supplying route exists. Its train
        // can wait for the first production under the normal full-load order.
        AILog.Info("Freight network: prioritising next link for "+AICargo.GetName(cargo)+".");
        if(steel) {
            // A factory already taking grain and livestock on another chain's
            // input line takes steel as a feeder branch instead of a second
            // line and station.
            if(this.TrySteelDelivery(source,chain.factory)) return true;
            if(!this.TrySeparateSteel(source,chain.factory)) this.state.retry=AIDate.GetCurrentDate()+7;
            return true;
        }
        if(!steel && (("hubs" in this.state && source in this.state.hubs) || this.source_label!="WOOD" || ("goods_standalone" in this.state && this.state.goods_standalone))) {
            local completed=this.TrySeparateGoods(source);
            this.state.goods_standalone <- false;
            if(!completed) this.state.retry=AIDate.GetCurrentDate()+7;
            return true;
        }
        local built=this.BuildBranch(steel?chain.factory:chain.city,steel,cargo);
        if(!built && !steel) this.state.goods_standalone <- true;
        if(this.state.transaction==null) this.ResumeHeld();
        if(!built) this.state.retry=AIDate.GetCurrentDate()+(!steel || this.builder.planning_timed_out?7:90);
        return true;
    }
    function ConnectHubOutlet(route,source,target)
    {
        // A cooldown is not a failed search. Check before dismantling the idle
        // pickup access or changing the hub's retry/fallback state.
        if(this.builder.DeferredConnection(route.ConnectionPlanKey(source,target))) return false;
        local hub=("hubs" in this.state && source in this.state.hubs) ? this.state.hubs[source] : null;
        if(hub!=null && !hub.used && AIRail.IsRailStationTile(hub.pickup.tile)) {
            if(!("hub_failures" in this.state)) this.state.hub_failures <- {};
            if(!("hub_deferred" in this.state)) this.state.hub_deferred <- {};
            local now=AIDate.GetCurrentDate();
            if(source in this.state.hub_deferred) {
                if(now<this.state.hub_deferred[source]) {
                    DualPickupStatus(hub,"Separate station");
                    local built=route.Connect(source,target);
                    DualPickupStatus(hub,built ? null : "Separate: retry");
                    return built;
                }
                // The shared pickup gets a fresh run of attempts after its wait.
                delete this.state.hub_deferred[source];
                this.state.hub_failures[source] <- 0;
            }
            if(!this.builder.ReleasePendingStations() || !RestoreDualAccess(hub)) return false;
            DualPickupStatus(hub,"Planning route");
            route.source_hub=hub;
            local built=route.Connect(source,target);
            route.source_hub=null;
            if(!built) {
                if(!this.builder.ReleasePendingStations()) return false;
                AIRail.SetCurrentRailType(AIRail.GetRailType(hub.pickup.tile));
                if(!BuildDualAccess(this.builder,hub)) AILog.Warning("Dual RIRO: idle pickup access needs repair.");
                local count=(source in this.state.hub_failures ? this.state.hub_failures[source] : 0)+1;
                this.state.hub_failures[source] <- count;
                DualPickupStatus(hub,"Retry: "+(this.builder.failure_detail==null ? "No route found" : this.builder.failure_detail));
                // The pickup exit is fixed, so a route this hub cannot serve
                // only changes as the map does; stop blocking the chain and
                // let separate stations carry the outlet in the meantime.
                if(count>=3) {
                    this.state.hub_deferred[source] <- now+365;
                    DualPickupStatus(hub,"Deferred: separate");
                    AILog.Info("Dual RIRO: no outlet through the shared pickup after "+count+" attempts; separate stations take over for a year.");
                }
            } else {
                if(source in this.state.hub_failures) delete this.state.hub_failures[source];
                DualPickupStatus(hub);
            }
            return built;
        }
        return route.Connect(source,target);
    }

    // A factory already served by the farm chain's input line takes steel as
    // a feeder branch: one input line and station for livestock, grain and
    // steel. Falls back to the separate steel line when no such factory line
    // exists or the branch cannot build.
    function TrySteelDelivery(mill,factory)
    {
        if(this.siblings==null) {AILog.Info("SteelDelivery: no siblings");return false;}
        foreach(n in this.siblings) {
            if(n==this || n.source_label!="FARM" || n.state.chain==null || !("factory" in n.state.chain)) continue;
            if(n.state.chain.factory!=factory || n.state.stage<n.FactoryIndex()) continue;
            if(n.TrySteelFeeder(mill)) {
                // The goods outlet next; it never shared the feeder branch.
                this.state.stage=2;this.state.retry=0;
                AILog.Info("Steel: the mill now feeds the shared factory input line.");
                return true;
            }
        }
        return false;
    }
    function TrySteelFeeder(mill)
    {
        if(this.source_label!="FARM" || this.state.chain==null || !("factory" in this.state.chain) ||
            this.state.stage<this.FactoryIndex()) return false;
        if(this.state.transaction!=null || this.state.held.len()>0 || ("plan" in this.state && this.state.plan!=null)) return false;
        if(!AIIndustry.IsValidIndustry(mill) || RivalIndustryStation(mill)) return false;
        if(("mills" in this.state) && (mill in this.state.mills)) return false;
        if(!this.FeederSiteValid(this.state.stations[this.FactoryIndex()],FreightCargo("STEL"),false)) return false;
        if(!this.builder.ReleasePendingStations()) return false;
        AILog.Info("Steel: joining the shared factory input line with a feeder branch.");
        return this.BuildBranch(mill,true,FreightCargo("STEL"),true);
    }
    function TrySeparateSteel(source,target)
    {
        if(!AIIndustry.IsValidIndustry(source) || !AIIndustry.IsValidIndustry(target) ||
            AIIndustry.IsCargoAccepted(target,FreightCargo("STEL"))!=AIIndustry.CAS_ACCEPTED) return false;
        if(RivalIndustryStation(source)) { AILog.Info("Steel: another company already serves this mill."); return false; }
        local route=SteelRoute(this.builder,null,"STEL");
        route.network=this;route.freight_name="Steel";
        AILog.Info("Steel: planning a separate steel mill -> factory route.");
        route.dual_next_target=AITown.GetLocation(this.state.chain.city);
        return this.ConnectHubOutlet(route,source,target);
    }
    function TrySeparateGoods(source)
    {
        RailTypeReview();
        if(RivalIndustryStation(source)) { AILog.Info("Factory goods: another company already serves this factory."); return false; }
        if(!this.builder.ReleasePendingStations()) return false;
        local choices=[],location=AIIndustry.GetLocation(source);
        local route=FactoryGoodsRoute(this.builder,null,"GOOD");
        route.network=this;route.freight_name="Factory goods";
        // A hub pickup can only serve destinations in front of its fixed exit.
        // Order towns so compatible ones are tried before towns the pickup
        // cannot reach. Prefer bus cities, then the chain's planned city
        // within the same priority group.
        // The town centre stands in for its station sites, which can tip a
        // boundary case either way, so this orders rather than filters.
        local hub=("hubs" in this.state && source in this.state.hubs) ? this.state.hubs[source] : null;
        local hub_ready=hub!=null && !hub.used && AIRail.IsRailStationTile(hub.pickup.tile) &&
            !(("hub_deferred" in this.state) && source in this.state.hub_deferred &&
                AIDate.GetCurrentDate()<this.state.hub_deferred[source]);
        local probe=hub_ready ? {tile=hub.pickup.tile,dir=hub.pickup.dir,exit=hub.pickup.exit} : null;
        local planned=probe!=null && this.state.chain!=null && "city" in this.state.chain ? this.state.chain.city : -1;
        local outlet_type=hub_ready ? AIRail.GetRailType(hub.pickup.tile) : AIRail.GetCurrentRailType();
        foreach(t,_ in AITownList()) {
            local distance=AIMap.DistanceManhattan(location,AITown.GetLocation(t));
            if(!IndustryDistanceAllowed(distance,outlet_type) || this.builder.DeferredConnection(route.ConnectionPlanKey(source,t))) continue;
            local loc=AITown.GetLocation(t);
            choices.append({town=t,priority=BusCityRailPriority(t),pop=AITown.GetPopulation(t),distance=distance,
                behind=probe!=null && !StationExitFacesTarget(probe,probe.exit,loc,this.builder.platform_length)});
        }
        choices.sort(function(a,b) {
            if(a.behind!=b.behind) return a.behind ? 1 : -1;
            if(a.priority!=b.priority) return a.priority>b.priority?-1:1;
            if(a.pop!=b.pop) return a.pop>b.pop?-1:1;
            return a.distance<b.distance?-1:a.distance>b.distance?1:0;
        });
        foreach(index,choice in choices) {
            if(choice.town!=planned || choice.behind || choice.priority!=choices[0].priority) continue;
            if(index>0) { choices.remove(index); choices.insert(0,choice); }
            break;
        }
        if(choices.len()==0) return false;
        local town=choices[0].town,old_run=this.builder.start_run;
        this.builder.start_run=3;
        AILog.Info("Factory goods: trying a separate station and route to "+AITown.GetName(town)+".");
        local built=this.ConnectHubOutlet(route,source,town);
        this.builder.start_run=old_run;
        if(built) this.state.chain.city=town;
        return built;
    }
    function BranchAttemptBlocked(key)
    {
        if(!("branch_tried" in this.state) || !(key in this.state.branch_tried)) return false;
        local value=this.state.branch_tried[key];
        return typeof value=="bool" ? value : AIDate.GetCurrentDate()<value;
    }
    // The legacy farm flag denotes an incoming source branch; cargo now
    // distinguishes one ore/wood train from the grain/livestock pair.
    function BuildBranch(target,industry,cargo,farm=false)
    {
        local previous=AIRail.GetCurrentRailType();
        if(AIRail.IsRailDepotTile(this.state.depot)) AIRail.SetCurrentRailType(AIRail.GetRailType(this.state.depot));
        this.builder.BeginPlanning(null,!farm,true);
        local result=false;
        try { result=this.BuildBranchWithinBudget(target,industry,cargo,farm); }
        catch(error) { AIRail.SetCurrentRailType(previous);throw error; }
        AIRail.SetCurrentRailType(previous);
        local origin=farm ? AIIndustry.GetLocation(target) : AIIndustry.GetLocation(this.state.stage==1 ? this.state.chain.mill : this.state.chain.factory);
        local name=farm ? AIIndustry.GetName(this.FeederIndustry(cargo)) : (industry ? AIIndustry.GetName(target) : AITown.GetName(target));
        this.builder.LogRouteFailure(origin,name,result);
        this.builder.planning_deadline=0;this.builder.reusable_rails=null;
        return result;
    }
    function BranchNetworkStation(farm,cargo=null)
    {
        return this.state.stations[farm ? this.FeederStationIndex(cargo) : this.state.stage].tile;
    }
    function BuildBranchWithinBudget(target,industry,cargo,farm=false)
    {
        local source=farm ? target : (this.state.stage==1 ? this.state.chain.mill : this.state.chain.factory);
        if(RivalIndustryStation(source)) return false;
        // Farm branches join a trunk, but their cargo destination is the factory.
        // Goods towns are selected below and checked against the producing industry.
        if(industry && !IndustryEndpointsAllowed(AIIndustry.GetLocation(source),
            AIIndustry.GetLocation(farm ? this.FeederIndustry(cargo) : target))) return false;
        local b=this.builder,helper=CoalRoutes(b);
        local depot_site=farm?null:this.PickupDepotSite();
        if(!farm && depot_site==null) {AILog.Info("Freight network: no room for a depot at the pickup station; postponing extension.");return false;}
        b.start_run=3; b.junction_reuse=true;
        helper.cargo=cargo;
        // Only the grain feeder can swap to livestock; steel and ore feeders
        // keep their own cargo.
        if(farm && cargo==FreightCargo("GRAI") && !this.IsRawFeeder(cargo) && AIIndustry.GetLastMonthProduction(target,FreightCargo("LVST"))>
            AIIndustry.GetLastMonthProduction(target,FreightCargo("GRAI"))) helper.cargo=FreightCargo("LVST");

        local target_tile=industry?AIIndustry.GetLocation(target):AITown.GetLocation(target);
        // Junction candidates walk a stored segment path from its goal end
        // towards its start, so j.d points from the segment's goal station
        // towards its start station. At a separated junction the diverge lane
        // carries host traffic travelling -d onto the branch, and the branch's
        // return lane rejoins the host travelling +d. The preferred d lines up
        // with the loaded train's own movement: leaving the host segment's
        // goal station it travels +j.d and diverges (-d), so d=-j.d; arriving
        // over another branch it travels goal-ward (-j.d) and diverges, so
        // d=+j.d; a farm branch merging towards its destination rejoins the
        // host travelling -j.d, so d=-j.d as well. On the trunk, goods traffic
        // arrives through the goal-side merge of the branch serving the
        // pickup, so junctions on the goal side of that merge rank ahead; the
        // rest force a far-end turnaround and are only used when nothing
        // better builds.
        // Segment endpoints store station anchors, not industry locations.
        // Comparing the factory industry tile to its station always selected
        // the opposite orientation for a farm joining the factory backbone.
        local far_tile=this.BranchNetworkStation(farm,cargo);
        local network_root=this.StationRoot(far_tile);
        local entry_at=null;
        foreach(segment in this.state.segments)
            if("goal_station" in segment && segment.goal_station==far_tile &&
                "junction_at" in segment && segment.junction_at!=null) {entry_at=segment.junction_at; break;}
        local candidates=[];
        foreach(index,j in this.state.junctions) if(!j.used) {
            if(network_root<0 || this.SegmentRoot(j.segment)!=network_root) continue;
            local serving=this.state.segments[j.segment];
            local goal_tile="goal_station" in serving ? serving.goal_station :
                (j.segment==0 && this.state.stations.len()>1 ? this.state.stations[1].tile : far_tile);
            local rank=0;
            if(goal_tile!=far_tile && !("junction_tile" in serving) &&
                entry_at!=null && ("at" in j) && j.at>entry_at) rank=1;
            candidates.append({index=index,score=rank*100000+AIMap.DistanceManhattan(j.tile,target_tile)});
        }
        if(candidates.len()==0) {
            b.failure_detail="No unused junction site";
            AILog.Info("Freight network: no unused junctions available; shared branch unavailable.");
            return false;
        }
        candidates.sort(function(a,z){return a.score<z.score?-1:a.score>z.score?1:0;});
        if(!("branch_tried" in this.state)) this.state.branch_tried <- {};
        if(!("branch_cursor" in this.state)) this.state.branch_cursor <- {};
        local cursor_key=target+":"+cargo;
        local first=cursor_key in this.state.branch_cursor?this.state.branch_cursor[cursor_key]:0;
        local deferred_attempt=false;
        // No cap: cheap rejections are fast, and searches are bounded by the
        // planning deadline. Every junction gets its preferred-orientation
        // attempt before the branch is declared unbuildable this turn.
        for(local turn=0;turn<candidates.len();turn++) {
            if(b.PlanningExpired()) return false;
            local position=(first+turn)%candidates.len(),candidate=candidates[position];
            local j=this.state.junctions[candidate.index];
            local serving=this.state.segments[j.segment];
            local goal_tile="goal_station" in serving ? serving.goal_station :
                (j.segment==0 && this.state.stations.len()>1 ? this.state.stations[1].tile : far_tile);
            // Fail closed: only the cargo-flow orientation is ever built. A
            // mirrored junction would force a far-end turnaround on a leg of
            // every trip; when no compatible layout exists the branch is
            // retried later with rotated junctions and sites instead.
            local d=goal_tile==far_tile ? -j.d : j.d;
            local sites=industry?helper.Sites(target,j.tile,farm):[];
            if(!industry) {
                local towns=[];
                foreach(t,_ in AITownList()) {
                    local dist=AIMap.DistanceManhattan(j.tile,AITown.GetLocation(t));
                    if(IndustryEndpointsAllowed(AIIndustry.GetLocation(source),AITown.GetLocation(t))) towns.append({town=t,priority=BusCityRailPriority(t),dist=dist,pop=AITown.GetPopulation(t)});
                }
                // Prefer bus cities, then larger towns.
                towns.sort(function(a,z){
                    if(a.priority!=z.priority) return a.priority>z.priority?-1:1;
                    if(a.pop!=z.pop) return a.pop>z.pop?-1:1;
                    return a.dist<z.dist?-1:1;
                });
                foreach(t in towns) {
                    local available=this.CitySites(t.town,j.tile);
                    sites=[];
                    foreach(site in available) {
                        local fresh=false;
                        foreach(e in [j.side,-j.side]) {
                            local key=t.town+":"+cargo+":"+candidate.index+":"+site.tile+":"+site.dir+":"+d+":"+e;
                            if(!this.BranchAttemptBlocked(key)) fresh=true;
                            else if(typeof this.state.branch_tried[key]=="integer") deferred_attempt=true;
                        }
                        if(fresh) sites.append(site);
                    }
                    if(sites.len()>0) {target=t.town;this.state.chain.city=t.town; break;}
                    if(b.PlanningExpired()) return false;
                }
            }
            AILog.Info("Freight network: branch station candidates="+sites.len());
            foreach(site in sites) foreach(e in [j.side,-j.side]) {
                if(b.PlanningExpired()) return false;
                if(farm && !this.FeederSiteValid(site,cargo,true)) continue;
                local attempt=target+":"+cargo+":"+candidate.index+":"+site.tile+":"+site.dir+":"+d+":"+e;
                if(this.BranchAttemptBlocked(attempt)) {
                    if(typeof this.state.branch_tried[attempt]=="integer") deferred_attempt=true;
                    continue;
                }
                local layout=PlanSeparatedJunction(j,d,e);
                if(layout==null || (!farm && depot_site.tile in layout.reserved)) {this.state.branch_tried[attempt] <- true;continue;}
                local ports=[];
                foreach(tiles in layout.lanes) ports.append([tiles.top(),tiles[tiles.len()-2]]);
                local start=ports[0],start2=ports[1],outbound=layout.outbound;
                if(b.LeftOutboundLane(site.exit)==outbound) {this.state.branch_tried[attempt] <- true;continue;}
                local goal=site.exit,off=b.PlatformOffset(site),goal2=[goal[0]+off,goal[1]+off];
                local reusable={},blocked={};
                foreach(segment in this.state.segments) foreach(nodes in [segment.a,segment.z])
                    foreach(n in nodes) blocked[n[0]] <- true;
                foreach(station in this.state.stations) foreach(t in b.StationTiles(station)) blocked[t] <- true;
                foreach(field in ["farms","mines","forests","mills"]) if(field in this.state) foreach(_,station in this.state[field]) {
                    foreach(t in b.StationTiles(station)) blocked[t] <- true;
                    blocked[station.depot] <- true;
                }
                foreach(t,_ in layout.reserved) blocked[t] <- true;
                foreach(port in ports) if(port[0] in blocked) delete blocked[port[0]];
                if(depot_site!=null) blocked[depot_site.tile] <- true;
                local reserved=[]; foreach(t,_ in blocked) reserved.append(t);
                foreach(t in b.StationTiles(site)) reserved.append(t);
                if(site.loop!=null) foreach(p in site.loop.pieces) if(p[1]!=site.loop.junction) reserved.append(p[1]);
                b.reusable_rails=reusable; b.retained_prefixes={};
                local first_reserved=clone reserved;
                for(local k=0;k<4;k++) first_reserved.append(goal2[0]+k*(goal2[0]-goal2[1]));
                local path=null,path2=null;
                this.state.branch_tried[attempt] <- true;
                if(!b.ReleasePendingStations()) return false;
                b.pending_stations=[{tile=site.tile,dir=site.dir}];
                if(!b.PrepareStation(site,b.pending_stations[0])) {
                    if(!b.ReleasePendingStations()) return false;
                    continue;
                }
                path=b.SearchPath(start,goal,first_reserved,null,64);
                if(path==null) {
                    if(b.planning_timed_out) {
                        this.state.branch_tried[attempt]=AIDate.GetCurrentDate()+30;
                        this.state.branch_cursor[cursor_key] <- (position+1)%candidates.len();
                        b.planning_deadline=0;
                        return false;
                    }
                    continue;
                }
                local primary_tiles={};local primary_clear=true;
                foreach(tile in b.PathTiles(path)) {
                    primary_tiles[tile] <- true;
                    if(AIRail.IsRailTile(tile)) primary_clear=false;
                }
                if(!primary_clear) {continue;}
                local tracks=b.BuildTrackPair(path,start,goal,start2,goal2,first_reserved,reserved,40);
                path2=tracks==null ? null : tracks.path2;
                if(tracks!=null) {
                    path=tracks.path;primary_tiles={};
                    foreach(tile in b.PathTiles(path)) primary_tiles[tile] <- true;
                }
                if(path2==null) {
                    if(b.planning_timed_out) {
                        this.state.branch_tried[attempt]=AIDate.GetCurrentDate()+30;
                        this.state.branch_cursor[cursor_key] <- (position+1)%candidates.len();
                        b.planning_deadline=0;
                        return false;
                    }
                    if(!b.ReleasePendingStations()) return false;
                    continue;
                }
                // Never add a junction to unrelated passenger/coal infrastructure.
                local foreign_rail=false;
                foreach(tile in b.PathTiles(path2))
                    if(AIRail.IsRailTile(tile) && !(tile in primary_tiles)) foreign_rail=true;
                if(foreign_rail) {if(!b.ReleasePendingStations()) return false;continue;}
                local entrance=b.StationEntrance(goal,goal2,path,path2);
                if(entrance==null) {if(!b.ReleasePendingStations()) return false;continue;}
                local f={path=path,start=start,goal=goal,secondary={path=path2,start=start2,goal=goal2},
                    entrances=[entrance],outbound=outbound,line_signals=[]};
                if(farm) {
                    local protected_tiles={};
                    foreach(t in b.StationTiles(site)) protected_tiles[t] <- true;
                    if(site.loop!=null) foreach(p in site.loop.pieces) foreach(t in p) protected_tiles[t] <- true;
                    depot_site=this.PickupDepotSite(NetworkSegment(f),true,protected_tiles);
                    if(depot_site==null || depot_site.tile in layout.reserved) {
                        if(!b.ReleasePendingStations()) return false;
                        continue;
                    }
                }
                f.path=PrependJunction(path,layout.lanes[0],layout);
                f.secondary.path=PrependJunction(path2,layout.lanes[1],layout);
                f.start=[layout.lanes[0][0],layout.lanes[0][0]-d];
                f.secondary.start=[layout.lanes[1][0],layout.lanes[1][0]-d];
                f.grade <- {signals=layout.signals,merges=layout.merges,d=d,kind=layout.kind,ramp=layout.ramp,end=layout.end};
                b.planning_deadline=0;
                this.state.plan <- {segment=NetworkSegment(f),entrance=entrance,cargo=cargo,junction=candidate.index,
                    site={tile=site.tile,dir=site.dir},depot_site=depot_site,
                    loop=site.loop==null ? null : {pieces=site.loop.pieces,signals=site.loop.signals,remove=site.loop.remove,junction=site.loop.junction}};
                if(farm) this.state.plan.farm <- target;
                b.reusable_rails=null;
                AILog.Info("Freight network: branch planned; junction oriented for "+
                    (d==-j.d ? "reverse" : "through")+" arrival so returning trains merge towards the "+
                    (farm ? (cargo==FreightCargo("WOOD")?"sawmill":cargo==FreightCargo("IORE")?"steel mill":"factory") : "pickup")+".");
                AILog.Info("Freight network: branch planned; bringing network trains into depot for junction construction.");
                return true;
            }
        }
        this.state.branch_cursor[cursor_key] <- (first+1)%candidates.len();
        b.reusable_rails=null; b.planning_deadline=0;
        if(deferred_attempt) b.planning_timed_out=true;
        AILog.Info(deferred_attempt ? "Freight network: branch approaches are cooling down; retrying later." : "Freight network: no safe branch found; existing network retained.");
        return false;
    }
    function PickupDepotSite(segment=null,planned=false,protected_tiles=null)
    {
        if(segment==null) segment=this.state.segments[this.state.stage-1];
        if(!("a" in segment) || !("z" in segment)) return null;
        // At the goal/pickup end, the outbound lane approaches the station.
        local lane=segment.outbound,nodes=lane==0?segment.a:segment.z;
        local other=lane==0?segment.z:segment.a;
        local near=lane==0?segment.goal:segment.goal2;
        local far=lane==0?segment.goal2:segment.goal;
        local step=near[0]-near[1],reserved=[];
        foreach(n in other) reserved.append(n[0]);
        if(protected_tiles!=null) foreach(tile,_ in protected_tiles) reserved.append(tile);
        local entrance={crosses=[{a=near[0]+step,b=far[0]+step}]};
        local site=this.builder.DepotSite(UnpackRailPath(nodes),reserved,entrance);
        if(site==null) return null;
        local tiles=this.builder.PathTiles(UnpackRailPath(nodes)),i=site.index;
        return {tile=site.depot,front=site.front,
            pieces=[[site.before,site.front,site.depot],[site.after,site.front,site.depot]],
            signals=[[tiles[i-1],tiles[i]],[tiles[i+1],tiles[i+2]]]};
    }
    function BuildPickupDepot(site,journal)
    {
        // Record before commands can suspend, so interrupted construction is recoverable.
        this.state.transaction.depot <- site.tile;
        if(!EnsureMoney(30000) || !AIRail.BuildRailDepot(site.tile,site.front)) {AILog.Warning("Pickup depot construction failed at "+site.tile+": "+AIError.GetLastErrorString());return false;}
        // Running signals may already occupy this tile (especially on farm branches).
        // Remove that waiting point before adding the depot junction, with rollback.
        if(site.pieces.len()>0 && !JournalSignal(journal,site.front,site.pieces[0][0],AIRail.SIGNALTYPE_NONE)) return false;
        foreach(p in site.pieces) if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) {
            journal.pieces.append(p);
            if(!AIRail.BuildRail(p[0],p[1],p[2])) {AILog.Warning("Pickup depot connection failed at "+p[1]+": "+AIError.GetLastErrorString());return false;}
        }
        local signals="signals" in site?site.signals:[site.signal];
        foreach(signal in signals) if(!JournalSignal(journal,signal[0],signal[1],AIRail.SIGNALTYPE_PBS_ONEWAY)) return false;
        AILog.Info("Freight network: dedicated pickup-station depot built at "+site.tile+".");
        return true;
    }
    function BuyBranchTrain(cargo,depot,source,destination,industry=null)
    {
        // Size the consist from the source industry's monthly output.
        local max_wagons=this.builder.platform_length-1;
        if(max_wagons<2) max_wagons=2;
        local demand=MonthlyCargoDemand(cargo,industry,null);
        local wagons=TrainBuyer(cargo).SizedWagons(demand,max_wagons);
        if(wagons<2) wagons=2;
        return TrainBuyer(cargo).BuildCargoTrain(depot,source,destination,wagons,true,false,this.builder.platform_length*16);
    }
    function ConstructBranch(f,site,j,cargo,farm=null)
    {
        local pickup_industry=farm!=null ? farm : (this.state.stage==1 ? this.state.chain.mill : this.state.chain.factory);
        if(RivalIndustryStation(pickup_industry)) return false;
        local b=this.builder, journal={pieces=[],structures=[],removed=[],signals=[]};
        // Reuse the depot position validated at plan time: re-deriving it
        // after the first line was built can disagree with that snapshot.
        local depot_site=("depot_site" in this.state.plan && this.state.plan.depot_site!=null) ?
            this.state.plan.depot_site : (farm==null?this.PickupDepotSite():this.PickupDepotSite(NetworkSegment(f),true));
        if(depot_site==null) return false;
        local size=StationFootprint(site.dir,b.platform_length);
        // Town roads can grow into the planned signal sites while trains return.
        if(site.loop!=null) foreach(signal in site.loop.signals) if(!AITile.IsBuildable(signal[0]) &&
            !(signal[0]==f.goal[0] && AIRail.IsRailTile(signal[0]))) {
                AILog.Info("Freight network: loop signal site blocked; falling back to standard terminus.");
                site.fallback_reason <- "Loop signal site blocked";
                site.loop=null;
                break;
            }
        local station_ok=b.CanBuildStation(site);
        local acceptance=AITile.GetCargoAcceptance(site.tile,cargo,size[0],size[1],AIStation.GetCoverageRadius(AIStation.STATION_TRAIN));
        if(!station_ok || (farm==null?acceptance<8:!this.FeederSiteValid(site,cargo,true) || !this.FeederSiteValid(this.state.stations[this.FeederStationIndex(cargo)],cargo,false))) {AILog.Warning("Freight network: planned station is no longer viable: build="+station_ok+", acceptance="+acceptance+", "+AIError.GetLastErrorString());return false;}
        foreach(pending in b.pending_stations) if("primary_recovery" in pending && pending.primary_recovery.upgrade!=null) {
            foreach(piece in pending.primary_recovery.upgrade.pieces) journal.pieces.append(piece);
            foreach(structure in pending.primary_recovery.upgrade.structures) journal.structures.append(structure);
        }
        this.state.transaction={upgrade=journal,station={tile=site.tile,dir=site.dir}};
        foreach(pending in b.pending_stations) if("earthwork_original" in pending)
            this.state.transaction.earthwork_original <- pending.earthwork_original;
        b.pending_stations=[];
        b.build_journal=journal;
        local ok=true;
        // Only the merge/diverge tiles need clearing; retain nearby main-line signals.
        foreach(tile in f.grade.merges) {
            local front=tile-f.grade.d,back=tile+f.grade.d;
            local a=AIRail.GetSignalType(tile,front),z=AIRail.GetSignalType(tile,back);
            if(a!=AIRail.SIGNALTYPE_NONE || z!=AIRail.SIGNALTYPE_NONE) {
                journal.signals.append([tile,front,back,a,z]);
                if(a!=AIRail.SIGNALTYPE_NONE) ok=AIRail.RemoveSignal(tile,front) && ok;
                else ok=AIRail.RemoveSignal(tile,back) && ok;
            }
        }
        ok=ok && (farm!=null || this.BuildPickupDepot(depot_site,journal)) && b.BuildStation(site) && b.BuildPath(f) && b.BuildPath(f.secondary);
        // Crossover pieces are journalled separately from running rails.
        foreach(c in f.entrances[0].crosses) foreach(p in [[c.from,c.a,c.b],[c.a,c.b,c.to]])
            if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) journal.pieces.append(p);
        if(ok) {
            ok=b.BuildStationEntrances(f);
            if(!ok) AILog.Warning("Freight network: station entrance construction failed: "+AIError.GetLastErrorString());
        }
        if(ok && site.loop!=null) {
            local recovery={pieces=[],signals=[],removed=[]};
            this.state.transaction.loop <- recovery;
            if(!site.loop.Build(recovery,true)) {
                // Build restores the original crossover and signals on failure.
                // Verify that base entrance before commissioning the terminus.
                ok=b.BuildStationEntrances(f);
                if(ok) RiroFallbackSign(site.tile,site.loop.failure_reason);
                AILog.Info("Freight network: RIRO construction failed; falling back to standard terminus.");
            } else RiroFallbackSign(site.tile);
        } else if(ok) {
            RiroFallbackSign(site.tile,"fallback_reason" in site ? site.fallback_reason : "No viable loop site");
            AILog.Info("Freight network: using standard terminus; RIRO loop does not fit.");
        }
        if(ok) foreach(signal in f.grade.signals)
            if(!JournalSignal(journal,signal[0],signal[1],AIRail.SIGNALTYPE_PBS_ONEWAY)) {AILog.Warning("Freight junction signal failed at "+signal[0]+": "+AIError.GetLastErrorString());ok=false;}
        if(ok) for(local lane=0;lane<2;lane++) {
            local line=lane==0?f:f.secondary;
            local tiles=b.PathTiles(line.path);
            if(lane==f.outbound) tiles.reverse();
            for(local i=3;i<tiles.len()-3;i+=b.platform_length+1) {
                local tile=tiles[i];
                if(AIMap.DistanceManhattan(tile,j.tile)<10) continue;
                b.AddOneWaySignal(f,tiles,i);
            }
        }
        if(ok && farm!=null) ok=this.BuildPickupDepot(depot_site,journal);
        b.build_journal=null;
        if(ok) AILog.Info("Freight junction: "+f.grade.kind+" separates crossing traffic; close approach and exit signals verified.");
        if(!ok) {AILog.Warning("Freight network: rolling back unfinished branch: "+AIError.GetLastErrorString());this.Recover();return false;}
        local source=farm==null?this.state.stations[this.state.stage]:site;
        local destination=farm==null?site:this.state.stations[this.FeederStationIndex(cargo)];
        local cargoes=farm==null?[cargo]:this.FeederCargoes(cargo);
        // The pickup industry each cargo trains' output is sized from.
        local source_industry=null;
        if(farm!=null) source_industry=farm;
        else if(cargo==FreightCargo("STEL")) source_industry=this.state.chain.mill;
        else if("factory" in this.state.chain) source_industry=this.state.chain.factory;
        else source_industry=this.state.chain.mill;
        this.state.transaction.trains <- [];
        foreach(c in cargoes) {
            local train=this.BuyBranchTrain(c,depot_site.tile,source.tile,destination.tile,source_industry);
            if(train<0) {this.Recover();return false;}
            this.state.transaction.trains.append(train);
        }
        // Commission together; farm trains wait until both purchases succeed.
        foreach(index,train in this.state.transaction.trains) {
            local route={depot=depot_site.tile,station_a=source.tile,station_b=destination.tile,
                source_industry=source_industry,target_industry=farm!=null?this.FeederIndustry(cargo):(cargo==FreightCargo("STEL")?this.state.chain.factory:-1)};
            this.optimiser.Register(train,route,b.platform_length);
            this.optimiser.trains[train].cargo=cargoes[index];
            this.optimiser.trains[train].network <- true;
            this.optimiser.trains[train].phase="dispatch";
            if(AIIndustry.IsValidIndustry(source_industry)) {
                this.optimiser.trains[train].source_industry <- source_industry;
                this.optimiser.trains[train].production_baseline <- AIIndustry.GetLastMonthProduction(source_industry,cargoes[index]);
                this.optimiser.trains[train].production_level <- this.optimiser.trains[train].production_baseline;
            }
        }
        if(farm==null) this.state.stations.append({tile=site.tile,dir=site.dir});
        else {
            local field=this.FeederSources(cargo);
            if(!(field in this.state)) this.state[field] <- {};
            this.state[field][farm] <- {tile=site.tile,dir=site.dir,depot=depot_site.tile};
        }
        j.used=true;
        local segment=NetworkSegment(f);
        segment.parent_segment <- j.segment; segment.junction_tile <- j.tile;
        segment.junction_at <- ("at" in j) ? j.at : null;
        segment.goal_station <- site.tile;
        this.RecordSegment(segment);
        if(farm==null) {
            this.state.stage++;
            if(cargo==FreightCargo("GOOD")) this.QueueFarmExpansion();
        }
        this.state.transaction=null;
        AILog.Info(farm==null?"Freight network: shared-track "+AICargo.GetName(cargo)+" branch commissioned.":(cargo==FreightCargo("WOOD")?"Freight network: wood branch commissioned into existing sawmill.":cargo==FreightCargo("IORE")?"Freight network: iron ore branch commissioned into existing steel mill.":"Freight network: farm branch commissioned with grain and livestock trains."));
        return true;
    }
}

// A fleet of independent freight networks. Waiting or exhausted projects yield;
// completed chains remain maintained while new sources can start another chain.
class FreightNetworks
{
    production_policy=null;
    networks=null; cursor=0; source_label="IORE"; passenger_optimiser=null; length=4;
    constructor(length,saved=null,label="IORE")
    {
        this.length=length;this.source_label=label;this.networks=[];
        this.production_policy=saved!=null && "production_policy" in saved ? saved.production_policy : IndustryProductionPolicy();
        if(saved!=null && "networks" in saved) {
            foreach(network in saved.networks) this.networks.append(FreightNetwork(length,network,label));
            if("cursor" in saved) this.cursor=saved.cursor;
        } else if(saved!=null) this.networks.append(FreightNetwork(length,saved,label));
        if(this.networks.len()==0) this.networks.append(FreightNetwork(length,null,label));
        foreach(n in this.networks) {
            n.state.production_policy=this.production_policy;
            n.siblings=this.networks;
        }
    }
    function NewNetwork() {local n=FreightNetwork(this.length,null,this.source_label);n.state.production_policy=this.production_policy;return n;}
    function Save()
    {
        local saved=[];foreach(network in this.networks) saved.append(network.Save());
        return {production_policy=clone this.production_policy,source_label=this.source_label,networks=saved,cursor=this.cursor};
    }
    function Review()
    {
        foreach(network in this.networks) network.Review();
        if(this.passenger_optimiser!=null) this.passenger_optimiser.Review();
    }
    function OnIndustryOpened(industry)
    {
        foreach(network in this.networks) network.OnIndustryOpened(industry);
    }
    function OnIndustryClosed(industry)
    {
        foreach(network in this.networks) network.OnIndustryClosed(industry);
    }
    function NeedsContinuation()
    {
        foreach(network in this.networks) if(network.NeedsContinuation()) return true;
        return false;
    }
    function TryPostGoodsFarms()
    {
        local excluded={};
        foreach(n in this.networks) if("farms" in n.state) foreach(farm,_ in n.state.farms) excluded[farm] <- true;
        foreach(n in this.networks) {
            if(!("post_goods_farms" in n.state) || !n.state.post_goods_farms) continue;
            n.excluded_sources=excluded;
            if(n.TryBuildFarm()) {n.state.post_goods_farms=false;return true;}
            // Retain the request across temporary waits, but let other work run.
            if(!n.FarmExpansionPending(true) && n.state.transaction==null && n.state.held.len()==0 &&
                (!("plan" in n.state) || n.state.plan==null)) n.state.post_goods_farms=false;
        }
        return false;
    }
    function TryFactoryGoods()
    {
        local count=this.networks.len();
        for(local i=0;i<count;i++) {
            local index=(this.cursor+i)%count,network=this.networks[index];
            if(!network.NeedsFactoryGoods()) continue;
            if(network.TryBuild()) {
                this.cursor=(index+1)%count;
                return true;
            }
        }
        return false;
    }
    function TryBuildFarm()
    {
        if(this.source_label!="IORE") return false;
        local excluded={},starter=null;
        foreach(network in this.networks) {
            if(network.source_label=="FARM" && network.state.stage==0) starter=network;
            if("farms" in network.state) foreach(farm,_ in network.state.farms) excluded[farm] <- true;
            foreach(field in ["mines","forests"]) if(field in network.state) foreach(source,_ in network.state[field]) excluded[source] <- true;
        }
        // Completed hubs get the first opportunity to add suppliers. Keep using
        // the original factory station, including when goods has a separate station.
        local hub_pending=false;
        foreach(completed in [true,false]) foreach(network in this.networks) {
            if(network.state.stage==0 || (network.state.stage>=network.LastStage())!=completed) continue;
            network.excluded_sources=excluded;
            if(!("farm_excluded_count" in network.state) || network.state.farm_excluded_count!=excluded.len()) {
                network.state.farm_scan <- 0;
                network.state.farm_excluded_count <- excluded.len();
            }
            if(network.TryBuildFarm()) return true;
            if(completed && (network.FarmExpansionPending(true) || network.state.transaction!=null ||
                network.state.held.len()>0 || ("plan" in network.state && network.state.plan!=null))) hub_pending=true;
        }
        // A temporary delay is not a reason to open another factory. Other
        // construction can still run while the existing hub waits for its retry.
        if(hub_pending) return false;
        if(starter==null) {
            starter=FreightNetwork(this.length,null,"FARM");
            starter.state.production_policy=this.production_policy;
            this.networks.append(starter);
        }
        starter.excluded_sources=excluded;
        return starter.TryBuildFarm();
    }
    function TryBuildOre() {return this.TryBuild("IORE");}
    function TryBuild(label=null)
    {
        local excluded={},failed={},vacant=false;
        foreach(network in this.networks) {
            if(network.state.chain!=null) excluded[network.state.chain.mine] <- true;
            if("farms" in network.state) foreach(farm,_ in network.state.farms) excluded[farm] <- true;
            foreach(field in ["mines","forests"]) if(field in network.state) foreach(source,_ in network.state[field]) excluded[source] <- true;
            foreach(key,value in network.state.failed) {
                // A stale sibling snapshot must not undo a proven failure or shorten a cooldown.
                if(!(key in failed) || typeof value=="bool" ||
                    (typeof failed[key]!="bool" && value>failed[key])) failed[key] <- value;
            }
            if(network.state.stage==0 && (label==null || network.source_label==label)) vacant=true;
        }
        local count=this.networks.len(),start=count>0?this.cursor%count:0;
        for(local i=0;i<count;i++) {
            local index=(start+i)%count,network=this.networks[index];
            if(label!=null && (network.source_label!=label || (label!="IORE" && label!="WOOD" && network.state.stage>=network.LastStage()))) continue;
            network.excluded_sources=excluded;network.state.failed=failed;
            this.cursor=(index+1)%count;
            if(network.TryBuild()) return true;
        }
        if(vacant) return false;
        local next=this.NewNetwork();
        next.excluded_sources=excluded;next.state.failed=failed;
        this.networks.append(next);
        this.cursor=this.networks.len()-1;
        AILog.Info("Freight expansion: looking for another "+this.source_label+" chain while existing networks remain in service.");
        return next.TryBuild();
    }
}
