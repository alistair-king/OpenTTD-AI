"""Isolated mixed-technology construction test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'RailTypeCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'2050', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nRailTypeCheck = \n', config)
driver = r'''
class RailScopeProbe extends FreightNetwork {
    expected=-1;
    function TryBuildOnRail() {
        if(AIRail.GetCurrentRailType()!=this.expected) throw "Extension used unrelated rail technology";
        return true;
    }
}
function OpenTTDAI::Start()
{
    this.Sleep(1);EnsureMoney(AICompany.GetMaxLoanAmount());
    local old=-1;
    foreach(type,_ in AIRailTypeList()) if(BestEngineSpeedOnRail(type)>0 && (old<0 || type<old)) old=type;
    if(old<0) throw "No legacy rail";
    AIRail.SetCurrentRailType(old);
    local depot=-1;
    for(local x=3;x<AIMap.GetMapSizeX()-4 && depot<0;x++) for(local y=3;y<AIMap.GetMapSizeY()-4 && depot<0;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(AITile.GetSlope(tile)!=AITile.SLOPE_FLAT || !AITile.IsBuildable(tile)) continue;
        if(AIRail.BuildRailDepot(tile,tile+1)) depot=tile;
    }
    if(depot<0) throw "Legacy depot missing";
    local engine=TrainBuyer(PassengerCargo()).BestEngine();
    local train=AIVehicle.BuildVehicle(depot,engine);
    if(train<0) throw "Legacy train missing";
    if(!RailTypeReview()) throw "Legacy fleet blocked new rail selection";
    local modern=AIRail.GetCurrentRailType();
    if(modern==old || AIEngine.CanRunOnRail(engine,modern)) throw "Fixture lacks incompatible new rail";
    local probe=RailScopeProbe(4);probe.state.stage=1;probe.state.depot=depot;probe.expected=old;
    if(!probe.TryBuild() || AIRail.GetCurrentRailType()!=modern) throw "Rail context not restored";
    local new_depot=-1;
    for(local x=3;x<AIMap.GetMapSizeX()-4 && new_depot<0;x++) for(local y=3;y<AIMap.GetMapSizeY()-4 && new_depot<0;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(AITile.GetSlope(tile)!=AITile.SLOPE_FLAT || !AITile.IsBuildable(tile)) continue;
        if(AIRail.BuildRailDepot(tile,tile+1)) new_depot=tile;
    }
    if(new_depot<0 || AIRail.GetRailType(new_depot)!=modern) throw "New depot not modern";
    local modern_engine=TrainBuyer(PassengerCargo()).BestEngine();
    if(AIVehicle.BuildVehicle(new_depot,modern_engine)<0) throw "No compatible modern train";
    if(AIRail.GetRailType(depot)!=old || !AIVehicle.IsValidVehicle(train)) throw "Legacy service changed";
    AILog.Info("RAILTYPE PASS: legacy fleet retained, new technology selected, network extensions scoped, compatible new depot/train built.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-railtype-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'RailTypeCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "RailTypeCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'railtype-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RAILTYPE PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
