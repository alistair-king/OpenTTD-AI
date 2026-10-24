"""Live city-bus construction, service, optimisation and persistence checks."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'BusCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000', 'initial_city_size':'8', 'larger_towns':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nBusCheck = \n', config)
driver = r'''
function OpenTTDAI::Start() {
    if(!EnsureMoney(300000)) throw "Funding failed";
    this.buses=CityBuses();
    for(local attempt=0;attempt<40 && this.buses.networks.len()==0;attempt++) {
        this.buses.TryBuild();this.Sleep(10);
    }
    if(this.buses.networks.len()==0) throw "No city bus network built";
    local net=this.buses.networks[0];
    if(net.stops.len()<4 || net.stops.len()>5 || net.vehicles.len()!=2) throw "Incorrect network size";
    local covered={};
    foreach(stop in net.stops) {
        if(!AIRoad.IsDriveThroughRoadStationTile(stop)) throw "Missing stop";
        local gain=0;foreach(h,p in this.buses.Coverage(stop,net.town)) if(!(h in covered)) {covered[h] <- true;gain++;}
        if(gain==0) throw "Stop adds no coverage";
        foreach(other in net.stops) if(stop!=other && AIMap.DistanceManhattan(stop,other)<5) throw "Stops too close";
    }
    foreach(bus in net.vehicles) {
        if(AIOrder.GetOrderCount(bus.id)!=net.stops.len()+1) throw "Incomplete orders";
        if(!AIOrder.IsGotoDepotOrder(bus.id,net.stops.len())) throw "Missing service order";
    }
    local saved=this.Save();this.Load(1,saved);this.buses=CityBuses(this.loaded_buses);net=this.buses.networks[0];
    if(net.vehicles.len()!=2 || this.buses.pending!=null) throw "Bus save/load failed";
    local visits={},delivered=false;
    for(local day=0;day<1400;day++) {
        this.buses.Review();
        foreach(bus in net.vehicles) if(AIVehicle.IsValidVehicle(bus.id)) {
            local station=AIStation.GetStationID(AIVehicle.GetLocation(bus.id));
            if(AIVehicle.GetState(bus.id)==AIVehicle.VS_AT_STATION && AIStation.IsValidStation(station)) visits[station] <- true;
            if(AIVehicle.GetProfitThisYear(bus.id)>0) delivered=true;
        }
        if(visits.len()>=net.stops.len() && delivered && day>365) break;
        this.Sleep(74);
    }
    if(visits.len()<net.stops.len() || !delivered) throw "Buses did not serve all stops and earn passenger income";
    // A save after starting a bus but before the phase assignment must not
    // toggle that moving bus back to stopped during dispatch recovery.
    local moving=net.vehicles[0];moving.phase="dispatch";
    this.buses=CityBuses(this.buses.Save());net=this.buses.networks[0];
    this.buses.next_review=0;this.buses.Review();
    if(moving.phase!="running" || AIVehicle.GetState(moving.id)==AIVehicle.VS_STOPPED) throw "Started bus dispatch recovery failed";
    // Retire the extra buses so recovery is tested from below the minimum,
    // rather than merely replacing one bus in a large fleet.
    if(net.vehicles.len()<=2 || net.vehicles.len()>12) throw "Demand growth or fleet cap failed";
    for(local i=2;i<net.vehicles.len();i++) net.vehicles[i].phase="sell";
    net.review=AIDate.GetCurrentDate()+1000;
    for(local n=0;n<700 && net.vehicles.len()>2;n++) {this.buses.Review();this.Sleep(74);}
    if(net.vehicles.len()!=2) throw "Surplus retirement failed";
    // A lost bus must be replaced; recover its saved ID as an invalid vehicle.
    local first=net.vehicles[0];
    AIVehicle.SendVehicleToDepot(first.id);
    for(local n=0;n<500 && !AIVehicle.IsStoppedInDepot(first.id);n++) this.Sleep(74);
    if(!AIVehicle.SellVehicle(first.id)) throw "Cannot simulate missing bus";
    net.review=0;this.buses.next_review=0;this.buses.Review();
    if(net.vehicles.len()<2) throw "Fleet recovery failed";
    // Exercise retirement with a save/load while the bus is returning.
    local retired=net.vehicles.top().id;net.vehicles.top().phase="sell";
    this.buses=CityBuses(this.buses.Save());net=this.buses.networks[0];
    net.review=AIDate.GetCurrentDate()+1000;
    for(local n=0;n<700 && AIVehicle.IsValidVehicle(retired);n++) {this.buses.Review();this.Sleep(74);}
    if(AIVehicle.IsValidVehicle(retired)) throw "Pending retirement failed";
    // Exercise real vehicle ageing, replacement purchase and depot sale.
    local old=net.vehicles[0].id;
    while(AIVehicle.GetAgeLeft(old)>170) this.Sleep(74*30);
    net.review=0;this.buses.next_review=0;this.buses.Review();
    local queued=false;foreach(bus in net.vehicles) if(bus.id==old && bus.phase=="sell") queued=true;
    if(!queued) throw "Ageing bus was not replaced";
    net.review=AIDate.GetCurrentDate()+1000;
    for(local n=0;n<700 && AIVehicle.IsValidVehicle(old);n++) {this.buses.Review();this.Sleep(74);}
    if(AIVehicle.IsValidVehicle(old)) throw "Renewed vehicle not sold";
    // Incomplete construction saved before commissioning must be removed,
    // preserving the underlying street.
    local partial=null;
    foreach(t,p in AITownList()) if(t!=net.town) {
        local plan=this.buses.Candidates(t);
        if(plan.sites.len()>0) {partial=plan.sites[0];break;}
    }
    if(partial==null) throw "No rollback test site";
    if(!AIRoad.BuildDriveThroughRoadStation(partial.tile,partial.front,AIRoad.ROADVEHTYPE_BUS,AIStation.STATION_NEW)) throw "Rollback fixture failed";
    this.buses.pending={stops=[partial.tile],depot=null};
    this.buses=CityBuses(this.buses.Save());
    if(!this.buses.Cleanup() || AIRoad.IsRoadStationTile(partial.tile) || !AIRoad.IsRoadTile(partial.tile)) throw "Saved construction cleanup failed";
    // Old saves must still load with no bus data.
    delete saved.buses;this.Load(1,saved);if(this.loaded_buses!=null) throw "Legacy save migration failed";
    AILog.Info("BUSES PASS: coverage, spacing, 4-5 stops, depot, orders, passenger income, every stop visited, fleet recovery, retirement, renewal, rollback and save/load.");
    while(true) this.Sleep(1000);
}
'''

with tempfile.TemporaryDirectory(prefix='openttdai-buses-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'BusCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "BusCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=90)
        (root / 'tests' / f'buses-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'BUSES PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
        assert 'City buses: added capacity' in result.stderr
        assert 'City buses: replacing an ageing bus.' in result.stderr
