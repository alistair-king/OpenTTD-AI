"""Isolated two-train traffic test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'CoalCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nCoalCheck = \n', config)
driver = r'''
::passenger_selections <- 0;
function OpenTTDAI::PickTownPair() { passenger_selections++; return null; }
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) throw "No rails";
    this.builder=RouteBuilder(4);
    this.builder.use_jump_search=true;
    this.builder.use_aystar=true;
    this.coal=CoalRoutes(this.builder);
    EnsureMoney(AICompany.GetMaxLoanAmount());
    for(local attempts=0; attempts<30 && this.coal.services.len()==0 && this.coal.phase; attempts++) {
        this.TryBuildRoute(); this.Sleep(10);
    }
    if(this.coal.services.len()==0) throw "No coal service built";
    if(passenger_selections!=0) throw "Passengers attempted before coal";
    local train=-1; foreach(id,_ in this.coal.services) { train=id; break; }
    local service=this.coal.services[train];
    if(!(train in this.coal.optimiser.trains)) throw "Coal optimiser not registered";
    if(AIVehicle.GetCapacity(train,PassengerCargo())!=0) throw "Passenger wagons on coal service";
    if((AIOrder.GetOrderFlags(train,0)&AIOrder.OF_FULL_LOAD)==0 ||
       (AIOrder.GetOrderFlags(train,1)&AIOrder.OF_NO_LOAD)==0) throw "Incorrect freight orders";
    local loaded=false, delivered=false, depot_seen=false;
    for(local tick=0;tick<60000 && !depot_seen;tick++) {
        local cargo=AIVehicle.GetCargoLoad(train,this.coal.cargo);
        local station=AIStation.GetStationID(AIVehicle.GetLocation(train));
        if(cargo>0) loaded=true;
        if(loaded && station==AIStation.GetStationID(service.station_b) && cargo==0) delivered=true;
        if(delivered && AIVehicle.GetLocation(train)==service.depot) depot_seen=true;
        this.Sleep(1);
    }
    if(!loaded || !delivered || !depot_seen) throw "Coal delivery cycle failed";
    local probe=AIVehicle.BuildVehicle(service.depot,this.coal.buyer.BestWagon());
    local wagon_length=AIVehicle.GetLength(probe);
    AIVehicle.SellVehicle(probe);
    // First growth is the penultimate slot: a passenger train would add mail.
    this.coal.optimiser.trains[train].max_length=AIVehicle.GetLength(train)+2*wagon_length;
    local original_capacity=AIVehicle.GetCapacity(train,this.coal.cargo);
    local upgraded=false, cloned=false;
    for(local tick=0;tick<90000 && !cloned;tick++) {
        this.coal.optimiser.Review();
        if(!upgraded && AIVehicle.GetCapacity(train,this.coal.cargo)>original_capacity &&
            this.coal.optimiser.trains[train].phase=="observe") {
            upgraded=true;
            this.coal.optimiser.trains[train].max_length=AIVehicle.GetLength(train);
            this.coal.optimiser.trains[train].review_after=AIDate.GetCurrentDate();
        }
        if(upgraded && this.coal.optimiser.trains.len()>1) {
            foreach(id,record in this.coal.optimiser.trains) if(id!=train) {
                if(record.phase!="dispatch" || !AIVehicle.IsStoppedInDepot(id) || record.dispatch_after<=AIDate.GetCurrentDate())
                    throw "Coal clone not staggered";
                if((AIOrder.GetOrderFlags(id,0)&AIOrder.OF_FULL_LOAD)==0 || (AIOrder.GetOrderFlags(id,1)&AIOrder.OF_NO_LOAD)==0)
                    throw "Coal clone lost freight orders";
                cloned=true;
            }
        }
        this.Sleep(1);
    }
    if(!upgraded || !cloned) throw "Coal demand optimisation did not expand service";
    foreach(mail,_ in AICargoList()) if(AICargo.HasCargoClass(mail,AICargo.CC_MAIL))
        foreach(id,_ in this.coal.optimiser.trains) if(AIVehicle.GetCapacity(id,mail)>0) throw "Mail on coal train";
    this.Load(1,this.Save());
    local restored=CoalRoutes(this.builder,this.loaded_coal);
    if(!(train in restored.services) || !(train in restored.optimiser.trains)) throw "Coal save/load failed";
    local next_pair=restored.PickPair();
    if(next_pair!=null && next_pair[0]==service.source) throw "Duplicate served mine after reload";
    this.builder.RecoverLiveConnections();
    if(this.builder.connected_pairs.len()!=0) throw "Coal route counted as town connection";
    for(local i=0;i<10000;i++) {
        local pair=this.coal.PickPair();
        if(pair==null) break;
        this.coal.attempted[pair[0]+":"+pair[1]] <- true;
    }
    this.TryBuildRoute();
    if(this.coal.phase || passenger_selections!=1) throw "Did not switch to passengers after coal exhaustion";
    local finished=CoalRoutes(this.builder,this.coal.Save());
    if(finished.phase) throw "Coal completion phase not saved";
    AILog.Info("COAL PASS: real mine loading, power station unloading, maintenance, roll-through stations, wagon growth, staggered clone, no mail, optimiser and save/load.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-coal-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'CoalCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "CoalCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'coal-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'COAL PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
