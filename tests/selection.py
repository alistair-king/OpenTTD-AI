"""Isolated live-game multi-AI route selection test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SelectionCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'max_no_competitors':'2', 'number_towns':'3'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSelectionCheck = \nSelectionCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1 + AIBase.RandRange(150));
    this.builder=RouteBuilder(4);
    local selection_ticks=0;
    for(local i=0;i<30;i++) {
        local started=AIController.GetTick();
        local pair=this.PickTownPair();
        selection_ticks+=AIController.GetTick()-started;
        if(pair!=null) {
            local distance=AIMap.DistanceManhattan(AITown.GetLocation(pair[0]),AITown.GetLocation(pair[1]));
            if(!RouteDistanceAllowed(distance) || this.builder.ConnectionFailed(pair[0],pair[1]) || this.builder.ConnectionBuilt(pair[0],pair[1])) {
                AILog.Error("SELECTION FAIL: ineligible pair"); return;
            }
            AILog.Info("SELECTION PICK "+pair[0]+":"+pair[1]);
        }
        this.Sleep(5);
    }
    AILog.Info("SELECTION TIMING: "+selection_ticks+" AI ticks for 30 selections.");
    AILog.Info("SELECTION PASS");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-selection-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SelectionCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SelectionCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=400000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'selection-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and result.stderr.count('SELECTION PASS') == 2
        picks = {}
        for company, pair in re.findall(r'\[(\d+)\] \[I\] SELECTION PICK ([0-9:]+)', result.stderr):
            picks.setdefault(company, []).append(pair)
        assert len(picks) == 2 and all(len(set(sequence)) > 1 for sequence in picks.values())
        first, second = list(picks.values())
        assert first != second, 'Both companies used identical route choices'
