"""Isolated live-game shared bridge track test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'StructureRetryCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nStructureRetryCheck = \n', config)
driver = r'''
class StructureRetryBuilder extends RouteBuilder {
    expected_exit=null; checked=false;
    function SearchPath(start,goal,reserved,preferred=null,batches=40,occupied=null) {
        if(this.committed_prefix) {
            local prefix=this.retained_prefixes[start[0]+":"+start[1]];
            if(prefix.top()!=this.expected_exit) throw "Retry is not at last structure exit";
            local saved=SavedStationReservations(this.pending_stations);
            if(saved[0].primary_recovery.upgrade.structures.len()==0) throw "Retained structure not journalled";
            foreach(span in saved[0].primary_recovery.upgrade.structures)
                if(BuiltRailSpanKind(span[0],span[1])!=span[2]) throw "Retry removed a completed structure";
            this.checked=true;
        }
        return this.SearchPathMode(start,goal,reserved,preferred,batches,occupied);
    }
}
function OpenTTDAI::Start() {
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("BRIDGE FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=StructureRetryBuilder(4);
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

    local original=this.builder.PathTiles(found.path);original.reverse();
    local last=-1,spans=[];
    for(local i=1;i<original.len();i++) if(IsStructureSpan(original[i-1],original[i])) {
        last=i;spans.append([original[i-1],original[i],BuiltRailSpanKind(original[i-1],original[i])]);
    }
    if(last<0) throw "No structure in fixture";
    this.builder.expected_exit=original[last];
    local reserved=[];
    foreach(site in [a,b]) foreach(tile in this.builder.StationTiles(site)) reserved.append(tile);
    local retry=this.builder.RetryFromMidpoint(found.path,found.start,found.goal,reserved,40);
    if(retry==null || !this.builder.checked) throw "Structure retry failed";
    local actual=this.builder.PathTiles(retry);actual.reverse();
    for(local i=0;i<=last;i++) if(actual[i]!=original[i]) throw "Retry changed retained prefix";
    local kinds=PathStructures(retry);
    foreach(span in spans) if(!(StructureKey(span[0],span[1]) in kinds) || kinds[StructureKey(span[0],span[1])]!=span[2])
        throw "Retried path lost structure metadata";
    if(!this.builder.UndoFirstLine()) throw "Retained structure rollback failed";
    foreach(span in spans) if(BuiltRailSpanKind(span[0],span[1])!=null) throw "Final rollback left structure";
    AILog.Info("STRUCTURE RETRY PASS: preserved prefix and all structures, last-exit seed, metadata and rollback.");
    while(true) this.Sleep(1000);
}
'''

if '--tunnel' in sys.argv:
    driver=driver.replace('    // A perpendicular railway is an obstacle the ordinary planner cannot enter.\n    for(local y=0;y<22;y++) {\n        local tile=origin+AIMap.GetTileIndex(19,y);\n        if(!AIRail.BuildRail(tile-w,tile,tile+w)) { AILog.Error("BRIDGE FAIL: barrier: "+AIError.GetLastErrorString()); return; }\n    }\n','    // Raised land with surface buildings blocks the direct surface route.\n    local terrain=PairedTerrain(2,512,100000);\n    // Construct test terrain directly; company finance rules are tested separately.\n    terrain.max_corners=512;\n    local height=AITile.GetCornerHeight(origin,AITile.CORNER_N)+1;\n    for(local x=13;x<=23;x++) for(local y=3;y<=19;y++)\n        if(!terrain.SetHeight(origin+AIMap.GetTileIndex(x,y),height)) throw "Plateau planning failed";\n    if(!terrain.MoveTo(terrain.targets)) throw "Plateau construction failed";\n    AIRoad.SetCurrentRoadType(AIRoad.ROADTYPE_ROAD);\n    for(local y=4;y<=17;y++) {\n        local tile=origin+AIMap.GetTileIndex(18,y);\n        if(!AIRoad.BuildRoadDepot(tile,tile+1)) throw "Surface building failed: "+AIError.GetLastErrorString();\n    }\n')
elif '--early' in sys.argv:
    driver=driver.replace('GetTileIndex(19,y)','GetTileIndex(11,y)')
else:
    driver=driver.replace('for(local y=0;y<22;y++) {','foreach(barrier in [11,26]) for(local y=1;y<21;y++) {').replace('GetTileIndex(19,y)','GetTileIndex(barrier,y)')
case = 'tunnel' if '--tunnel' in sys.argv else ('early' if '--early' in sys.argv else 'multiple')
with tempfile.TemporaryDirectory(prefix='openttdai-structure_retry-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'StructureRetryCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "StructureRetryCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'structure_retry-{case}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'STRUCTURE RETRY PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
