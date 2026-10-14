"""Isolated live-game fleet expansion test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'FleetCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'6', 'map_y':'6', 'max_no_competitors':'1', 'town_cargo_scale':'5000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nFleetCheck = \n', config)
driver = r'''
class BigDemandOptimiser extends ServiceOptimiser {
    // Fixed demand so the expansion mechanics are deterministic regardless of
    // how productive the fixture map's towns are.
    function ExpansionShortfall(train, record) { return 5000; }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if (!PickRailType()) { AILog.Error("FLEET FAIL: rail"); return; }
    this.builder = RouteBuilder(4);
    this.buyer = TrainBuyer(PassengerCargo());
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local route = null;
    while (route == null) {
        local pair = this.PickTownPair();
        if (pair != null) route = this.builder.ConnectTowns(pair[0],pair[1]);
        this.Sleep(75);
    }
    // Seven standard wagons plus an engine exactly fill four platform tiles.
    local train = this.buyer.BuildPassengerTrain(route.depot,route.station_a,route.station_b,7);
    if (!AIVehicle.IsValidVehicle(train) || AIVehicle.GetLength(train)!=64) { AILog.Error("FLEET FAIL: full-length fixture"); return; }
    this.optimiser = BigDemandOptimiser(this.buyer);
    this.optimiser.Register(train,route,4);
    // The dedicated-mail feature would otherwise add a mail train when both
    // stations accept mail; this fixture tests the passenger clone path.
    ::accepting_native <- AICargoList_StationAccepting;
    ::reject_station <- this.optimiser.trains[train].station_b;
    ::AICargoList_StationAccepting <- function(station) {
        return station==reject_station ? AIList() : accepting_native(station);
    };
    // Let the fixture accumulate a full load despite the small test towns.
    AIOrder.SetOrderFlags(train,0,AIOrder.OF_NON_STOP_INTERMEDIATE|AIOrder.OF_FULL_LOAD);
    local before = AIVehicle.GetCapacity(train,this.buyer.cargo);
    local restored = false;
    local extra = -1;
    local stages = {};
    local dispatch_after = 0;
    local released = false;
    for (local tick = 0; tick < 60000; tick++) {
        local review_date=AIDate.GetCurrentDate();
        this.optimiser.Review();
        if (!restored && this.optimiser.trains[train].phase == "pending") {
            AIOrder.SetOrderFlags(train,0,AIOrder.OF_NON_STOP_INTERMEDIATE);
            local saved = this.Save();
            this.Load(1,saved);
            this.optimiser = BigDemandOptimiser(this.buyer,this.loaded_services);
            restored = true;
        }
        if (extra < 0 && this.optimiser.trains.len() == 2) {
            foreach (id, record in this.optimiser.trains) {
                if (id != train) extra = id;
                stages[id] <- 0;
                if (this.optimiser.RouteReady(record)) { AILog.Error("FLEET FAIL: no route cooldown"); return; }
            }
            dispatch_after = this.optimiser.trains[extra].dispatch_after;
            if(this.optimiser.trains[extra].phase!="dispatch" || !AIVehicle.IsStoppedInDepot(extra) ||
                dispatch_after<review_date+15 || dispatch_after>AIDate.GetCurrentDate()+30) {
                AILog.Error("FLEET FAIL: missing departure delay phase="+this.optimiser.trains[extra].phase+", stopped="+AIVehicle.IsStoppedInDepot(extra)+", remaining="+(dispatch_after-AIDate.GetCurrentDate())); return;
            }
            local saved = this.Save();
            this.Load(1,saved);
            this.optimiser = BigDemandOptimiser(this.buyer,this.loaded_services);
        }
        if (extra >= 0) {
            if(AIDate.GetCurrentDate()<dispatch_after && !AIVehicle.IsStoppedInDepot(extra)) {
                AILog.Error("FLEET FAIL: departed early after save/load"); return;
            }
            if(AIDate.GetCurrentDate()>=dispatch_after && !AIVehicle.IsStoppedInDepot(extra)) released=true;
            // Extra trains are newly assembled three-wagon consists, not full copies.
            if (!restored || this.optimiser.trains.len()!=2 || AIVehicle.GetCapacity(train,this.buyer.cargo)!=before ||
                AIVehicle.GetCapacity(extra,this.buyer.cargo)<=0 ||
                AIVehicle.GetCapacity(extra,this.buyer.cargo)>=before || AIVehicle.GetLength(extra)>64) {
                AILog.Error("FLEET FAIL: copied consist or duplicate purchase"); return;
            }
            foreach (order in [0,1,2]) if (AIOrder.GetOrderDestination(extra,order)!=AIOrder.GetOrderDestination(train,order)) {
                AILog.Error("FLEET FAIL: different route"); return;
            }
            local complete = true;
            foreach (id, stage in stages) {
                local tile = AIVehicle.GetLocation(id);
                local station = AIStation.GetStationID(tile);
                if (stage==0 && station==AIStation.GetStationID(route.station_a)) stages[id]=1;
                else if (stage==1 && station==AIStation.GetStationID(route.station_b)) stages[id]=2;
                else if (stage==2 && tile==route.depot) stages[id]=3;
                else if (stage==3 && station==AIStation.GetStationID(route.station_a)) stages[id]=4;
                if (stages[id]<4) complete=false;
            }
            if (complete && released) {
                if ((AIOrder.GetOrderFlags(extra,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) { AILog.Error("FLEET FAIL: clone stop order"); return; }
                AILog.Info("FLEET PASS: full-length crowded train, saved expansion, identical new consist, both trains completed A-B-depot-A.");
                while (true) this.Sleep(1000);
            }
        }
        this.Sleep(1);
    }
    AILog.Error("FLEET FAIL: timed out extra="+extra);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-fleet-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'FleetCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "FleetCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [43]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'fleet-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'FLEET PASS:' in result.stderr, 'Fleet checks did not complete'
        assert 'FLEET FAIL:' not in result.stderr
