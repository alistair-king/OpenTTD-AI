"""Isolated live-game multi-AI route selection test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'PopulationCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'max_no_competitors':'2', 'number_towns':'3'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nPopulationCheck = \nPopulationCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.builder=RouteBuilder(4);
    // Begin above every town, forcing the population fallback on a real map.
    local towns=AITownList();
    local highest=0;
    foreach(town,_ in towns) if(AITown.GetPopulation(town)>highest) highest=AITown.GetPopulation(town);
    this.population_threshold=highest+1;
    local initial=this.population_threshold;
    local pair=this.PickTownPair();
    if(pair==null || this.population_threshold>=initial || this.population_threshold<50) {
        AILog.Error("POPULATION FAIL: did not find smaller towns"); return;
    }
    foreach(town in pair) if(AITown.GetPopulation(town)<this.population_threshold) {
        AILog.Error("POPULATION FAIL: threshold violated"); return;
    }
    local threshold=this.population_threshold;
    if(this.PickTownPair()==null || this.population_threshold!=threshold) {
        AILog.Error("POPULATION FAIL: lowered despite available pair"); return;
    }
    local saved=this.Save();
    this.population_threshold=null;
    this.Load(1,saved);
    if(this.population_threshold!=threshold) { AILog.Error("POPULATION FAIL: save/load"); return; }
    local ids=[];
    foreach(town,_ in towns) ids.append(town);
    foreach(a in ids) foreach(b in ids) if(a<b) this.builder.RememberFailure(a,b);
    if(this.PickTownPair()!=null || this.population_threshold!=50 || this.PickTownPair()!=null) {
        AILog.Error("POPULATION FAIL: floor or failed-pair protection"); return;
    }
    this.Load(1,{});
    if(this.population_threshold!=null) { AILog.Error("POPULATION FAIL: legacy save"); return; }
    AILog.Info("POPULATION PASS: gradual relaxation, stable threshold, floor, failure memory and save/load.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-population-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'PopulationCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "PopulationCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=400000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'population-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and result.stderr.count('POPULATION PASS') == 2
        assert 'POPULATION FAIL' not in result.stderr
