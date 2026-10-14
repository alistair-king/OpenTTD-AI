"""Isolated live-game endpoint relocation and retention test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'RelocationCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_growth_rate':'0'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nRelocationCheck = \n', config)
driver = r'''
class RelocationBuilder extends RouteBuilder
{
    origins=null; targets=null; origin_town=-1; blame="start";
    calls=0; builds=0; preserved=false; origin_moved=false; old_a=null; old_b=null; old_id=-1; widened=false;
    function FindStationSites(town,target,dir=null,source=null,central=true,coverage_bias=true) {
        return town==this.origin_town ? this.origins : this.targets;
    }
    function BuildStation(site) {
        this.builds++;
        return RouteBuilder(4).BuildStation(site);
    }
    function FindPathBetween(a,b,batches=40) {
        this.calls++;
        if(this.calls==1) {
            this.old_a=a.tile; this.old_b=b.tile;
            this.old_id=AIStation.GetStationID(this.blame=="start" ? b.tile : a.tile);
        }
        if(this.calls==2) {
            if(this.blame=="start") this.preserved=b.tile==this.old_b && a.tile!=this.old_a && AIStation.GetStationID(b.tile)==this.old_id && this.builds==3;
            else if(this.blame=="target") this.preserved=a.tile==this.old_a && b.tile!=this.old_b && AIStation.GetStationID(a.tile)==this.old_id && this.builds==3;
            else this.widened=a.tile==this.old_a && b.tile==this.old_b && batches==80 && this.builds==2;
        }
        if(this.calls>1 && this.blame=="target" && a.tile!=this.old_a) this.origin_moved=true;
        this.route_failure=this.blame;
        return null;
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) { AILog.Error("RELOCATION FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local normal=RouteBuilder(4);
    local aa=null,bb=null,ta=-1,tb=-1;
    foreach(town,_ in AITownList()) {
        local sites=normal.FindStationSites(town,AITown.GetLocation(town),null,aa==null ? null : aa[0]);
        if(sites.len()<2) continue;
        if(aa==null) { aa=[sites[0],sites[1]]; ta=town; }
        else { bb=[sites[0],sites[1]]; tb=town; break; }
    }
    if(bb==null) { AILog.Error("RELOCATION FAIL: fixture"); return; }
    foreach(blame in ["start","target","middle"]) {
        local builder=RelocationBuilder(4);
        builder.origins=aa; builder.targets=bb; builder.origin_town=ta; builder.blame=blame;
        this.builder=builder;
        // Test relocation within one direction; reverse.py covers the outer retry.
        builder.PlanReservedRoute(ta,tb);
        builder.ReleasePendingStations();
        if(builder.calls<2 || builder.origin_moved || (blame=="middle" ? !builder.widened : !builder.preserved) ||
            builder.pending_stations.len()!=0 || AIStationList(AIStation.STATION_TRAIN).Count()!=0) {
            AILog.Error("RELOCATION FAIL: "+blame+", calls="+builder.calls+", builds="+builder.builds); return;
        }
    }
    AILog.Info("RELOCATION PASS: origin-only and target-only relocation preserve the other station; middle retries widen without rebuilding; final cleanup complete.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-relocation-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'RelocationCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "RelocationCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'relocation-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RELOCATION PASS:' in result.stderr, 'Relocation checks did not complete'
        assert 'RELOCATION FAIL:' not in result.stderr
