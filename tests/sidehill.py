"""Live route smoothing, train traffic and terrain restoration test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SidehillCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSidehillCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("SIDEHILL FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("SIDEHILL FAIL: no fixture"); return; }
    if(!AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) { AILog.Error("SIDEHILL FAIL: levelling: "+AIError.GetLastErrorString()); return; }
    local w=AIMap.GetMapSizeX();
    local a={tile=origin+AIMap.GetTileIndex(1,2),dir=AIRail.RAILTRACK_NE_SW};
    local b={tile=origin+AIMap.GetTileIndex(33,17),dir=AIRail.RAILTRACK_NE_SW};
    if(!this.builder.BuildStation(a) || !this.builder.BuildStation(b)) { AILog.Error("SIDEHILL FAIL: stations: "+AIError.GetLastErrorString()); return; }
    this.builder.pending_stations=[clone a,clone b];
    local found=this.builder.FindPathBetween(a,b);
    if(found==null) throw "Flat route not found";
    local primary=this.builder.PathTiles(found.path);
    local secondary={}; foreach(tile in this.builder.PathTiles(found.secondary.path)) secondary[tile] <- true;
    local hill=null;
    // Raise a corner alongside a shared diagonal piece, keeping the first rail viable.
    for(local i=primary.len()/3;i<2*primary.len()/3 && hill==null;i++) {
        local tile=primary[i];
        if(!(tile in secondary)) continue;
        foreach(corner in PairedTerrain().Corners(tile)) {
            local terrain=PairedTerrain();
            if(!terrain.SetHeight(corner,AITile.GetCornerHeight(corner,AITile.CORNER_N)+1) || !terrain.Apply()) continue;
            local valid=true;
            {
                local test=AITestMode();
                local check=[found.goal[1]];
                foreach(t in primary) check.append(t); check.append(found.start[1]);
                for(local k=1;k<check.len()-1;k++) if(!AIRail.BuildRail(check[k-1],check[k],check[k+1])) { valid=false; break; }
            }
            if(valid) { hill=terrain; break; }
            if(!terrain.Restore()) throw "Fixture restoration failed";
        }
    }
    if(hill==null) throw "No sidehill fixture";
    local snapshot={};
    for(local x=8;x<=30;x++) for(local y=3;y<=20;y++) {
        local tile=origin+AIMap.GetTileIndex(x,y);
        snapshot[tile] <- AITile.GetCornerHeight(tile,AITile.CORNER_N);
    }
    local old_secondary=found.secondary.path;
    local path=this.builder.SearchPath(found.secondary.start,found.secondary.goal,[],primary,40,this.builder.TrackReservations(found.path,found.start,found.goal));
    if(path==null) throw "Detour not found";
    local original_tiles=this.builder.PathTiles(old_secondary);
    local detour=this.builder.PathTiles(path);
    local differs=original_tiles.len()!=detour.len();
    if(!differs) foreach(i,tile in original_tiles) if(tile!=detour[i]) differs=true;
    if(!differs) throw "Fixture did not split tracks";
    found.secondary.path=path;
    found.quality=this.builder.PathQuality(found.path,found.start,found.goal);
    found.quality.score+=this.builder.PathQuality(path,found.secondary.start,found.secondary.goal).score;
    local before=found.quality.score;
    found=this.builder.ImproveTerrain(found,a,b);
    if(found==null || found.quality.score>=before) throw "Earthworks did not improve route";
    local after_primary=this.builder.PathTiles(found.path);
    if(after_primary.len()!=primary.len()) throw "Primary track moved";
    foreach(i,tile in primary) if(after_primary[i]!=tile) throw "Primary track moved";
    local restored=this.builder.PathTiles(found.secondary.path);
    if(restored.len()!=original_tiles.len()) throw "Second track still detours";
    foreach(i,tile in original_tiles) if(restored[i]!=tile) throw "Second track still detours";
    if(!("earthwork_original" in this.builder.pending_stations[0])) throw "Earthworks recovery not recorded";
    if(!this.builder.BuildPath(found) || !this.builder.BuildPath(found.secondary) ||
        !this.builder.BuildStationEntrances(found)) { AILog.Error("SIDEHILL FAIL: construction"); return; }
    local depot=this.builder.BuildDepot(found.depot_site);
    if(!AIRail.IsRailDepotTile(depot) || !this.builder.BuildLineSignals(found)) { AILog.Error("SIDEHILL FAIL: depot/signals"); return; }
    local buyer=TrainBuyer(PassengerCargo());
    local train=buyer.BuildPassengerTrain(depot,a.tile,b.tile,3);
    if(!AIVehicle.IsValidVehicle(train)) { AILog.Error("SIDEHILL FAIL: purchase"); return; }
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
    if(stage!=4) { AILog.Error("SIDEHILL FAIL: train stuck, stage="+stage); return; }
    AIVehicle.SendVehicleToDepot(train);
    for(local tick=0;tick<10000 && !AIVehicle.IsStoppedInDepot(train);tick++) this.Sleep(1);
    if(!AIVehicle.SellVehicle(train)) { AILog.Error("SIDEHILL FAIL: sell"); return; }
    AITile.DemolishTile(depot);
    this.builder.CleanupRoute(found,a,b);
    if(!this.builder.ReleasePendingStations()) throw "Earthworks restoration failed";
    foreach(tile,height in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=height) throw "Original ridge not restored";
    AILog.Info("SIDEHILL PASS: sidehill cut away, first track unchanged, close diagonal second track restored, train circuit and rollback passed.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-sidehill-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SidehillCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SidehillCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'sidehill-{"water" if "--water" in sys.argv else "rail"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'SIDEHILL PASS:' in result.stderr, 'Bridge checks did not complete'
        assert 'SIDEHILL FAIL:' not in result.stderr
