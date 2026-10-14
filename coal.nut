function FreightCargo(label)
{
    foreach(cargo,_ in AICargoList()) if(AICargo.GetCargoLabel(cargo)==label) return cargo;
    return -1;
}

function CoalCargo() { return FreightCargo("COAL"); }

// Shared freight construction and optimisation; configuration selects the industry chain.
class CoalRoutes
{
    dual_next_target=null;
    source_hub=null;
    continuation=false;
    builder=null;
    cargo=-1;
    buyer=null;
    optimiser=null;
    passenger_optimiser=null;
    freight_name="Coal";
    minimum_production=100;
    production_policy=null;
    output_label=null;
    retry_after=0;
    attempted=null;
    deferred=null;
    services=null;
    phase=true;
    single_first=true;
    allow_single_station=true;
    production_month=null;
    startup_complete=false;
    land_sources_only=false;
    constructor(builder,saved=null,label="COAL")
    {
        this.builder=builder;
        this.production_policy=saved!=null && "production_policy" in saved ? saved.production_policy : IndustryProductionPolicy();
        if(label=="IORE") { this.freight_name="Iron ore"; this.minimum_production=1; this.output_label="STEL"; }
        if(label=="WOOD") { this.freight_name="Wood"; this.minimum_production=1; this.output_label="GOOD"; }
        // Oil wells produce orders of magnitude more units than other
        // industries: the initial viability threshold is 100,000 units/month,
        // relaxed by the shared production policy down to 10% when no
        // viable connection exists.
        if(label=="OIL_") { this.freight_name="Oil"; this.minimum_production=100000; this.output_label="GOOD"; this.land_sources_only=true; }
        this.cargo=FreightCargo(label); this.buyer=TrainBuyer(this.cargo);
        this.optimiser=ServiceOptimiser(this.buyer,saved!=null && "optimiser" in saved ? saved.optimiser : null);
        this.attempted={}; this.services={}; this.deferred={};
        if(saved!=null) {
            this.startup_complete="startup_complete" in saved ? saved.startup_complete : false;
            this.deferred="deferred" in saved ? clone saved.deferred : {};
            this.attempted=clone saved.attempted; this.services=clone saved.services; this.phase=saved.phase;
            this.retry_after="retry_after" in saved ? saved.retry_after : 0;
        }
    }
    function Save() { return {production_policy=clone this.production_policy,startup_complete=this.StartupComplete(),deferred=clone this.deferred,attempted=clone this.attempted,services=clone this.services,phase=this.phase,optimiser=this.optimiser.Save(),retry_after=this.retry_after}; }

    function StartupComplete()
    {
        // Latch after the first commissioned service, including older saved games.
        if(!this.startup_complete) foreach(train,route in this.optimiser.trains)
            if(AIVehicle.IsValidVehicle(train) && AIStation.IsValidStation(route.station_a) &&
                AIStation.IsValidStation(route.station_b)) {this.startup_complete=true;break;}
        return this.startup_complete;
    }

    // A newly opened industry is interesting when it produces this manager's
    // cargo or accepts it while producing the chain output.
    function InterestedIn(industry)
    {
        if(this.cargo<0 || !AIIndustry.IsValidIndustry(industry)) return false;
        local outputs=IndustryOutputs(industry);
        if(outputs==null) return false;
        foreach(c,_ in outputs) if(c==this.cargo) return true;
        return this.IsDestination(industry);
    }

    function OnIndustryOpened(industry)
    {
        if(!this.InterestedIn(industry)) return;
        if(AIDate.GetCurrentDate()<this.retry_after || !this.phase) {
            this.retry_after=AIDate.GetCurrentDate();
            this.phase=true;
            AILog.Info(this.freight_name+": a new industry opened; re-checking connections now.");
        }
    }

    // Pair keys are "source:target"; OpenTTD's Squirrel has no split(), so
    // match the colon-delimited id with slice comparisons.
    function PairTouchesIndustry(key, industry)
    {
        local prefix=industry+":";
        if(key.len()>prefix.len() && key.slice(0,prefix.len())==prefix) return true;
        local suffix=":"+industry;
        return key.len()>suffix.len() && key.slice(key.len()-suffix.len())==suffix;
    }

    function OnIndustryClosed(industry)
    {
        local affected=[];
        foreach(train,service in this.services)
            if(service.source==industry || (this.DestinationIsIndustry() && service.target==industry)) affected.append(service);
        foreach(train,record in this.optimiser.trains) {
            local closed=("source_industry" in record && record.source_industry==industry) ||
                ("target_industry" in record && record.target_industry==industry);
            foreach(service in affected) if(record.station_a==AIStation.GetStationID(service.station_a) &&
                record.station_b==AIStation.GetStationID(service.station_b)) closed=true;
            if(closed) this.optimiser.ForceSale(train);
        }
        // Forget attempted and deferred pairs involving the dead industry.
        local dead=[];
        foreach(key,_value in this.attempted)
            if(this.PairTouchesIndustry(key,industry)) dead.append(key);
        foreach(key in dead) delete this.attempted[key];
        dead=[];
        foreach(key,_value in this.deferred)
            if(this.PairTouchesIndustry(key,industry)) dead.append(key);
        foreach(key in dead) delete this.deferred[key];
    }

    // Once per game month: refresh each service's source production level so
    // fleet expansion can respond to growth and shrinking.
    function UpdateProductionNotes()
    {
        local today=AIDate.GetCurrentDate();
        local month=AIDate.GetYear(today)*12+AIDate.GetMonth(today);
        if(month==this.production_month) return;
        this.production_month=month;
        foreach(train,service in this.services) {
            if(!(train in this.optimiser.trains) || !AIIndustry.IsValidIndustry(service.source)) continue;
            local record=this.optimiser.trains[train];
            local level=AIIndustry.GetLastMonthProduction(service.source,this.cargo);
            if("production_level" in record) record.production_level=level; else record.production_level <- level;
            if(!("production_baseline" in record)) record.production_baseline <- level;
        }
    }

    // During startup, passengers must wait while a timed-out coal pair is
    // merely cooling down. Exhausted pairs and funds waits do yield.
    function YieldsStartup()
    {
        if(!this.phase) return true;
        foreach(_key,_value in this.deferred) return false;
        return true;
    }

    function Review()
    {
        this.UpdateProductionNotes();
        this.optimiser.Review();
        ExpandBlockedStations(this.builder,this.optimiser,null,StationExpansionJournal);
        if(this.passenger_optimiser!=null) this.passenger_optimiser.Review();
    }

    function IsDestination(industry)
    {
        if(AIIndustry.IsCargoAccepted(industry,this.cargo)!=AIIndustry.CAS_ACCEPTED) return false;
        local outputs=IndustryOutputs(industry);
        if(outputs==null) return false;
        if(this.output_label==null) return outputs.Count()==0;
        foreach(output,_ in outputs) if(AICargo.GetCargoLabel(output)==this.output_label) return true;
        return false;
    }

    function HasCompetingMineStation(industry)
    {
        return RivalIndustryStation(industry);
    }

    function PickPair()
    {
        RailTypeReview();
        if(this.cargo<0 || this.buyer.BestEngine()<0 || this.buyer.BestWagon()<0) return null;
        local sources=[],targets=[],production={};
        foreach(industry,_ in AIIndustryList()) {
            local monthly=AIIndustry.GetLastMonthProduction(industry,this.cargo);
            if(monthly>=IndustryProductionMinimum(this.production_policy,this.minimum_production) && (!this.land_sources_only || !AIIndustry.IsBuiltOnWater(industry)) && !this.HasCompetingMineStation(industry)) {
                sources.append(industry);
                // Rival-served sources are excluded rather than discounted.
                production[industry] <- monthly;
            }
            else if(this.IsDestination(industry)) targets.append(industry);
        }
        local best=null, score=-1.0, best_production=-1;
        foreach(source in sources) {
            if(production[source]<best_production) continue;
            local served=false;
            foreach(train,service in this.services) if(service.source==source) {
                foreach(id,record in this.optimiser.trains) if(AIVehicle.IsValidVehicle(id) && record.station_a==AIStation.GetStationID(service.station_a)) served=true;
            }
            if(served) continue;
            foreach(target in targets) {
                local key=source+":"+target;
                if(key in this.attempted || key in this.deferred || this.builder.DeferredConnection(this.ConnectionPlanKey(source,target))) continue;
                local dist=AIMap.DistanceManhattan(AIIndustry.GetLocation(source),AIIndustry.GetLocation(target));
                if(!IndustryDistanceAllowed(dist)) continue;
                local value=production[source]*(75+AIBase.RandRange(51)).tofloat()/
                    dist;
                // Competition-adjusted output takes precedence over distance and random tie-breaks.
                if(production[source]>best_production || value>score) {
                    best_production=production[source]; score=value; best=[source,target];
                }
            }
        }
        return best;
    }

    function Sites(industry,target,loading)
    {
        local sites=this.SiteCandidates(industry,target,loading,false);
        foreach(site in sites) if(site.loop!=null) return sites;
        if(this.builder.PlanningExpired()) return sites;
        local reshaped=this.SiteCandidates(industry,target,loading,true);
        return reshaped.len()>0 ? reshaped : sites;
    }

    function SiteCandidates(industry,target,loading,reshape)
    {
        local radius=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
        local tiles=loading ? AITileList_IndustryProducing(industry,radius) : AITileList_IndustryAccepting(industry,radius);
        local candidates=[];
        foreach(tile,_ in tiles) foreach(dir in [AIRail.RAILTRACK_NE_SW,AIRail.RAILTRACK_NW_SE]) {
            if(this.builder.PlanningExpired()) return [];
            local size=StationFootprint(dir,this.builder.platform_length,this.builder.station_platforms);
            if(!AreaIsBuildable(tile,size[0],size[1])) continue;
            local value=loading ? AITile.GetCargoProduction(tile,this.cargo,size[0],size[1],radius) :
                AITile.GetCargoAcceptance(tile,this.cargo,size[0],size[1],radius);
            if(value<(loading ? 1:8)) continue;
            local site={tile=tile,dir=dir,platforms=this.builder.station_platforms};
            foreach(exit in StationExits(tile,dir,this.builder.platform_length)) {
                local candidate=this.builder.RiroSite(site,exit,reshape);
                if(candidate==null) continue;
                // Both station mouths are offered, the far one penalised: the
                // far mouth has the opposite junction handedness, so the
                // preferred branch orientation can always find a compatible
                // approach. The pickup depot probe handles either mouth.
                candidate.score <- AIMap.DistanceManhattan(exit[0],target)+AIMap.DistanceManhattan(tile,AIIndustry.GetLocation(industry))+
                    (StationExitFacesTarget(site,exit,target,this.builder.platform_length) ? 0 : 10000);
                candidates.append(candidate);
            }
        }
        candidates.sort(function(a,b) {
            if((a.loop==null)!=(b.loop==null)) return a.loop!=null ? -1 : 1;
            if(("earthwork" in a)!=("earthwork" in b)) return ("earthwork" in a) ? 1 : -1;
            return a.score<b.score ? -1 : (a.score>b.score ? 1:0);
        });
        if(candidates.len()>6) candidates.resize(6);
        return candidates;
    }

    function TryBuild()
    {
        if(!this.phase && (this.deferred.len()>0 || (this.minimum_production>1 && this.production_policy.percent>10)) && AIDate.GetCurrentDate()>=this.retry_after) {
            local remaining={};
            foreach(key,value in this.deferred) {
                if(this.builder.DeferredConnection("industry:"+this.cargo+":"+key)) remaining[key] <- value;
            }
            this.deferred=remaining; this.phase=true;
            AILog.Info(this.freight_name+": rechecking connections after the selection cooldown.");
        }
        if(!this.phase) return false;
        if(AIDate.GetCurrentDate()<this.retry_after) return false;
        local pair=this.PickPair();
        if(pair==null) {
            if(this.minimum_production>1 && this.cargo>=0 && this.buyer.BestEngine()>=0 && this.buyer.BestWagon()>=0 &&
                RelaxIndustryProduction(this.production_policy,this.freight_name)) {
                // Schedule a fresh scan even after reaching the final threshold.
                this.phase=true;
            } else this.phase=false;
            this.retry_after=AIDate.GetCurrentDate()+30;
            AILog.Info(this.freight_name+": no remaining viable untried connections at the production threshold; other route types may now be planned.");
            return false;
        }
        local available=AICompany.GetBankBalance(AICompany.COMPANY_SELF)+AICompany.GetMaxLoanAmount()-AICompany.GetLoanAmount();
        local required=AIEngine.GetPrice(this.buyer.BestEngine())+AIEngine.GetPrice(this.buyer.BestWagon())*(this.builder.platform_length*2-1)+80000;
        if(available<required) {
            this.retry_after=AIDate.GetCurrentDate()+30;
            AILog.Info(this.freight_name+": waiting for funds; yielding to other construction.");
            return false;
        }
        AILog.Info(this.freight_name+": planning "+AIIndustry.GetName(pair[0])+" -> "+AIIndustry.GetName(pair[1]));
        local key=pair[0]+":"+pair[1];
        this.attempted[key] <- true;
        // Connect can yield and process industry-closure events, which remove
        // this key. Early rejection can also leave the previous timeout flag.
        this.builder.planning_timed_out=false;
        local built=this.Connect(pair[0],pair[1]);
        if(!built && this.builder.planning_timed_out && key in this.attempted) {
            delete this.attempted[key];
            // Never resurrect a cancelled pair in the retry queue.
            if(AIIndustry.IsValidIndustry(pair[0]) && this.DestinationValid(pair[1])) {
                this.deferred[key] <- true;
                this.retry_after=AIDate.GetCurrentDate()+7;
            }
        }
        return true;
    }

    function BuyInitialTrain(depot,a,z,source)
    {
        local max_wagons=this.builder.platform_length>3 ? this.builder.platform_length-1 : 2;
        local wagons=this.buyer.SizedWagons(MonthlyCargoDemand(this.cargo,source,null),max_wagons);
        return this.buyer.BuildCargoTrain(depot,a,z,wagons);
    }
    function ServiceBuilt(found,a,z,train) {}
    function AcceptInfrastructure(found) {return true;}

    function DestinationIsIndustry() {return true;}
    function DestinationValid(target) {return AIIndustry.IsValidIndustry(target);}
    function DestinationLocation(target) {return AIIndustry.GetLocation(target);}

    function ConnectionPlanKey(source,target) {return "industry:"+this.cargo+":"+source+":"+target;}
    function Connect(source,target)
    {
        RailTypeReview();
        if(this.source_hub!=null) AIRail.SetCurrentRailType(AIRail.GetRailType(this.source_hub.pickup.tile));
        if(!AIIndustry.IsValidIndustry(source) || !this.DestinationValid(target) ||
            !IndustryEndpointsAllowed(AIIndustry.GetLocation(source),this.DestinationLocation(target))) return false;
        if(!AIIndustry.IsValidIndustry(source) || (this.land_sources_only && AIIndustry.IsBuiltOnWater(source)) || RivalIndustryStation(source)) return false;
        local key=this.ConnectionPlanKey(source,target);
        if(this.builder.DeferredConnection(key)) return false;
        if(!this.builder.ReleasePendingStations()) return false;
        // Coal/industry endpoints do not grow over the route, so the return
        // line can safely wait for demand; town routes cannot.
        this.builder.single_first=this.single_first;
        this.builder.BeginPlanning(key,this.continuation || this.source_hub!=null,true);
        local result=this.ConnectWithinBudget(source,target);
        // A short search is inconclusive, not proof that no route exists.
        if(!result && this.builder.search_batches_limit<(40*this.builder.planning_percent+99)/100) this.builder.planning_timed_out=true;
        this.builder.LogRouteFailure(AIIndustry.GetLocation(source),
            this.DestinationIsIndustry()?AIIndustry.GetName(target):AITown.GetName(target),result);
        this.builder.FinishConnection(key,result);
        if(!result) this.builder.startup_failures++; else this.builder.startup_failures=0;
        if(!result) this.builder.ReleasePendingStations();
        this.builder.planning_deadline=0;
        this.builder.extra_reserved=null;
        return result;
    }
    function ConnectWithinBudget(source,target)
    {
        local b=this.builder;
        local deadline=b.planning_deadline;
        if(!AIIndustry.IsValidIndustry(source) || !this.DestinationValid(target)) return false;
        if(!b.ReleasePendingStations()) return false;
        local starts=this.source_hub==null ? this.Sites(source,this.DestinationLocation(target),true) : DualPickupSites(b,this.source_hub,this.DestinationLocation(target));
        local ends=this.Sites(target,AIIndustry.GetLocation(source),false);
        if(this.dual_next_target!=null) {
            local preferred=[];
            local from_tile=AIIndustry.GetLocation(source);
            foreach(site in ends) {
                if(b.PlanningExpired()) break;
                // The incoming line reaches the closest loop of the planned
                // dual hub, so the far section never drags the route across
                // extra bridges or earthworks.
                local dual=PlanDualStation(b,site,this.dual_next_target,false,from_tile);
                if(dual!=null) preferred.append(dual);
                // Leave attempts for ordinary layouts if the larger hub fails.
                if(preferred.len()>=2) break;
            }
            if(preferred.len()<2) foreach(site in ends) {
                if(b.PlanningExpired()) break;
                local dual=PlanDualStation(b,site,this.dual_next_target,true,from_tile);
                if(dual!=null) preferred.append(dual);
                if(preferred.len()>=2) break;
            }
            foreach(site in ends) preferred.append(site);
            ends=preferred;
        }
        if(this.source_hub==null && this.allow_single_station && (starts.len()==0 || ends.len()==0) && !b.PlanningExpired()) {
            AILog.Info("Station fallback: no two-platform site; trying a permanent one-train line.");
            b.station_platforms=1;
            starts=this.Sites(source,this.DestinationLocation(target),true);
            ends=this.Sites(target,AIIndustry.GetLocation(source),false);
            b.station_platforms=2;
        }
        if(starts.len()==0 || ends.len()==0)
            b.failure_detail=starts.len()==0 ? "No source station site" : "No destination station site";
        b.retained_prefixes={}; b.reuse_prefixes=false;
        foreach(a in starts) foreach(z in ends) {
            if(RivalIndustryStation(source)) { b.failure_detail="A rival company serves this industry"; return false; }
            b.planning_deadline=deadline;
            if(b.PlanningExpired()) return false;
            if(StationPlatforms(a)>1 && b.LeftOutboundLane(a.exit)==b.LeftOutboundLane(z.exit)) {
                b.failure_detail="Station exits share one outbound lane";
                continue;
            }
            if(!StationExitFacesTarget(a,a.exit,z.tile,b.platform_length)) {
                b.failure_detail=this.source_hub!=null ? "Destination is behind the hub pickup exit" :
                    "Source station exit does not face the destination";
                continue;
            }
            if(!StationExitFacesTarget(z,z.exit,a.tile,b.platform_length)) {
                b.failure_detail="Destination station exit does not face the source";
                continue;
            }
            b.single_first=this.single_first && !("dual" in z) && this.source_hub==null;
            b.extra_reserved=[];
            if(this.source_hub!=null && "delivery_reserved" in this.source_hub)
                foreach(tile in this.source_hub.delivery_reserved) b.extra_reserved.append(tile);
            foreach(site in [a,z]) if("dual" in site) foreach(tile in site.dual.reserved) b.extra_reserved.append(tile);
            foreach(site in [a,z]) if(site.loop!=null) foreach(p in site.loop.pieces)
                if(p[1]!=site.loop.pieces[site.loop.pieces.len()-1][1]) b.extra_reserved.append(p[1]);
            if(!b.TryStationPair(a,z)) {if(b.PlanningExpired()) return false;continue;}
            if(!b.ReserveStations(a,z)) { b.ReleasePendingStations(); continue; }
            local found=b.FindPathBetween(a,z);
            // Smooth both running lines before building; reserved RIRO loops stay protected.
            if(found!=null) found=b.ImproveTerrain(found,a,z);
            if(found==null) { b.ReleasePendingStations(); continue; }
            if(RivalIndustryStation(source)) {
                b.CleanupRoute(found,a,z); b.ReleasePendingStations();
                b.failure_detail="A rival company serves this industry";
                return false;
            }
            b.failure_detail="Station construction failed";
            if(this.source_hub!=null) DualPickupStatus(this.source_hub,"Building route");
            if(!b.BuildPlannedStations(a,z)) { b.ReleasePendingStations(); continue; }
            b.failure_detail="Track/depot/signals failed";
            local built=b.BuildPath(found) && b.BuildPath(found.secondary) && b.BuildStationEntrances(found);
            local depot=built ? b.BuildDepot(found.depot_site) : AIMap.TILE_INVALID;
            built=built && AIRail.IsRailDepotTile(depot) && b.BuildLineSignals(found);
            if(built) {
                b.BuildPreferredStations(found);
                if("dual" in z && !("roro" in found.entrances[1])) built=false;
                if(this.source_hub!=null && !("roro" in found.entrances[0])) built=false;
            }
            if(built && !this.AcceptInfrastructure(found)) built=false;
            local train=-1;
            local size=StationFootprint(z.dir,b.platform_length,StationPlatforms(z));
            if(built) {
                local acceptance=(AIIndustry.IsValidIndustry(source) && this.DestinationValid(target)) ?
                    AITile.GetCargoAcceptance(z.tile,this.cargo,size[0],size[1],AIStation.GetCoverageRadius(AIStation.STATION_TRAIN)) : 0;
                if(acceptance>=8) {
                    b.failure_detail="Train purchase failed";
                    train=this.BuyInitialTrain(depot,a.tile,z.tile,source);
                } else b.failure_detail="Destination accepts "+acceptance+"/8 "+AICargo.GetName(this.cargo)+" at the new station";
            }
            if(train>=0) {
                this.services[train] <- {source=source,target=target,source_industry=source,target_industry=this.DestinationIsIndustry()?target:-1,station_a=a.tile,station_b=z.tile,depot=depot,single_route=SaveSingleRoute(b,found,a,z)};
                this.optimiser.Register(train,this.services[train],b.platform_length);
                if(AIIndustry.IsValidIndustry(source)) {
                    this.optimiser.trains[train].source_industry <- source;
                    this.optimiser.trains[train].production_baseline <- AIIndustry.GetLastMonthProduction(source,this.cargo);
                    this.optimiser.trains[train].production_level <- this.optimiser.trains[train].production_baseline;
                }
                if(this.source_hub!=null) this.source_hub.used=true;
                this.ServiceBuilt(found,a,z,train);
                if("dual" in z) AILog.Info("Dual RIRO: delivery service commissioned; shared pickup platforms ready for the next cargo leg.");
                if(this.source_hub!=null) AILog.Info("Dual RIRO: onward service now uses the shared station's separate pickup section.");
                b.pending_stations=[]; b.extra_reserved=null; b.ClearSearchSigns();
                AILog.Info("permanent_single" in found ? "Single-platform line commissioned; fleet permanently limited to one train." : "single" in found ? "Single main line commissioned without signals; two-platform stations retained." : "Two platforms and two connected tracks verified; station crossovers provide depot access.");
                local loops=0;
                foreach(entrance in found.entrances) if("roro" in entrance) loops++;
                AILog.Info(this.freight_name+": service operating with "+loops+" RIRO and "+(2-loops)+" standard terminus stations. Train="+train);
                return true;
            }
            if(AIRail.IsRailDepotTile(depot)) AITile.DemolishTile(depot);
            b.CleanupRoute(found,a,z); b.ReleasePendingStations();
        }
        b.extra_reserved=null; b.ClearSearchSigns();
        AILog.Info(this.freight_name+": no complete freight route found for this pair.");
        return false;
    }
}
