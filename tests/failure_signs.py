"""Live disabled-sign and legacy cleanup regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'FailureSignCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nFailureSignCheck = \n', config)
driver = r'''
function OpenTTDAI::Start() {
    local b=RouteBuilder(4),tile=AIMap.GetTileIndex(10,10);
    local old=AISign.BuildSign(tile,"[VF] To destination");
    local search=AISign.BuildSign(tile,"[VT search] old search");
    local riro=AISign.BuildSign(tile,"RIRO: Terrain unsafe or limit");
    local user_sign=AISign.BuildSign(tile,"Keep my sign");
    if(!AISign.IsValidSign(riro) || !AISign.IsValidSign(old) || !AISign.IsValidSign(search) || !AISign.IsValidSign(user_sign)) throw "Fixture failed";
    b.ClearSearchSigns();
    if(AISign.IsValidSign(riro) || AISign.IsValidSign(old) || AISign.IsValidSign(search) || !AISign.IsValidSign(user_sign)) throw "Cleanup failed";
    b.failure_detail="No destination station site";b.planning_timed_out=true;
    b.LogRouteFailure(tile,"Destination",false);
    RiroFallbackSign(tile,"Return track not separate");
    RiroFallbackSign(tile);
    local count=0;foreach(id,_ in AISignList()) count++;
    if(count!=1) throw "Created a new failure sign";
    AILog.Info("FAILURE SIGNS PASS: old markers removed, user sign preserved, failures only logged.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-failure_signs-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'FailureSignCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "FailureSignCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'failure_signs-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'FAILURE SIGNS PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
