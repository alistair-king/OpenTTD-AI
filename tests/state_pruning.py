"""Compare legacy and reduced A* states on identical terrain, then verify shared diagonal construction."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'StateCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'town_growth_rate':'0', 'allow_town_roads':'false', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nStateCheck = \n', config)
driver = r'''
class OriginalStateFinder extends RailPathFinder {
    function _Key(node) {
        return node.tile + ":" + node.from + ":" + node.hx + ":" + node.hy + ":" + node.straight + ((node.previous_node != null && AIMap.DistanceManhattan(node.previous_node.tile, node.tile) > 1) ? ("structure" in node ? ":"+node.structure : ":bridge") : "");
    }
}

function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("STATE FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-32 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(AITile.GetMinHeight(tile)<1 || !AreaIsBuildable(tile,28,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(27,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("STATE FAIL: no fixture"); return; }
    AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(27,21));
    local w=AIMap.GetMapSizeX();
    local a=origin+AIMap.GetTileIndex(2,2);
    local b=origin+AIMap.GetTileIndex(24,17);
    local start=[a,a-1];
    local goal=[b,b+1];
    local check=RailPathFinder();
    local node={tile=a,from=a-1,hx=1,hy=0,straight=0,previous_node=null};
    local other=clone node;other.straight=2;
    if(check._Key(node)!=check._Key(other)) throw "Redundant straight-run state retained";
    check.cost.close_turn=1;
    if(check._Key(node)==check._Key(other)) throw "Cost-sensitive states merged";
    check.cost.close_turn=0;check._jump=true;
    if(check._Key(node)==check._Key(other)) throw "Jump-sensitive states merged";
    check._jump=false;other=clone node;other.hx=0;other.hy=1;
    if(check._Key(node)==check._Key(other)) throw "Arrival headings merged";
    other=clone node;other.previous_node={tile=a-4};other.structure <- "bridge";
    if(check._Key(node)==check._Key(other)) throw "Bridge arrival merged with ordinary rail";
    local tunnel=clone other;tunnel.structure="tunnel";
    if(check._Key(tunnel)==check._Key(other)) throw "Structure kinds merged";
    foreach(blocked in [false,true]) {
        local reserved=[];
        if(blocked) for(local y=0;y<15;y++) reserved.append(origin+12+y*w);
        local lengths=[],counts=[];
        foreach(pf in [RailPathFinder(),OriginalStateFinder()]) {
            pf.InitializePath([start],[goal],reserved);
            local found=false,t=AIController.GetTick();
            for(local batch=0;batch<200 && found==false;batch++) found=pf.FindPath(200);
            if(found==false || found==null) throw "Comparison search failed states="+pf._expanded+" near="+pf._nearest_goal+" start="+AITile.IsBuildable(a)+" goal="+AITile.IsBuildable(b)+" bank="+AICompany.GetBankBalance(AICompany.COMPANY_SELF)+" error="+AIError.GetLastErrorString();
            local length=0;
            for(local path=found;path!=null;path=path.GetParent()) length++;
            lengths.append(length);counts.append(pf._expanded);
            AILog.Info("STATE BENCH blocked="+blocked+" expanded="+pf._expanded+" ticks="+(AIController.GetTick()-t)+" tiles="+length);
        }
        if(lengths[0]!=lengths[1]) throw "Shortest route length changed";
        if(counts[0]>counts[1]) throw "Fixture expanded more states";
    }
    local first=this.builder.SearchPath(start,goal,[]);
    if(first==null) { AILog.Error("STATE FAIL: primary"); return; }
    local occupied=this.builder.TrackReservations(first,start,goal);
    local start2=[a+w,a+w-1];
    local goal2=[b+w,b+w+1];
    local second=this.builder.SearchPath(start2,goal2,[],this.builder.PathTiles(first),40,occupied);
    if(second==null) { AILog.Error("STATE FAIL: secondary"); return; }
    local paired=this.builder.TrackReservations(second,start2,goal2);
    local shared=[];
    foreach(tile,mask in paired) if(tile in occupied) {
        if((mask&occupied[tile])!=0 || !ParallelRailPieces(mask|occupied[tile])) { AILog.Error("STATE FAIL: conflicting pieces"); return; }
        shared.append(tile);
    }
    if(shared.len()<1) { AILog.Error("STATE FAIL: not close enough, shared="+shared.len()); return; }
    local line={path=first,start=start,goal=goal,line_signals=[]};
    local other={path=second,start=start2,goal=goal2};
    if(!this.builder.BuildPath(line) || !this.builder.BuildPath(other)) { AILog.Error("STATE FAIL: construction"); return; }
    local signals=[];
    foreach(route in [line,other]) {
        local tiles=[route.goal[1]];
        foreach(tile in this.builder.PathTiles(route.path)) tiles.append(tile);
        tiles.append(route.start[1]);
        if(route==line) tiles.reverse();
        for(local i=1;i<tiles.len()-1;i++) if(tiles[i] in occupied && tiles[i] in paired) {
            if(!this.builder.AddOneWaySignal(line,tiles,i)) { AILog.Error("STATE FAIL: signal"); return; }
            signals.append([tiles[i],tiles[i-1],tiles[i+1]]);
        }
    }
    foreach(signal in signals) if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY ||
        AIRail.GetSignalType(signal[0],signal[2])!=AIRail.SIGNALTYPE_NONE) { AILog.Error("STATE FAIL: opposing signals"); return; }
    local removed=signals[0];
    AIRail.RemoveSignal(removed[0],removed[1]);
    if(!AIRail.RemoveRail(removed[1],removed[0],removed[2]) || AIRail.GetRailTracks(removed[0])!=paired[removed[0]]) {
        AILog.Error("STATE FAIL: independent removal"); return;
    }
    foreach(signal in signals) if(signal[0]==removed[0] && signal[1]!=removed[1] &&
        AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY) { AILog.Error("STATE FAIL: removed other signal"); return; }
    AILog.Info("STATE PASS: shared tiles="+shared.len()+", separate rail pieces, opposing one-way signals and independent removal.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-state-pruning-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'StateCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "StateCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'state-pruning-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'STATE PASS:' in result.stderr, 'State pruning checks did not complete'
        assert 'STATE FAIL:' not in result.stderr
