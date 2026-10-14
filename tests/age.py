"""Isolated live-game twenty-year renewal test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'AgeCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'number_towns':'3', 'terrain_type':'1', 'land_generator':'1', 'quantity_sea_lakes':'0', 'max_no_competitors':'1', 'town_cargo_scale':'1000', 'disasters':'false', 'vehicle_breakdowns':'0', 'max_loan':'2000000', 'starting_year':'1950', 'never_expire_vehicles':'true', 'engine_renew':'false'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nAgeCheck = \n', config)
driver = r'''
class OldEngineBuyer extends TrainBuyer
{
    function NewerPowerfulEngine(train,depot) { return -1; }
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
    AICompany.SetAutoRenewStatus(false);
    if (!PickRailType()) { AILog.Error("AGE FAIL: rail"); return; }
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
    if(!AIVehicle.IsValidVehicle(original)) { AILog.Error("AGE FAIL: fixture"); return; }
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
    for(local tick=0;tick<400000;tick++) {
        local reliability=AIVehicle.IsValidVehicle(original)?AIVehicle.GetReliability(original):100;
        // Keep this fixture focused on engine replacement, with a fixed consist.
        foreach(id, record in this.optimiser.trains) record.review_after=AIDate.GetCurrentDate()+365;
        this.optimiser.Review();
        if(original in this.optimiser.trains && this.optimiser.trains[original].phase=="engine" && !saved_queue) {
            if(AIVehicle.GetAge(original)<20*365 && AIVehicle.GetAgeLeft(original)>0) { AILog.Error("AGE FAIL: reliability threshold"); return; }
            if((AIOrder.GetOrderFlags(original,2)&AIOrder.OF_STOP_IN_DEPOT)==0)
                throw "Renewal did not arm a depot stop";
            // Simulate route planning missing the whole normal service window.
            for(local wait=0;wait<15000 && !AIVehicle.IsStoppedInDepot(original);wait++) this.Sleep(1);
            if(!AIVehicle.IsStoppedInDepot(original)) throw "Renewal train did not wait for the busy optimiser";
            this.Sleep(200);
            if(!AIVehicle.IsStoppedInDepot(original)) throw "Renewal train left before replacement";
            local saved=this.Save();
            this.Load(1,saved);
            this.optimiser=ServiceOptimiser(this.buyer,this.loaded_services);
            saved_queue=true;
            if(!rejected) this.optimiser.trains[original].max_length=1;
        }
        if(!rejected && saved_queue && original in this.optimiser.trains && this.optimiser.trains[original].phase=="observe") {
            if(AIVehicle.GetCapacity(original,this.buyer.cargo)!=capacity || this.optimiser.trains[original].replacement!=-1 ||
                (AIOrder.GetOrderFlags(original,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) {
                AILog.Error("AGE FAIL: platform-limit rollback"); return;
            }
            this.optimiser.trains[original].max_length=64;
            this.optimiser.trains[original].engine_check_after=0;
            rejected=true;
            saved_queue=false;
            AILog.Info("AGE TEST: oversized replacement rejected, carriages restored and original service resumed.");
        }
        if(!AIVehicle.IsValidVehicle(original) && replacement<0) {
            foreach(id,record in this.optimiser.trains) replacement=id;
            if(replacement<0 || !rejected) { AILog.Error("AGE FAIL: missing replacement; id="+replacement+", queued="+saved_queue+", rollback="+rejected+", bank="+AICompany.GetBankBalance(AICompany.COMPANY_SELF)); return; }
            local engine=AIVehicle.GetEngineType(replacement);
            if(AIVehicle.GetAge(replacement)>=365 ||
                AIVehicle.GetCapacity(replacement,this.buyer.cargo)<capacity || AIVehicle.GetLength(replacement)>64) {
                AILog.Error("AGE FAIL: replacement quality"); return;
            }
            local actual=[];
            for(local i=1;i<AIVehicle.GetNumWagons(replacement);i++) if(AIEngine.IsWagon(AIVehicle.GetWagonEngineType(replacement,i))) actual.append(AIVehicle.GetWagonEngineType(replacement,i));
            if(actual.len()!=wagons.len()) { AILog.Error("AGE FAIL: lost carriages"); return; }
            for(local i=0;i<actual.len();i++) if(actual[i]!=wagons[i]) { AILog.Error("AGE FAIL: changed carriages"); return; }
        }
        if(replacement>=0) {
            local tile=AIVehicle.GetLocation(replacement);
            local station=AIStation.GetStationID(tile);
            if(stage==0 && station==AIStation.GetStationID(route.station_a)) stage=1;
            else if(stage==1 && station==AIStation.GetStationID(route.station_b)) stage=2;
            else if(stage==2 && tile==route.depot) stage=3;
            else if(stage==3 && station==AIStation.GetStationID(route.station_a)) stage=4;
            if(stage==4) {
                if((AIOrder.GetOrderFlags(replacement,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) { AILog.Error("AGE FAIL: stopped order"); return; }
                AILog.Info("AGE PASS: lifetime/twenty-year renewal without a newer engine, queued save/load, fresh engine, retained carriages and complete service circuit.");
                while(true) this.Sleep(1000);
            }
        }
        this.Sleep(1);
    }
    AILog.Error("AGE FAIL: timeout replacement="+replacement+", queued="+saved_queue);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-age-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'AgeCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "AgeCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=1800000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'age-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'AGE PASS:' in result.stderr, 'Engine checks did not complete'
        assert 'AGE FAIL:' not in result.stderr
