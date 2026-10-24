// City passenger loops. Only existing, verified two-way streets are used;
// construction never clears houses to make a corridor through a town.
class CityBuses
{
    networks=null; cooldown=null; pending=null; cargo=null; next_review=0;
    constructor(saved=null) {
        this.networks=[];this.cooldown={};this.cargo=PassengerCargo();
        if(saved!=null) {
            this.networks=saved.networks;this.cooldown=saved.cooldown;
            this.pending=saved.pending;
        }
        ::BusRailTowns={};
        foreach(net in this.networks) {
            BusRailTowns[net.town] <- true;
            if(!("rail_followup" in net)) net.rail_followup <- 0;
        }
    }
    function Save() {return {networks=this.networks,cooldown=this.cooldown,pending=this.pending};}
    function Neighbours(tile) {
        local result=[],x=AIMap.GetTileX(tile),y=AIMap.GetTileY(tile);
        foreach(d in [[1,0],[-1,0],[0,1],[0,-1]]) {
            local nx=x+d[0],ny=y+d[1];
            if(nx>=0 && ny>=0 && nx<AIMap.GetMapSizeX() && ny<AIMap.GetMapSizeY())
                result.append(AIMap.GetTileIndex(nx,ny));
        }
        return result;
    }
    function Engine() {
        local best=null,score=0;
        foreach(id,_ in AIEngineList(AIVehicle.VT_ROAD)) {
            if(!AIEngine.IsBuildable(id) || AIEngine.GetCargoType(id)!=this.cargo ||
                !AIRoad.RoadVehHasPowerOnRoad(AIEngine.GetRoadType(id),AIRoad.ROADTYPE_ROAD)) continue;
            local value=AIEngine.GetCapacity(id)*AIEngine.GetMaxSpeed(id).tofloat() /
                (1+AIEngine.GetRunningCost(id));
            if(value>score) {score=value;best=id;}
        }
        return best;
    }
    function Funds(amount) {
        EnsureMoney(amount);
        return AICompany.GetBankBalance(AICompany.COMPANY_SELF)>=amount;
    }
    function Cleanup() {
        if(this.pending==null) return true;
        // Keep unsuccessful removals in saved state and retry before building.
        for(local i=this.pending.stops.len()-1;i>=0;i--) {
            local tile=this.pending.stops[i];
            if(!AIRoad.IsRoadStationTile(tile) || AIRoad.RemoveRoadStation(tile)) this.pending.stops.remove(i);
        }
        if(this.pending.depot!=null && (!AIRoad.IsRoadDepotTile(this.pending.depot) ||
            AIRoad.RemoveRoadDepot(this.pending.depot))) this.pending.depot=null;
        if(this.pending.stops.len()==0 && this.pending.depot==null) this.pending=null;
        return this.pending==null;
    }
    // Passenger-producing house tiles in this stop's catchment. Count each
    // house once across the whole network, rather than summing overlapping stops.
    function Coverage(tile,town) {
        local result={},r=AIStation.GetCoverageRadius(AIStation.STATION_BUS_STOP);
        local x=AIMap.GetTileX(tile),y=AIMap.GetTileY(tile);
        for(local dx=-r;dx<=r;dx++) for(local dy=-r;dy<=r;dy++) {
            local nx=x+dx,ny=y+dy;
            if(nx<0 || ny<0 || nx>=AIMap.GetMapSizeX() || ny>=AIMap.GetMapSizeY()) continue;
            local t=AIMap.GetTileIndex(nx,ny);
            if(!AITile.IsHouseTile(t) || AITile.GetClosestTown(t)!=town) continue;
            local production=AITile.GetCargoProduction(t,this.cargo,1,1,0);
            if(production>0) result[t] <- production;
        }
        return result;
    }
    function Candidates(town) {
        local centre=AITown.GetLocation(town),cx=AIMap.GetTileX(centre),cy=AIMap.GetTileY(centre);
        local roads={},candidates=[];
        for(local dx=-28;dx<=28;dx++) for(local dy=-28;dy<=28;dy++) {
            local x=cx+dx,y=cy+dy;
            if(x<0 || y<0 || x>=AIMap.GetMapSizeX() || y>=AIMap.GetMapSizeY()) continue;
            local tile=AIMap.GetTileIndex(x,y);
            if(AIRoad.HasRoadType(tile,AIRoad.ROADTYPE_ROAD) && AIRoad.IsRoadTile(tile)) roads[tile] <- true;
        }
        // Label mutually reachable street components; isolated roads cannot
        // produce a network whose buses get lost between stops.
        local labels={},component=0;
        foreach(start,_ in roads) {
            if(start in labels) continue;
            local queue=[start];labels[start] <- component;
            for(local i=0;i<queue.len();i++) foreach(n in this.Neighbours(queue[i])) {
                if(!(n in roads) || n in labels) continue;
                if(AIRoad.AreRoadTilesConnected(queue[i],n) && AIRoad.AreRoadTilesConnected(n,queue[i])) {
                    labels[n] <- component;queue.append(n);
                }
            }
            component++;
        }
        foreach(tile,_ in roads) {
            if(AITile.IsStationTile(tile) || AITile.GetClosestTown(tile)!=town ||
                AITile.GetCargoAcceptance(tile,this.cargo,1,1,AIStation.GetCoverageRadius(AIStation.STATION_BUS_STOP))<8) continue;
            local cover=this.Coverage(tile,town);
            if(cover.len()==0) continue;
            foreach(front in this.Neighbours(tile)) {
                if(!(front in labels) || labels[front]!=labels[tile] || !AIRoad.AreRoadTilesConnected(tile,front)) continue;
                local ok=false;
                {local test=AITestMode();ok=AIRoad.BuildDriveThroughRoadStation(tile,front,AIRoad.ROADVEHTYPE_BUS,AIStation.STATION_NEW);}
                if(ok) {candidates.append({tile=tile,front=front,component=labels[tile],cover=cover});break;}
            }
        }
        return {sites=candidates,roads=roads,labels=labels};
    }
    function Select(sites) {
        local best=[],best_value=0,components={};
        foreach(site in sites) components[site.component] <- true;
        foreach(component,_ in components) {
            local selected=[],covered={},value=0;
            for(local count=0;count<5;count++) {
                local choice=null,gain_best=0;
                foreach(site in sites) {
                    if(site.component!=component) continue;
                    local close=false;
                    foreach(s in selected) if(AIMap.DistanceManhattan(s.tile,site.tile)<5) {close=true;break;}
                    if(close) continue;
                    local gain=0;
                    foreach(house,production in site.cover) if(!(house in covered)) gain+=production;
                    if(gain>gain_best) {gain_best=gain;choice=site;}
                }
                if(choice==null) break;
                selected.append(choice);value+=gain_best;
                foreach(house,p in choice.cover) covered[house] <- p;
            }
            if(selected.len()>=4 && value>best_value) {best=selected;best_value=value;}
        }
        // Short nearest-neighbour circuit avoids a zigzag between catchments.
        local ordered=[];
        if(best.len()>0) ordered.append(best.remove(0));
        while(best.len()>0) {
            local nearest=0;
            for(local i=1;i<best.len();i++) if(AIMap.DistanceManhattan(ordered.top().tile,best[i].tile)<
                AIMap.DistanceManhattan(ordered.top().tile,best[nearest].tile)) nearest=i;
            ordered.append(best.remove(nearest));
        }
        return ordered;
    }
    function BuildDepot(plan,component) {
        foreach(front,label in plan.labels) {
            if(label!=component || AITile.IsStationTile(front)) continue;
            foreach(tile in this.Neighbours(front)) {
                if(!AITile.IsBuildable(tile)) continue;
                local ok=false;
                {local test=AITestMode();ok=AIRoad.BuildRoadDepot(tile,front) && AIRoad.BuildRoad(front,tile);}
                if(!ok) continue;
                // Persist the intended tile before commands can yield to a save.
                this.pending.depot=tile;
                if(!AIRoad.BuildRoadDepot(tile,front)) {this.pending.depot=null;continue;}
                if(AIRoad.BuildRoad(front,tile) && AIRoad.AreRoadTilesConnected(front,tile) &&
                    AIRoad.AreRoadTilesConnected(tile,front)) return tile;
                if(!AIRoad.RemoveRoadDepot(tile)) return null;
                this.pending.depot=null;
            }
        }
        return null;
    }
    function AddBus(net,engine,reverse=null) {
        if(!AIRoad.IsRoadDepotTile(net.depot) || !this.Funds(AIEngine.GetPrice(engine)+10000)) return false;
        local id=AIVehicle.BuildVehicle(net.depot,engine);
        if(!AIVehicle.IsValidVehicle(id)) return false;
        // Track a stopped purchase before issuing orders, including across saves.
        if(reverse==null) {
            local forward=0,backward=0;
            foreach(bus in net.vehicles) if(bus.reverse) backward++;else forward++;
            reverse=backward<forward;
        }
        net.vehicles.append({id=id,phase="dispatch",reverse=reverse});
        return this.Dispatch(net,net.vehicles.top());
    }
    function Dispatch(net,bus) {
        // A save can land after the start command but before phase assignment.
        // Recover that moving bus without toggling it back to stopped.
        if(AIOrder.GetOrderCount(bus.id)==net.stops.len()+1 &&
            !AIVehicle.IsStoppedInDepot(bus.id) && AIVehicle.GetState(bus.id)!=AIVehicle.VS_STOPPED) {
            bus.phase="running";return true;
        }
        // A save can interrupt order creation; rebuild the incomplete order list.
        while(AIOrder.GetOrderCount(bus.id)>0) if(!AIOrder.RemoveOrder(bus.id,0)) return false;
        for(local i=0;i<net.stops.len();i++) {
            local index=bus.reverse ? net.stops.len()-1-i : i;
            if(!AIOrder.AppendOrder(bus.id,net.stops[index],AIOrder.OF_NONE)) return false;
        }
        if(!AIOrder.AppendOrder(bus.id,net.depot,AIOrder.OF_SERVICE_IF_NEEDED)) return false;
        if(!AIOrder.SkipToOrder(bus.id,net.vehicles.len()%net.stops.len())) return false;
        if(!AIVehicle.StartStopVehicle(bus.id)) return false;
        bus.phase="running";
        return true;
    }
    function TryBuild() {
        if(this.cargo==0xFF || !AIRoad.IsRoadTypeAvailable(AIRoad.ROADTYPE_ROAD)) return false;
        AIRoad.SetCurrentRoadType(AIRoad.ROADTYPE_ROAD);
        if(!this.Cleanup()) return false;
        local engine=this.Engine();if(engine==null) return false;
        local towns=AITownList();towns.Valuate(AITown.GetPopulation);towns.Sort(AIList.SORT_BY_VALUE,false);
        if(towns.Count()==0) return false;
        local populations=[];foreach(t,p in towns) populations.append(p);
        populations.sort();
        local minimum=populations[populations.len()/2];if(minimum<1000) minimum=1000;
        foreach(town,pop in towns) {
            if(pop<minimum) continue;
            local served=false;foreach(net in this.networks) if(net.town==town) served=true;
            if(served || (town in this.cooldown && this.cooldown[town]>AIDate.GetCurrentDate())) continue;
            this.cooldown[town] <- AIDate.GetCurrentDate()+180;
            if(!this.Funds(2*AIEngine.GetPrice(engine)+40000)) return false;
            local plan=this.Candidates(town),sites=this.Select(plan.sites);
            if(sites.len()<4) return true;
            this.pending={stops=[],depot=null};
            foreach(site in sites) {
                this.pending.stops.append(site.tile);
                if(!AIRoad.BuildDriveThroughRoadStation(site.tile,site.front,AIRoad.ROADVEHTYPE_BUS,AIStation.STATION_NEW)) {
                    this.pending.stops.pop();this.Cleanup();return true;
                }
            }
            local depot=this.BuildDepot(plan,sites[0].component);
            if(depot==null) {this.Cleanup();return true;}
            local net={town=town,stops=clone this.pending.stops,depot=depot,vehicles=[],
                review=AIDate.GetCurrentDate()+90,quiet=0,rail_followup=0};
            this.networks.append(net);BusRailTowns[town] <- true;this.pending=null;
            this.AddBus(net,engine);this.AddBus(net,engine);
            AILog.Info("City buses: "+AITown.GetName(town)+", "+net.stops.len()+" spread-out stops, "+net.vehicles.len()+" buses.");
            return true;
        }
        return false;
    }
    function Review() {
        local today=AIDate.GetCurrentDate();
        if(today<this.next_review) return;
        this.next_review=today+7;
        if(!AIRoad.IsRoadTypeAvailable(AIRoad.ROADTYPE_ROAD)) return;
        AIRoad.SetCurrentRoadType(AIRoad.ROADTYPE_ROAD);
        local engine=this.Engine();
        foreach(net in this.networks) {
            local selling=false;
            for(local i=net.vehicles.len()-1;i>=0;i--) {
                local bus=net.vehicles[i];
                if(!AIVehicle.IsValidVehicle(bus.id)) {net.vehicles.remove(i);continue;}
                if(bus.phase=="dispatch") this.Dispatch(net,bus);
                if(bus.phase=="sell") {
                    selling=true;
                    if(AIVehicle.IsStoppedInDepot(bus.id)) {
                        if(AIVehicle.SellVehicle(bus.id)) net.vehicles.remove(i);
                    } else {
                        local order=AIOrder.GetOrderCount(bus.id)-1;
                        if(order>=0 && AIOrder.IsGotoDepotOrder(bus.id,order) &&
                            AIOrder.SetOrderFlags(bus.id,order,AIOrder.OF_STOP_IN_DEPOT)) {
                            AIOrder.SkipToOrder(bus.id,order);
                            if(AIVehicle.GetState(bus.id)==AIVehicle.VS_STOPPED) AIVehicle.StartStopVehicle(bus.id);
                        }
                    }
                }
            }
            if(today<net.review || engine==null || selling) continue;
            net.review=today+90;
            local waiting=0,capacity=0,profit=0,old=null;
            local valid=true;
            foreach(stop in net.stops) {
                if(!AIRoad.IsRoadStationTile(stop)) {valid=false;break;}
                waiting+=AIStation.GetCargoWaiting(AIStation.GetStationID(stop),this.cargo);
            }
            if(!valid) continue;
            foreach(bus in net.vehicles) {
                capacity+=AIVehicle.GetCapacity(bus.id,this.cargo);
                profit+=AIVehicle.GetProfitLastYear(bus.id);
                if(bus.phase=="running" && AIVehicle.GetAgeLeft(bus.id)<180) old=bus;
            }
            if(old!=null) {
                if(this.AddBus(net,engine,old.reverse)) {old.phase="sell";AILog.Info("City buses: replacing an ageing bus.");}
            } else if(net.vehicles.len()<2 || (waiting>capacity && net.vehicles.len()<12)) {
                if(this.AddBus(net,engine)) AILog.Info("City buses: added capacity for waiting passengers.");
                net.quiet=0;
            } else {
                if(waiting<capacity/4 && profit<0) net.quiet++;else net.quiet=0;
                if(net.quiet>=4 && net.vehicles.len()>2) {
                    net.vehicles.top().phase="sell";net.quiet=0;
                    AILog.Info("City buses: retiring a surplus bus after sustained low demand and losses.");
                }
            }
        }
    }
}
