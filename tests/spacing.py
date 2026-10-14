"""Isolated live-game additional town station spacing test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SpacingCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_growth_rate':'0'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSpacingCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) { AILog.Error("SPACING FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local checked=0;
    local coverage=AIStation.GetCoverageRadius(AIStation.STATION_TRAIN);
    foreach(town,_ in AITownList()) {
        local sites=this.builder.FindStationSites(town,AITown.GetLocation(town));
        if(sites.len()<2) continue;
        local first=sites[0];
        if(!this.builder.BuildStation(first)) continue;
        local existing=this.builder.ExistingTownStationTiles(town);
        if(existing.len()!=8) { AILog.Error("SPACING FAIL: existing footprint"); return; }
        local close=clone first; close.production=100;
        local far=clone close;
        local x=AIMap.GetTileX(first.tile);
        far.tile=AIMap.GetTileIndex(x<AIMap.GetMapSizeX()/2 ? x+20 : x-20,AIMap.GetTileY(first.tile));
        if(this.builder.StationSpacingScore(close,existing,coverage)>=this.builder.StationSpacingScore(far,existing,coverage)) {
            AILog.Error("SPACING FAIL: distance preference"); return;
        }
        local second=this.builder.FindStationSites(town,AITown.GetLocation(town));
        if(second.len()==0) { this.builder.RemoveStation(first); continue; }
        for(local i=0;i<second.len();i++) {
            if(second[i].spacing_score!=this.builder.StationSpacingScore(second[i],existing,coverage) ||
                (i>0 && second[i].placement_score>second[i-1].placement_score)) {
                AILog.Error("SPACING FAIL: ranked shortlist"); return;
            }
        }
        this.builder.pending_stations=[first];
        if(this.builder.ExistingTownStationTiles(town).len()!=0) { AILog.Error("SPACING FAIL: pending station counted"); return; }
        this.builder.ReleasePendingStations();
        if(++checked==2) break;
    }
    if(checked<1) { AILog.Error("SPACING FAIL: no fixture"); return; }
    AILog.Info("SPACING PASS: owned station footprints detected, greater separation preferred, shortlist ranked, pending reservations excluded.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-spacing-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'SpacingCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "SpacingCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'spacing-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'SPACING PASS:' in result.stderr, 'Spacing checks did not complete'
        assert 'SPACING FAIL:' not in result.stderr
