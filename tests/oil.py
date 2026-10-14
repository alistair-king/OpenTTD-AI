"""Isolated oil-well to refinery delivery test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'OilCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nOilCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);if(!PickRailType()) throw "No rail";
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);this.oil=CoalRoutes(this.builder,null,"OIL_");
    if(this.oil.cargo<0 || this.oil.output_label!="GOOD" || !this.oil.single_first) throw "Oil configuration missing";
    if(this.oil.minimum_production!=100000) throw "Oil production threshold default wrong";
    local best=0;
    foreach(i,_ in AIIndustryList()) {
        local m=AIIndustry.GetLastMonthProduction(i,this.oil.cargo);
        if(m>best && !AIIndustry.IsBuiltOnWater(i)) best=m;
    }
    if(best==0) throw "No land oil well on this map";
    AILog.Info("OIL PROBE: best land well produces "+best+" units/month");
    // The initial 100,000-unit threshold must reject a young map's wells.
    this.oil.TryBuild();
    if(this.oil.services.len()>0) throw "Service built below the initial production threshold";
    // Eligibility passes (production relaxation) lower the bar to the well's
    // actual output; the route then builds to that well.
    this.oil.minimum_production=best;
    for(local i=0;i<100 && this.oil.services.len()==0;i++) {
        this.oil.TryBuild();this.Sleep(74*30);
    }
    if(this.oil.services.len()==0) throw "No oil service";
    local train=-1;foreach(id,_ in this.oil.services) {train=id;break;}
    local service=this.oil.services[train],record=this.oil.optimiser.trains[train];
    if(AIIndustry.IsBuiltOnWater(service.source) || !this.oil.IsDestination(service.target)) throw "Wrong oil endpoints";
    if(record.single_route==null || record.single_route.dual) throw "Oil not single track";
    if(AIVehicle.GetCapacity(train,this.oil.cargo)<=0 || AIVehicle.GetCapacity(train,PassengerCargo())>0) throw "Wrong wagons";
    local loaded=false,delivered=false,maintained=false;
    for(local tick=0;tick<100000 && !maintained;tick++) {
        local load=AIVehicle.GetCargoLoad(train,this.oil.cargo);
        if(load>0) loaded=true;
        if(loaded && AIStation.GetStationID(AIVehicle.GetLocation(train))==record.station_b && load==0) delivered=true;
        if(delivered && AIVehicle.GetLocation(train)==service.depot) maintained=true;
        this.Sleep(1);
    }
    if(!maintained) throw "Oil delivery/maintenance failed";
    this.Load(1,this.Save());
    local restored=CoalRoutes(this.builder,this.loaded_oil,"OIL_");
    if(!(train in restored.services) || !(train in restored.optimiser.trains) ||
        restored.optimiser.trains[train].single_route==null) throw "Oil save/load failed";
    restored.OnIndustryClosed(service.source);
    if(!("industry_closed" in restored.optimiser.trains[train]) ||
        !restored.optimiser.trains[train].industry_closed) throw "Closed well not retired";
    AILog.Info("OIL PASS: well to refinery, oil wagons, single track, delivery, maintenance and save/load.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-oil-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'OilCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "OilCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'oil-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'OIL PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
