"""Isolated live-game earthworks test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'TerrainCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'6', 'map_y':'6', 'max_no_competitors':'1', 'starting_year':'1950', 'inflation':'false', 'max_loan':'500000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nTerrainCheck = \n', config)
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
    local snapshot = {};
    for (local dx = -6; dx <= 6; dx++) for (local dy = -6; dy <= 6; dy++) {
        local tile = center + dx + dy*AIMap.GetMapSizeX();
        snapshot[tile] <- AITile.GetCornerHeight(tile, AITile.CORNER_N);
    }
    // With cash below the reserve but loan headroom, Apply must borrow.
    local interval=AICompany.GetLoanInterval();
    local loan=(AICompany.GetLoanAmount()-AICompany.GetBankBalance(AICompany.COMPANY_SELF)+50000)/interval*interval;
    if(loan<0 || !AICompany.SetLoanAmount(loan)) throw "Low-cash fixture failed";
    local borrowing=PairedTerrain(3,96,40000);
    if(!borrowing.SetHeight(center,snapshot[center]+1) || !borrowing.Apply()) throw "Available loan headroom ignored";
    if(AICompany.GetLoanAmount()<=loan) throw "Borrowing was not exercised";
    if(!borrowing.Restore()) throw "Borrowing fixture restoration failed";
    local capped=PairedTerrain(3,96,0);
    if(!capped.SetHeight(center,snapshot[center]+1) || capped.Apply() || capped.failure_reason!="Earthworks cost limit") throw "Cost-limit reason incorrect";
    foreach(tile,old in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=old) throw "Rejected budget changed terrain";
    foreach (change in [2,-2,3]) {
        local terrain = change==3 ? PairedTerrain(3,96,40000) : PairedTerrain();
        if (!terrain.SetHeight(center, snapshot[center]+change) || !terrain.Apply()) {
            AILog.Error("EARTHWORK FAIL: apply " + change); return;
        }
        if (AITile.GetCornerHeight(center, AITile.CORNER_N) != snapshot[center]+change) {
            AILog.Error("EARTHWORK FAIL: height"); return;
        }
        foreach (tile, old in snapshot) {
            local actual = AITile.GetCornerHeight(tile, AITile.CORNER_N);
            if (Abs(actual-old)>Abs(change) || (!(tile in terrain.targets) && actual != old)) {
                AILog.Error("EARTHWORK FAIL: unplanned propagation"); return;
            }
        }
        if (!terrain.Restore()) { AILog.Error("EARTHWORK FAIL: restore"); return; }
        foreach (tile, old in snapshot) if (AITile.GetCornerHeight(tile, AITile.CORNER_N) != old) {
            AILog.Error("EARTHWORK FAIL: restoration mismatch"); return;
        }
    }
    local bounded = PairedTerrain();
    if (bounded.SetHeight(center, snapshot[center]+3)) { AILog.Error("EARTHWORK FAIL: limit"); return; }
    bounded.Protect([center]);
    if (bounded.SetHeight(center, snapshot[center]+1)) { AILog.Error("EARTHWORK FAIL: protected corner"); return; }
    AILog.Info("EARTHWORK PASS: raise/lower two levels, optional three-level route allowance, bounded propagation, exact restoration, protected corners.");
    while (true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-terrain-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'TerrainCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "TerrainCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'earthworks-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'EARTHWORK PASS:' in result.stderr, 'Terrain checks did not complete'
        assert 'EARTHWORK FAIL:' not in result.stderr
