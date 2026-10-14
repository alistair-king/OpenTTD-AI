"""Compare direct-goal and station-approach A* on identical terrain and blocked approaches."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ApproachCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'town_growth_rate':'0', 'allow_town_roads':'false', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nApproachCheck = \n', config)
driver = r'''

class DirectGoalFinder extends RailPathFinder {
    function _GoalEstimate(tile,from) {return AIMap.DistanceManhattan(tile,this._goal)*this.cost.tile;}
}
function OpenTTDAI::Start()
{
    this.Sleep(1);this.SetCompanyName();
    if(!PickRailType()) throw "No rails";
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-32 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(AITile.GetMinHeight(tile)<1 || !AreaIsBuildable(tile,28,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(27,21))) origin=tile;
    }
    if(origin==null) throw "No comparison fixture";
    if(!AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(27,21))) throw "Levelling failed";
    local w=AIMap.GetMapSizeX(),a=origin+4+4*w,b=origin+20+14*w;
    local bounds=[];
    for(local x=0;x<28;x++) {bounds.append(origin+x);bounds.append(origin+x+21*w);}
    for(local y=0;y<22;y++) {bounds.append(origin+y*w);bounds.append(origin+27+y*w);}
    local total_old=0,total_new=0;
    foreach(scenario in [0,1,2,3,4,5]) {
        local start=scenario==3 ? [b,b+1] : [a,a-1];
        local goal=scenario==3 ? [a,a+1] : [b,scenario==0?b+1:(scenario==2?b-w:b-1)];
        local reserved=clone bounds;
        if(scenario==4) for(local y=8;y<=17;y++) reserved.append(origin+18+y*w);
        if(scenario==5) reserved.append(goal[0]+3*(goal[0]-goal[1]));
        local lengths=[],counts=[],results=[];
        foreach(pf in [DirectGoalFinder(),RailPathFinder()]) {
            pf.InitializePath([start],[goal],reserved);
            if(pf._GoalEstimate(goal[0],goal[0]+goal[0]-goal[1])!=0) throw "Goal estimate nonzero";
            local t=AIController.GetTick(),found=false;
            for(local batch=0;batch<200 && found==false;batch++) found=pf.FindPath(200);
            if(found==false) throw "Search exceeded test budget";
            local length=0;
            for(local path=found;path!=null;path=path.GetParent()) {
                if(path.GetStructure()!=null) throw "Flat fixture unexpectedly used structure";
                length++;
            }
            lengths.append(length);counts.append(pf._expanded);results.append(found);
            AILog.Info("APPROACH BENCH scenario="+scenario+" expanded="+pf._expanded+" ticks="+(AIController.GetTick()-t)+" tiles="+length);
        }
        if(lengths[0]!=lengths[1]) throw "Route success or shortest length changed";
        if(scenario==5 && lengths[1]!=0) throw "Blocked throat was bypassed";
        if(scenario!=5 && lengths[1]==0) throw "Reachable route failed";
        total_old+=counts[0];total_new+=counts[1];

    }
    if(total_new>=total_old) throw "No total expansion improvement";
    AILog.Info("APPROACH PASS: identical success and shortest lengths, expanded="+total_old+" -> "+total_new);
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-approach-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ApproachCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ApproachCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'approach-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'APPROACH PASS:' in result.stderr, 'Approach checks did not complete'
        assert 'APPROACH FAIL:' not in result.stderr
