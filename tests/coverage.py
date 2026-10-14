"""Isolated live-game passenger coverage ranking test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'CoverageCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_growth_rate':'0'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nCoverageCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) { AILog.Error("COVERAGE FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local checked=0;
    foreach(town,_ in AITownList()) {
        local sites=this.builder.FindStationSites(town,AITown.GetLocation(town));
        if(sites.len()<2) continue;
        this.builder.station_evaluations={};
        this.builder.station_shortlists={};
        local cached=this.builder.FindStationSites(town,AITown.GetLocation(town));
        local again=this.builder.FindStationSites(town,AITown.GetLocation(town));
        if(cached.len()!=sites.len() || again.len()!=sites.len()) { AILog.Error("COVERAGE FAIL: cache length"); return; }
        for(local k=0;k<sites.len();k++) if(sites[k].tile!=again[k].tile || sites[k].dir!=again[k].dir || sites[k].production!=again[k].production) {
            AILog.Error("COVERAGE FAIL: cache changed ranking"); return;
        }
        this.builder.station_evaluations=null;
        this.builder.station_shortlists=null;
        for(local i=0;i<sites.len();i++) {
            local site=sites[i];
            local size=StationFootprint(site.dir,4);
            local actual=AITile.GetCargoProduction(site.tile,PassengerCargo(),size[0],size[1],AIStation.GetCoverageRadius(AIStation.STATION_TRAIN));
            if(actual!=site.production || actual<=0) { AILog.Error("COVERAGE FAIL: footprint coverage"); return; }
            if(i>0 && (site.placement_score>sites[i-1].placement_score ||
                (site.placement_score==sites[i-1].placement_score && site.center_distance<sites[i-1].center_distance))) {
                AILog.Error("COVERAGE FAIL: ranking"); return;
            }
        }
        local centre=AITown.GetLocation(town);
        local target=AIMap.GetTileIndex(AIMap.GetTileX(centre)<AIMap.GetMapSizeX()/2 ? AIMap.GetMapSizeX()-2 : 1,AIMap.GetTileY(centre));
        // Reuse one cache while switching between facing and unrestricted passes.
        this.builder.station_evaluations={}; this.builder.station_shortlists={};
        this.builder.FindStationSites(town,target,null,null,false);
        local facing=this.builder.FindStationSites(town,target);
        foreach(site in facing) {
            if(site.placement_score!=site.spacing_score*this.builder.StationFacingWeight(site,target)) throw "Facing weight missing from rank";
            if(!this.builder.FacesDestination(site.tile,site.dir,centre,target) ||
                (!("earthwork" in site) && !this.builder.CanStationThroat(this.builder.NearestStationExit(site,target),this.builder.PlatformOffset(site)))) {
                AILog.Error("COVERAGE FAIL: destination-facing site or approach"); return;
            }
        }
        this.builder.station_evaluations=null; this.builder.station_shortlists=null;
        if(++checked==3) break;
    }
    local xsite={tile=AIMap.GetTileIndex(40,40),dir=AIRail.RAILTRACK_NE_SW};
    local ysite={tile=AIMap.GetTileIndex(40,40),dir=AIRail.RAILTRACK_NW_SE};
    foreach(target in [AIMap.GetTileIndex(80,40),AIMap.GetTileIndex(4,40)])
        if(this.builder.StationFacingWeight(xsite,target)<3*this.builder.StationFacingWeight(ysite,target)) throw "Weak east/west orientation";
    foreach(target in [AIMap.GetTileIndex(40,80),AIMap.GetTileIndex(40,4)])
        if(this.builder.StationFacingWeight(ysite,target)<3*this.builder.StationFacingWeight(xsite,target)) throw "Weak north/south orientation";
    if(checked<2) { AILog.Error("COVERAGE FAIL: insufficient towns"); return; }
    AILog.Info("COVERAGE PASS: coverage and facing weighted together, centre distance breaks ties, both-platform catchment verified.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-coverage-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'CoverageCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "CoverageCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'coverage-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'COVERAGE PASS:' in result.stderr, 'Coverage checks did not complete'
        assert 'COVERAGE FAIL:' not in result.stderr
