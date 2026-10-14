"""Isolated live-game station reservation and rollback test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ReservationCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_growth_rate':'0'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nReservationCheck = \n', config)
driver = r'''
class FailingReservedBuilder extends RouteBuilder
{
    first=null; second=null; first_town=-1; checked=false; fail_second=false; builds=0;
    function FindStationSites(town,target,dir=null,source=null,central=true,coverage_bias=true) {
        return town==this.first_town ? [this.first] : [this.second];
    }
    function FindPathBetween(a,b,batches=40) {
        this.checked=this.VerifyStation(a) && this.VerifyStation(b) && this.pending_stations.len()==2;
        return null;
    }
    function BuildStation(site) {
        this.builds++;
        if(this.fail_second && this.builds==2) return false;
        return RouteBuilder(this.platform_length).BuildStation(site);
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) { AILog.Error("RESERVATION FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local normal=RouteBuilder(4);
    local a=null,b=null,ta=-1,tb=-1;
    foreach(town,_ in AITownList()) {
        local sites=normal.FindStationSites(town,AITown.GetLocation(town),null,a);
        if(sites.len()==0) continue;
        if(a==null) { a=sites[0]; ta=town; }
        else { b=sites[0]; tb=town; break; }
    }
    if(b==null) { AILog.Error("RESERVATION FAIL: fixture"); return; }
    local builder=FailingReservedBuilder(4);
    builder.first=a; builder.second=b; builder.first_town=ta;
    this.builder=builder;
    if(builder.ConnectTowns(ta,tb)!=null || !builder.checked || builder.pending_stations.len()!=0 ||
        AIStationList(AIStation.STATION_TRAIN).Count()!=0) { AILog.Error("RESERVATION FAIL: failed path cleanup"); return; }
    builder.fail_second=true; builder.builds=0;
    if(builder.ReserveStations(a,b) || !builder.ReleasePendingStations() || builder.pending_stations.len()!=0 || AIStationList(AIStation.STATION_TRAIN).Count()!=0) {
        AILog.Error("RESERVATION FAIL: partial purchase cleanup"); return;
    }
    builder.fail_second=false;
    if(!builder.ReserveStations(a,b)) { AILog.Error("RESERVATION FAIL: saved fixture"); return; }
    local saved=this.Save();
    this.Load(1,saved);
    this.builder=RouteBuilder(4);
    this.builder.pending_stations=this.loaded_pending_stations;
    if(!this.builder.ReleasePendingStations() || AIStationList(AIStation.STATION_TRAIN).Count()!=0) {
        AILog.Error("RESERVATION FAIL: save/load cleanup"); return;
    }
    AILog.Info("RESERVATION PASS: stations precede path search, failed search and partial build cleaned, saved reservations removed.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-reservation-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ReservationCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ReservationCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'reservation-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RESERVATION PASS:' in result.stderr, 'Reservation checks did not complete'
        assert 'RESERVATION FAIL:' not in result.stderr
