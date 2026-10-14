"""Ore feeder selection, scheduling, connected-component and save/load regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
wood = "--wood" in sys.argv
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'OreFeederCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nOreFeederCheck = \n', config)
driver = r'''
function OreCopy(value) {
    if(typeof value=="array") {local r=[];foreach(v in value) r.append(OreCopy(v));return r;}
    if(typeof value=="table") {local r={};foreach(k,v in value) r[k] <- OreCopy(v);return r;}
    if(typeof value=="instance" || typeof value=="float") throw "Unsupported save data";
    return value;
}
class OreSchedulerProbe extends FreightNetwork {
    called=false;
    function TryBuild() {this.called=true;return true;}
}
class OreJunctionProbe extends FreightNetwork {
    function JunctionCandidates(segment) {return [{tile=20,segment=99,used=false},{tile=30,segment=99,used=false}];}
}
class OreSelectionProbe extends FreightNetwork {
    selected=-1;
    function FeederSiteValid(site,cargo,loading) {return true;}
    function RestoreOreJunctions() {}
    function BuildBranch(target,industry,cargo,farm=false) {
        if(!industry || !farm || cargo!=FreightCargo("IORE")) throw "Wrong incoming branch mode";
        this.selected=target;return true;
    }
}
function OpenTTDAI::Start() {
    this.Sleep(1);PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local probe=OreSchedulerProbe(4),manager=FreightNetworks(4);
    probe.state.stage=3;probe.state.chain={mine=9,mill=10,factory=11,city=0};
    probe.state.mines <- {[12]={tile=100,dir=0,depot=101}};
    manager.networks=[probe];
    if(!manager.TryBuildOre() || !probe.called || !(12 in probe.excluded_sources)) throw "Completed ore network skipped or mine duplicated";
    local migration=OreJunctionProbe(4);
    migration.state.segments=[{}];migration.state.junctions=[{tile=20,segment=0,used=true}];
    migration.RestoreOreJunctions();migration.RestoreOreJunctions();
    if(migration.state.junctions.len()!=2 || !migration.state.junctions[0].used || migration.state.junctions[1].segment!=0)
        throw "Old ore junction recovery duplicated or reopened used junctions";
    local n=FreightNetwork(4),cargo=FreightCargo("IORE");
    n.state.stations=[{tile=10},{tile=20},{tile=30}];
    n.state.stage=3;n.state.chain={mine=0,mill=1,factory=2};
    n.state.segments=[{goal_station=20},{goal_station=30},{goal_station=40,parent_segment=0}];
    if(n.BranchNetworkStation(true,cargo)!=20 || n.BranchNetworkStation(true)!=30 ||
        n.FeederIndustry(cargo)!=1 || n.FeederCargoes(cargo).len()!=1 || n.FeederCargoes(FreightCargo("GRAI")).len()!=2)
        throw "Ore feeder inherited farm destination/cargo";
    if(n.StationRoot(20)!=0 || n.StationRoot(30)!=1 || n.StationRoot(40)!=0) throw "Disconnected tracks confused";
    // Exercise selection against real industries; isolate path construction
    // so random maps without a long parallel junction don't invalidate this test.
    local mines=[],mill=-1;
    foreach(i,_ in AIIndustryList()) {
        if(AIIndustry.GetLastMonthProduction(i,cargo)>0) mines.append(i);
        if(AIIndustry.IsCargoAccepted(i,cargo)==AIIndustry.CAS_ACCEPTED) mill=i;
    }
    if(mines.len()<3 || mill<0) throw "Industry fixture insufficient: sources="+mines.len();
    local pair=null;
    foreach(i,_ in AIIndustryList()) if(AIIndustry.IsCargoAccepted(i,cargo)==AIIndustry.CAS_ACCEPTED) {
        local eligible=[];
        foreach(mine in mines) if(IndustryEndpointsAllowed(AIIndustry.GetLocation(mine),AIIndustry.GetLocation(i))) eligible.append(mine);
        if(eligible.len()>=2) {pair={mill=i,mines=eligible};break;}
    }
    if(pair==null) throw "No multi-mine fixture";
    local feeder=OreSelectionProbe(4);
    feeder.state.stage=3;feeder.state.chain={mine=pair.mines[0],mill=pair.mill,factory=pair.mill,city=0};
    feeder.state.stations=[{tile=10},{tile=AIIndustry.GetLocation(pair.mill),dir=0}];
    feeder.state.segments=[{goal_station=feeder.state.stations[1].tile},{goal_station=30}];
    feeder.state.junctions=[{segment=0,used=false}];
    // Build a real depot to supply the network's rail type for distance policy.
    local depot=-1;
    foreach(t,_ in AITileList_IndustryAccepting(pair.mill,4)) {
        if(AITile.IsBuildable(t) && AITile.IsBuildable(t+1) && AIRail.BuildRailDepot(t,t+1)) {depot=t;break;}
    }
    if(depot<0) throw "No test depot";
    feeder.state.depot=depot;
    if(!feeder.TryOreFeeder() || feeder.selected==pair.mines[0]) throw "Additional mine not selected";
    local selected=feeder.selected;
    feeder.excluded_sources={[selected]=true};feeder.selected=-1;
    feeder.TryOreFeeder();if(feeder.selected==selected) throw "Sibling mine selected twice";
    feeder.excluded_sources=null;feeder.state.mines[selected] <- {tile=100,dir=0,depot=depot};feeder.selected=-1;
    feeder.TryOreFeeder();if(feeder.selected==selected) throw "Own mine selected twice";
    local saved=OreCopy(feeder.Save()),restored=FreightNetwork(4,saved);
    if(!(selected in restored.state.mines)) throw "Mine ownership lost on load";
    delete feeder.state.mines[selected];
    feeder.excluded_sources={};foreach(mine in pair.mines) if(mine!=selected) feeder.excluded_sources[mine] <- true;
    feeder.state.failed[feeder.FeederKey(selected,cargo)] <- AIDate.GetCurrentDate()+30;feeder.selected=-1;
    feeder.TryOreFeeder();if(feeder.selected==selected) throw "Retry ignored cooldown";
    feeder.state.failed[feeder.FeederKey(selected,cargo)]=AIDate.GetCurrentDate()-1;
    if(!feeder.TryOreFeeder() || feeder.selected!=selected) throw "Expired cooldown never retried";
    feeder.state.junctions=[{segment=1,used=false}];feeder.selected=-1;
    if(feeder.TryOreFeeder() || feeder.selected!=-1) throw "Ore fed disconnected steel outlet";
    feeder.state.junctions=[{segment=0,used=false}];feeder.state.plan <- {farm=selected,cargo=cargo};
    if(feeder.TryOreFeeder()) throw "In-progress branch replaced";
    AILog.Info("ORE FEEDER PASS: scheduling, cargo/destination, component separation, source exclusions, cooldowns and save/load.");
    while(true) this.Sleep(1000);
}
'''
if wood:
    config = re.sub(r'^multiple_industry_per_town = .*$', 'multiple_industry_per_town = true', config, flags=re.M)
    config = re.sub(r'^industry_density = .*$', 'industry_density = 5', config, flags=re.M)
    driver = driver.replace('"IORE"', '"WOOD"').replace('TryBuildOre()', 'TryBuild("WOOD")').replace('TryOreFeeder()', 'TryIndustryFeeder()')
    for cls in ['OreSchedulerProbe', 'FreightNetworks', 'FreightNetwork', 'OreSelectionProbe']:
        driver = driver.replace(cls+'(4)', cls+'(4,null,"WOOD")')
    driver = driver.replace('.state.mines', '.state.forests').replace(' in restored.state.mines', ' in restored.state.forests')
    driver = driver.replace('stage=3', 'stage=2').replace('factory=pair.mill,', '')
    driver = driver.replace('ORE FEEDER PASS:', 'WOOD FEEDER PASS:')
with tempfile.TemporaryDirectory(prefix='openttdai-feeder-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'OreFeederCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "OreFeederCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'{"wood" if wood else "ore"}-feeder-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and ('WOOD FEEDER PASS:' if wood else 'ORE FEEDER PASS:') in result.stderr
        assert 'Your script made an error' not in result.stderr
