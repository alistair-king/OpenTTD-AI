"""Live A* straight-diagonal regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'KinkCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nKinkCheck = \n', config)
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
    local w=AIMap.GetMapSizeX(),base=origin+AIMap.GetTileIndex(8,8);
    // An otherwise straight line steps sideways by one tile and back.
    local tiles=[];
    for(local k=0;k<=6;k++) tiles.append(base+k);
    tiles.append(base+6+w);tiles.append(base+7+w);tiles.append(base+8+w);
    for(local k=8;k<=16;k++) tiles.append(base+k);
    local path=null;foreach(t in tiles) path=VibePath(t,path);
    local pf=RailPathFinder();pf.InitializePath([[base,base-1]],[[base+16,base+17]]);
    local result=pf.StraightenPath(path),clean=RouteBuilder(4).PathTiles(result);
    if(clean.len()!=17) throw "Kink not removed";
    foreach(t in clean) if(AIMap.GetTileY(t)!=AIMap.GetTileY(base)) throw "Direct alignment not used";
    local diagonal=[base],t=base;
    for(local k=0;k<10;k++) {
        if(k==4) {foreach(step in [1,1,w,w]) {t+=step;diagonal.append(t);} k++;}
        else foreach(step in [1,w]) {t+=step;diagonal.append(t);}
    }
    local bent=null;foreach(tile in diagonal) bent=VibePath(tile,bent);
    pf.InitializePath([[base,base-1]],[[t,t+w]]);
    local straight=pf.StraightenPath(bent);
    if(straight==bent) throw "Diagonal kink not improved";
    local builder=RouteBuilder(4);
    if(builder.PathQuality(straight,[base,base-1],[t,t+w]).score>=builder.PathQuality(bent,[base,base-1],[t,t+w]).score)
        throw "Diagonal quality did not improve";
    // Reservations and the other running track must keep necessary detours.
    pf.InitializePath([[base,base-1]],[[base+16,base+17]],[base+7]);
    local blocked=RouteBuilder(4).PathTiles(pf.StraightenPath(path));
    foreach(t in blocked) if(t==base+7) throw "Shortcut crossed reserved tile";
    local occupied={};occupied[base+7] <- RailPiece(base+6,base+7,base+8);
    pf.InitializePath([[base,base-1]],[[base+16,base+17]],[],null,occupied);
    blocked=RouteBuilder(4).PathTiles(pf.StraightenPath(path));
    foreach(t in blocked) if(t==base+7) throw "Shortcut merged running lines";
    // Leave the path around a structure unchanged.
    local structure=null;foreach(index,t in tiles) structure=VibePath(t,structure,index==8?"bridge":null);
    pf.InitializePath([[base,base-1]],[[base+16,base+17]]);
    if(pf.StraightenPath(structure)!=structure) throw "Structure rewritten";
    AILog.Info("KINK PASS: direct replacement, reserved tiles, occupied track and structure protection.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-smoothing-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'KinkCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "KinkCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'kink-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'KINK PASS:' in result.stderr, 'Straightness check did not complete'
        assert 'STRAIGHTNESS FAIL:' not in result.stderr
