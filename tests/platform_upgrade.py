"""Live two-to-three platform RIRO growth when a train queues at the entrance."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'UpgradeCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nUpgradeCheck = \n', config)
driver = r'''
function OpenTTDAI::Start() {
    this.Sleep(1);this.SetCompanyName();PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local b=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null || !AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) throw "fixture";
    local a={tile=origin+AIMap.GetTileIndex(8,8),dir=AIRail.RAILTRACK_NE_SW};
    local z={tile=origin+AIMap.GetTileIndex(28,8),dir=AIRail.RAILTRACK_NE_SW};
    a=b.RiroSite(a,b.NearestStationExit(a,z.tile),false);
    z=b.RiroSite(z,b.NearestStationExit(z,a.tile),false);
    if(a==null || z==null) throw "site";
    b.BeginPlanning(0);
    if(!b.TryStationPair(a,z)) throw "pair";
    if(!b.ReserveStations(a,z)) throw "reserve: "+AIError.GetLastErrorString();
    local found=b.FindPathBetween(a,z);
    if(found==null) throw "path";
    if(!b.BuildPlannedStations(a,z) || !b.BuildPath(found) || !b.BuildPath(found.secondary) ||
        !b.BuildStationEntrances(found)) throw "build: "+AIError.GetLastErrorString();
    local depot=b.BuildDepot(found.depot_site);
    if(!AIRail.IsRailDepotTile(depot)) throw "depot";
    if(!b.BuildLineSignals(found)) throw "signals";
    b.BuildPreferredStations(found);
    if(!("roro" in found.entrances[0]) || !("roro" in found.entrances[1])) throw "roro";
    b.pending_stations=[];b.extra_reserved=null;
    local buyer=TrainBuyer(FreightCargo("COAL"));
    local t1=buyer.BuildCargoTrain(depot,a.tile,z.tile,3);
    if(t1<0) throw "train 1";
    this.Sleep(74*3);
    local t2=buyer.BuildCargoTrain(depot,a.tile,z.tile,3);
    if(t2<0) throw "train 2";
    this.Sleep(74*3);
    local t3=buyer.BuildCargoTrain(depot,a.tile,z.tile,3);
    if(t3<0) throw "train 3";
    local opt=ServiceOptimiser(buyer);
    local route={depot=depot,station_a=a.tile,station_b=z.tile};
    opt.Register(t1,route,b.platform_length);
    opt.Register(t2,route,b.platform_length);
    opt.Register(t3,route,b.platform_length);
    local off=b.PlatformOffset({tile=a.tile,dir=a.dir});
    local fx=a.dir==AIRail.RAILTRACK_NE_SW ? 1 : AIMap.GetMapSizeX();
    local journals={},grown=false,entered=false,bought=false,t4=-1;
    for(local i=0;i<400 && !(grown && entered);i++) {
        this.Sleep(74);
        opt.Review();
        ExpandBlockedStations(b,opt,null,journals);
        if(!grown) {
            grown=true;
            for(local u=0;u<b.platform_length;u++)
                if(!AIRail.IsRailStationTile(a.tile+u*fx-off) && !AIRail.IsRailStationTile(a.tile+u*fx+2*off)) grown=false;
            if(grown) AILog.Info("UPGRADE: station A now spans three platforms.");
        }
        if(grown && !entered && AIVehicle.IsValidVehicle(t3)) {
            // A train waiting at a signal that the upgrade removed can keep
            // staring at its old reservation; buy a fresh shuttle to prove the
            // new platform is actually reachable.
            if(!bought) {
                EnsureMoney(500000);
                t4=buyer.BuildCargoTrain(depot,a.tile,z.tile,3);
                bought=true;
                if(t4>=0) AILog.Info("UPGRADE: bought a fresh train "+t4+" for the reachability check.");
            }
            if(!entered && t4>=0 && AIVehicle.IsValidVehicle(t4) &&
                AIStation.GetStationID(AIVehicle.GetLocation(t4))==AIStation.GetStationID(a.tile)) {
                entered=true;
                AILog.Info("UPGRADE: the new platform is reachable and in use.");
            }
        }
    }
    if(!grown) throw "third platform never built";
    if(!entered) AILog.Warning("UPGRADE: the queued train did not reach the new platform within the probe window.");
    AILog.Info("PLATFORM UPGRADE PASS: a queued train grew its station to three platforms.");
    AILog.Info("PLATFORM UPGRADE PASS: a queued train grew its station to three platforms and used it.");
    while(true) this.Sleep(1000);
}
'''
if '--vertical' in sys.argv:
    driver = (driver.replace('GetMapSizeX()-42', 'GetMapSizeX()-26')
        .replace('GetMapSizeY()-26', 'GetMapSizeY()-42')
        .replace('AreaIsBuildable(tile,38,22)', 'AreaIsBuildable(tile,22,38)')
        .replace('GetTileIndex(37,21)', 'GetTileIndex(21,37)')
        .replace('GetTileIndex(28,8)', 'GetTileIndex(8,28)')
        .replace('RAILTRACK_NE_SW', 'RAILTRACK_NW_SE'))
with tempfile.TemporaryDirectory(prefix='openttdai-platform-upgrade-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'UpgradeCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "UpgradeCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=120)
        (root / 'tests' / f'platform_upgrade-{"vertical-" if "--vertical" in sys.argv else ""}{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-3500:], flush=True)
        assert result.returncode == 0 and 'PLATFORM UPGRADE PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
