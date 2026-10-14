"""Permanent single-platform fallback integration test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'CompactPassengerCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nCompactPassengerCheck = \n', config)
driver = r'''
class NarrowPassengerBuilder extends RouteBuilder {
    sites=null;
    function FindStationSites(town,target,dir=null,source=null,central=true,coverage_bias=true) {
        local site=clone this.sites[town];site.platforms <- this.station_platforms;
        return this.CanBuildStation(site) ? [site] : [];
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local b=NarrowPassengerBuilder(4),origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22) || AITile.GetMinHeight(tile)<2) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null || !AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) throw "No flat fixture";
    b.sites=[{tile=origin+AIMap.GetTileIndex(5,8),dir=AIRail.RAILTRACK_NE_SW,production=100,center_distance=0},
             {tile=origin+AIMap.GetTileIndex(29,8),dir=AIRail.RAILTRACK_NE_SW,production=100,center_distance=0}];
    foreach(site in b.sites) {
        // An occupied tile alongside the platform makes two platforms impossible.
        local blocked=site.tile+AIMap.GetMapSizeX();
        if(!AIRail.BuildRailDepot(blocked,blocked+AIMap.GetMapSizeX())) throw "Could not obstruct second platform";
        if(b.CanBuildStation(site)) throw "Two-platform station incorrectly fits";
        local narrow=clone site;narrow.platforms <- 1;
        if(!b.CanBuildStation(narrow)) throw "One-platform station should fit";
    }
    local route=b.PlanReservedRoute(0,1);
    if(route==null || route.single_route==null || !route.single_route.permanent) throw "Passenger fallback failed";
    if(b.station_platforms!=2) throw "Station search width not restored";
    local buyer=TrainBuyer(PassengerCargo());
    local train=buyer.BuildCargoTrain(route.depot,route.station_a,route.station_b,2,false);
    if(train<0) throw "Passenger purchase failed";
    local optimiser=ServiceOptimiser(buyer);optimiser.Register(train,route,4);
    optimiser=ServiceOptimiser(buyer,optimiser.Save());
    if(optimiser.MailTrainWanted(optimiser.trains[train]) || optimiser.CanExpandFleet(train,optimiser.trains[train])) throw "Passenger/mail fleet limit lost";
    local seen={},depot=false;
    for(local tick=0;tick<30000;tick++) {
        local station=AIStation.GetStationID(AIVehicle.GetLocation(train));
        if(station==AIStation.GetStationID(route.station_a) || station==AIStation.GetStationID(route.station_b)) seen[station] <- true;
        if(seen.len()==2 && AIVehicle.GetLocation(train)==route.depot) {depot=true;break;}
        this.Sleep(1);
    }
    if(!depot) throw "Passenger did not complete circuit";
    AIVehicle.SendVehicleToDepot(train);
    for(local tick=0;tick<10000 && !AIVehicle.IsStoppedInDepot(train);tick++) this.Sleep(1);
    if(!AIVehicle.IsStoppedInDepot(train) || !AIVehicle.SellVehicle(train)) throw "Could not retire fixture train";
    foreach(site in b.sites) {
        site.platforms <- 1;b.RemoveStation(site);
        if(AIRail.IsRailStationTile(site.tile) || !AIRail.IsRailDepotTile(site.tile+AIMap.GetMapSizeX())) throw "Compact cleanup damaged adjacent infrastructure";
    }
    AILog.Info("COMPACT PASS: real narrow footprints, passenger fallback, circuit, saved mail/fleet cap and safe station cleanup.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-compact-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'CompactPassengerCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "CompactPassengerCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=150)
        (root / 'tests' / f'compact-passenger-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'COMPACT PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
