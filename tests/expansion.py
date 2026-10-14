"""Expansion scheduling and backwards-compatible multi-network regression tests."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ExpansionCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nExpansionCheck = \n', config)
driver = r'''
// Isolate scheduling from town searches; no passenger work in this fixture.
function OpenTTDAI::PickTownPair() {return null;}
class EmptyJunctionNetwork extends FreightNetwork {
    fallback_called=false;
    function PickupDepotSite(segment=null,planned=false,protected_tiles=null) {return {};}
    function TrySeparateGoods(source) {this.fallback_called=true;return false;}
}
class DepotRetryNetwork extends FreightNetwork {
    requests=0;allow=false;
    function RequestDepot(id) {this.requests++;return this.allow?AIVehicle.SendVehicleToDepot(id):false;}
}
class WaitingNetwork extends FreightNetwork {function Hold() {return false;}}
class RecoveryNetwork extends FreightNetwork {function Recover() {return false;}}
class ConstructionProbe {
    state=null;calls=0;build=false;excluded_sources=null;priority=false;
    constructor(stage,build=false) {this.build=build;this.state={stage=stage,chain=stage==0?null:{mine=123},failed={}};}
    function NeedsContinuation() {return this.priority;}
    function TryBuild() {this.calls++;return this.build;}
}
class ExpansionProbe extends FreightNetworks {
    function NewNetwork() {return ConstructionProbe(0,true);}
}
class PriorityCoal {
    calls=null;build=false;
    constructor(calls) {this.calls=calls;}
    function TryBuild() {calls.append("coal");return build;}
    function StartupComplete() {return true;}
}
class PriorityFarms {
    calls=null;build=true;factory_ready=false;hub_ready=false;
    function TryBuildFarmHub() {if(!hub_ready) return false;calls.append("farm hub");return true;}
    function TryFactoryGoods() {if(!factory_ready) return false;calls.append("factory goods");return true;}
    constructor(calls) {this.calls=calls;}
    function TryBuildFarm() {calls.append("farm");return build;}
    function NeedsContinuation() {return true;}
    function TryBuild() {calls.append("goods");return true;}
}
class FarmHubProbe extends FreightNetwork {
    visited=0;ready=false;potential=true;
    function TryBuildFarm() {this.visited++;return this.ready;}
    function FarmExpansionPending(include_deferred=false) {return this.potential && include_deferred;}
}
function OpenTTDAI::Start()
{
    this.Sleep(1);if(!PickRailType()) throw "No rails";
    local industries=FreightNetwork(4),coal_probe=CoalRoutes(RouteBuilder(4));
    if(industries.Produces(-1,FreightCargo("GOOD")) || coal_probe.InterestedIn(-1) || coal_probe.IsDestination(-1))
        throw "Removed industry remained eligible";
    foreach(pair in [[51,0],[0,51],[51,50],[50,51]])
        if(!industries.FarmProductionEligible(pair[0],pair[1])) throw "Qualifying single farm cargo rejected";
    foreach(pair in [[0,0],[50,50],[49,50],[30,30]])
        if(industries.FarmProductionEligible(pair[0],pair[1])) throw "Farm below either-cargo threshold accepted";
    local power=-1,producer=-1,produced=-1;
    foreach(id,_ in AIIndustryList()) {
        local outputs=IndustryOutputs(id);
        if(outputs==null) continue;
        if(coal_probe.IsDestination(id)) power=id;
        foreach(c,_ in outputs) {producer=id;produced=c;break;}
    }
    if(power<0 || producer<0) throw "Missing industry fixture";
    if(!industries.Produces(producer,produced)) throw "Valid production rejected";
    // Simulate closure between validity checking and the cargo-list query.
    local original_outputs=IndustryOutputs;
    ::IndustryOutputs=function(id) {return null;};
    if(industries.Produces(producer,produced) || coal_probe.InterestedIn(producer) || coal_probe.IsDestination(power))
        throw "Missing output list treated as valid industry";
    ::IndustryOutputs=original_outputs;
    if(!coal_probe.IsDestination(power)) throw "Valid empty-output destination rejected";
    // Simulate rival stations covering every industry; sources must be skipped,
    // while an industry remains a valid delivery destination.
    local original_rival=RivalIndustryStation;
    ::RivalIndustryStation=function(id) {return true;};
    if(coal_probe.PickPair()!=null || industries.PickFarmChain()!=null ||
        industries.PickFreshChain()!=null || industries.PickWoodChain()!=null)
        throw "Rival-served source selected";
    if(!coal_probe.IsDestination(power)) throw "Rival destination incorrectly excluded";
    if(coal_probe.Connect(producer,power) || industries.TrySeparateGoods(producer))
        throw "Rival source passed construction guard";
    ::RivalIndustryStation=original_rival;

    local city=-1;foreach(t,_ in AITownList()) {city=t;break;}
    foreach(used in [false,true]) {
        local empty=EmptyJunctionNetwork(4,null,"FARM");
        empty.state.stage=1;
        empty.state.chain={mine=producer,mill=producer,factory=producer,city=city};
        empty.state.stations=[{tile=AIIndustry.GetLocation(producer)},{tile=AIIndustry.GetLocation(producer)}];
        // Reproduce both an empty list and a list exhausted by earlier builds.
        if(used) empty.state.junctions=[{used=true}];
        empty.state.branch_cursor <- {};
        empty.state.branch_cursor[city+":"+FreightCargo("GOOD")] <- 99;
        if(!empty.TryBuild() || !empty.fallback_called)
            throw "Factory goods did not directly attempt separate route";
        if(empty.builder.planning_deadline!=0 || empty.builder.reusable_rails!=null)
            throw "Failed branch left active planning state";
        empty.state.retry=0;empty.TryBuild();
        if(!empty.fallback_called) throw "Separate goods fallback not attempted";
    }
    local retry_probe=FreightNetwork(4);
    retry_probe.state.branch_tried <- {permanent=true,timeout=AIDate.GetCurrentDate()+30};
    if(!retry_probe.BranchAttemptBlocked("permanent") || !retry_probe.BranchAttemptBlocked("timeout") ||
        retry_probe.BranchAttemptBlocked("new")) throw "Branch attempt cooldown broken";
    retry_probe.state.branch_tried.timeout=AIDate.GetCurrentDate();
    if(retry_probe.BranchAttemptBlocked("timeout")) throw "Timed-out branch permanently rejected";
    local hub_manager=FreightNetworks(4),hub=FarmHubProbe(4,null,"FARM"),newer=FarmHubProbe(4,null,"FARM");
    hub.state.stage=2;hub.state.farms <- { [123]=true };hub.ready=true;
    hub.state.stations=[{tile=10},{tile=20},{tile=30}];
    hub.state.goods_outlet <- {source=40,destination=30,depot=50};
    newer.state.stage=1;newer.ready=true;
    hub_manager.networks=[newer,hub];
    hub.QueueFarmExpansion();
    if(!FreightNetwork(4,hub.Save()).state.post_goods_farms) throw "Farm handover lost on save/load";
    if(!hub_manager.TryPostGoodsFarms() || hub.state.post_goods_farms || hub.visited!=1 || newer.visited!=0)
        throw "New goods route did not hand construction back to its own factory";
    hub.visited=0;
    if(!hub_manager.TryBuildFarm() || hub.visited!=1 || newer.visited!=0)
        throw "Completed factory did not get first expansion opportunity";
    if(hub.BranchNetworkStation(true)!=20) throw "Farm branch redirected to goods station";
    hub.ready=false;newer.ready=false;
    if(hub_manager.TryBuildFarm() || hub_manager.networks.len()!=2)
        throw "Deferred factory expansion opened a new backbone";
    if(!(123 in newer.excluded_sources)) throw "Already served farms not excluded";
    local calls=[];
    this.coal=PriorityCoal(calls);this.network=PriorityFarms(calls);
    this.coal.build=true;this.network.factory_ready=true;
    this.TryBuildRoute();
    if(calls.len()!=1 || calls[0]!="coal") throw "Coal did not take first priority";
    calls.resize(0);this.coal.build=false;
    this.TryBuildRoute();
    if(calls.len()!=1 || calls[0]!="factory goods") throw "Factory outlet priority broken";
    calls.resize(0);this.network.factory_ready=false;
    this.TryBuildRoute();
    if(calls.len()!=1 || calls[0]!="farm") throw "Farms did not follow coal";
    calls.resize(0);this.network.build=false;this.TryBuildRoute();
    if(calls.len()!=1 || calls[0]!="goods") throw "Ore network did not follow farms";
    this.coal=null;this.network=null;this.continuation_turn=true;
    local policy=RouteBuilder(4),key=policy.ConnectionKey(2,3);
    policy.BeginPlanning(key);
    if(policy.search_batches_limit!=8 || policy.planning_deadline-AIController.GetTick()>1200) throw "First search not bounded";
    policy.FinishConnection(key,false);
    if(!policy.ConnectionFailed(3,2) || policy.planning_history[key].after-AIDate.GetCurrentDate()!=30) throw "First cooldown missing";
    policy.planning_history[key].after=AIDate.GetCurrentDate();
    if(policy.ConnectionFailed(2,3)) throw "Cooldown never expires";
    policy.BeginPlanning(key);
    if(policy.search_batches_limit!=16) throw "Retry did not get larger search";
    policy.FinishConnection(key,false);
    if(policy.planning_history[key].after-AIDate.GetCurrentDate()!=60) throw "Repeat cooldown not longer";
    local savedNetwork=FreightNetwork(4);savedNetwork.builder.planning_history=policy.planning_history;
    local loadedNetwork=FreightNetwork(4,savedNetwork.Save());
    if(!loadedNetwork.builder.DeferredConnection(key)) throw "Network cooldown lost in save";
    policy.FinishConnection(key,true);
    if(policy.DeferredConnection(key)) throw "Success retained cooldown";
    policy.BeginPlanning(key);
    local a={tile=10000,dir=1,exit=[10001,10000]},b={tile=11000,dir=1,exit=[10999,11000]};
    if(!policy.TryStationPair(a,b)) throw "First pair rejected";
    local near=clone b;near.tile++;near.exit=[11000,11001];
    if(policy.TryStationPair(a,near)) throw "Near-identical pair retried";
    local turned=clone b;turned.exit=[11001,11000];
    if(!policy.TryStationPair(a,turned)) throw "Opposite-facing approach wrongly deduplicated";
        EnsureMoney(AICompany.GetMaxLoanAmount());
    local depot=-1;
    for(local y=10;y<100 && depot<0;y++) for(local x=10;x<100 && depot<0;x++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,9,1) || AITile.GetSlope(tile)!=AITile.SLOPE_FLAT) continue;
        local flat=true;for(local k=1;k<9;k++) if(AITile.GetSlope(tile+k)!=AITile.SLOPE_FLAT) flat=false;
        if(flat && AIRail.BuildRailDepot(tile,tile+1)) depot=tile;
    }
    if(depot<0) throw "No depot fixture";
    for(local k=1;k<8;k++) if(!AIRail.BuildRail(depot+k-1,depot+k,depot+k+1)) throw "Depot fixture disconnected";
    local train=AIVehicle.BuildVehicle(depot,TrainBuyer(PassengerCargo()).BestEngine());
    if(!AIVehicle.IsValidVehicle(train) || !AIVehicle.StartStopVehicle(train)) throw "No test locomotive";
    for(local k=0;k<100 && AIVehicle.IsInDepot(train);k++) this.Sleep(1);
    if(AIVehicle.IsInDepot(train)) throw "Locomotive stayed in fixture depot";
    local retry=DepotRetryNetwork(4);retry.optimiser.trains[train] <- {};
    retry.state.plan <- {};
    if(retry.Hold() || retry.Hold() || retry.requests!=2 || retry.state.held.len()!=0) throw "Failed depot request was not retried";
    retry.allow=true;
    retry.Hold();
    if(retry.requests!=3 || retry.state.held.len()!=1) throw "Successful depot request not tracked";
    retry.Hold();
    if(retry.requests!=3) throw "Repeated hold toggled depot order";
    retry.state.hold_since=AIDate.GetCurrentDate()-181;
    if(retry.TryBuild() || retry.state.plan!=null || retry.state.held.len()!=0) throw "Timed-out train not released";
    if(!AIOrder.IsCurrentOrderPartOfOrderList(train) && AIOrder.IsGotoDepotOrder(train,AIOrder.ORDER_CURRENT))
        throw "Cancelled project left temporary depot order";
    local budget=RouteBuilder(4);
    if(budget.BudgetForAge(20*365)!=8000 || budget.BudgetForAge(365)!=4800) throw "Mature planning is unbounded";
    local towns=AITownList();local town=towns.Begin();
    local expired=FreightNetwork(4);
    expired.builder.planning_deadline=AIController.GetTick();
    if(expired.CitySites(town,AITown.GetLocation(town)).len()!=0 || !expired.builder.planning_timed_out)
        throw "Station search ignored project deadline";
    expired.state.plan <- {};expired.state.hold_since=AIDate.GetCurrentDate()-181;
    if(expired.TryBuild() || expired.state.plan!=null || expired.state.retry<=AIDate.GetCurrentDate())
        throw "Depot timeout did not yield and defer";
    expired.state.failed["temporary"] <- AIDate.GetCurrentDate()+180;
    expired.state.failed["permanent"] <- true;
    if(!expired.FailedChoice("temporary") || !expired.FailedChoice("permanent")) throw "Failure cooldown ignored";
    expired.state.failed["temporary"]=AIDate.GetCurrentDate()-1;
    if(!expired.FailedChoice("temporary")) throw "Expired retry overtook fresh route choices";
    expired.retry_deferred=true;
    if(expired.FailedChoice("temporary")) throw "Planning timeout became permanent";
    local saved=expired.Save(),loaded=FreightNetwork(4,saved);
    if(loaded.state.hold_since!=-1 || loaded.state.retry!=expired.state.retry) throw "Wait recovery lost on save";
    local waiting=WaitingNetwork(4);waiting.state.plan <- {};
    this.network=waiting;this.wood_network=ConstructionProbe(0,true);this.network_next=true;
    this.coal=null;this.routes=999;
    this.TryBuildRoute();
    if(this.wood_network.calls!=1) throw "Waiting network starved other construction";
    this.network=RecoveryNetwork(4);this.network.state.transaction={};this.network_next=true;
    this.TryBuildRoute();
    if(this.wood_network.calls!=2) throw "Blocked recovery starved other construction";
    this.network=ConstructionProbe(1,true);this.network.priority=true;
    this.wood_network=ConstructionProbe(0,true);this.network_next=true;this.wood_next=true;this.continuation_turn=true;
    this.construction_cursor=0;
    this.TryBuildRoute();
    if(this.network.calls!=1 || this.wood_network.calls!=0) throw "Ore slot was skipped";
    this.TryBuildRoute();
    if(this.network.calls!=1 || this.wood_network.calls!=1) throw "Wood did not receive its regular slot";
    local fleet=ExpansionProbe(4);
    fleet.networks=[ConstructionProbe(3,false)];fleet.cursor=0;
    if(!fleet.TryBuild() || fleet.networks.len()!=2 || !(123 in fleet.networks[1].excluded_sources))
        throw "Completed chain blocked a new source";
    local first=ConstructionProbe(1,false),second=ConstructionProbe(1,true);
    first.state.failed["known"] <- true;
    second.state.failed["known"] <- AIDate.GetCurrentDate()+20;
    fleet.networks=[first,second];fleet.cursor=0;
    if(!fleet.TryBuild() || first.calls!=1 || second.calls!=1) throw "Network queue does not yield";
    if(typeof second.state.failed["known"]!="bool") throw "Old snapshot overwrote proven route failure";
    local legacy=FreightNetwork(4);legacy.state.chain={mine=123};legacy.state.stage=3;
    local restored=FreightNetworks(4,legacy.Save());
    if(restored.networks.len()!=1 || restored.networks[0].state.chain.mine!=123) throw "Legacy network lost";
    restored.networks.append(FreightNetwork(4));
    local roundtrip=FreightNetworks(4,restored.Save());
    if(roundtrip.networks.len()!=2 || roundtrip.networks[0].state.stage!=3) throw "Multiple network save lost";
    local coal=CoalRoutes(RouteBuilder(4));coal.retry_after=AIDate.GetCurrentDate()+30;
    if(coal.TryBuild()) throw "Coal wait monopolises construction";
    AILog.Info("PRODUCTION PASS: bounded planning, timed-out depot waits, scheduling fairness, repeat networks and save migration.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-expansion-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ExpansionCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ExpansionCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()').replace('function OpenTTDAI::PickTownPair()', 'function OpenTTDAI::UnusedPickTownPair()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'expansion-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PRODUCTION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
