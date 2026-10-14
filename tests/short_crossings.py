"""Isolated live-game shared bridge track test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ShortCrossingCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nShortCrossingCheck = \n', config)
driver = r'''function OpenTTDAI::Start() {
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

    for(local x=2;x<=32;x++) foreach(y in [8,9]) {
        local tile=origin+AIMap.GetTileIndex(x,y);
        if(!AIRail.BuildRail(tile-1,tile,tile+1)) throw "Running-track fixture failed";
    }
    foreach(e in [w,-w]) {
        local j={tile=origin+AIMap.GetTileIndex(8,8),side=w,forward=1};
        local plan=PlanSeparatedJunction(j,1,e);
        if(plan==null || AIMap.DistanceManhattan(plan.ramp,plan.end)!=3) throw "Junction crossing is not minimal";
        local journal={pieces=[],structures=[],removed=[],signals=[]};
        this.builder.build_journal=journal;
        foreach(tiles in plan.lanes) {
            local path=null;
            foreach(tile in tiles) path=VibePath(tile,path,tile==plan.end?plan.kind:null);
            local found={path=path,start=[tiles[0],tiles[0]-1],goal=[tiles.top(),tiles.top()+e]};
            if(!this.builder.BuildPath(found)) throw "Short junction construction failed";
        }
        this.builder.build_journal=null;
        if(!RestoreSingleUpgrade({upgrade=journal})) throw "Short junction cleanup failed";
        for(local x=2;x<=32;x++) foreach(y in [8,9]) {
            local tile=origin+AIMap.GetTileIndex(x,y);
            if(!AIRail.AreTilesConnected(tile-1,tile,tile+1)) throw "Junction damaged original tracks";
        }
    }
    // A stepped hill offers an outer long tunnel and a nearer, shorter one.
    for(local x=2;x<=32;x++) foreach(y in [8,9]) {
        local tile=origin+AIMap.GetTileIndex(x,y);
        if(!AIRail.RemoveRail(tile-1,tile,tile+1)) throw "Running-track cleanup failed";
    }
    local terrain=PairedTerrain(2,512,100000);
    terrain.max_change=2;terrain.max_corners=512;
    local h=AITile.GetCornerHeight(origin,AITile.CORNER_N);
    for(local x=10;x<=24;x++) for(local y=3;y<=18;y++)
        if(!terrain.SetHeight(origin+AIMap.GetTileIndex(x,y),h+1)) throw "Outer hill fixture failed";
    for(local x=14;x<=20;x++) for(local y=3;y<=18;y++)
        if(!terrain.SetHeight(origin+AIMap.GetTileIndex(x,y),h+2)) throw "Inner hill fixture failed";
    if(!terrain.MoveTo(terrain.targets)) throw "Hill construction failed";
    local outer=origin+AIMap.GetTileIndex(9,12),inner=origin+AIMap.GetTileIndex(13,12);
    local end=AITunnel.GetOtherTunnelEnd(outer),short_end=AITunnel.GetOtherTunnelEnd(inner);
    if(RailTunnelCost(outer,end)<0 || RailTunnelCost(inner,short_end)<0) throw "Tunnel fixture invalid";
    local pf=RailPathFinder(),start=origin+AIMap.GetTileIndex(4,12),goal=origin+AIMap.GetTileIndex(30,12);
    pf.InitializePath([[start,start-1]],[[goal,goal+1]],[]);
    if(!pf._ShorterTunnelAhead(outer,end,1)) throw "Missed shorter tunnel entrance";
    if(pf._ShorterTunnelAhead(inner,short_end,1)) throw "Rejected shortest tunnel";
    local queued=pf._open.Count();
    pf._ExpandTunnel({tile=outer,from=outer-1,hx=1,hy=0,g=0,previous_node=null});
    if(pf._open.Count()!=queued) throw "Planner offered unnecessarily long tunnel";
    pf._ExpandTunnel({tile=inner,from=inner-1,hx=1,hy=0,g=0,previous_node=null});
    if(pf._open.Count()!=queued+1) throw "Planner omitted shortest viable tunnel";
    pf._reserved[inner] <- true;
    if(pf._ShorterTunnelAhead(outer,end,1)) throw "Shorter entrance bypassed reservation";
    AILog.Info("SHORT CROSSING PASS: shortest junctions, construction, rollback and nearer tunnel portal selection.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-short_crossings-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ShortCrossingCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ShortCrossingCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'short_crossings-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'SHORT CROSSING PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
