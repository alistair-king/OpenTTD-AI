"""Live reverse-attempt orchestration regression checks."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ReverseCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_growth_rate':'0'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nReverseCheck = \n', config)
driver = r'''
class ReverseBuilder extends RouteBuilder
{
    calls=0; source=-1; target=-1; mode="success";
    function PlanReservedRoute(a,b,guard=null) {
        this.calls++;
        if(this.calls==1) { this.source=a; this.target=b; }
        else if(a!=this.target || b!=this.source || this.ConnectionFailed(a,b) ||
            this.retained_prefixes!=null || this.station_shortlists!=null || this.pending_stations.len()!=0 ||
            guard.count_a!=7 || guard.count_b!=2) throw "Reverse state/guard mismatch";
        this.retained_prefixes={old=true}; this.station_shortlists={old=true};
        this.attempt_failure=this.mode=="cancel" ? "cancelled" : "no_path";
        if(this.calls==2 && this.mode=="success") { this.MarkConnection(a,b); return {station_a=a,station_b=b,depot=0}; }
        return null;
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    local towns=[];
    foreach(town,_ in AITownList()) { towns.append(town); if(towns.len()==2) break; }
    if(towns.len()!=2) throw "No fixture towns";
    local guard={controller=this,count_a=2,count_b=7};
    foreach(mode in ["success","fail","cancel"]) {
        local builder=ReverseBuilder(4); builder.mode=mode;
        local route=builder.ConnectTowns(towns[0],towns[1],guard);
        if(mode=="success") {
            if(route==null || route.station_a!=towns[1] || builder.calls!=2 || builder.ConnectionFailed(towns[0],towns[1])) throw "Reverse success lost";
            if(builder.ConnectTowns(towns[0],towns[1],guard)!=null || builder.calls!=2) throw "Built route retried";
        } else if(mode=="fail") {
            if(route!=null || builder.calls!=2 || !builder.ConnectionFailed(towns[1],towns[0])) throw "Failure not remembered after both attempts";
            builder.ConnectTowns(towns[1],towns[0],guard);
            if(builder.calls!=2) throw "Failed route retried";
        } else if(builder.calls!=1 || builder.ConnectionFailed(towns[0],towns[1])) throw "Cancelled route retried";
    }
    AILog.Info("REVERSE PASS: endpoints and competition guard swapped, state cleared, success retained, both failures remembered, cancellation respected.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-reverse-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ReverseCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ReverseCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'reverse-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'REVERSE PASS:' in result.stderr, 'Reservation checks did not complete'
        assert 'REVERSE FAIL:' not in result.stderr
