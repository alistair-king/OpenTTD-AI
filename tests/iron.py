"""Isolated two-train traffic test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'IronCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nIronCheck = \n', config)
driver = r'''
::passenger_selections <- 0;
function OpenTTDAI::PickTownPair() { passenger_selections++; return null; }
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) throw "No rails";
    this.builder=RouteBuilder(4);
    this.builder.single_first=true;
    this.builder.use_jump_search=true;
    this.builder.use_aystar=true;
    this.iron=CoalRoutes(this.builder,null,"IORE");
    this.coal=CoalRoutes(this.builder);
    this.coal.retry_after=AIDate.GetCurrentDate()+30;
    this.TryBuildRoute();
    if(this.iron.attempted.len()!=0 || passenger_selections!=0) throw "Ore or passengers started during coal priority";
    this.coal.phase=false;
    if(this.iron.PickPair()==null) {
        this.TryBuildRoute();
        if(passenger_selections!=1 || this.iron.phase) throw "Absent ore pairs blocked passengers";
        AILog.Info("IRON PASS: no eligible mine/mill pair; passengers remain available.");
        while(true) this.Sleep(1000);
    }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    for(local attempts=0; attempts<30 && this.iron.services.len()==0 && this.iron.phase; attempts++) {
        this.TryBuildRoute(); this.Sleep(10);
    }
    if(this.iron.services.len()==0) throw "No iron service built";
    local previous=passenger_selections;
    this.TryBuildRoute();
    if(passenger_selections!=previous+1) throw "Ore attempt did not alternate with passengers";

    local train=-1; foreach(id,_ in this.iron.services) { train=id; break; }
    local service=this.iron.services[train];
    if(!this.iron.IsDestination(service.target)) throw "Destination is not a steel mill";
    if(service.single_route==null || service.single_route.dual) throw "Initial route was not single track";
    local data=service.single_route;
    local checked={};
    foreach(p in data.primary) checked[p[0]] <- true;
    foreach(p in data.stubs) checked[p[1]] <- true;
    foreach(p in data.loop_signals) checked[p[0]] <- true;
    foreach(tile,_ in checked) foreach(off in [1,-1,AIMap.GetMapSizeX(),-AIMap.GetMapSizeX()])
        if(AIMap.IsValidTile(tile+off) && AIMap.DistanceManhattan(tile,tile+off)==1 && AIRail.GetSignalType(tile,tile+off)!=AIRail.SIGNALTYPE_NONE)
            throw "Signals present on initial single route";
    local saved_single=this.iron.Save();
    this.iron=CoalRoutes(this.builder,saved_single,"IORE");
    if(this.iron.optimiser.trains[train].single_route==null || this.iron.optimiser.trains[train].single_route.dual)
        throw "Single-track state lost in save/load";
    if(!(train in this.iron.optimiser.trains)) throw "Iron optimiser not registered";
    if(AIVehicle.GetCapacity(train,PassengerCargo())!=0) throw "Passenger wagons on iron service";
    if((AIOrder.GetOrderFlags(train,0)&AIOrder.OF_FULL_LOAD)==0 ||
       (AIOrder.GetOrderFlags(train,1)&AIOrder.OF_NO_LOAD)==0) throw "Incorrect freight orders";
    local loaded=false, delivered=false, depot_seen=false;
    for(local tick=0;tick<60000 && !depot_seen;tick++) {
        local cargo=AIVehicle.GetCargoLoad(train,this.iron.cargo);
        local station=AIStation.GetStationID(AIVehicle.GetLocation(train));
        if(cargo>0) loaded=true;
        if(loaded && station==AIStation.GetStationID(service.station_b) && cargo==0) delivered=true;
        if(delivered && AIVehicle.GetLocation(train)==service.depot) depot_seen=true;
        this.Sleep(1);
    }
    if(!loaded || !delivered || !depot_seen) throw "Iron delivery cycle failed";
    local probe=AIVehicle.BuildVehicle(service.depot,this.iron.buyer.BestWagon());
    local wagon_length=AIVehicle.GetLength(probe);
    AIVehicle.SellVehicle(probe);
    // First growth is the penultimate slot: a passenger train would add mail.
    this.iron.optimiser.trains[train].max_length=AIVehicle.GetLength(train)+2*wagon_length;
    local original_capacity=AIVehicle.GetCapacity(train,this.iron.cargo);
    local upgraded=false, cloned=false;
    for(local tick=0;tick<90000 && !cloned;tick++) {
        this.iron.optimiser.Review();
        if(!upgraded && AIVehicle.GetCapacity(train,this.iron.cargo)>original_capacity &&
            this.iron.optimiser.trains[train].phase=="observe") {
            upgraded=true;
            this.iron.optimiser.trains[train].max_length=AIVehicle.GetLength(train);
            this.iron.optimiser.trains[train].review_after=AIDate.GetCurrentDate();
        }
        if(upgraded && this.iron.optimiser.trains.len()>1) {
            foreach(id,record in this.iron.optimiser.trains) if(id!=train) {
                if(record.phase!="dispatch" || !AIVehicle.IsStoppedInDepot(id) || record.dispatch_after<=AIDate.GetCurrentDate())
                    throw "Iron clone not staggered";
                if((AIOrder.GetOrderFlags(id,0)&AIOrder.OF_FULL_LOAD)==0 || (AIOrder.GetOrderFlags(id,1)&AIOrder.OF_NO_LOAD)==0)
                    throw "Iron clone lost freight orders";
                cloned=true;
            }
        }
        this.Sleep(1);
    }
    if(!upgraded || !cloned) throw "Iron demand optimisation did not expand service";
    if(!this.iron.optimiser.trains[train].single_route.dual) throw "Second train added before return track";
    foreach(p in data.merges) if(AIRail.AreTilesConnected(p[0],p[1],p[2])) throw "Temporary single-track merge survived upgrade";
    local visits={}; foreach(id,_ in this.iron.optimiser.trains) visits[id] <- 0;
    local all_visited=false;
    for(local tick=0;tick<60000 && !all_visited;tick++) {
        foreach(id,record in this.iron.optimiser.trains) record.review_after=AIDate.GetCurrentDate()+365;
        this.iron.optimiser.Review();
        all_visited=true;
        foreach(id,mask in visits) {
            local station=AIStation.GetStationID(AIVehicle.GetLocation(id));
            if(station==AIStation.GetStationID(service.station_a)) visits[id]=visits[id]|1;
            if(station==AIStation.GetStationID(service.station_b)) visits[id]=visits[id]|2;
            if(visits[id]!=3) all_visited=false;
        }
        this.Sleep(1);
    }
    if(!all_visited) throw "Two-train traffic failed after conversion";
    foreach(mail,_ in AICargoList()) if(AICargo.HasCargoClass(mail,AICargo.CC_MAIL))
        foreach(id,_ in this.iron.optimiser.trains) if(AIVehicle.GetCapacity(id,mail)>0) throw "Mail on iron train";
    this.Load(1,this.Save());
    local restored=CoalRoutes(this.builder,this.loaded_iron,"IORE");
    if(!(train in restored.services) || !(train in restored.optimiser.trains)) throw "Iron save/load failed";
    local next_pair=restored.PickPair();
    if(next_pair!=null && next_pair[0]==service.source) throw "Duplicate served mine after reload";
    this.builder.RecoverLiveConnections();
    if(this.builder.connected_pairs.len()!=0) throw "Iron route counted as town connection";
    for(local i=0;i<10000;i++) {
        local pair=this.iron.PickPair();
        if(pair==null) break;
        this.iron.attempted[pair[0]+":"+pair[1]] <- true;
    }
    this.iron_next=true;
    local previous_count=passenger_selections;
    this.TryBuildRoute();
    if(this.iron.phase || passenger_selections!=previous_count+1) throw "Did not switch to passengers after iron exhaustion";
    local finished=CoalRoutes(this.builder,this.iron.Save(),"IORE");
    if(finished.phase) throw "Iron completion phase not saved";
    AILog.Info("IRON PASS: real mine loading, steel mill unloading, maintenance, roll-through stations, wagon growth, staggered clone, no mail, optimiser and save/load.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-iron-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'IronCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "IronCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'iron-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'IRON PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
