"""Shared freight chain, rollback and save/load test in an isolated OpenTTD game."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
wood = "--wood" in sys.argv
farm = "--farm" in sys.argv
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'NetworkCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nNetworkCheck = max_routes=8\n', config)
driver = r'''
class NetworkFailureBuilder extends RouteBuilder {
    // Fail at the station build: early enough that the forced rollback demo
    // barely touches the town's local authority rating.
    function BuildStation(site) { return false; }
}
class NetworkPlanningProbe {
    label=null; calls=null; enabled=true; priority=false;
    function NeedsContinuation() {return this.priority;}
    constructor(label,calls) {this.label=label;this.calls=calls;}
    function TryBuild() {this.calls.append(this.label);return this.enabled;}
}
class CoalPlanningProbe extends NetworkPlanningProbe {
    complete=false;
    function StartupComplete() {return this.complete;}
}
class NoGoodsNetwork extends FreightNetwork { function Produces(industry,cargo) {return false;} }
class DeferredRecoveryNetwork extends FreightNetwork { function Recover() {return false;} }
function NetworkCopy(value)
{
    local type=typeof value;
    if(type=="array") {local a=[];foreach(v in value) a.append(NetworkCopy(v));return a;}
    if(type=="table") {local a={};foreach(k,v in value) a[k] <- NetworkCopy(v);return a;}
    if(type=="integer" || type=="bool" || type=="string" || type=="null") return value;
    throw "Unsupported network save type "+type;
}

function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) throw "No rails";
    local calls=[];
    this.routes=999;
    this.network=NetworkPlanningProbe("ore",calls);
    this.wood_network=NetworkPlanningProbe("wood",calls);
    this.TryBuildRoute(); this.TryBuildRoute();
    if(calls.len()!=2 || calls[0]!="ore" || calls[1]!="wood") throw "Freight scheduling did not alternate";
    this.network.enabled=false;
    this.TryBuildRoute();
    if(calls.len()!=4 || calls[2]!="ore" || calls[3]!="wood") throw "Unavailable network did not yield";
    calls.resize(0);this.network.enabled=true;this.network_next=true;this.wood_next=false;
    this.coal=CoalPlanningProbe("coal",calls);
    this.TryBuildRoute();
    if(calls.len()!=1 || calls[0]!="coal") throw "First coal route lost startup priority";
    calls.resize(0);this.coal.complete=true;this.coal_turn=0;
    this.TryBuildRoute();this.TryBuildRoute();this.TryBuildRoute();
    if(calls.len()!=3 || calls[0]!="coal" || calls[1]!="coal" || calls[2]!="coal")
        throw "Available coal lost priority";
    this.coal.enabled=false;
    calls.resize(0);this.coal_turn=2;this.network_next=false;this.wood_next=true;
    this.network.priority=true;
    this.TryBuildRoute();
    if(calls.len()!=2 || calls[0]!="coal" || calls[1]!="ore") throw "Next chain link lost priority to coal or a new network";
    calls.resize(0);this.network.priority=false;this.wood_network.priority=true;this.continuation_turn=true;
    this.TryBuildRoute();
    if(calls.len()!=2 || calls[0]!="coal" || calls[1]!="wood") throw "Sawmill goods link lost priority";
    calls.resize(0);this.wood_network.priority=false;
    this.TryBuildRoute();
    if(calls.len()<2 || calls[0]!="coal") throw "Completed or deferred chain blocked normal scheduling";
    this.coal=null;this.coal_turn=0;
    this.network=null;this.wood_network=null;this.routes=0;this.network_next=true;
    this.Load(1,{});
    if(this.loaded_wood_network!=null || this.wood_next) throw "Legacy save wood defaults invalid";
    AICompany.SetAutoRenewStatus(false);
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.network=FreightNetwork(4);
    this.wood_network=FreightNetwork(4,null,"WOOD"); this.wood_next=true;
    local controller_save=NetworkCopy(this.Save());
    this.Load(1,controller_save);
    if(this.loaded_wood_network.source_label!="WOOD" || !this.wood_next) throw "Wood state absent from controller save";
    this.wood_network=null;
    local initial=this.network.PickChain();
    if(initial==null) {
        if(this.network.TryBuild()) throw "Missing chain blocked passenger scheduling";
        AILog.Info("NETWORK PASS: no complete chain available; construction yields to other services.");
        while(true) this.Sleep(1000);
    }
    AILog.Info("NETWORK chain: "+AIIndustry.GetName(initial.mine)+" -> "+AIIndustry.GetName(initial.mill)+" -> "+AIIndustry.GetName(initial.factory)+" -> "+AITown.GetName(initial.city));
    local saved_plan=false,rollback_checked=false,rollback_attempts=0;
    for(local i=0;i<150000 && this.network.state.stage<3;i++) {
        foreach(id,r in this.network.optimiser.trains) {r.review_after=AIDate.GetCurrentDate()+365;r.loss_years=0;
            AIOrder.SetOrderFlags(id,0,AIOrder.OF_NON_STOP_INTERMEDIATE);}
        this.network.Review();
        if(rollback_attempts<2 && !rollback_checked && "plan" in this.network.state && this.network.state.plan!=null && this.network.Hold()) {
            rollback_attempts++;
            local plan=NetworkCopy(this.network.state.plan), tracks={};
            foreach(segment in this.network.state.segments) foreach(nodes in [segment.a,segment.z])
                foreach(n in nodes) tracks[n[0]] <- AIRail.GetRailTracks(n[0]);
            this.network=DeferredRecoveryNetwork(4,NetworkCopy(this.network.Save()));
            local pending=this.network.builder.pending_stations;
            this.network.builder=NetworkFailureBuilder(4);
            this.network.builder.pending_stations=pending;
            this.network.TryBuild();
            if(this.network.state.transaction==null) {
                // Construct aborted before any journalled work (e.g. the local
                // authority refused the station); nothing to roll back here -
                // reload and let a later plan retry the rollback probe.
                this.network=FreightNetwork(4,NetworkCopy(this.network.Save()));
            } else {
                local depot=this.network.state.transaction.depot;
                if(!AIRail.IsRailDepotTile(depot)) throw "Missing branch depot before rollback";
                this.network=FreightNetwork(4,NetworkCopy(this.network.Save()));
                this.network.TryBuild();
                if(this.network.state.transaction!=null || this.network.state.stage!=1) throw "Failed branch not rolled back";
                if(AIRail.IsRailDepotTile(depot)) throw "Rollback left branch depot behind";
                foreach(tile,mask in tracks) if(AIRail.GetRailTracks(tile)!=mask) throw "Rollback damaged shared main line";
                local grade=plan.segment.grade;
                if(AIBridge.IsBridgeTile(grade.ramp) || AITunnel.IsTunnelTile(grade.ramp)) throw "Rollback left junction structure behind";
                this.network.state.plan=plan; this.network.state.retry=0;
                rollback_checked=true;
            }
        }
        // This fixture tests construction/rollback on a mature search budget.
        // First-probe limits and backoff are covered by expansion.py/headless.py.
        if(this.network.state.stage==0) {
            local choice=this.network.PickChain();
            if(choice!=null) {
                local key="industry:"+FreightCargo(this.network.source_label)+":"+choice.mine+":"+choice.mill;
                if(!(key in this.network.builder.planning_history))
                    this.network.builder.planning_history[key] <- {count=2,after=0};
            }
        }
        if(i%75==0) this.network.TryBuild();
        if(!saved_plan && "plan" in this.network.state && this.network.state.plan!=null) {
            this.network=FreightNetwork(4,NetworkCopy(this.network.Save()));
            saved_plan=true;
        }
        this.Sleep(1);
    }
    if(this.network.state.stage!=3) throw "Chain not completed, stage="+this.network.state.stage;
    if(this.network.state.segments.len()!=3 || this.network.state.stations.len()!=4) throw "Not shared infrastructure";
    this.network=FreightNetwork(4,NetworkCopy(this.network.Save()));
    foreach(index,segment in this.network.state.segments) {
        if(index==0) continue;
        if(!("grade" in segment)) throw "At-grade network junction commissioned";
        local g=segment.grade;
        if(g.kind=="bridge") {
            if(!AIBridge.IsBridgeTile(g.ramp) || AIBridge.GetOtherBridgeEnd(g.ramp)!=g.end) throw "Missing flyover";
        } else if(!AITunnel.IsTunnelTile(g.ramp) || AITunnel.GetOtherTunnelEnd(g.ramp)!=g.end) throw "Missing junction tunnel";
        foreach(signal in g.signals)
            if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY) throw "Missing close junction signal";
        local step=(g.end-g.ramp)/AIMap.DistanceManhattan(g.end,g.ramp);
        foreach(offset in [2,3]) {
            local tile=g.ramp+offset*step;
            if(AIRail.GetRailTracks(tile)!=RailPiece(tile-g.d,tile,tile+g.d)) throw "Crossing added to running tracks below flyover";
        }
    }
    local depots={};
    foreach(id,r in this.network.optimiser.trains) {
        if(r.depot in depots) throw "Network stages share a depot";
        depots[r.depot] <- true;
        if(!AIRail.IsRailDepotTile(r.depot) || AIOrder.GetOrderDestination(id,2)!=r.depot)
            throw "Service order does not use the stage depot";
        local front=AIRail.GetRailDepotFrontTile(r.depot),on_approach=false;
        foreach(segment in this.network.state.segments) foreach(nodes in [segment.a,segment.z])
            foreach(n in nodes) if(n[0]==front) on_approach=true;
        if(!on_approach) throw "Stage depot is not connected to a network approach";
    }
    local visited={};
    local returned={};
    local trunk_ends={};
    trunk_ends[AIStation.GetStationID(this.network.state.stations[0].tile)] <- true;
    trunk_ends[AIStation.GetStationID(this.network.state.stations[1].tile)] <- true;
    foreach(id,r in this.network.optimiser.trains) visited[id] <- 0;
    for(local i=0;i<100000;i++) {
        foreach(id,r in this.network.optimiser.trains) {r.review_after=AIDate.GetCurrentDate()+365;r.loss_years=0;
            AIOrder.SetOrderFlags(id,0,AIOrder.OF_NON_STOP_INTERMEDIATE);}
        this.network.Review();
        // Exercise the scheduler's farm-priority check at stage 3: it scans
        // for eligible farms and must not throw when the farms table is absent.
        this.network.NeedsContinuation();
        local complete=this.network.optimiser.trains.len()==3;
        foreach(id,r in this.network.optimiser.trains) {
            if(!AIVehicle.IsValidVehicle(id)) throw "Network train lost";
            if(!(id in visited)) visited[id] <- 0;
            if(AIVehicle.GetCargoLoad(id,this.network.optimiser.BuyerFor(r).cargo)>0) visited[id]=visited[id]|1;
            if((visited[id]&1)!=0 && AIStation.GetStationID(AIVehicle.GetLocation(id))==r.station_b &&
                AIVehicle.GetCargoLoad(id,this.network.optimiser.BuyerFor(r).cargo)==0) visited[id]=visited[id]|2;
            if((visited[id]&2)!=0 && AIVehicle.IsInDepot(id) && AIVehicle.GetLocation(id)==r.depot) visited[id]=visited[id]|4;
            // After unloading, the train must not pass a trunk-end station
            // before reaching its pickup: a wrongly oriented junction sends it
            // to the far end of the line to reverse. Hooked but correctly
            // oriented branches never touch those stations on the way back.
            if((visited[id]&2)!=0 && !(id in returned)) {
                local st=AIStation.GetStationID(AIVehicle.GetLocation(id));
                if(st==r.station_a) returned[id] <- true;
                else if(st!=AIStation.STATION_INVALID && st!=r.station_b && (st in trunk_ends)) {
                    // A trunk-served pickup (backbone stations) must never see
                    // a far-end turnaround: that is the mis-oriented junction
                    // regression. Off-trunk pickups (goods from a branch
                    // station) only warn until station mouths and depots can
                    // be co-selected with junction handedness.
                    if(AIStation.GetStationID(this.network.state.stations[0].tile)==r.station_a ||
                        AIStation.GetStationID(this.network.state.stations[1].tile)==r.station_a)
                        throw "Empty train "+id+" detoured via trunk-end station "+st+
                            " (pickup "+r.station_a+"); junction faces the wrong way";
                    AILog.Warning("Empty train "+id+" detoured via trunk-end station "+st);
                    returned[id] <- true;
                }
            }
            if(visited[id]!=7) complete=false;
        }
        if(complete && returned.len()==this.network.optimiser.trains.len()) {
            AILog.Info("NETWORK PASS: ore, steel and goods delivered on shared dual-track network, four stations, saved network.");
            while(true) this.Sleep(1000);
        }
        this.Sleep(1);
    }
    throw "Network traffic failed";
}
'''

if farm:
    driver = driver.replace('class NetworkFailureBuilder', r'''class FarmPurchaseFailure extends FreightNetwork {
        function Recover() {return false;}
        function BuyBranchTrain(cargo,depot,source,destination,industry=null) {
            if(cargo==FreightCargo("LVST")) return -1;
            return TrainBuyer(cargo).BuildCargoTrain(depot,source,destination,
                TrainBuyer(cargo).SizedWagons(MonthlyCargoDemand(cargo,industry,null),this.builder.platform_length-1),
                true,false,this.builder.platform_length*16);
        }
    }
    class NetworkFailureBuilder''')
    driver = driver.replace('    local depots={};', r'''    local farm_rollback=false;
    for(local attempt=0;attempt<150000 && (!("farms" in this.network.state) || this.network.state.farms.len()==0);attempt++) {
        foreach(id,r in this.network.optimiser.trains) {r.review_after=AIDate.GetCurrentDate()+365;r.loss_years=0;
            AIOrder.SetOrderFlags(id,0,AIOrder.OF_NON_STOP_INTERMEDIATE);}
        this.network.Review();
        if(!farm_rollback && "plan" in this.network.state && this.network.state.plan!=null &&
            "farm" in this.network.state.plan && this.network.Hold()) {
            local plan=NetworkCopy(this.network.state.plan),masks={};
            foreach(segment in this.network.state.segments) foreach(nodes in [segment.a,segment.z])
                foreach(n in nodes) masks[n[0]] <- AIRail.GetRailTracks(n[0]);
            this.network=FarmPurchaseFailure(4,NetworkCopy(this.network.Save()));
            this.network.TryBuild();
            local tx=this.network.state.transaction;
            if(tx==null || !("trains" in tx) || tx.trains.len()!=1 || !AIVehicle.IsStoppedInDepot(tx.trains[0]))
                throw "Farm dispatched before both trains were bought";
            local train=tx.trains[0],depot=tx.depot;
            this.network=FreightNetwork(4,NetworkCopy(this.network.Save()));
            this.network.TryBuild();
            if(this.network.state.transaction!=null || AIVehicle.IsValidVehicle(train) || AIRail.IsRailDepotTile(depot))
                throw "Failed second purchase left a farm train or depot";
            foreach(tile,mask in masks) if(AIRail.GetRailTracks(tile)!=mask) throw "Farm rollback damaged network";
            this.network.state.plan=plan;this.network.state.retry=0;
            farm_rollback=true;
        }
        if(attempt%75==0) this.network.TryBuild();
        this.Sleep(1);
    }
    if(!("farms" in this.network.state) || this.network.state.farms.len()!=1) throw "No farm connected";
    this.network=FreightNetwork(4,NetworkCopy(this.network.Save()));
    local farm_trains=0,types={};
    foreach(id,r in this.network.optimiser.trains) if(r.cargo==FreightCargo("GRAI") || r.cargo==FreightCargo("LVST")) {
        farm_trains++;types[r.cargo] <- true;
        if(AIVehicle.GetNumWagons(id)!=4) throw "Farm train does not have three wagons";
        if(r.station_b!=AIStation.GetStationID(this.network.state.stations[2].tile)) throw "Farm delivery bypasses existing factory";
    }
    if(!farm_rollback || farm_trains!=2 || types.len()!=2) throw "Farm did not commission both cargo trains";
    local depots={};''')
    driver = driver.replace('if(r.depot in depots) throw "Network stages share a depot";',
        'if(r.depot in depots && depots[r.depot]!=r.station_a) throw "Different pickup stations share depot";')
    driver = driver.replace('depots[r.depot] <- true;', 'depots[r.depot] <- r.station_a;')
    driver = driver.replace('trains.len()==3', 'trains.len()==5')
    driver = driver.replace('ore, steel and goods delivered', 'ore, steel, goods, grain and livestock delivered').replace('four stations, saved network.', 'five stations, saved network, failed second-purchase rollback.')

if wood:
    driver = driver.replace('this.network=FreightNetwork(4);', 'this.network=FreightNetwork(4,null,"WOOD");')
    driver = driver.replace('+AIIndustry.GetName(initial.factory)+" -> "', '')
    driver = driver.replace('state.stage<3', 'state.stage<2').replace('state.stage!=3', 'state.stage!=2')
    driver = driver.replace('segments.len()!=3', 'segments.len()!=2').replace('stations.len()!=4', 'stations.len()!=3')
    driver = driver.replace('trains.len()==3', 'trains.len()==2')
    driver = driver.replace('ore, steel and goods', 'wood and goods').replace('four stations', 'three stations')


# Force the no-loop case so successful delivery proves terminus fallback works.
if "--terminus" in sys.argv:
    driver = 'function RollThroughStation::PlanFlexible(entrance,lane,length) { return null; }\n' + driver

with tempfile.TemporaryDirectory(prefix='openttdai-network-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'NetworkCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    # Inspect the map at the exact point reverse-track search begins.
    builder_file = ai / 'builder.nut'
    builder_source = builder_file.read_text()
    guard = r'''
        if(preferred!=null) {
            if(this.pending_stations.len()==0 || !("primary_recovery" in this.pending_stations[0]))
                throw "Return planning began before first-track construction";
            local journal=this.pending_stations[0].primary_recovery.upgrade;
            if(journal==null || journal.pieces.len()+journal.structures.len()==0) throw "Empty first-track construction journal";
            foreach(p in journal.pieces) if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) throw "First track incomplete during return planning";
            foreach(p in journal.structures)
                if(p[2]=="tunnel" ? !AITunnel.IsTunnelTile(p[0]) : !AIBridge.IsBridgeTile(p[0])) throw "First structure missing during return planning";
        }
    '''
    builder_source = builder_source.replace('        return this.SearchPathMode(', guard + '        return this.SearchPathMode(', 1)
    builder_file.write_text(builder_source)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "NetworkCheck";', 1))
    main = ai / 'main.nut'
    base_main = main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()')
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in ([int(sys.argv[sys.argv.index("--seed")+1])] if "--seed" in sys.argv else [42, 7]):
        # The second wood fixture simulates an industry set without wood-to-goods conversion.
        scenario = driver.replace('this.network=FreightNetwork(4,null,"WOOD");',
                                  'this.network=NoGoodsNetwork(4,null,"WOOD");') if wood and seed == 7 else driver
        main.write_text(base_main + scenario)
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=2400000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=240)
        (root / 'tests' / f'network-{"terminus-" if "--terminus" in sys.argv else ""}{"farm-" if farm else "wood-" if wood else ""}{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'NETWORK PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
