"""Live route smoothing, train traffic and terrain restoration test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SinglePassengerCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSinglePassengerCheck = \n', config)
driver = r'''
::native_restore <- RestoreSingleUpgrade;
::hold_recovery <- false;
::RestoreSingleUpgrade <- function(data) {
    if(hold_recovery && data.upgrade!=null) return false;
    return native_restore(data);
};
function CopySave(value)
{
    local t=typeof value;
    if(t=="array") { local out=[]; foreach(v in value) out.append(CopySave(v)); return out; }
    if(t=="table") { local out={}; foreach(k,v in value) out[k] <- CopySave(v); return out; }
    if(t!="integer" && t!="string" && t!="bool" && t!="null") throw "Unsupported saved type: "+t;
    return value;
}
function OpenTTDAI::Start()
{
    this.Sleep(1); this.SetCompanyName(); AICompany.SetAutoRenewStatus(false);
    if(!PickRailType()) throw "No rail";
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4); this.builder.single_first=true;
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null || !AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) throw "No fixture";
    local a={tile=origin+AIMap.GetTileIndex(1,8),dir=AIRail.RAILTRACK_NE_SW};
    local z={tile=origin+AIMap.GetTileIndex(33,8),dir=AIRail.RAILTRACK_NE_SW};
    if(!this.builder.ReserveStations(a,z)) throw "Station preparation";
    local found=this.builder.FindPathBetween(a,z);
    if(found==null || !("single" in found)) throw "Single planning failed";
    if(!found.depot_site.approach || found.depot_site.distance<10 || found.depot_site.distance>20)
        throw "Depot not on approach 10-20 tiles before crossover";
    foreach(tile in this.builder.PathTiles(found.path))
        if(tile==found.depot_site.depot) throw "Main track occupies its depot site";

    if(!this.builder.BuildPlannedStations(a,z) || !this.builder.BuildPath(found) ||
        !this.builder.BuildPath(found.secondary) || !this.builder.BuildStationEntrances(found)) throw "Single build failed";
    local depot=this.builder.BuildDepot(found.depot_site);
    if(!AIRail.IsRailDepotTile(depot)) throw "Depot failed";
    this.builder.BuildPreferredStations(found);
    local route={station_a=a.tile,station_b=z.tile,depot=depot,single_route=SaveSingleRoute(this.builder,found,a,z)};
    this.builder.pending_stations=[];
    this.buyer=TrainBuyer(PassengerCargo());
    local train=this.buyer.BuildPassengerTrain(depot,a.tile,z.tile,3);
    if(train<0) throw "Train failed";
    this.optimiser=ServiceOptimiser(this.buyer); this.optimiser.Register(train,route,4);
    local stage=0;
    for(local tick=0;tick<40000 && stage<3;tick++) {
        local id=AIStation.GetStationID(AIVehicle.GetLocation(train));
        if(stage==0 && id==AIStation.GetStationID(a.tile)) stage=1;
        else if(stage==1 && id==AIStation.GetStationID(z.tile)) stage=2;
        else if(stage==2 && id==AIStation.GetStationID(a.tile)) stage=3;
        this.Sleep(1);
    }
    if(stage!=3) throw "Initial bidirectional passenger circulation failed";
    AIVehicle.SendVehicleToDepot(train);
    for(local tick=0;tick<20000 && !AIVehicle.IsStoppedInDepot(train);tick++) this.Sleep(1);
    if(!AIVehicle.IsStoppedInDepot(train)) throw "Train not held safely";
    local record=this.optimiser.trains[train], data=record.single_route;
    // No possible target: the running single route must remain intact.
    data.reserved.append(data.goal2[0]);
    if(UpgradeSingleRoute(train,record) || data.dual || data.upgrade!=null) throw "Failed search changed route";
    data.reserved.pop();
    // Fail after construction and platform signalling, then simulate a save/load
    // while rollback is pending. No second train may be commissioned in this state.
    local front=data.depot_site.front; data.depot_site.front=AIMap.TILE_INVALID;
    hold_recovery=true;
    if(UpgradeSingleRoute(train,record) || data.dual || data.upgrade==null || !AIVehicle.IsStoppedInDepot(train))
        throw "Upgrade failure not held for recovery";
    data.depot_site.front=front;
    local saved=CopySave(this.Save()); this.Load(1,saved);
    this.optimiser=ServiceOptimiser(this.buyer,this.loaded_services);
    record=this.optimiser.trains[train]; data=record.single_route;
    hold_recovery=false;
    if(!RestoreSingleUpgrade(data) || data.upgrade!=null) throw "Saved upgrade recovery failed";
    foreach(p in data.merges) if(!AIRail.AreTilesConnected(p[0],p[1],p[2])) throw "Single merge not restored";
    foreach(e in data.entrances) foreach(signal in e.signals)
        if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_NONE) throw "Signal remained after rollback";
    if(!UpgradeSingleRoute(train,record) || !data.dual) throw "Successful conversion failed";
    foreach(p in data.merges) if(AIRail.AreTilesConnected(p[0],p[1],p[2])) throw "Merge remained after conversion";
    AIOrder.SkipToOrder(train,0); AIVehicle.StartStopVehicle(train);
    stage=0;
    for(local tick=0;tick<40000 && stage<3;tick++) {
        local id=AIStation.GetStationID(AIVehicle.GetLocation(train));
        if(stage==0 && id==AIStation.GetStationID(a.tile)) stage=1;
        else if(stage==1 && id==AIStation.GetStationID(z.tile)) stage=2;
        else if(stage==2 && id==AIStation.GetStationID(a.tile)) stage=3;
        this.Sleep(1);
    }
    if(stage!=3) throw "Upgraded passenger circulation failed";
    AILog.Info("SMOOTHING PASS: single passenger circuit, blocked upgrade, saved partial construction rollback, successful one-way conversion and circuit.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-single-passenger-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SinglePassengerCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SinglePassengerCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'single-passenger-{"water" if "--water" in sys.argv else "rail"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'SMOOTHING PASS:' in result.stderr, 'Bridge checks did not complete'
        assert 'SMOOTHING FAIL:' not in result.stderr
