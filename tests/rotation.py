"""Isolated construction rotation and save/load regression test."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'RotationCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nRotationCheck = \n', config)
driver = r'''
::chosen <- [];
::available <- true;
function OpenTTDAI::TryConstructionKind(kind) {chosen.append(kind);return available;}
function OpenTTDAI::Start() {
    local expected=["coal","goods","farm","ore","farm","passengers","farm","wood","passengers","buses",
        "coal","goods","farm","ore","farm","passengers","farm","wood","passengers","buses","oil"];
    for(local i=0;i<63;i++) {
        this.TryBuildRoute();
        if(chosen.top()!=expected[i%21]) throw "Priority starvation/incorrect weight";
        this.Load(1,this.Save()); // Cursor must survive reloading every turn.
    }
    available=false;chosen=[];this.TryBuildRoute();
    if(chosen.len()!=8) throw "Unavailable categories retried within same turn";
    local unique={};foreach(k in chosen) {if(k in unique) throw "Duplicate attempt";unique[k] <- true;}
    local legacy=this.Save();delete legacy.construction_cursor;this.Load(1,legacy);
    if(this.construction_cursor!=0) throw "Old save migration failed";
    if(FreightNetwork(4).builder.start_run!=3) throw "Long mandatory freight departure remains";
    AILog.Info("ROTATION PASS: repeated failed attempts cannot starve categories; weights, unavailable work, save/load and freight departures checked.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-rotation-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'RotationCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "RotationCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'rotation-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'ROTATION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
