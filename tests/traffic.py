"""Isolated two-train traffic test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SignalCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'1', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSignalCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if (!PickRailType()) { AILog.Error("TRAFFIC FAIL: rail type"); return; }
    local cargo = PassengerCargo();
    this.builder = RouteBuilder(AIController.GetSetting("platform_length"));
    this.buyer = TrainBuyer(cargo);
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local route = null;
    while (route == null) {
        local pair = this.PickTownPair();
        if (pair != null) route = this.builder.ConnectTowns(pair[0], pair[1]);
        this.Sleep(75);
    }
    local front=AIRail.GetRailDepotFrontTile(route.depot);
    local a_tiles=AITileList_StationType(AIStation.GetStationID(route.station_a),AIStation.STATION_TRAIN);
    local nearest=10000;
    foreach(tile,_ in a_tiles) {
        local distance=AIMap.DistanceManhattan(tile,front);
        if(distance<nearest) nearest=distance;
    }
    if(nearest<6) throw "Depot still beside station crossover";
    local trains = [];
    for (local i = 0; i < 2; i++) {
        local train = this.buyer.BuildPassengerTrain(route.depot, route.station_a, route.station_b, 3);
        if (!AIVehicle.IsValidVehicle(train)) { AILog.Error("TRAFFIC FAIL: purchase"); return; }
        trains.append({ id = train, stage = 0 });
        this.Sleep(75);
    }
    // Simulate an older save with missing connection bookkeeping.
    this.builder.connected_pairs={};
    this.builder.used_towns={};
    this.builder.RecoverLiveConnections();
    local town_a=AIStation.GetNearestTown(AIStation.GetStationID(route.station_a));
    local town_b=AIStation.GetNearestTown(AIStation.GetStationID(route.station_b));
    if(!this.builder.ConnectionBuilt(town_a,town_b) || !this.builder.ConnectionBuilt(town_b,town_a) ||
        this.builder.TownRouteCount(town_a)!=1 || this.builder.TownRouteCount(town_b)!=1 ||
        this.builder.ConnectTowns(town_a,town_b)!=null || this.builder.ConnectTowns(town_b,town_a)!=null) {
        AILog.Error("TRAFFIC FAIL: duplicate live connection"); return;
    }
    AILog.Info("DUPLICATE PASS: live orders restore missing memory, both directions blocked, two trains counted as one connection.");
    local a = AIStation.GetStationID(route.station_a);
    local b = AIStation.GetStationID(route.station_b);
    for (local tick = 0; tick < 40000; tick++) {
        local complete = true;
        foreach (train in trains) {
            local tile = AIVehicle.GetLocation(train.id);
            local station = AIStation.GetStationID(tile);
            if (train.stage == 0 && station == a) train.stage = 1;
            else if (train.stage == 1 && station == b) train.stage = 2;
            else if (train.stage == 2 && tile == route.depot) train.stage = 3;
            else if (train.stage == 3 && station == a) train.stage = 4;
            if (train.stage < 4) complete = false;
        }
        if (complete) {
            AILog.Info("TRAFFIC PASS: both trains visited A, B, maintenance depot, then A again.");
            while (true) this.Sleep(1000);
        }
        this.Sleep(1);
    }
    foreach (train in trains) AILog.Error("TRAFFIC FAIL: train=" + train.id + ", stage=" + train.stage);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-traffic-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SignalCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SignalCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'traffic-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'TRAFFIC PASS:' in result.stderr, 'Two-train circuit did not complete'
        assert 'TRAFFIC FAIL:' not in result.stderr

        for before, after, corners in re.findall(r'matching adjacent track tiles=(\d+) -> (\d+), changed corners=(\d+)', result.stderr):
            assert 0 < int(corners) <= 96

        assert 'Depot approaches verified: signals on both sides of the junction.' in result.stderr
