"""Isolated live-game engine replacement test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'EngineCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'number_towns':'3', 'terrain_type':'1', 'land_generator':'1', 'quantity_sea_lakes':'0', 'max_no_competitors':'1', 'town_cargo_scale':'100'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nEngineCheck = \n', config)
driver = r'''
class OldEngineBuyer extends TrainBuyer
{
    function BestEngine()
    {
        local best = -1;
        foreach (engine, _ in AIEngineList(AIVehicle.VT_RAIL)) {
            if (AIEngine.IsWagon(engine) || !AIEngine.IsBuildable(engine) ||
                !AIEngine.HasPowerOnRail(engine,AIRail.GetCurrentRailType()) || !AIEngine.CanRunOnRail(engine,AIRail.GetCurrentRailType())) continue;
            if (best<0 || AIEngine.GetPower(engine)<AIEngine.GetPower(best)) best=engine;
        }
        return best;
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if (!PickRailType()) { AILog.Error("ENGINE FAIL: rail"); return; }
    this.builder=RouteBuilder(4);
    this.buyer=OldEngineBuyer(PassengerCargo());
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local route=null;
    while(route==null) {
        local pair=this.PickTownPair();
        if(pair!=null) route=this.builder.ConnectTowns(pair[0],pair[1]);
        this.Sleep(75);
    }
    local original=this.buyer.BuildPassengerTrain(route.depot,route.station_a,route.station_b,3);
    if(!AIVehicle.IsValidVehicle(original)) { AILog.Error("ENGINE FAIL: fixture"); return; }
    local old_engine=AIVehicle.GetEngineType(original);
    local capacity=AIVehicle.GetCapacity(original,this.buyer.cargo);
    local wagons=[];
    for(local i=1;i<AIVehicle.GetNumWagons(original);i++) if(AIEngine.IsWagon(AIVehicle.GetWagonEngineType(original,i))) wagons.append(AIVehicle.GetWagonEngineType(original,i));
    this.optimiser=ServiceOptimiser(this.buyer);
    this.optimiser.Register(original,route,4);
    local saved_queue=false;
    local replacement=-1;
    local rejected=false;
    local stage=0;
    for(local tick=0;tick<180000;tick++) {
        local reliability=AIVehicle.IsValidVehicle(original)?AIVehicle.GetReliability(original):100;
        // Keep this fixture focused on engine replacement, with a fixed consist.
        foreach(id, record in this.optimiser.trains) record.review_after=AIDate.GetCurrentDate()+365;
        this.optimiser.Review();
        if(original in this.optimiser.trains && this.optimiser.trains[original].phase=="engine" && !saved_queue) {
            if(reliability>=66 || AIVehicle.GetAge(original)<5*365) { AILog.Error("ENGINE FAIL: reliability threshold"); return; }
            local saved=this.Save();
            this.Load(1,saved);
            this.optimiser=ServiceOptimiser(this.buyer,this.loaded_services);
            saved_queue=true;
            if(!rejected) this.optimiser.trains[original].max_length=1;
        }
        if(!rejected && saved_queue && original in this.optimiser.trains && this.optimiser.trains[original].phase=="observe") {
            if(AIVehicle.GetCapacity(original,this.buyer.cargo)!=capacity || this.optimiser.trains[original].replacement!=-1 ||
                (AIOrder.GetOrderFlags(original,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) {
                AILog.Error("ENGINE FAIL: platform-limit rollback"); return;
            }
            this.optimiser.trains[original].max_length=64;
            this.optimiser.trains[original].engine_check_after=0;
            rejected=true;
            saved_queue=false;
            AILog.Info("ENGINE TEST: oversized replacement rejected, carriages restored and original service resumed.");
        }
        if(!AIVehicle.IsValidVehicle(original) && replacement<0) {
            foreach(id,record in this.optimiser.trains) replacement=id;
            // rejected already proves the queue + save/load + rollback stage ran;
            // a re-queued train still at its depot is worked on in the same
            // review, so the intermediate "engine" phase is not observable.
            if(replacement<0 || !rejected) { AILog.Error("ENGINE FAIL: missing replacement"); return; }
            local engine=AIVehicle.GetEngineType(replacement);
            if(AIEngine.GetDesignDate(engine)<=AIEngine.GetDesignDate(old_engine) || AIEngine.GetPower(engine)<=AIEngine.GetPower(old_engine) ||
                AIVehicle.GetCapacity(replacement,this.buyer.cargo)<capacity || AIVehicle.GetLength(replacement)>64) {
                AILog.Error("ENGINE FAIL: replacement quality"); return;
            }
            local actual=[];
            for(local i=1;i<AIVehicle.GetNumWagons(replacement);i++) if(AIEngine.IsWagon(AIVehicle.GetWagonEngineType(replacement,i))) actual.append(AIVehicle.GetWagonEngineType(replacement,i));
            if(actual.len()!=wagons.len()) { AILog.Error("ENGINE FAIL: lost carriages"); return; }
            for(local i=0;i<actual.len();i++) if(actual[i]!=wagons[i]) { AILog.Error("ENGINE FAIL: changed carriages"); return; }
        }
        if(replacement>=0) {
            local tile=AIVehicle.GetLocation(replacement);
            local station=AIStation.GetStationID(tile);
            if(stage==0 && station==AIStation.GetStationID(route.station_a)) stage=1;
            else if(stage==1 && station==AIStation.GetStationID(route.station_b)) stage=2;
            else if(stage==2 && tile==route.depot) stage=3;
            else if(stage==3 && station==AIStation.GetStationID(route.station_a)) stage=4;
            if(stage==4) {
                if((AIOrder.GetOrderFlags(replacement,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) { AILog.Error("ENGINE FAIL: stopped order"); return; }
                AILog.Info("ENGINE PASS: five-year age gate and sub-66 reliability, queued save/load, newer higher-power engine, retained carriages and complete service circuit.");
                while(true) this.Sleep(1000);
            }
        }
        this.Sleep(1);
    }
    AILog.Error("ENGINE FAIL: timeout replacement="+replacement+", queued="+saved_queue);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-engine-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'EngineCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "EngineCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 43]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=1800000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=180)
        (root / 'tests' / f'engine-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'ENGINE PASS:' in result.stderr, 'Engine checks did not complete'
        assert 'ENGINE FAIL:' not in result.stderr
