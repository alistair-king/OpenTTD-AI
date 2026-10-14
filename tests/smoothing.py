"""Live route smoothing, train traffic and terrain restoration test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SmoothingCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSmoothingCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("SMOOTHING FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    this.builder.use_jump_search=true;
    this.builder.use_aystar=true;
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("SMOOTHING FAIL: no fixture"); return; }
    if(!AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) { AILog.Error("SMOOTHING FAIL: levelling: "+AIError.GetLastErrorString()); return; }
    local w=AIMap.GetMapSizeX();
    local a={tile=origin+AIMap.GetTileIndex(1,8),dir=AIRail.RAILTRACK_NE_SW};
    local b={tile=origin+AIMap.GetTileIndex(33,8),dir=AIRail.RAILTRACK_NE_SW};
    if(!this.builder.ReserveStations(a,b)) { AILog.Error("SMOOTHING FAIL: stations: "+AIError.GetLastErrorString()); return; }
    // A shallow ridge crosses both future running lines.
    for(local y=6;y<=12;y++) if(!AITile.RaiseTile(origin+AIMap.GetTileIndex(18,y),AITile.SLOPE_N)) throw "Ridge construction failed";
    this.builder.pending_stations=[clone a,clone b];
    local snapshot={};
    for(local x=10;x<=26;x++) for(local y=3;y<=16;y++) {
        local tile=origin+AIMap.GetTileIndex(x,y);
        snapshot[tile] <- AITile.GetCornerHeight(tile,AITile.CORNER_N);
    }
    // Model a reserved RIRO footprint beside the cutting: its corners must stay intact.
    local protected_tile=origin+AIMap.GetTileIndex(18,5);
    this.builder.extra_reserved=[protected_tile];
    local protected_heights={};
    foreach(corner in PairedTerrain().Corners(protected_tile))
        protected_heights[corner] <- AITile.GetCornerHeight(corner,AITile.CORNER_N);
    local found=this.builder.FindPathBetween(a,b);
    if(found==null) throw "Original route not found";
    local before=found.quality.score;
    found=this.builder.ImproveTerrain(found,a,b);
    if(found==null) throw "Earthworks lost route";
    foreach(site in [a,b]) foreach(tile in this.builder.StationTiles(site))
        if(AIRail.IsRailStationTile(tile)) throw "Station built before route was determined";
    foreach(id,_ in AISignList())
        if(AISign.GetName(id).find("[VT search]")!=null) throw "Pathfinding sign created";
    if(!this.builder.BuildPlannedStations(a,b)) throw "Deferred station construction failed";
    local lowered=false;
    foreach(tile,height in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)<height) lowered=true;
    if(!lowered) throw "Ridge was not lowered";
    foreach(tile,height in protected_heights)
        if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=height) throw "Reserved loop terrain changed";
    if(!("earthwork_original" in this.builder.pending_stations[0])) throw "Earthworks recovery not recorded";
    if(!this.builder.BuildPath(found) || !this.builder.BuildPath(found.secondary) ||
        !this.builder.BuildStationEntrances(found)) { AILog.Error("SMOOTHING FAIL: construction"); return; }
    local depot=this.builder.BuildDepot(found.depot_site);
    if(!AIRail.IsRailDepotTile(depot) || !this.builder.BuildLineSignals(found)) { AILog.Error("SMOOTHING FAIL: depot/signals"); return; }
    local buyer=TrainBuyer(PassengerCargo());
    local train=buyer.BuildPassengerTrain(depot,a.tile,b.tile,3);
    if(!AIVehicle.IsValidVehicle(train)) { AILog.Error("SMOOTHING FAIL: purchase"); return; }
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
    if(stage!=4) { AILog.Error("SMOOTHING FAIL: train stuck, stage="+stage); return; }
    AIOrder.SetOrderFlags(train,2,AIOrder.OF_STOP_IN_DEPOT);
    AIOrder.SkipToOrder(train,2);
    for(local tick=0;tick<10000 && !AIVehicle.IsStoppedInDepot(train);tick++) this.Sleep(1);
    if(!AIVehicle.SellVehicle(train)) { AILog.Error("SMOOTHING FAIL: sell"); return; }
    AITile.DemolishTile(depot);
    this.builder.CleanupRoute(found,a,b);
    if(!this.builder.ReleasePendingStations()) throw "Earthworks restoration failed";
    foreach(tile,height in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=height) throw "Original ridge not restored";
    AILog.Info("SMOOTHING PASS: both-track route improved, train completed circuit, original terrain restored after cleanup.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-smoothing-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SmoothingCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SmoothingCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'smoothing-{"water" if "--water" in sys.argv else "rail"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'SMOOTHING PASS:' in result.stderr, 'Bridge checks did not complete'
        assert 'SMOOTHING FAIL:' not in result.stderr
