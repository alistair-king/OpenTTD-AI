"""Isolated live-game shared bridge track test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'BridgeCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nBridgeCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("BRIDGE FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("BRIDGE FAIL: no fixture"); return; }
    if(!AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) { AILog.Error("BRIDGE FAIL: levelling: "+AIError.GetLastErrorString()); return; }
    local w=AIMap.GetMapSizeX();
    local a={tile=origin+AIMap.GetTileIndex(1,8),dir=AIRail.RAILTRACK_NE_SW};
    local b={tile=origin+AIMap.GetTileIndex(33,8),dir=AIRail.RAILTRACK_NE_SW};
    if(!this.builder.BuildStation(a) || !this.builder.BuildStation(b)) { AILog.Error("BRIDGE FAIL: stations: "+AIError.GetLastErrorString()); return; }
    this.builder.pending_stations=[clone a,clone b];
    // A perpendicular railway is an obstacle the ordinary planner cannot enter.
    for(local y=0;y<22;y++) {
        local tile=origin+AIMap.GetTileIndex(19,y);
        if(!AIRail.BuildRail(tile-w,tile,tile+w)) { AILog.Error("BRIDGE FAIL: barrier: "+AIError.GetLastErrorString()); return; }
    }
    local found=this.builder.FindPathBetween(a,b);
    if(found==null) { AILog.Error("BRIDGE FAIL: planning"); return; }
    local spans=[];
    foreach(line in [found,found.secondary]) {
        local tiles=this.builder.PathTiles(line.path);
        local count=0;
        for(local i=1;i<tiles.len();i++) if(IsStructureSpan(tiles[i-1],tiles[i])) {
            if(AIMap.DistanceManhattan(tiles[i-1],tiles[i])!=2) throw "Bridge extends beyond the first usable landing";
            spans.append([tiles[i-1],tiles[i]]); count++;
        }
        if(count!=1) { AILog.Error("BRIDGE FAIL: expected one span per track, got "+count); return; }
    }
    if(AIMap.DistanceManhattan(spans[0][0],spans[1][0])!=1 || AIMap.DistanceManhattan(spans[0][1],spans[1][1])!=1) {
        AILog.Error("BRIDGE FAIL: paired spans not adjacent"); return;
    }
    if(!this.builder.BuildPath(found) || !this.builder.BuildPath(found.secondary) ||
        !this.builder.BuildStationEntrances(found)) { AILog.Error("BRIDGE FAIL: construction"); return; }
    local depot=this.builder.BuildDepot(found.depot_site);
    if(!AIRail.IsRailDepotTile(depot) || !this.builder.BuildLineSignals(found)) { AILog.Error("BRIDGE FAIL: depot/signals"); return; }
    local buyer=TrainBuyer(PassengerCargo());
    local train=buyer.BuildPassengerTrain(depot,a.tile,b.tile,3);
    if(!AIVehicle.IsValidVehicle(train)) { AILog.Error("BRIDGE FAIL: purchase"); return; }
    local stage=0;
    for(local tick=0;tick<40000 && stage<4;tick++) {
        local tile=AIVehicle.GetLocation(train);
        local station=AIStation.GetStationID(tile);
        if(stage==0 && station==AIStation.GetStationID(a.tile)) stage=1;
        else if(stage==1 && station==AIStation.GetStationID(b.tile)) stage=2;
        else if(stage==2 && tile==depot) stage=3;
        else if(stage==3 && station==AIStation.GetStationID(a.tile)) stage=4;
        this.Sleep(1);
    }
    if(stage!=4) { AILog.Error("BRIDGE FAIL: train stuck, stage="+stage); return; }
    if(!AIOrder.InsertOrder(train,0,depot,AIOrder.OF_STOP_IN_DEPOT) || !AIOrder.SkipToOrder(train,0)) throw "Depot cleanup order failed";
    for(local tick=0;tick<10000 && !AIVehicle.IsStoppedInDepot(train);tick++) this.Sleep(1);
    if(!AIVehicle.SellVehicle(train)) { AILog.Error("BRIDGE FAIL: sell"); return; }
    AITile.DemolishTile(depot);
    this.builder.CleanupRoute(found,a,b);
    foreach(span in spans) if(AIBridge.IsBridgeTile(span[0]) || AIBridge.IsBridgeTile(span[1])) { AILog.Error("BRIDGE FAIL: cleanup"); return; }
    for(local y=0;y<22;y++) {
        local tile=origin+AIMap.GetTileIndex(19,y);
        if(!AIRail.AreTilesConnected(tile-w,tile,tile+w)) { AILog.Error("BRIDGE FAIL: barrier damaged"); return; }
    }
    AILog.Info("BRIDGE PASS: adjacent spans, signals, train A-B-depot-A, cleanup preserves railway below.");
    while(true) this.Sleep(1000);
}
'''
if '--water' in sys.argv:
    # Canal construction is fixture setup, not part of the AI route budget.
    config = re.sub(r'^max_loan = .*$', 'max_loan = 2000000', config, flags=re.M)
    # Keep canal ends inside the levelled rectangle rather than on its edge slopes.
    driver = driver.replace('y=0;y<22;y++', 'y=2;y<20;y++')
    driver = driver.replace('AIRail.BuildRail(tile-w,tile,tile+w)', 'AIMarine.BuildCanal(tile)')
    driver = driver.replace('AIRail.AreTilesConnected(tile-w,tile,tile+w)', 'AIMarine.IsCanalTile(tile)')
    driver = driver.replace('railway below', 'canal below')
with tempfile.TemporaryDirectory(prefix='openttdai-bridge-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'BridgeCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "BridgeCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'bridge-{"water" if "--water" in sys.argv else "rail"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'BRIDGE PASS:' in result.stderr, 'Bridge checks did not complete'
        assert 'BRIDGE FAIL:' not in result.stderr
