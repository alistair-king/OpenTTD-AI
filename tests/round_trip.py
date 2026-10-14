"""Expansion scheduling and backwards-compatible multi-network regression tests."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'TripCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nTripCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    local o=ServiceOptimiser(TrainBuyer(PassengerCargo()));
    local r={station_a=10,station_b=20};
    if(o.TripDays(r)!=30) throw "Missing legacy default";
    o.TripSample(r,100,10,false);
    o.TripSample(r,101,-1,true);
    o.TripSample(r,120,20,false);
    o.TripSample(r,155,10,false);
    o.TripSample(r,161,-1,true);
    if(o.TripDays(r)!=60) throw "Round trip not measured departure to departure";
    o.TripSample(r,170,10,false);o.TripSample(r,171,-1,true);
    if(o.TripDays(r)!=60) throw "Incomplete trip changed estimate";
    o.TripSample(r,180,20,false);o.TripSample(r,200,10,false);
    o.TripSample(r,211,-1,true);
    if(o.TripDays(r)!=55) throw "Smoothing incorrect";
    PickRailType();EnsureMoney(500000);
    local depot=-1;
    for(local y=10;y<100 && depot<0;y++) for(local x=10;x<100 && depot<0;x++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(AreaIsBuildable(tile,2,1) && AIRail.BuildRailDepot(tile,tile+1)) depot=tile;
    }
    if(depot<0) throw "No depot fixture";
    local buyer=TrainBuyer(PassengerCargo()),wagon=buyer.BestWagon();
    local id=AIVehicle.BuildVehicle(depot,buyer.BestEngine());
    local carriage=AIVehicle.BuildVehicle(depot,wagon);
    if(!AIVehicle.IsValidVehicle(id) || !AIVehicle.IsValidVehicle(carriage) ||
        !AIVehicle.MoveWagon(carriage,0,id,AIVehicle.GetNumWagons(id)-1)) throw "No capacity fixture";
    local route={station_a=10,station_b=20,depot=depot,cargo=buyer.cargo,trip_days=30};
    o.trains[id] <- route;
    local cap=AIVehicle.GetCapacity(id,buyer.cargo);
    if(o.MonthlyCapacity(route,buyer.cargo)!=cap) throw "Monthly capacity wrong";
    route.trip_days=60;
    if(o.MonthlyCapacity(route,buyer.cargo)!=cap/2) throw "Long trip did not reduce monthly throughput";
    if(o.MonthlyCapacity(route,FreightCargo("LVST"))!=0) throw "Different cargo counted";
    local saved=clone r;
    o.TripSample(saved,220,20,false);o.TripSample(saved,260,10,false);o.TripSample(saved,271,-1,true);
    if(saved.trip_days!=56) throw "Retained timer not usable after saving";
    AILog.Info("PRODUCTION PASS: round-trip measurement, complete-cycle gating, integer smoothing and legacy fallback.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-round-trip-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'TripCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "TripCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'round-trip-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PRODUCTION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
