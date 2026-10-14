"""Isolated live-game temporary pathfinding sign lifecycle test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SignCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSignCheck = \n', config)
driver = r'''
class SignObserver
{
    seen=false; moving=false; too_many=false;
    function Review() {
        local count=0;
        foreach(id,_ in AISignList()) {
            local name=AISign.GetName(id);
            if(name.len()>=12 && name.slice(0,12)=="[VT search] ") {
                count++;
                if(name.find("states")!=null) this.moving=true;
            }
        }
        if(count>=2) this.seen=true;
        if(count>3) this.too_many=true;
    }
}

function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("SIGNS FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local observer=SignObserver();
    this.builder.optimiser=observer;
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-32 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,28,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(27,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("SIGNS FAIL: no fixture"); return; }
    AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(27,21));
    local w=AIMap.GetMapSizeX();
    local a=origin+AIMap.GetTileIndex(2,2);
    local b=origin+AIMap.GetTileIndex(24,17);
    local start=[a,a-1];
    local goal=[b,b+1];
    local first=this.builder.SearchPath(start,goal,[]);
    if(first==null) { AILog.Error("SIGNS FAIL: primary"); return; }
    if(!observer.seen || observer.too_many || AISignList().Count()!=0) { AILog.Error("SIGNS FAIL: sign lifecycle"); return; }
    local occupied=this.builder.TrackReservations(first,start,goal);
    local start2=[a+w,a+w-1];
    local goal2=[b+w,b+w+1];
    local second=this.builder.SearchPath(start2,goal2,[],this.builder.PathTiles(first),40,occupied);
    if(second==null) { AILog.Error("SIGNS FAIL: secondary"); return; }
    local paired=this.builder.TrackReservations(second,start2,goal2);
    local shared=[];
    foreach(tile,mask in paired) if(tile in occupied) {
        if((mask&occupied[tile])!=0 || !ParallelRailPieces(mask|occupied[tile])) { AILog.Error("SIGNS FAIL: conflicting pieces"); return; }
        shared.append(tile);
    }
    if(shared.len()<8) { AILog.Error("SIGNS FAIL: not close enough, shared="+shared.len()); return; }
    local line={path=first,start=start,goal=goal,line_signals=[]};
    local other={path=second,start=start2,goal=goal2};
    if(!this.builder.BuildPath(line) || !this.builder.BuildPath(other)) { AILog.Error("SIGNS FAIL: construction"); return; }
    local signals=[];
    foreach(route in [line,other]) {
        local tiles=[route.goal[1]];
        foreach(tile in this.builder.PathTiles(route.path)) tiles.append(tile);
        tiles.append(route.start[1]);
        if(route==line) tiles.reverse();
        for(local i=1;i<tiles.len()-1;i++) if(tiles[i] in occupied && tiles[i] in paired) {
            if(!this.builder.AddOneWaySignal(line,tiles,i)) { AILog.Error("SIGNS FAIL: signal"); return; }
            signals.append([tiles[i],tiles[i-1],tiles[i+1]]);
        }
    }
    foreach(signal in signals) if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY ||
        AIRail.GetSignalType(signal[0],signal[2])!=AIRail.SIGNALTYPE_NONE) { AILog.Error("SIGNS FAIL: opposing signals"); return; }
    local removed=signals[0];
    AIRail.RemoveSignal(removed[0],removed[1]);
    if(!AIRail.RemoveRail(removed[1],removed[0],removed[2]) || AIRail.GetRailTracks(removed[0])!=paired[removed[0]]) {
        AILog.Error("SIGNS FAIL: independent removal"); return;
    }
    foreach(signal in signals) if(signal[0]==removed[0] && signal[1]!=removed[1] &&
        AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY) { AILog.Error("SIGNS FAIL: removed other signal"); return; }
    if(!observer.moving || observer.too_many || AISignList().Count()!=0) { AILog.Error("SIGNS FAIL: moving marker cleanup"); return; }
    // A bounded unsuccessful search must also clean its markers.
    if(this.builder.SearchPath(start,goal,[],null,0)!=null || AISignList().Count()!=0) { AILog.Error("SIGNS FAIL: failure cleanup"); return; }
    local keep=AISign.BuildSign(a,"Keep my sign");
    local stale=this.builder.SearchSign(b,"Interrupted search");
    this.builder.ClearSearchSigns();
    if(!AISign.IsValidSign(keep) || AISign.IsValidSign(stale)) { AILog.Error("SIGNS FAIL: unrelated sign cleanup"); return; }
    AISign.RemoveSign(keep);
    AILog.Info("SIGNS PASS: shared tiles="+shared.len()+", separate rail pieces, opposing one-way signals and independent removal.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-signs-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SignCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SignCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'signs-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'SIGNS PASS:' in result.stderr, 'Diagonal checks did not complete'
        assert 'SIGNS FAIL:' not in result.stderr
