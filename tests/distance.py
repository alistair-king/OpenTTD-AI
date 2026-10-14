"""Isolated endpoint-distance and freight bypass regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'DistanceCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nDistanceCheck = \n', config)
driver = r'''
class DistanceGuardProbe extends CoalRoutes {
    function DestinationValid(target) {return true;}
    function DestinationLocation(target) {return target;}
    function ConnectionPlanKey(source,target) {throw "Out-of-range request reached planning";}
}
function OpenTTDAI::Start() {
    foreach(d in [0,1,49,151,300]) if(RouteDistanceAllowed(d)) throw "Bad distance accepted";
    foreach(d in [50,51,100,149,150]) if(!RouteDistanceAllowed(d)) throw "Valid distance rejected";
    local a=AIMap.GetTileIndex(20,20),b=AIMap.GetTileIndex(45,45);
    if(!RouteEndpointsAllowed(a,b)) throw "Diagonal Manhattan boundary rejected";
    if(RouteEndpointsAllowed(a,AIMap.GetTileIndex(44,45))) throw "Short diagonal accepted";
    local probe=DistanceGuardProbe(RouteBuilder(4)),count=0;
    foreach(i,_ in AIIndustryList()) {
        if(probe.Connect(i,AIIndustry.GetLocation(i))) throw "Short direct route accepted";
        count++;
    }
    if(count==0) throw "No industries tested";
    local network=FreightNetwork(4);
    local chain=network.PickFarmChain();
    if(chain==null) throw "No eligible farm chain in fixture";
    if(!RouteEndpointsAllowed(AIIndustry.GetLocation(chain.mine),AIIndustry.GetLocation(chain.factory)) ||
        !RouteEndpointsAllowed(AIIndustry.GetLocation(chain.factory),AITown.GetLocation(chain.city))) throw "Short farm/goods selection";
    // An old saved chain must also be rejected before looking up its stations or junctions.
    network.state.chain=chain;
    network.state.stage=1;
    if(network.BuildBranchWithinBudget(chain.factory,true,FreightCargo("GRAI"),true)) throw "Short farm branch accepted";
    AILog.Info("DISTANCE PASS: boundaries, diagonals, direct requests, farm/goods selection and saved branch guard.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-distance-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'DistanceCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "DistanceCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'distance-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'DISTANCE PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
