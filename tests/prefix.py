"""Isolated live-game retained route prefix test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'PrefixCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nPrefixCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("PREFIX FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-32 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(AITile.GetMinHeight(tile)<1 || !AreaIsBuildable(tile,28,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(27,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("PREFIX FAIL: no fixture"); return; }
    AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(27,21));
    local w=AIMap.GetMapSizeX();
    local a=origin+AIMap.GetTileIndex(2,2);
    local b=origin+AIMap.GetTileIndex(24,17);
    local start=[a,a-1];
    local goal=[b,b+1];
    // Block the old goal's mandatory approach, but allow exploration near it.
    local blocked=[b-1];
    local failed=this.builder.SearchPath(start,goal,blocked);
    local key=start[0]+":"+start[1];
    if(failed!=null || this.builder.search_failure!="target" || !(key in this.builder.retained_prefixes)) {
        AILog.Error("PREFIX FAIL: near-target failure did not retain progress"); return;
    }
    local prefix=clone this.builder.retained_prefixes[key];
    if(prefix.len()<8) { AILog.Error("PREFIX FAIL: prefix too short"); return; }
    this.builder.reuse_prefixes=true;
    local new_goal=[b+2*w,b+2*w+1];
    local path=this.builder.SearchPath(start,new_goal,blocked);
    if(path==null) { AILog.Error("PREFIX FAIL: new target unreachable"); return; }
    local tiles=this.builder.PathTiles(path); tiles.reverse();
    for(local i=0;i<prefix.len();i++) if(tiles[i]!=prefix[i]) { AILog.Error("PREFIX FAIL: first half changed"); return; }
    local quality=this.builder.PathQuality(path,start,new_goal);
    if(quality.bends==999 || !this.builder.BuildPath({path=path,start=start,goal=new_goal})) {
        AILog.Error("PREFIX FAIL: retained join not buildable"); return;
    }
    AILog.Info("PREFIX PASS: near-target failure retained "+prefix.len()+" tiles; moved target, unchanged origin and first half, complete path built.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-prefix-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'PrefixCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "PrefixCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'prefix-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PREFIX PASS:' in result.stderr, 'Prefix checks did not complete'
        assert 'PREFIX FAIL:' not in result.stderr
