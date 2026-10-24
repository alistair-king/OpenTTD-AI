"""Bus-city passenger and goods priority, scheduling and persistence checks."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'BusRailPriorityCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000', 'initial_city_size':'8', 'larger_towns':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nBusRailPriorityCheck = \n', config)
driver = r'''
::attempts <- [];
::available <- true;
function OpenTTDAI::TryConstructionKind(kind) {attempts.append(kind);return available;}
class GoodsCityProbe extends FreightNetwork {
    destination=-1;
    function ConnectHubOutlet(route,source,target) {this.destination=target;return true;}
}
function OpenTTDAI::Start() {
    this.Sleep(1);PickRailType();EnsureMoney(100000);
    this.builder=RouteBuilder(4);
    local normal=this.PickTownPairAtPopulation(50);
    if(normal==null) throw "Missing town pairs";
    local target=-1;
    foreach(t,_ in AITownList()) {
        if(t==normal[0] || t==normal[1] || AITown.GetPopulation(t)<50) continue;
        foreach(other,_ in AITownList()) if(other!=t && AITown.GetPopulation(other)>=50 &&
            RouteDistanceAllowed(AIMap.DistanceManhattan(AITown.GetLocation(t),AITown.GetLocation(other)))) {target=t;break;}
        if(target>=0) break;
    }
    if(target<0) throw "No alternative passenger city";
    // Saved bus networks rebuild the shared priority registry.
    this.buses=CityBuses({networks=[{town=target}],cooldown={},pending=null});
    local pair=this.PickTownPairAtPopulation(50);
    if(pair==null || (pair[0]!=target && pair[1]!=target)) throw "Bus city did not outrank other passenger pairs";
    foreach(t,_ in AITownList()) if(t!=target) this.builder.RememberFailure(t,target);
    pair=this.PickTownPairAtPopulation(50);
    if(pair==null || pair[0]==target || pair[1]==target) throw "Impossible bus city blocked other passenger work";
    this.TryBuildRoute();this.TryBuildRoute();
    if(attempts.len()!=2 || attempts[0]!="passengers" || attempts[1]!="goods") throw "Bus follow-up turns missing";
    local saved=this.Save();this.Load(1,saved);this.buses=CityBuses(this.loaded_buses);
    if(this.buses.networks[0].rail_followup!=2 || BusCityRailPriority(target)!=1) throw "Priority save/load failed";
    attempts=[];this.TryBuildRoute();if(attempts[0]!="coal") throw "Follow-ups repeated after reload";
    this.buses.networks[0].rail_followup=0;attempts=[];available=false;this.TryBuildRoute();
    local unique={};foreach(kind in attempts) {if(kind in unique) throw "Failed priority retried in normal turn";unique[kind] <- true;}
    if(attempts.len()!=8) throw "Failed follow-ups starved normal categories";
    ::BusRailTowns={};
    local farm=FreightNetwork(4,null,"FARM"),base=farm.PickFarmChain();
    if(base==null) throw "No farm chain fixture";
    local goods=FreightCargo("GOOD"),city=-1;
    foreach(t,_ in AITownList()) {
        if(t==base.city) continue;
        local loc=AITown.GetLocation(t);
        if(IndustryDistanceAllowed(AIMap.DistanceManhattan(AIIndustry.GetLocation(base.factory),loc)) &&
            AITile.GetCargoAcceptance(loc,goods,1,1,6)>=8) {city=t;break;}
    }
    if(city<0) throw "No alternative goods destination";
    BusRailTowns[city] <- true;
    local preferred=farm.PickFarmChain();
    if(preferred==null || preferred.city!=city) throw "Farm chain ignored bus city";
    local outlet=GoodsCityProbe(4,null,"FARM");outlet.state.chain=clone base;
    outlet.TrySeparateGoods(base.factory);
    if(outlet.destination!=city) throw "Factory outlet ignored bus city";
    if(!CityDestinationBetter(city,1,base.city,1000000)) throw "Bus priority is only a score multiplier";
    AILog.Info("BUS RAIL PRIORITY PASS: passenger selection, impossible-city fallback, bounded follow-ups, persistence, farm chains and factory goods destinations.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-bus-rail-priority-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'BusRailPriorityCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "BusRailPriorityCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'bus-rail-priority-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'BUS RAIL PRIORITY PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
