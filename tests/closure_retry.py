"""Regression for closure events invalidating an in-flight freight attempt."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ClosureRetryCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'2050', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nClosureRetryCheck = \n', config)
driver = r'''
class ClosureDuringPlanning extends CoalRoutes {
    pair=null;scenario="source";
    function PickPair() {return this.pair;}
    function Connect(source,target) {
        if(scenario=="source") this.OnIndustryClosed(source);
        if(scenario=="target") this.OnIndustryClosed(target);
        if(scenario=="early") return false;
        this.builder.planning_timed_out=true;
        return scenario=="success";
    }
}
function OpenTTDAI::Start() {
    PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local ids=[];foreach(i,_ in AIIndustryList()) {ids.append(i);if(ids.len()==2) break;}
    if(ids.len()!=2) throw "Missing fixture industries";
    foreach(label in ["OIL_","COAL","IORE"]) foreach(scenario in ["source","target","timeout","success","early"]) {
        local route=ClosureDuringPlanning(RouteBuilder(4),null,label);
        route.pair=ids;route.scenario=scenario;
        route.builder.planning_timed_out=true; // stale state from another attempt
        if(!route.TryBuild()) throw "Fixture did not attempt a route";
        local key=ids[0]+":"+ids[1];
        if(scenario=="source" || scenario=="target") {
            if(key in route.attempted || key in route.deferred) throw "Closed pair resurrected";
        } else if(scenario=="timeout") {
            if(key in route.attempted || !(key in route.deferred)) throw "Live timeout not deferred";
        } else if(!(key in route.attempted) || key in route.deferred) throw "Success/early rejection wrongly deferred";
    }
    AILog.Info("CLOSURE RETRY PASS: closure during planning, normal timeout, success and stale timeout checked for oil, coal and ore.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-closure_retry-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ClosureRetryCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ClosureRetryCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'closure_retry-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'CLOSURE RETRY PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
