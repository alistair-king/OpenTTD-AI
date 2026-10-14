"""Isolated live-game service optimisation test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'OptimiserCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'6', 'map_y':'6', 'max_no_competitors':'1', 'town_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nOptimiserCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if (!PickRailType()) { AILog.Error("OPTIMISER FAIL: rail"); return; }
    this.builder = RouteBuilder(4);
    this.buyer = TrainBuyer(PassengerCargo());
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local route = null;
    while (route == null) {
        local pair = this.PickTownPair();
        if (pair != null) route = this.builder.ConnectTowns(pair[0],pair[1]);
        this.Sleep(75);
    }
    local train = this.buyer.BuildPassengerTrain(route.depot,route.station_a,route.station_b,2);
    if (!AIVehicle.IsValidVehicle(train)) { AILog.Error("OPTIMISER FAIL: train"); return; }
    this.optimiser = ServiceOptimiser(this.buyer);
    this.optimiser.Register(train,route,4);
    local before = AIVehicle.GetCapacity(train,this.buyer.cargo);
    local wagons = AIVehicle.GetNumWagons(train);
    local restored = false;
    local added = false;
    local limited = false;
    local limit_queued = false;
    local warmup_end = this.optimiser.trains[train].review_after;
    for (local tick = 0; tick < 60000; tick++) {
        this.optimiser.Review();
        local record = this.optimiser.trains[train];
        if (record.phase == "pending" && AIDate.GetCurrentDate() < warmup_end) {
            AILog.Error("OPTIMISER FAIL: upgrade before warmup"); return;
        }
        if (limited && record.phase == "pending") limit_queued = true;
        if (!restored && record.phase == "pending") {
            local saved = this.Save();
            this.optimiser = null;
            this.Load(1,saved);
            this.optimiser = ServiceOptimiser(this.buyer,this.loaded_services);
            restored = true;
        }
        if (AIVehicle.GetCapacity(train,this.buyer.cargo) > before) added = true;
        if (added && this.optimiser.trains[train].phase == "observe" && !AIVehicle.IsStoppedInDepot(train)) {
            // Computed expansion adds every carriage the shortfall needs.
            if (!restored || AIVehicle.GetNumWagons(train) <= wagons || AIVehicle.GetLength(train)>64 ||
                AIOrder.GetOrderCount(train) != 3 || (AIOrder.GetOrderFlags(train,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) {
                AILog.Error("OPTIMISER FAIL: upgrade or resumed orders"); return;
            }
            if (!limited) {
                // Leave less room than a wagon, exercising the measured length check.
                this.optimiser.trains[train].max_length = AIVehicle.GetLength(train)+1;
                this.optimiser.trains[train].review_after = AIDate.GetCurrentDate();
                limited = true;
                // Explicitly queue the negative fit case; the first upgrade above
                // was triggered only by observed passenger demand.
                limit_queued = this.optimiser.Queue(train,this.optimiser.trains[train]);
                this.Sleep(1);
                continue;
            }
            if (!limit_queued) { this.Sleep(1); continue; }
            if (AIVehicle.GetState(train) != AIVehicle.VS_AT_STATION) { this.Sleep(1); continue; }
            AILog.Info("OPTIMISER PASS: full departure with backlog, queued save/load, one carriage at depot, platform limit and automatic restart.");
            while (true) this.Sleep(1000);
        }
        this.Sleep(1);
    }
    AILog.Error("OPTIMISER FAIL: timed out restored="+restored+", added="+added);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-optimiser-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'OptimiserCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "OptimiserCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [43]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'optimiser-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'OPTIMISER PASS:' in result.stderr, 'Optimiser checks did not complete'
        assert 'OPTIMISER FAIL:' not in result.stderr
