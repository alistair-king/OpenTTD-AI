"""Progressive industry production thresholds and save/load regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ProductionRelaxCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'2050', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nProductionRelaxCheck = \n', config)
driver = r'''
class ExhaustedCoal extends CoalRoutes {
    scans=0;
    function PickPair() {this.scans++;return null;}
}
class ExhaustedFarms extends FreightNetwork {
    function PickFreshChain() {return null;}
}
class AvailableFarms extends FreightNetwork {
    function PickFreshChain() {return {mine=1};}
}
function OpenTTDAI::Start() {
    this.Sleep(1);PickRailType();
    local policy=IndustryProductionPolicy();
    foreach(percent in [75,50,25,10]) {
        policy.next_relax=0;
        if(!RelaxIndustryProduction(policy,"Test") || policy.percent!=percent) throw "Wrong exhaustion step";
        if(RelaxIndustryProduction(policy,"Test")) throw "Threshold dropped twice in one month";
    }
    policy.next_relax=0;
    if(RelaxIndustryProduction(policy,"Test") || IndustryProductionMinimum(policy,1)!=1) throw "Threshold floor broken";
    local coal=ExhaustedCoal(RouteBuilder(4));
    foreach(minimum in [75,50,25,10]) {
        coal.retry_after=0;coal.production_policy.next_relax=0;
        if(coal.TryBuild()) throw "Empty coal search claimed construction";
        if(IndustryProductionMinimum(coal.production_policy,100)!=minimum) throw "Coal did not relax";
        local scans=coal.scans;coal.TryBuild();
        if(coal.scans!=scans) throw "Coal rescanned during cooldown";
    }
    coal.retry_after=0;coal.TryBuild();
    if(coal.scans!=5 || coal.phase) throw "Final coal threshold never scanned";
    local loaded=CoalRoutes(RouteBuilder(4),coal.Save());
    if(loaded.production_policy.percent!=10) throw "Coal threshold lost";
    local legacy=coal.Save();delete legacy.production_policy;
    if(CoalRoutes(RouteBuilder(4),legacy).production_policy.percent!=100) throw "Legacy coal default";
    local manager=FreightNetworks(4);
    local farm=ExhaustedFarms(4,null,"FARM");
    farm.state.production_policy=manager.production_policy;manager.networks.append(farm);
    if(farm.FarmProductionEligible(50,50) || !farm.FarmProductionEligible(51,0)) throw "Original farm boundary changed";
    farm.PickChain();
    if(!farm.FarmProductionEligible(39,0) || farm.FarmProductionEligible(38,38)) throw "Relaxed farm boundary incorrect";
    if(manager.networks[0].state.production_policy.percent!=75) throw "Existing hub threshold not shared";
    local restored=FreightNetworks(4,manager.Save());
    if(restored.production_policy.percent!=75 || restored.networks[0].state.production_policy.percent!=75) throw "Farm threshold lost";
    local fresh=restored.NewNetwork();
    if(fresh.state.production_policy.percent!=75) throw "New network reset threshold";
    local available=AvailableFarms(4,null,"FARM");
    if(available.PickChain()==null || available.state.production_policy.percent!=100) throw "Usable routes lowered threshold";
    foreach(label in ["IORE","WOOD"]) {
        local other=ExhaustedCoal(RouteBuilder(4),null,label);
        other.TryBuild();if(other.production_policy.percent!=100) throw "Already minimal cargo relaxed";
    }
    // Oil's base threshold is 100,000 units/month; it relaxes like coal.
    if(CoalRoutes(RouteBuilder(4),null,"OIL_").minimum_production!=100000) throw "Oil threshold default wrong";
    local oil=ExhaustedCoal(RouteBuilder(4),null,"OIL_");
    foreach(minimum in [75000,50000,25000,10000]) {
        oil.retry_after=0;oil.production_policy.next_relax=0;
        if(oil.TryBuild()) throw "Empty oil search claimed construction";
        if(IndustryProductionMinimum(oil.production_policy,100000)!=minimum) throw "Oil did not relax";
        local scans=oil.scans;oil.TryBuild();
        if(oil.scans!=scans) throw "Oil rescanned during cooldown";
    }
    AILog.Info("PRODUCTION RELAX PASS: staged monthly relaxation, final scan, shared farm thresholds, cargo floors and save/load.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-rotation-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ProductionRelaxCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ProductionRelaxCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'production-relax-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PRODUCTION RELAX PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
