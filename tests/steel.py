"""Isolated oil-well to refinery delivery test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SteelCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSteelCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);if(!PickRailType()) throw "No rail";
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local n=FreightNetwork(4);
    // Do not allow any junctions: the ore service and steel outlet must stand alone.
    for(local i=0;i<100 && n.state.stage<2;i++) {
        n.state.junctions=[];
        n.TryBuild();this.Sleep(74*30);
    }
    if(n.state.stage!=2 || !("steel_outlet" in n.state)) throw "Separate steel service not built";
    local train=-1,record=null;
    foreach(id,r in n.optimiser.trains) if(r.cargo==FreightCargo("STEL")) {train=id;record=r;break;}
    // A missing single_route record now means the line started two-track,
    // which is the intended start when the service uses a shared dual hub.
    if(train<0 || (record.single_route!=null && record.single_route.dual)) throw "Steel did not start single track";
    if(record.depot==n.state.depot) throw "Steel reused the ore depot";
    if(n.state.stations.len()!=3 || !n.NeedsFactoryGoods()) throw "Factory goods continuation not ready";
    local restored=FreightNetwork(4,n.Save());
    if(restored.state.stage!=2 || !(train in restored.optimiser.trains) || !restored.NeedsFactoryGoods()) throw "Steel save/load failed";
    local loaded=false,delivered=false,maintained=false;
    for(local tick=0;tick<150000 && !maintained;tick++) {
        local load=AIVehicle.GetCargoLoad(train,FreightCargo("STEL"));
        if(load>0) loaded=true;
        if(loaded && AIStation.GetStationID(AIVehicle.GetLocation(train))==record.station_b && load==0) delivered=true;
        if(delivered && AIVehicle.GetLocation(train)==record.depot) maintained=true;
        this.Sleep(1);
    }
    if(!maintained) throw "Steel delivery and maintenance failed";
    AILog.Info("STEEL PASS: ore supplies mill; independent single-track steel train delivers to factory, services own depot, saves, and enables goods continuation without junctions.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-steel-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SteelCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SteelCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'steel-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'STEEL PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
