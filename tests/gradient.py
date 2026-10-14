"""Live comparison of route selection with and without a height-change penalty."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'GradientCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nGradientCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("GRADIENT FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-52 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,48,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(47,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("GRADIENT FAIL: no fixture"); return; }
    AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(47,21));
    local w=AIMap.GetMapSizeX();
    local curve=RailPathFinder();
    if(curve.cost.turn!=0 || curve.cost.close_turn!=0) throw "User bend penalties still enabled";
    local t=origin+AIMap.GetTileIndex(10,5);
    curve.InitializePath([[origin+2,origin+1]],[[origin+40,origin+41]],[]);
    local n={tile=t,from=t-1,hx=1,hy=1,straight=0,previous_node=null,g=0,h=0};
    curve._forbid_right_angles=true;
    if(curve._CanConnect(n,t-w)) throw "Game right-angle prohibition ignored";
    curve._forbid_right_angles=false;
    if(!curve._CanConnect(n,t-w)) throw "Extra AI right-angle restriction retained";

    local a=origin+AIMap.GetTileIndex(2,10);
    local b=origin+AIMap.GetTileIndex(44,10);
    // Twelve low ridges offer a straight but undulating route, or a flatter detour.
    foreach(x in [6,9,12,15,18,21,24,27,30,33,36,39]) for(local y=10;y<=11;y++) {
        local corner=origin+AIMap.GetTileIndex(x,y);
        if(!AITile.RaiseTile(corner,AITile.SLOPE_N)) throw "Fixture raise failed";
    }
    local totals=[];
    foreach(weight in [0,55]) {
        local pf=RailPathFinder(); pf.cost.height_change=weight;
        pf.InitializePath([[a,a-1]],[[b,b+1]],[]);
        local path=false;
        for(local batch=0;batch<80 && path==false;batch++) path=pf.FindPath(200);
        if(path==null || path==false) throw "Gradient route not found";
        local tiles=this.builder.PathTiles(path);
        local height_changes=0;
        for(local i=1;i<tiles.len();i++) height_changes+=Abs(AITile.GetMaxHeight(tiles[i])-AITile.GetMaxHeight(tiles[i-1]));
        totals.append(height_changes);
        AILog.Info("GRADIENT RESULT: weight="+weight+", height changes="+height_changes+", tiles="+tiles.len());
        if(weight==55 && !this.builder.BuildPath({path=path,start=[a,a-1],goal=[b,b+1]})) throw "Flatter route unbuildable";
    }
    if(totals[1]>=totals[0]) throw "Height penalty did not prefer flatter route";
    local pf=RailPathFinder();
    local low=origin+AIMap.GetTileIndex(4,10), high=origin+AIMap.GetTileIndex(5,10);
    if(pf.HeightCost(low,high)!=55 || pf.HeightCost(high,low)!=55) throw "Asymmetric gradient cost";
    AILog.Info("GRADIENT PASS: fewer height changes preferred, uphill/downhill weighted equally, selected track built.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-gradient-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'GradientCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "GradientCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'gradient-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'GRADIENT PASS:' in result.stderr, 'Gradient checks did not complete'
        assert 'GRADIENT FAIL:' not in result.stderr
