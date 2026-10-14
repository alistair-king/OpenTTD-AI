"""Isolated live-game loss-making train retirement test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'RetirementCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'number_towns':'3', 'terrain_type':'1', 'land_generator':'1', 'quantity_sea_lakes':'0', 'max_no_competitors':'1', 'town_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nRetirementCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    ::RetiredRailways=RailwayRetirement();
    if (!PickRailType()) { AILog.Error("RETIRE FAIL: rail"); return; }
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
    if (!AIVehicle.IsValidVehicle(train)) { AILog.Error("RETIRE FAIL: purchase"); return; }
    local guard=this.buyer.BuildCargoTrain(route.depot,route.station_a,route.station_b,2,false,false,64);
    if(!AIVehicle.IsValidVehicle(guard)) throw "No shared route guard";
    // An isolated test service with no passenger income and genuine running costs.
    foreach (order in [0,1]) AIOrder.SetOrderFlags(train,order,AIOrder.OF_NON_STOP_INTERMEDIATE|AIOrder.OF_NO_LOAD);
    this.optimiser = ServiceOptimiser(this.buyer);
    this.optimiser.Register(train,route,4);
    local probe = { profit_year = 2000, loss_years = 0 };
    this.optimiser.UpdateProfitHistory(probe,2001,-100,100);
    if (probe.loss_years != 0) { AILog.Error("RETIRE FAIL: partial year"); return; }
    this.optimiser.UpdateProfitHistory(probe,2002,-100,700);
    this.optimiser.UpdateProfitHistory(probe,2002,-100,700);
    if (probe.loss_years != 1) { AILog.Error("RETIRE FAIL: duplicated year"); return; }
    this.optimiser.UpdateProfitHistory(probe,2003,100,1000);
    if (probe.loss_years != 0) { AILog.Error("RETIRE FAIL: profitable year"); return; }
    this.optimiser.UpdateProfitHistory(probe,2004,-100,1400);
    this.optimiser.UpdateProfitHistory(probe,2005,0,1700);
    if (probe.loss_years != 0) { AILog.Error("RETIRE FAIL: break-even year"); return; }
    this.optimiser.UpdateProfitHistory(probe,2006,-100,2100);
    this.optimiser.UpdateProfitHistory(probe,2008,-100,2800);
    if (probe.loss_years != 1) { AILog.Error("RETIRE FAIL: missing years"); return; }
    local history_saved = false;
    local sale_saved = false;
    local retiring = false;
    for (local tick = 0; tick < 150000; tick++) {
        local age = AIVehicle.GetAge(train);
        // Keep this fixture about retirement, not demand-driven mail expansion.
        this.optimiser.trains[train].review_after=AIDate.GetCurrentDate()+365;
        this.optimiser.Review();
        if (!AIVehicle.IsValidVehicle(train)) {
            if (!retiring || !history_saved || !sale_saved || train in this.optimiser.trains) {
                AILog.Error("RETIRE FAIL: sale lifecycle"); return;
            }
            local anchors={depot=route.depot,station_a=AIStation.GetStationID(route.station_a),station_b=AIStation.GetStationID(route.station_b),cargo=PassengerCargo()};
            for(local i=0;i<1000 && RetiredRailways.jobs.len()>0;i++) RetiredRailways.Step();
            if(!AIRail.IsRailDepotTile(route.depot) || !AIRail.IsRailStationTile(route.station_a)) throw "Shared route removed with live stopped train";
            RetiredRailways.Queue(anchors);
            if(!AIVehicle.SellVehicle(guard)) throw "Guard sale failed";
            // Resume both a partial scan and a partially demolished railway.
            RetiredRailways.Step();
            RetiredRailways=RailwayRetirement(RetiredRailways.Save());
            while(RetiredRailways.jobs.len()>0 && !RetiredRailways.jobs[0].ready) RetiredRailways.Step();
            RetiredRailways.Step();
            RetiredRailways=RailwayRetirement(RetiredRailways.Save());
            for(local i=0;i<3000 && RetiredRailways.jobs.len()>0;i++) {RetiredRailways.Step();this.Sleep(1);}
            if(RetiredRailways.jobs.len()>0 || AIRail.IsRailDepotTile(route.depot) ||
                AIRail.IsRailStationTile(route.station_a) || AIRail.IsRailStationTile(route.station_b)) throw "Retired railway not removed";
            if(RetiredRailways.completed.len()!=1) throw "No cleanup completion";
            foreach(p in RetiredRailways.completed[0].tiles) if(RetiredRailways.Rail(p.tile)) throw "Rails left behind";
            local connected_before=this.builder.connected_pairs.len();
            this.routes=connected_before;
            this.network=FreightNetworks(4);
            this.network.networks[0].state.depot=route.depot;
            this.network.networks[0].state.stage=1;
            this.FinishRetirements();
            if(this.network.networks.len()!=0 || this.builder.connected_pairs.len()!=connected_before-1 ||
                this.routes!=connected_before-1) throw "Retired network bookkeeping remained";
            AILog.Info("RETIRE PASS: real losses, five-year age gate, saved annual history, depot return, whole-train sale, shared-track protection and saved railway cleanup.");
            while (true) this.Sleep(1000);
        }
        local record = this.optimiser.trains[train];
        if (!history_saved && record.loss_years >= 2) {
            local saved = this.Save();
            this.Load(1,saved);
            this.optimiser = ServiceOptimiser(this.buyer,this.loaded_services);
            history_saved = true;
        }
        if (record.phase == "sell" || record.phase == "sell_route") {
            if (age <= 5*365 || record.loss_years < 3) { AILog.Error("RETIRE FAIL: premature sale"); return; }
            retiring = true;
            if (!sale_saved) {
                local saved = this.Save();
                this.Load(1,saved);
                this.optimiser = ServiceOptimiser(this.buyer,this.loaded_services);
                sale_saved = true;
            }
        }
        this.Sleep(5);
    }
    AILog.Error("RETIRE FAIL: timed out");
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-retirement-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'RetirementCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "RetirementCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 43]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=1200000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'retirement-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RETIRE PASS:' in result.stderr, 'Retirement checks did not complete'
        assert 'RETIRE FAIL:' not in result.stderr
