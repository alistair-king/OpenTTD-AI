"""Isolated live-game rival station detection and town weighting test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'CompetitionCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'max_no_competitors':'2', 'number_towns':'3'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nCompetitionCheck = \nCompetitionCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) { AILog.Error("COMPETITION FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    local own_town=-1;
    local self=AICompany.ResolveCompanyID(AICompany.COMPANY_SELF);
    local towns=AITownList();
    foreach(town,_ in towns) {
        // Each company takes a different town, avoiding the other's fixture.
        if(town%2 != self%2) continue;
        local centre=AITown.GetLocation(town);
        for(local dx=-8;dx<=8 && own_town<0;dx++) for(local dy=-8;dy<=8 && own_town<0;dy++) {
            local x=AIMap.GetTileX(centre)+dx, y=AIMap.GetTileY(centre)+dy;
            if(x<1 || y<1 || x>=AIMap.GetMapSizeX()-1 || y>=AIMap.GetMapSizeY()-1) continue;
            local tile=AIMap.GetTileIndex(x,y);
            if(!AITile.IsBuildable(tile) || AITile.GetClosestTown(tile)!=town ||
                AITile.GetCargoProduction(tile,PassengerCargo(),1,1,3)<=0) continue;
            if(AIRail.BuildRailStation(tile,AIRail.RAILTRACK_NE_SW,1,1,AIStation.STATION_NEW)) own_town=town;
        }
        if(own_town>=0) break;
    }
    if(own_town<0) { AILog.Error("COMPETITION FAIL: fixture"); return; }
    if(this.HasCompetingStation(own_town)) { AILog.Error("COMPETITION FAIL: own station counted"); return; }
    for(local i=0;i<3000;i++) {
        if(i%20==0) this.competition_cache=null;
        foreach(town,_ in towns) if(town!=own_town && this.HasCompetingStation(town)) {
            if(this.CompetitionWeight(town,500,1000)!=0.1 || this.CompetitionWeight(town,1000,1000)!=0.1 ||
                this.CompetitionWeight(town,2000,1000)!=0.1 || this.CompetitionWeight(own_town,500,1000)!=1.0) {
                AILog.Error("COMPETITION FAIL: competition penalty"); return;
            }
            AILog.Info("COMPETITION PASS: rival detected, own station ignored, small and large towns penalised.");
            while(true) this.Sleep(1000);
        }
        this.Sleep(10);
    }
    AILog.Error("COMPETITION FAIL: no rival found");
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-competition-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'CompetitionCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "CompetitionCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=400000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'competition-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and result.stderr.count('COMPETITION PASS') == 2
        assert 'COMPETITION FAIL' not in result.stderr
