"""Live roll-through station geometry, circulation, fallback and cleanup test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'MidpointCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nMidpointCheck = \n', config)
driver = r'''
class MidpointBuilder extends RouteBuilder {
    failed=false; checked=false; original_tiles=null; always_fail=false;
    function SearchPath(start,goal,reserved,preferred=null,batches=40,occupied=null) {
        if(preferred!=null && (!this.failed || this.always_fail)) {
            this.failed=true;
            this.original_tiles=clone preferred;this.original_tiles.reverse();
            this.search_failure="middle";
            return null;
        }
        if(this.committed_prefix) {
            local tiles=this.original_tiles,end=tiles.len()/2;
            for(local i=0;i<end-1;i++) {
                local before=i==0 ? start[1] : tiles[i-1];
                if(!AIRail.AreTilesConnected(before,tiles[i],tiles[i+1])) throw "Source half was removed";
            }
            for(local i=end;i<tiles.len()-1;i++)
                if(AIRail.AreTilesConnected(tiles[i-1],tiles[i],tiles[i+1])) throw "Tail was not removed";
            this.checked=true;
        }
        return this.SearchPathMode(start,goal,reserved,preferred,batches,occupied);
    }
}
function OpenTTDAI::Start() {
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("RORO FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=MidpointBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("RORO FAIL: no fixture"); return; }
    if(!AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) { AILog.Error("RORO FAIL: levelling: "+AIError.GetLastErrorString()); return; }
    local w=AIMap.GetMapSizeX();
    local a={tile=origin+AIMap.GetTileIndex(5,8),dir=AIRail.RAILTRACK_NE_SW};
    local b={tile=origin+AIMap.GetTileIndex(29,8),dir=AIRail.RAILTRACK_NE_SW};
    if(!this.builder.BuildStation(a) || !this.builder.BuildStation(b)) { AILog.Error("RORO FAIL: stations: "+AIError.GetLastErrorString()); return; }
    this.builder.pending_stations=[clone a,clone b];

    local found=this.builder.FindPathBetween(a,b);
    if(found==null || !this.builder.failed || !this.builder.checked) throw "Midpoint retry did not succeed";
    if(!this.builder.BuildPath(found) || !this.builder.BuildPath(found.secondary)) throw "Retried tracks did not build";
    if(this.builder.committed_prefix || this.builder.reuse_prefixes) throw "Retry settings leaked";
    local tiles=this.builder.PathTiles(found.path);
    local old=this.builder.original_tiles;
    foreach(tile in tiles) if(tile==old[(3*old.len())/4]) throw "Retry used the identical failed tail";
    // Remove the secondary independently, then verify the live journal removes
    // every original and replacement primary piece, including retained rail.
    local secondary={upgrade={pieces=[],structures=[],removed=[],signals=[]}};
    local all=[found.secondary.goal[1]];
    foreach(tile in this.builder.PathTiles(found.secondary.path)) all.append(tile);
    all.append(found.secondary.start[1]);
    for(local i=1;i<all.len()-1;i++) secondary.upgrade.pieces.append([all[i-1],all[i],all[i+1]]);
    if(!RestoreSingleUpgrade(secondary) || !this.builder.UndoFirstLine()) throw "Retry rollback failed";
    foreach(tile in tiles) if(AIRail.IsRailTile(tile)) throw "Retry left primary rail behind";
    foreach(tile in old) if(AIRail.IsRailTile(tile)) throw "Retry left old tail behind";
    // An obstacle appearing after planning forces an actual construction error.
    local reserved=[];
    foreach(site in [a,b]) foreach(tile in this.builder.StationTiles(site)) reserved.append(tile);
    local planned=this.builder.SearchPathMode(found.start,found.goal,reserved);
    if(planned==null) throw "Construction-failure fixture search failed";
    this.builder.original_tiles=this.builder.PathTiles(planned);this.builder.original_tiles.reverse();
    local obstacle=this.builder.original_tiles[(3*this.builder.original_tiles.len())/4];
    if(!AIRail.BuildRailDepot(obstacle,obstacle+1)) throw "Construction obstacle failed";
    this.builder.checked=false;
    local rebuilt=this.builder.BuildTrackPair(planned,found.start,found.goal,found.secondary.start,
        found.secondary.goal,reserved,reserved,40);
    if(rebuilt==null || !this.builder.checked) throw "Partial construction retry failed";
    if(!this.builder.UndoFirstLine() || !AIRail.IsRailDepotTile(obstacle)) throw "Rollback damaged unrelated infrastructure";
    if(!AITile.DemolishTile(obstacle)) throw "Fixture cleanup failed";
    this.builder.always_fail=true;this.builder.failed=false;this.builder.checked=false;
    if(this.builder.FindPathBetween(a,b)!=null || !this.builder.checked) throw "Exhausted retry incorrectly succeeded";
    foreach(tile in this.builder.original_tiles) if(AIRail.IsRailTile(tile)) throw "Exhausted retry left rail";
    AILog.Info("MIDPOINT PASS: retained source half, removed tail, alternative path, bounded failure and rollback.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-midpoint-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'MidpointCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "MidpointCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    template=main.read_text()
    for seed, vertical in [(42,False),(7,False),(42,True),(7,True)]:
        content=template
        if vertical:
            content=content.replace('GetMapSizeX()-42','GetMapSizeX()-26').replace('GetMapSizeY()-26','GetMapSizeY()-42').replace('tile,38,22','tile,22,38').replace('(37,21)','(21,37)').replace('(5,8)','(8,5)').replace('(29,8)','(8,29)').replace('dir=AIRail.RAILTRACK_NE_SW','dir=AIRail.RAILTRACK_NW_SE')
        main.write_text(content)
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'midpoint-{vertical}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'MIDPOINT PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
