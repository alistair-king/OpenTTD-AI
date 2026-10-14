"""Isolated live-game failed-connection memory test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'MemoryCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'6', 'map_y':'6', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nMemoryCheck = \n', config)
driver = r'''
class NoPathBuilder extends RouteBuilder
{
    searches = 0;
    function FindStationSites(town_id, target, preferred_dir = null, source_site = null, central = true, coverage_bias = true)
    {
        this.searches++;
        return [];
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.builder = NoPathBuilder(4);
    local pair = this.PickTownPair();
    if (pair == null) { AILog.Error("MEMORY FAIL: no fixture pair"); return; }
    local a = pair[0];
    local b = pair[1];
    if (this.builder.ConnectTowns(a,b) != null || this.builder.searches != 1 ||
        !this.builder.ConnectionFailed(a,b) || !this.builder.ConnectionFailed(b,a)) {
        AILog.Error("MEMORY FAIL: failed pair not remembered"); return;
    }
    this.builder.ConnectTowns(a,b);
    this.builder.ConnectTowns(b,a);
    if (this.builder.searches != 1) { AILog.Error("MEMORY FAIL: repeated search"); return; }
    if (!this.builder.TownIsFree(a) || !this.builder.TownIsFree(b) ||
        this.builder.ConnectionFailed(a,b+10000)) {
        AILog.Error("MEMORY FAIL: unrelated partner blocked"); return;
    }
    local next = this.PickTownPair();
    if (next != null && this.builder.ConnectionFailed(next[0],next[1])) {
        AILog.Error("MEMORY FAIL: selector chose failed pair"); return;
    }
    this.builder.RememberFailure(a,b,"town","industry");
    if (!this.builder.ConnectionFailed(b,a,"industry","town") ||
        this.builder.ConnectionFailed(a,b,"industry","industry")) {
        AILog.Error("MEMORY FAIL: endpoint kinds mixed"); return;
    }
    this.routes = 3;
    local data = this.Save();
    this.builder = null;
    this.Load(1,data);
    // Saving again before Start initializes the builder must retain loaded memory.
    local pending = this.Save();
    this.builder = NoPathBuilder(4,pending.failed_connections);
    if (this.routes != 3 || !this.builder.ConnectionFailed(b,a) ||
        !this.builder.ConnectionFailed(b,a,"industry","town")) {
        AILog.Error("MEMORY FAIL: save/load"); return;
    }
    this.builder.ConnectTowns(b,a);
    if (this.builder.searches != 0) { AILog.Error("MEMORY FAIL: retry after reload"); return; }
    this.Load(1,{ routes = 2 });
    this.builder = RouteBuilder(4,this.loaded_failures);
    if (this.routes != 2 || this.builder.ConnectionFailed(a,b)) {
        AILog.Error("MEMORY FAIL: legacy save"); return;
    }
    if (TownRouteLimit(999,350) != 1 || TownRouteLimit(1000,350) != 2 ||
        TownRouteLimit(1999,1000) != 1 || TownRouteLimit(2000,1000) != 2 ||
        TownRouteLimit(6000,1000) != 4 || TownRouteLimit(100000,1000) != 4) {
        AILog.Error("MEMORY FAIL: hub capacity thresholds"); return;
    }
    this.builder.MarkConnection(a,b);
    this.builder.MarkConnection(a,b+10000);
    this.builder.MarkConnection(b,a);
    if (this.builder.TownRouteCount(a) != 2 || this.builder.TownRouteCount(b) != 1 ||
        this.builder.TownIsFree(a,2) || !this.builder.TownIsFree(a,3) ||
        !this.builder.ConnectionBuilt(b,a) || this.builder.ConnectionBuilt(a,b+20000)) {
        AILog.Error("MEMORY FAIL: hub counts or duplicate pair"); return;
    }
    local hub_data = this.Save();
    this.builder = null;
    this.Load(1,hub_data);
    local hub_pending = this.Save();
    this.builder = NoPathBuilder(4,hub_pending.failed_connections,hub_pending.connected_pairs);
    this.builder.ConnectTowns(b,a);
    if (this.builder.searches != 0 || this.builder.TownRouteCount(a) != 2 ||
        !this.builder.ConnectionBuilt(b+10000,a)) {
        AILog.Error("MEMORY FAIL: hub persistence"); return;
    }
    AILog.Info("HUB PASS: route limits, multiple destinations, duplicate suppression and saved connection counts.");
    AILog.Info("MEMORY PASS: failed pair skipped both ways, other partners allowed, typed endpoints, save/load and legacy saves.");
    while (true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-memory-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'MemoryCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "MemoryCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'memory-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'MEMORY PASS:' in result.stderr, 'Memory checks did not complete'
        assert 'MEMORY FAIL:' not in result.stderr

        assert 'HUB PASS:' in result.stderr
