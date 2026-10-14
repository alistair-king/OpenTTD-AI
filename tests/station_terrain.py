"""Isolated live-game earthworks test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'StationTerrainCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'max_no_competitors':'1', 'max_loan':'500000', 'tree_placer':'0'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nStationTerrainCheck = \n', config)
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
            if (AITile.GetCornerHeight(tile, AITile.CORNER_N) < 4) continue;
            local clear = true;
            for (local dx = -7; dx <= 7; dx++) for (local dy = -7; dy <= 7; dy++) {
                local near = AIMap.GetTileIndex(x+dx,y+dy);
                if (!AITile.IsBuildable(near) || AITile.IsWaterTile(near)) clear = false;
            }
            if (clear && AITile.GetCornerHeight(tile-7-7*AIMap.GetMapSizeX(),AITile.CORNER_N)>=4) center = tile;
        }
    }
    if (center == null) { AILog.Error("STATIONTERRAIN FAIL: no fixture"); return; }
    if(!PickRailType()) throw "No rail type";
    local w=AIMap.GetMapSizeX();
    local anchor=center-7-7*w;
    AITile.LevelTiles(anchor,center+7+7*w);
    local site={tile=center-2-w,dir=AIRail.RAILTRACK_NE_SW};
    local target=center+7;
    // Buildable station + a hill beside its return loop: preserve the loop's
    // earthworks even on the ordinary (non-reshape) station-selection pass.
    local route_builder=RouteBuilder(4);
    local route_exit=route_builder.NearestStationExit(site,target);
    local off=route_builder.PlatformOffset(site),lane=route_builder.LeftOutboundLane(route_exit);
    local entrance={signals=[[route_exit[0],route_exit[1]],[route_exit[0]+off,route_exit[1]+off]]};
    local near=entrance.signals[lane],other=entrance.signals[1-lane];
    local f=near[1]-near[0],side=near[1]-other[1];
    local hill=near[1]+6*f+side;
    if(!AITile.RaiseTile(hill,AITile.SLOPE_N)) throw "Return hill fixture failed";
    if(!route_builder.CanBuildStation(site)) throw "Fixture station should already be buildable";
    local riro=route_builder.RiroSite(site,route_exit,false);
    if(riro==null || riro.loop==null || riro.loop.terrain.targets.len()==0 || !("earthwork" in riro))
        throw "Ordinary station selection discarded planned loop earthworks";
    local pending_riro=clone riro;
    if(!route_builder.PrepareStation(riro,pending_riro) || !route_builder.BuildStation(riro)) throw "Early loop levelling failed";
    if(!riro.loop.PrepareTerrain() || riro.loop.terrain.targets.len()!=0) throw "Loop still needs levelling after station build";
    route_builder.pending_stations=[pending_riro];
    if(!route_builder.ReleasePendingStations()) throw "Early loop rollback failed";
    AITile.LevelTiles(anchor,center+7+7*w);
    foreach(change in [1,-1,2,-2,3,-3]) {
        if("earthwork" in site) delete site.earthwork;
        local height=AITile.GetCornerHeight(center,AITile.CORNER_N);
        for(local n=0;n<Abs(change);n++) if(!(change>0 ? AITile.RaiseTile(center,AITile.SLOPE_N) : AITile.LowerTile(center,AITile.SLOPE_N))) throw "Fixture slope failed";
        this.builder=RouteBuilder(4);
        local snapshot={};
        for(local dx=-6;dx<=6;dx++) for(local dy=-6;dy<=6;dy++) {
            local tile=center+dx+dy*w;
            snapshot[tile] <- AITile.GetCornerHeight(tile,AITile.CORNER_N);
        }
        local exit=this.builder.NearestStationExit(site,target);
        local candidate=this.builder.RiroSite(site,exit);
        if(candidate==null || candidate.loop==null) throw "No RIRO candidate";
        // Some dips support the station directly and need no earthworks.
        if(!("earthwork" in candidate)) {
            if(!this.builder.CanBuildStation(site) || !candidate.loop.PrepareTerrain()) throw "Natural station unusable";
            AITile.LevelTiles(anchor,center+7+7*w);continue;
        }
        local plan=candidate.earthwork;
        if(plan==null) throw "No levelling plan";
        site.earthwork <- plan;
        site.spacing_score <- 12.75; // Real station ranking is a float: never persist it.
        local pending=clone site;
        this.builder.pending_stations.append(pending);
        if(!this.builder.PrepareStation(site,pending) || !this.builder.BuildStation(site)) throw "Station preparation/build failed: "+AIError.GetLastErrorString()+", bank="+AICompany.GetBankBalance(AICompany.COMPANY_SELF);
        if(AITile.GetCornerHeight(center,AITile.CORNER_N)!=height) throw "Station not levelled";
        if(!candidate.loop.PrepareTerrain()) throw "Full RIRO footprint was not levelled: "+AIError.GetLastErrorString()+", junction slope="+AITile.GetSlope(candidate.loop.junction);
        if(!this.builder.VerifyStation(site) || !this.builder.CanStationThroat(plan.exit,this.builder.PlatformOffset(site))) throw "Station entrance unusable";
        // Exercise save/reload recovery of earthworks as well as station removal.
        local saved=this.Save();
        if("spacing_score" in saved.pending_stations[0] || "earthwork" in saved.pending_stations[0]) throw "Planning data leaked into save";
        this.Load(1,saved);
        this.builder=RouteBuilder(4); this.builder.pending_stations=this.loaded_pending_stations;
        if(!this.builder.ReleasePendingStations()) throw "Station rollback failed";
        foreach(tile,old in snapshot) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=old) throw "Terrain rollback mismatch";
        if(AIStationList(AIStation.STATION_TRAIN).Count()!=0) throw "Station remains";
        // Restore the full disturbed patch, including propagated slopes.
        AITile.LevelTiles(anchor,center+7+7*w);
    }
    AILog.Info("STATIONTERRAIN PASS: raised dips, lowered bumps, built platforms and usable throat, save/reload restored exact terrain.");
    while (true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-terrain-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'StationTerrainCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "StationTerrainCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'station-terrain-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'STATIONTERRAIN PASS:' in result.stderr, 'Terrain checks did not complete'
        assert 'STATIONTERRAIN FAIL:' not in result.stderr
