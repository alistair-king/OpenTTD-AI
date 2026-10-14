"""Isolated two-train traffic test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'StartupCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nStartupCheck = \n', config)
driver = r'''
::startup_budget <- 2400;
class BudgetBuilder extends RouteBuilder { function PlanningBudget() { return startup_budget; } }
class TimedOutBuilder extends RouteBuilder {
    function PlanReservedRoute(a,b,guard=null) {
        this.planning_deadline=AIController.GetTick();
        this.PlanningExpired();
        return null;
    }
}
class TimedOutCoal extends CoalRoutes {
    function Connect(source,target) { this.builder.planning_timed_out=startup_budget!=0; return false; }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) throw "No rails";
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local budgets=RouteBuilder(4);
    if(budgets.PlanningBudget()!=2400) throw "Incorrect first-route budget";
    budgets.startup_failures=4;
    if(budgets.PlanningBudget()!=4800) throw "Difficult-map allowance did not grow";
    budgets.startup_failures=100;
    if(budgets.PlanningBudget()!=8000) throw "Difficult-map allowance not capped";
    local towns=[]; foreach(town,_ in AITownList()) towns.append(town);
    if(towns.len()<2) throw "Not enough towns";
    local builder=TimedOutBuilder(4);
    if(builder.ConnectTowns(towns[0],towns[1])!=null || !builder.planning_timed_out ||
        builder.planning_deadline!=0 || builder.failed_connections.len()!=0 ||
        builder.pending_stations.len()!=0 || builder.retry_after[towns[0]]<=AIController.GetTick())
        throw "Timed-out town route not safely deferred";
    local coal=TimedOutCoal(BudgetBuilder(4));
    local pair=coal.PickPair(); if(pair==null) throw "No coal fixture";
    local key=pair[0]+":"+pair[1];
    if(!coal.TryBuild() || !(key in coal.deferred) || key in coal.attempted) throw "Coal timeout marked permanent";
    coal.phase=false;
    local restored=TimedOutCoal(coal.builder,coal.Save());
    if(!(key in restored.deferred) || restored.TryBuild()) throw "Coal deferral lost or retried too early";
    startup_budget=0;
    restored.retry_after=0;
    if(!restored.TryBuild() || !restored.phase || restored.deferred.len()!=0) throw "Established coal retry failed";
    AILog.Info("PRODUCTION PASS: startup deadline, town cooldown, cleanup, saved coal deferral and established retry.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-startup-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'StartupCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "StartupCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'startup-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PRODUCTION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
