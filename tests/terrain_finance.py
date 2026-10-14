"""Isolated live-game earthworks test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'TerrainFinanceCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'6', 'map_y':'6', 'max_no_competitors':'1', 'starting_year':'1950', 'inflation':'false', 'max_loan':'500000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nTerrainFinanceCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local center = null;
    for (local x = 8; x < AIMap.GetMapSizeX()-8 && center == null; x++) {
        for (local y = 8; y < AIMap.GetMapSizeY()-8 && center == null; y++) {
            local tile = AIMap.GetTileIndex(x,y);
            if (AITile.GetCornerHeight(tile, AITile.CORNER_N) < 3) continue;
            local clear = true;
            for (local dx = -5; dx <= 5; dx++) for (local dy = -5; dy <= 5; dy++) {
                local near = AIMap.GetTileIndex(x+dx,y+dy);
                if (!AITile.IsBuildable(near) || AITile.IsWaterTile(near)) clear = false;
            }
            if (clear) center = tile;
        }
    }
    if (center == null) { AILog.Error("EARTHWORK FAIL: no fixture"); return; }
    // Prepare a flat test patch so the minor adjustment moves only one corner.
    local w=AIMap.GetMapSizeX();
    if(!AITile.LevelTiles(center-3-3*w,center+3+3*w)) throw "Could not level fixture";
    local snapshot = {};
    for (local dx = -6; dx <= 6; dx++) for (local dy = -6; dy <= 6; dy++) {
        local tile = center + dx + dy*AIMap.GetMapSizeX();
        snapshot[tile] <- AITile.GetCornerHeight(tile, AITile.CORNER_N);
    }
    foreach(sample in [[0,499999,false],[0,500000,true],[1,1000000,false],[100000,5000000,false]])
        if(EarthworksFinanciallyReady(sample[0],sample[1])!=sample[2]) throw "Finance threshold incorrect";
    if(EarthworksFinanciallyReady(0,510000,10001) || !EarthworksFinanciallyReady(0,510000,10000)) throw "Reserve boundary incorrect";
    if(AICompany.GetLoanAmount()<=0) throw "Fixture must have outstanding debt";
    local small=PairedTerrain(4,160,60000);
    if(small.max_change!=1 || small.max_corners!=16 || small.max_cost!=5000) throw "Startup limits not applied";
    if(small.SetHeight(center,snapshot[center]+2)) throw "Large planning change accepted with debt";
    // A previously saved, ambitious plan cannot bypass the execution guard.
    local stale=PairedTerrain(4,160,60000);
    stale.targets[center] <- snapshot[center]+2;
    local loan=AICompany.GetLoanAmount();
    if(stale.Apply() || stale.failure_reason!="Wait for debt-free cash") throw "Cached intensive plan accepted";
    if(AICompany.GetLoanAmount()!=loan) throw "Borrowed for intensive work";
    foreach(tile,old in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=old) throw "Rejected plan changed terrain";
    // Minor affordable adjustments remain possible, and rollback is unrestricted.
    local minor=PairedTerrain(4,160,60000);
    if(!minor.SetHeight(center,snapshot[center]+1) || !minor.Apply()) throw "Minor terrain work rejected";
    if(!minor.Restore()) throw "Minor rollback failed";
    foreach(tile,old in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=old) throw "Rollback mismatch";
    AILog.Info("EARTHWORK PASS: loan/cash boundaries, reserve, startup limits, cached-plan rejection, minor work and rollback.");
    while (true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-terrain-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'TerrainFinanceCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "TerrainFinanceCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'terrain-finance-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'EARTHWORK PASS:' in result.stderr, 'Terrain checks did not complete'
        assert 'EARTHWORK FAIL:' not in result.stderr
