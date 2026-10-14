"""Live jump-search comparison, reconstruction and fallback test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'JumpCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nJumpCheck = \n', config)
driver = r'''
::NativeRailFinder <- RailPathFinder;
class FailedJumpFinder extends RailPathFinder {
    function FindPath(iterations) {
        return null;
    }
}

function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("PAIRED FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-32 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,28,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(27,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("PAIRED FAIL: no fixture"); return; }
    AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(27,21));
    local w=AIMap.GetMapSizeX();
    local a=origin+AIMap.GetTileIndex(2,2);
    local b=origin+AIMap.GetTileIndex(24,17);
    local start=[a,a-1];
    local goal=[b,b+1];
    local start2=[a+w,a+w-1];
    local goal2=[b+w,b+w+1];
    local jump_path=null;
    foreach(enabled in [false,true]) {
        local pf=RailPathFinder(); pf._jump=enabled;
        pf.InitializePath([start],[goal],[]);
        local result=false, started=AIController.GetTick();
        for(local batch=0;batch<40 && result==false;batch++) result=pf.FindPath(200);
        if(result==null || result==false) throw "Jump comparison did not connect";
        AILog.Info("JUMP BENCH: enabled="+enabled+", ticks="+(AIController.GetTick()-started)+", states="+pf._expanded+", jump steps="+pf._jump_steps);
        if(enabled) { if(pf._jump_steps==0) throw "No jumps exercised"; jump_path=result; }
    }
    local jump_line={path=jump_path,start=start,goal=goal,line_signals=[]};
    if(!this.builder.BuildPath(jump_line)) throw "Jump route failed actual rail construction";
    local tiles=[goal[1]];
    foreach(tile in this.builder.PathTiles(jump_path)) tiles.append(tile);
    tiles.append(start[1]);
    for(local i=1;i<tiles.len()-1;i++) {
        if(AIMap.DistanceManhattan(tiles[i-1],tiles[i])!=1) throw "Jump was mistaken for a bridge";
        if(!AIRail.RemoveRail(tiles[i-1],tiles[i],tiles[i+1])) throw "Jump test cleanup failed";
    }
    local axis=RailPathFinder(); axis._jump=true;
    axis.InitializePath([start],[[a+20,a+21]],[]);
    local axis_path=axis.FindPath(4000);
    if(axis_path==null || axis_path==false || axis._jump_steps==0) throw "Straight-axis jumps failed";
    ::jump_fixture_count <- 0;
    ::RailPathFinder <- function() {
        jump_fixture_count++;
        return jump_fixture_count==1 ? FailedJumpFinder() : NativeRailFinder();
    };
    this.builder.use_jump_search=true;
    local fallback=this.builder.SearchPath(start,goal,[]);
    if(fallback==null || this.builder.jump_trial) throw "Jump fallback failed";
    ::RailPathFinder <- NativeRailFinder;
    local joint=PairedPathFinder(start,goal,start2,goal2,[]);
    local result=false;
    for(local batch=0;batch<10 && result==false;batch++) result=joint.FindPath(100);
    if(result==null || result==false) { AILog.Error("PAIRED FAIL: joint search "+joint.expanded); return; }
    AILog.Info("Joint states="+joint.expanded);
    local first=result.path, second=result.path2;
    local occupied=this.builder.TrackReservations(first,start,goal);
    local paired=this.builder.TrackReservations(second,start2,goal2);
    local shared=[];
    foreach(tile,mask in paired) if(tile in occupied) {
        if((mask&occupied[tile])!=0 || !ParallelRailPieces(mask|occupied[tile])) { AILog.Error("PAIRED FAIL: conflicting pieces"); return; }
        shared.append(tile);
    }
    if(shared.len()<8) { AILog.Error("PAIRED FAIL: not close enough, shared="+shared.len()); return; }
    local line={path=first,start=start,goal=goal,line_signals=[]};
    local other={path=second,start=start2,goal=goal2};
    if(!this.builder.BuildPath(line) || !this.builder.BuildPath(other)) { AILog.Error("PAIRED FAIL: construction"); return; }
    local signals=[];
    foreach(route in [line,other]) {
        local tiles=[route.goal[1]];
        foreach(tile in this.builder.PathTiles(route.path)) tiles.append(tile);
        tiles.append(route.start[1]);
        if(route==line) tiles.reverse();
        for(local i=1;i<tiles.len()-1;i++) if(tiles[i] in occupied && tiles[i] in paired) {
            if(!this.builder.AddOneWaySignal(line,tiles,i)) { AILog.Error("PAIRED FAIL: signal"); return; }
            signals.append([tiles[i],tiles[i-1],tiles[i+1]]);
        }
    }
    foreach(signal in signals) if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY ||
        AIRail.GetSignalType(signal[0],signal[2])!=AIRail.SIGNALTYPE_NONE) { AILog.Error("PAIRED FAIL: opposing signals"); return; }
    local removed=signals[0];
    AIRail.RemoveSignal(removed[0],removed[1]);
    if(!AIRail.RemoveRail(removed[1],removed[0],removed[2]) || AIRail.GetRailTracks(removed[0])!=paired[removed[0]]) {
        AILog.Error("PAIRED FAIL: independent removal"); return;
    }
    foreach(signal in signals) if(signal[0]==removed[0] && signal[1]!=removed[1] &&
        AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY) { AILog.Error("PAIRED FAIL: removed other signal"); return; }
    AILog.Info("PAIRED PASS: shared tiles="+shared.len()+", separate rail pieces, opposing one-way signals and independent removal.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-jump-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'JumpCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "JumpCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'jump-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PAIRED PASS:' in result.stderr, 'Paired checks did not complete'
        assert 'PAIRED FAIL:' not in result.stderr
