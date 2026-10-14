"""Permanent single-platform fallback integration test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ClosureCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nClosureCheck = \n', config)
driver = r'''
class ClosedServiceProbe {
    trains=null;sold=null;
    constructor() {this.trains={};this.sold={};}
    function ForceSale(id) {this.sold[id] <- true;}
}
class CompactCoal extends CoalRoutes {
    wider_checked=false;
    function Sites(endpoint,target,loading) {
        if(this.builder.station_platforms==2) {this.wider_checked=true;return [];}
        if(!this.wider_checked) throw "Compact station considered before wider stations";
        return CoalRoutes(this.builder).Sites(endpoint,target,loading);
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local b=RouteBuilder(4),coal=CompactCoal(b);
    for(local attempt=0;attempt<100 && coal.services.len()==0;attempt++) {
        coal.TryBuild();this.Sleep(74*8);
    }
    if(coal.services.len()!=1) throw "Compact coal route did not commission";
    local train=-1;foreach(id,_ in coal.services) train=id;
    local record=coal.optimiser.trains[train],service=coal.services[train];
    if(record.single_route==null || !("permanent" in record.single_route) || !record.single_route.permanent)
        throw "Permanent fleet restriction not recorded";
    if(b.station_platforms!=2) throw "Fallback leaked into next route";
    foreach(tile in [service.station_a,service.station_b]) {
        local station=AIStation.GetStationID(tile);
        if(AITileList_StationType(station,AIStation.STATION_TRAIN).Count()!=4)
            throw "Station has more than one platform";
        local site={tile=tile,dir=AIRail.GetRailStationDirection(tile),platforms=1};
        if(b.StationTiles(site).len()!=4) throw "Incorrect compact footprint";
        local saved=SavedStationReservations([site]);
        if(StationPlatforms(saved[0])!=1) throw "Cleanup lost station width on save";
    }
    if(coal.optimiser.CanExpandFleet(train,record) || coal.optimiser.MailTrainWanted(record) || UpgradeSingleRoute(train,record))
        throw "Compact route permitted another train or track upgrade";
    coal=CompactCoal(b,coal.Save());record=coal.optimiser.trains[train];
    if(coal.optimiser.CanExpandFleet(train,record) || !record.single_route.permanent)
        throw "Reload lost one-train restriction";
    if(FarmBackbone(b).allow_single_station)
        throw "Farm backbone permitted one-train fallback";
    if(!NetworkBackbone(b).allow_single_station ||
        FreightNetwork(4).JunctionCandidates({permanent_single=true}).len()!=0)
        throw "Compact freight backbone advertised shared-track junctions";
    local loaded=false,delivered=false,depot_seen=false;
    for(local tick=0;tick<100000;tick++) {
        if(AIVehicle.GetCargoLoad(train,coal.cargo)>0) loaded=true;
        if(loaded && AIStation.GetStationID(AIVehicle.GetLocation(train))==record.station_b && AIVehicle.GetCargoLoad(train,coal.cargo)==0) delivered=true;
        if(delivered && AIVehicle.GetLocation(train)==record.depot) {depot_seen=true;break;}
        this.Sleep(1);
    }
    if(!loaded || !delivered || !depot_seen) throw "Compact train failed delivery and maintenance circuit";
    local n=FreightNetwork(4),probe=ClosedServiceProbe();
    n.optimiser=probe;n.state.chain={mine=10000,mill=10001,factory=10002};
    n.state.steel_outlet <- {source=service.station_a,destination=service.station_b};
    n.state.goods_outlet <- {source=service.station_a,destination=service.station_b};
    probe.trains[1] <- {station_a=-10,station_b=AIStation.GetStationID(service.station_b)};
    probe.trains[2] <- {station_a=AIStation.GetStationID(service.station_a),station_b=-11};
    probe.trains[3] <- {station_a=-12,station_b=-13};
    n.OnIndustryClosed(10002);
    if(!(1 in probe.sold) || !(2 in probe.sold) || 3 in probe.sold) throw "Separate steel/goods closure matching failed";
    ::RetiredRailways=RailwayRetirement();
    local extra=coal.buyer.BuildCargoTrain(service.depot,service.station_a,service.station_b,2,true,false,64);
    if(extra<0) throw "No additional consist";
    coal.optimiser.Register(extra,service,4);
    // Old saves lack endpoint IDs and clones have no CoalRoutes.services entry.
    delete coal.optimiser.trains[extra].source_industry;
    delete coal.optimiser.trains[extra].target_industry;
    coal.OnIndustryClosed(service.target);
    foreach(id,r in coal.optimiser.trains) if(!("industry_closed" in r)) throw "Closure missed an added train";
    if(AIVehicle.IsValidVehicle(train) && coal.optimiser.trains[train].phase!="sell" && !AIVehicle.IsStoppedInDepot(train)) throw "Depot diversion was not immediate: "+AIError.GetLastErrorString()+" flags="+AIOrder.GetOrderFlags(train,2)+" state="+AIVehicle.GetState(train);
    coal=CompactCoal(b,coal.Save());
    for(local tick=0;tick<30000 && coal.optimiser.trains.len()>0;tick++) {
        coal.optimiser.ReviewClosures();this.Sleep(1);
    }
    if(AIVehicle.IsValidVehicle(train) || AIVehicle.IsValidVehicle(extra)) throw "Closure trains not sold";
    RetiredRailways=RailwayRetirement(RetiredRailways.Save());
    for(local tick=0;tick<5000 && RetiredRailways.jobs.len()>0;tick++) {RetiredRailways.Step();this.Sleep(1);}
    if(AIRail.IsRailDepotTile(service.depot) || AIRail.IsRailStationTile(service.station_a) || AIRail.IsRailStationTile(service.station_b)) throw "Closed line infrastructure remained";
    AILog.Info("CLOSURE PASS: immediate depot diversion, added trains, saved urgent retirement and unused railway demolition.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-compact-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ClosureCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ClosureCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=150)
        (root / 'tests' / f'closure-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'CLOSURE PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
