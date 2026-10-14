"""Isolated construction rotation and save/load regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'RailPolicyCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'2050', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nRailPolicyCheck = \n', config)
driver = r'''
class RailBudgetProbe extends RouteBuilder {
    function PlanningBudget() {return 8000;}
}
function OpenTTDAI::Start() {
    this.Sleep(1);
    local specs=[[0,40,125,85],[1,50,150,100],[2,60,225,150],[3,75,300,200]];
    local b=RailBudgetProbe(4);
    foreach(spec in specs) {
        local type=spec[0],lo=spec[1],hi=spec[2],percent=spec[3];
        if(!AIRail.IsRailTypeAvailable(type)) throw "Test rail type unavailable";
        AIRail.SetCurrentRailType(type);
        if(IndustryDistanceAllowed(lo-1) || !IndustryDistanceAllowed(lo) || !IndustryDistanceAllowed(hi) || IndustryDistanceAllowed(hi+1)) throw "Industry range boundary";
        local from=AIMap.GetTileIndex(5,5),to=AIMap.GetTileIndex(105,105);
        if(IndustryEndpointsAllowed(from,to)!=(type>=2)) throw "Coordinate distance not used";
        if(!RouteDistanceAllowed(50) || !RouteDistanceAllowed(150) || RouteDistanceAllowed(151) || RouteDistanceAllowed(49)) throw "Passenger ranges changed";
        foreach(count in [0,1,2]) {
            b.planning_history["rail-test"] <- {count=count,after=0};
            b.BeginPlanning("rail-test",false,true);
            local baseline=count==0?1200:count==1?2400:8000;
            local ticks=b.planning_deadline-AIController.GetTick();
            if(ticks>baseline*percent/100 || ticks<baseline*percent/100-5) throw "Project budget not scaled";
            local batches=count==0?8:count==1?16:40;
            if(b.SearchBatchBudget(40)!=(batches*percent+99)/100) throw "Search still capped at 40";
            local attempts=count==0?4:count==1?8:36;
            if(b.station_attempt_limit!=(attempts*percent+99)/100) throw "Station attempts not scaled";
        }
        b.BeginPlanning("onward-"+type,true,true);
        if(b.planning_deadline-AIController.GetTick()<12000*percent/100-5 || b.SearchBatchBudget(40)!=(40*percent+99)/100) throw "Onward scale";
        b.BeginPlanning("passenger");
        if(b.planning_percent!=100 || b.SearchBatchBudget(40)!=8) throw "Freight scale leaked to passenger";
        b.BeginPlanning("cleanup",false,true);b.FinishConnection("cleanup",true);
        if(b.planning_percent!=100 || b.search_batches_limit!=40) throw "Budget scale not reset";
        AILog.Info("RAIL POLICY checked "+AIRail.GetName(type)+": "+lo+"-"+hi+", budget="+percent+"%");
    }
    if(IndustryRailPolicy(25).budget_percent!=100) throw "Custom rail baseline";
    AILog.Info("RAIL POLICY PASS: boundaries, coordinates, new/retry/onward budgets, search caps and passenger isolation.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-rotation-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'RailPolicyCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "RailPolicyCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'rail-policy-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RAIL POLICY PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
