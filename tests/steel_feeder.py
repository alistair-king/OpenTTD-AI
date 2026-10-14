"""Steel feeders share a factory's existing grain/livestock input line."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SteelFeederCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSteelFeederCheck = \n', config)
driver = r'''
class FarmBranchProbe extends FreightNetwork {
    calls=0;got_target=-1;got_cargo=-1;
    source_label="FARM";
    function FeederSiteValid(site,cargo,loading) {return true;}
    function BuildBranch(target,industry,cargo,farm=false) {
        if(!industry || !farm || cargo!=FreightCargo("STEL")) throw "Steel feeder built a wrong branch";
        this.calls++;this.got_target=target;this.got_cargo=cargo;
        return true;
    }
}
function OpenTTDAI::Start() {
    this.Sleep(1);PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local n=FreightNetwork(4),cargo=FreightCargo("STEL");
    n.state.chain={mine=0,mill=1,factory=2,city=0};
    n.state.stage=1;
    n.state.stations=[{tile=10},{tile=20},{tile=30}];
    if(!n.IsSteelFeeder(cargo) || n.IsSteelFeeder(FreightCargo("GRAI"))) throw "Steel feeder cargo flag wrong";
    if(n.FeederSources(cargo)!="mills") throw "Steel feeder source field wrong";
    if(n.FeederStationIndex(cargo)!=n.FactoryIndex()) throw "Steel feeder must deliver to the factory station";
    if(n.FeederIndustry(cargo)!=2) throw "Steel feeder industry must be the factory";
    if(n.FeederCargoes(cargo).len()!=1) throw "Steel feeder must not inherit farm cargoes";
    if(n.FeederKey(7,cargo).slice(0,10)!="steel-feed") throw "Steel feeder key wrong";
    local mill=-1;
    foreach(i,_ in AIIndustryList()) if(AIIndustry.IsValidIndustry(i)) {mill=i;break;}
    if(mill<0) throw "No industry on this map";
    // The IORE network hands the mill to a farm sibling's input line.
    local farm=FarmBranchProbe(4);
    farm.source_label="FARM";
    farm.state.chain={mine=5,mill=2,factory=2,city=0};
    farm.state.stage=2;
    farm.state.stations=[{tile=10},{tile=20}];
    local ore=FreightNetwork(4);
    ore.source_label="IORE";
    local shared=[];
    shared.append(farm);shared.append(ore);
    farm.siblings=shared;ore.siblings=shared;
    ore.state.chain={mine=6,mill=7,factory=2,city=0};
    ore.state.stage=1;
    if(!ore.TrySteelDelivery(mill,2)) throw "Steel delivery did not use the farm input line";
    if(farm.calls!=1 || farm.got_target!=mill || farm.got_cargo!=cargo) throw "Feeder branch built for the wrong mill or cargo";
    if(ore.state.stage!=2) throw "Steel feeder did not advance the ore chain to goods";
    // A factory without a farm input line falls back to the separate line.
    local ore2=FreightNetwork(4);
    ore2.source_label="IORE";ore2.siblings=shared;
    ore2.state.chain={mine=6,mill=7,factory=3,city=0};
    ore2.state.stage=1;
    if(ore2.TrySteelDelivery(mill,3)) throw "Steel delivery matched a factory with no farm line";
    // A mill that already feeds the line is not fed twice.
    farm.state.mills <- {[mill]={tile=0,dir=0,depot=0}};
    if(ore.TrySteelDelivery(mill,2)) throw "Steel feeder ran twice for the same mill";
    AILog.Info("STEEL FEEDER PASS: steel joins the shared factory input line; separate line kept as fallback.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-steel-feeder-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SteelFeederCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SteelFeederCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=120)
        (root / 'tests' / f'steel_feeder-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-2500:], flush=True)
        assert result.returncode == 0 and 'STEEL FEEDER PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
