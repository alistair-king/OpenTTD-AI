"""Live A* straight-diagonal regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'StraightnessCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nStraightnessCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1); this.SetCompanyName();
    if(!PickRailType()) throw "No rail type";
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-30 && origin==null;y++) {
        local t=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(t,40,28) || AITile.GetMaxHeight(t)==0) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(t,t+AIMap.GetTileIndex(39,27))) origin=t;
    }
    if(origin==null || !AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(39,27))) throw "No flat fixture";
    local start=[origin+AIMap.GetTileIndex(4,4),origin+AIMap.GetTileIndex(3,4)];
    local goal=[origin+AIMap.GetTileIndex(34,20),origin+AIMap.GetTileIndex(35,20)];
    local scores=[];
    foreach(turn in [0,50]) {
        local pf=RailPathFinder(); pf.cost.turn=turn;
        pf.InitializePath([start],[goal]);
        local path=false;
        for(local batch=0;batch<80 && typeof path=="bool";batch++) path=pf.FindPath(200);
        if(path==null || typeof path=="bool") throw "Search failed";
        local quality=RouteBuilder(4).PathQuality(path,start,goal);
        scores.append(quality.bends);
        AILog.Info("STRAIGHTNESS: turn="+turn+", bends="+quality.bends+", states="+pf._expanded);
        if(turn>0 && quality.bends>4) throw "Unnecessary bends on flat diagonal";
    }
    if(scores[1]>=scores[0]) throw "Straightness did not improve";
    AILog.Info("STRAIGHTNESS PASS: straight diagonal preferred over repeated bends.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-smoothing-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'StraightnessCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "StraightnessCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'straightness-{"water" if "--water" in sys.argv else "rail"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'STRAIGHTNESS PASS:' in result.stderr, 'Straightness check did not complete'
        assert 'STRAIGHTNESS FAIL:' not in result.stderr
