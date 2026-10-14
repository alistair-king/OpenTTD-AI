"""Expansion scheduling and backwards-compatible multi-network regression tests."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'FarmStartCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nFarmStartCheck = \n', config)
driver = r'''
class FarmGoodsProbe extends FreightNetwork {
    called=false;
    function TrySeparateGoods(source) {
        if(source!=this.state.chain.factory)
            throw "Farm continuation did not target factory goods";
        this.called=true;return false;
    }
}
class FailedFarmPurchase extends FreightNetwork {
    purchases=0;
    function BuyBranchTrain(cargo,depot,source,destination,industry=null) {
        this.purchases++;
        if(this.purchases==2) return -1;
        return TrainBuyer(cargo).BuildCargoTrain(depot,source,destination,2,true,false,64);
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local manager=FreightNetworks(4);
    for(local i=0;i<12000;i++) {
        manager.TryBuildFarm();
        local built=null;
        foreach(n in manager.networks) if(n.source_label=="FARM" && n.state.stage>0) built=n;
        if(built!=null) break;
        this.Sleep(20);
    }
    local network=null;
    foreach(n in manager.networks) if(n.source_label=="FARM" && n.state.stage>0) network=n;
    if(network==null) throw "Independent farm did not build";
    if(!network.NeedsFactoryGoods()) throw "Connected factory outlet not prioritised";
    network.state.retry=AIDate.GetCurrentDate()+90;
    if(network.NeedsFactoryGoods()) throw "Deferred goods outlet blocked other work";
    network.state.retry=0;
    if(network.state.stations.len()!=2 || network.optimiser.trains.len()!=2) throw "Farm pair incomplete";
    foreach(id,r in network.optimiser.trains) if(!AIVehicle.IsStoppedInDepot(id)) throw "Train dispatched before pair ready";
    local before=AIVehicleList().Count();
    local failing=FailedFarmPurchase(4,null,"FARM");
    local trunk=FarmBackbone(failing.builder,null,"GRAI");trunk.network=failing;
    if(trunk.BuyInitialTrain(network.state.depot,network.state.stations[0].tile,
        network.state.stations[1].tile,network.state.chain.mine)>=0) throw "Second purchase failure ignored";
    if(AIVehicleList().Count()!=before) throw "Failed pair left a train behind";
    manager=FreightNetworks(4,manager.Save());
    foreach(n in manager.networks) if(n.source_label=="FARM" && n.state.stage>0) network=n;
    if(network.FactoryIndex()!=1 || network.LastStage()!=2) throw "Farm save lost stage semantics";
    if(network.BranchNetworkStation(true)!=network.state.stations[1].tile ||
        network.BranchNetworkStation(false)!=network.state.stations[1].tile)
        throw "Farm junction endpoint is not the factory station";
    local legacy=FreightNetwork(4);
    legacy.state.stage=2;legacy.state.stations=[{tile=10},{tile=20},{tile=30}];
    if(legacy.BranchNetworkStation(true)!=30 || legacy.BranchNetworkStation(false)!=30)
        throw "Ore factory junction endpoint changed";
    local outlet=FarmGoodsProbe(4,network.Save());
    outlet.TryBuild();if(!outlet.called) throw "Farm network did not schedule goods outlet";
    if(outlet.state.retry<=AIDate.GetCurrentDate()) throw "Failed goods attempt did not yield";
    local loaded={},delivered={};
    for(local i=0;i<100000;i++) {
        foreach(id,r in network.optimiser.trains) r.review_after=AIDate.GetCurrentDate()+365;
        network.Review();
        foreach(id,r in network.optimiser.trains) {
            if(AIVehicle.GetCargoLoad(id,r.cargo)>0) loaded[id] <- true;
            if(id in loaded && AIStation.GetStationID(AIVehicle.GetLocation(id))==r.station_b &&
                AIVehicle.GetCargoLoad(id,r.cargo)==0) delivered[r.cargo] <- true;
        }
        if(delivered.len()==2) {AILog.Info("PRODUCTION PASS: independent farm backbone, both cargoes delivered, save/load.");while(true) this.Sleep(1000);}
        this.Sleep(1);
    }
    throw "Farm pair did not deliver";
}
'''
if "--no-junctions" in sys.argv:
    driver = driver.replace('function OpenTTDAI::Start()', r'''class NoJunctionFarm extends FreightNetwork {
    function JunctionCandidates(segment) { return []; }
}
function OpenTTDAI::Start()''')
    driver = driver.replace('local manager=FreightNetworks(4);',
        'local manager=FreightNetworks(4); manager.networks=[NoJunctionFarm(4,null,"FARM")];')
    driver = driver.replace('if(!network.NeedsFactoryGoods())',
        'if(network.state.junctions.len()!=0) throw "No-junction fixture changed";\n    if(!network.NeedsFactoryGoods())')
if "--goods" in sys.argv:
    # This fixture builds both a farm backbone and a complete dual-track outlet.
    config = re.sub(r'^max_loan = .*$', 'max_loan = 20000000', config, flags=re.M)
    driver = driver.replace('if(delivered.len()==2) {AILog.Info', 'if(delivered.len()==2) {break;}\n        if(false) {AILog.Info')
    driver = driver.replace('    throw "Farm pair did not deliver";', r'''    if(delivered.len()!=2) throw "Farm pair did not deliver";
    local supply_station=network.state.stations[1].tile,supply_depot=network.state.depot;
    for(local attempt=0;attempt<200 && network.state.stage<2;attempt++) {
        network.TrySeparateGoods(network.state.chain.factory);
        this.Sleep(74*8);
    }
    if(network.state.stage!=2 || !("goods_outlet" in network.state)) throw "Separate goods route not built";
    if(network.state.goods_outlet.source==supply_station || network.state.goods_outlet.depot==supply_depot)
        throw "Goods outlet did not use separate infrastructure";
    foreach(id,record in network.optimiser.trains) if(record.cargo==FreightCargo("GOOD")) {
        if(record.single_route!=null) throw "Goods deferred its return track";
    }
    network=FreightNetwork(4,network.Save());
    foreach(id,record in network.optimiser.trains) if(record.cargo==FreightCargo("GOOD") &&
        record.single_route!=null) throw "Dual goods route changed on save/load";
    if(!network.state.post_goods_farms) throw "Goods completion lost farm expansion handover on save/load";
    if(network.state.segments.len()!=2) throw "Separate track missing from maintenance records";
    foreach(j in network.state.junctions) if(j.segment==1) throw "Disconnected goods line offered as farm junction";
    local goods=FreightCargo("GOOD"),loaded_goods=false;
    for(local tick=0;tick<100000;tick++) {
        foreach(id,r in network.optimiser.trains) if(r.cargo==goods) {
            if(r.source_industry!=network.state.chain.factory || AIOrder.GetOrderDestination(id,2)!=r.depot)
                throw "Goods service lost its factory/depot";
            if(AIVehicle.GetCargoLoad(id,goods)>0) loaded_goods=true;
            if(loaded_goods && AIStation.GetStationID(AIVehicle.GetLocation(id))==r.station_b && AIVehicle.GetCargoLoad(id,goods)==0) {
                AILog.Info("PRODUCTION PASS: farm delivery followed by separate factory goods station, city delivery and save/load.");
                while(true) this.Sleep(1000);
            }
        }
        this.Sleep(1);
    }
    foreach(id,r in network.optimiser.trains) AILog.Info("Goods fixture diagnostic: train="+id+", cargo="+r.cargo+", state="+AIVehicle.GetState(id)+", tile="+AIVehicle.GetLocation(id)+", depot="+r.depot+", load="+AIVehicle.GetCargoLoad(id,r.cargo)+", current="+AIOrder.ResolveOrderPosition(id,AIOrder.ORDER_CURRENT)+", source="+AIStation.GetLocation(r.station_a)+", target="+AIStation.GetLocation(r.station_b));
    throw "Separate goods train did not deliver";''')

# Force the no-loop case so successful delivery proves terminus fallback works.
if "--terminus" in sys.argv:
    driver = 'function RollThroughStation::PlanFlexible(entrance,lane,length) { return null; }\n' + driver

with tempfile.TemporaryDirectory(prefix='openttdai-farm-start-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'FarmStartCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "FarmStartCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=1800000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=180)
        (root / 'tests' / f'farm-start-{"goods-" if "--goods" in sys.argv else ""}{"terminus-" if "--terminus" in sys.argv else ""}{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PRODUCTION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
