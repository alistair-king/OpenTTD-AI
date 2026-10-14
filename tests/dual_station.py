"""Live dual RIRO layout, shared-station reuse, rollback and priority checks."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'DualStationCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'2000000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nDualStationCheck = \n', config)
driver = r'''
class ExpiringDualBuilder extends RouteBuilder {
    checks=0;expire_after=1;
    function PlanningExpired() {return this.checks++>=this.expire_after;}
}
class HubAttemptProbe {
    calls=0;source_hub=null;succeed=false;
    function ConnectionPlanKey(source,target) {return "hub-regression";}
    function Connect(source,target) {this.calls++;return this.succeed;}
}
class DualPriorityProbe {
    state=null;called=false;
    constructor() {this.state={dual_priority=true};}
    function NeedsContinuation() {return true;}
    function TryBuild() {this.called=true;return true;}
}
function PickupSignCount(tile) {
    local count=0;
    foreach(id,_ in AISignList()) if(AISign.GetLocation(id)==tile && AISign.GetName(id).find("[VT pickup] ")==0) count++;
    return count;
}
function CheckPrimitive(value) {
    local t=typeof value;
    if(t=="array" || t=="table") {foreach(k,v in value) {CheckPrimitive(k);CheckPrimitive(v);}return;}
    if(t!="null" && t!="integer" && t!="bool" && t!="string") throw "Unsupported saved hub type "+t;
    if(t=="string" && value.len()>254) throw "Saved hub string too long";
}
function OpenTTDAI::Start() {
    this.Sleep(1);this.SetCompanyName();PickRailType();EnsureMoney(AICompany.GetMaxLoanAmount());
    local origin=null,b=RouteBuilder(4);
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null || !AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) throw "fixture";
    foreach(reverse in [false,true]) {
        local a={tile=origin+AIMap.GetTileIndex(8,8),dir=AIRail.RAILTRACK_NE_SW};
        local z={tile=origin+AIMap.GetTileIndex(28,8),dir=AIRail.RAILTRACK_NE_SW};
        a=b.RiroSite(a,b.NearestStationExit(a,z.tile),false);
        z=b.RiroSite(z,b.NearestStationExit(z,a.tile),false);
        if(a==null || z==null) throw "site";
        local dual=PlanDualStation(b,z,origin+AIMap.GetTileIndex(reverse?37:0,8));
        if(dual==null) throw "dual plan";
        local hub=dual.dual;
        if(!reverse) {
            local limited=ExpiringDualBuilder(4);
            if(PlanDualStation(limited,z,origin+AIMap.GetTileIndex(0,8))==null || limited.checks<2)
                throw "Expired search discarded a valid dual layout";
            limited.checks=0;limited.expire_after=0;
            if(PlanDualStation(limited,z,origin+AIMap.GetTileIndex(0,8))!=null)
                throw "Already-expired search returned an unchecked layout";
        }
        AILog.Info("DUAL orientation "+reverse+" pickup step="+(hub.pickup.exit[0]-hub.pickup.exit[1]));
        b.BeginPlanning(0);
        if(!b.TryStationPair(a,dual) || !b.TryStationPair(a,z)) throw "fallback dedup";
        if(!b.ReserveStations(a,dual) || !b.BuildPlannedStations(a,dual)) throw "build: "+AIError.GetLastErrorString();
        if(PickupSignCount(hub.pickup.tile)!=1) {
            foreach(id,_ in AISignList()) AILog.Info("SIGN "+AISign.GetName(id)+" tile="+AISign.GetLocation(id)+" wanted="+hub.pickup.tile);
            throw "Missing pickup status sign";
        }
        DualPickupStatus(hub,"Planning route");DualPickupStatus(hub,"Planning route");
        b.ClearSearchSigns();
        if(PickupSignCount(hub.pickup.tile)!=1) throw "Duplicate or removed pickup status";
        local saved_status=clone hub;
        foreach(id,_ in AISignList()) if(AISign.GetLocation(id)==hub.pickup.tile) AISign.RemoveSign(id);
        DualPickupStatus(saved_status,saved_status.pickup_status);
        if(PickupSignCount(hub.pickup.tile)!=1) throw "Saved status not restored";
        if(AIStation.GetStationID(z.tile)!=AIStation.GetStationID(hub.pickup.tile)) throw "not joined";
        local scan=RailwayRetirement(),job={front=[z.tile],seen={},tiles=[],scan=0,ready=false};
        while(!job.ready) scan.Scan(job);
        if(!(hub.pickup.tile in job.seen)) throw "upgrade/cleanup missed pickup";
        if(!reverse) {
            local network=FreightNetwork(4),probe=HubAttemptProbe(),today=AIDate.GetCurrentDate();
            network.state.hubs <- {};network.state.hubs[123] <- hub;
            network.state.hub_failures <- {};network.state.hub_failures[123] <- 2;
            network.builder.planning_history["hub-regression"] <- {count=1,after=today+30};
            local access=hub.access,cash=AICompany.GetBankBalance(AICompany.COMPANY_SELF);
            for(local i=0;i<3;i++) if(network.ConnectHubOutlet(probe,123,456)) throw "Cooldown reported success";
            if(probe.calls!=0 || network.state.hub_failures[123]!=2 || "hub_deferred" in network.state ||
                hub.access!=access || AICompany.GetBankBalance(AICompany.COMPANY_SELF)!=cash)
                throw "Cooldown changed hub state or rebuilt access";
            network.builder.planning_history["hub-regression"].after=today;
            if(network.ConnectHubOutlet(probe,123,456) || probe.calls!=1 ||
                network.state.hub_failures[123]!=3 || network.state.hub_deferred[123]<=today)
                throw "Real failed attempt did not trigger fallback";
            network.ConnectHubOutlet(probe,123,456);
            if(probe.calls!=2 || network.state.hub_failures[123]!=3 || probe.source_hub!=null)
                throw "Separate-station fallback broken";
            probe.succeed=true;
            if(!network.ConnectHubOutlet(probe,123,456) || PickupSignCount(hub.pickup.tile)!=0 || hub.pickup_status!=null)
                throw "Completed outlet left a status sign";
        }
        if(!RestoreDualAccess(hub)) throw "strip idle";
        local sites=DualPickupSites(b,hub,a.tile);
        if(sites.len()!=1 || !("hub_existing" in sites[0])) throw "reuse source";
        local pending=b.pending_stations;b.pending_stations=[sites[0]];
        if(!b.ReleasePendingStations() || !AIRail.IsRailStationTile(z.tile) || !AIRail.IsRailStationTile(hub.pickup.tile)) throw "reuse cleanup destroyed station";
        b.pending_stations=pending;
        if(!BuildDualAccess(b,hub)) throw "restore idle: "+AIError.GetLastErrorString();
        b.extra_reserved=clone hub.reserved;
        foreach(site in [a,dual]) foreach(p in site.loop.pieces)
            if(p[1]!=site.loop.pieces[site.loop.pieces.len()-1][1]) b.extra_reserved.append(p[1]);
        b.planning_deadline=0;b.search_batches_limit=40;b.single_first=false;
        local found=b.FindPathBetween(a,dual);
        if(found==null) throw "full path";
        if(!b.BuildPath(found) || !b.BuildPath(found.secondary) || !b.BuildStationEntrances(found)) throw "approaches";
        b.BuildPreferredStations(found);
        if(!("roro" in found.entrances[0]) || !("roro" in found.entrances[1])) throw "delivery RIRO";
        foreach(p in found.entrances[1].roro.built) foreach(tile in hub.reserved)
            if(p[1]==tile) throw "delivery touches pickup";
        if(!reverse) {
            local inbound={};
            foreach(tile in hub.delivery_reserved) if(AIRail.IsRailTile(tile)) inbound[tile] <- AIRail.GetRailTracks(tile);
            local inlet_pending=b.pending_stations;b.pending_stations=[];
            if(!RestoreDualAccess(hub)) throw "outlet prepare";
            local source=DualPickupSites(b,hub,a.tile)[0];
            local target={tile=hub.pickup.tile-20,dir=AIRail.RAILTRACK_NE_SW};
            target=b.RiroSite(target,b.NearestStationExit(target,source.tile),false);
            if(target==null) throw "outlet target";
            b.extra_reserved=clone hub.delivery_reserved;
            foreach(site in [source,target]) if(site.loop!=null) foreach(p in site.loop.pieces)
                if(p[1]!=site.loop.pieces[site.loop.pieces.len()-1][1]) b.extra_reserved.append(p[1]);
            b.planning_deadline=0;b.station_attempts=[];
            if(!b.ReserveStations(source,target)) throw "outlet reserve";
            local outlet=b.FindPathBetween(source,target);
            if(outlet==null) throw "outlet path";
            if(!b.BuildPlannedStations(source,target) || !b.BuildPath(outlet) || !b.BuildPath(outlet.secondary) ||
                !b.BuildStationEntrances(outlet)) throw "outlet build";
            b.BuildPreferredStations(outlet);
            if(!("roro" in outlet.entrances[0])) throw "outlet lost RIRO";
            b.CleanupRoute(outlet,source,target);
            if(!b.ReleasePendingStations()) throw "outlet rollback";
            foreach(tile,tracks in inbound) if(AIRail.GetRailTracks(tile)!=tracks) throw "outlet changed delivery tracks";
            if(!AIRail.IsRailStationTile(hub.pickup.tile) || !AIRail.IsRailStationTile(z.tile)) throw "outlet removed hub";
            b.pending_stations=inlet_pending;
            if(!BuildDualAccess(b,hub)) throw "outlet idle restore";
        }
        b.CleanupRoute(found,a,dual);
        local saved=SavedStationReservations(b.pending_stations);
        CheckPrimitive(saved);CheckPrimitive(hub);
        b.pending_stations=saved;
        if(!b.ReleasePendingStations() || AIRail.IsRailStationTile(z.tile) || AIRail.IsRailStationTile(hub.pickup.tile)) throw "rollback";
    }
    foreach(id,_ in AISignList()) if(AISign.GetName(id).find("[VT pickup] ")==0) throw "Rollback left pickup sign";
    b.BeginPlanning("fresh");
    if(b.search_batches_limit!=8 || b.station_attempt_limit!=4) throw "New route budget changed";
    b.BeginPlanning("outlet",true);
    if(b.search_batches_limit!=40 || b.planning_deadline-AIController.GetTick()<11990) throw "Onward budget too short";
    b.planning_history["outlet"] <- {count=1,after=0};
    b.BeginPlanning("outlet",true);
    if(b.planning_deadline-AIController.GetTick()<15990) throw "Retry budget too short";
    local probe=DualPriorityProbe();this.network={networks=[probe]};this.wood_network=null;this.coal=null;
    this.TryBuildRoute();if(!probe.called || probe.state.dual_priority) throw "Onward construction not next";
    AILog.Info("DUAL STATION PASS: both facings, join, reuse, rollback, shared scan, fallback.");
    while(true) this.Sleep(1000);
}
'''
if '--earthworks' in sys.argv:
    driver=driver.replace('PlanDualStation(limited,z,origin+AIMap.GetTileIndex(0,8))','PlanDualStation(limited,z,origin+AIMap.GetTileIndex(0,8),true)')
    driver=driver.replace('        local dual=PlanDualStation',
        '        local old_height=AITile.GetCornerHeight(z.tile,AITile.CORNER_N);\n'
        '        if(!AITile.RaiseTile(z.tile,AITile.SLOPE_N)) throw "test hill";\n'
        '        local dual=PlanDualStation')
    driver=driver.replace('reverse?37:0,8));', 'reverse?37:0,8),true);')
    driver=driver.replace('        local hub=dual.dual;',
        '        if(!("earthwork" in dual) || dual.earthwork.targets.len()==0) throw "no dual earthworks";\n'
        '        local hub=dual.dual;')
    driver=driver.replace('    }\n    b.BeginPlanning("fresh");',
        '        if(AITile.GetCornerHeight(z.tile,AITile.CORNER_N)!=old_height+1) throw "earthwork rollback: actual="+AITile.GetCornerHeight(z.tile,AITile.CORNER_N)+" expected="+(old_height+1);\n'
        '        if(!AITile.LowerTile(z.tile,AITile.SLOPE_N)) throw "reset hill";\n'
        '    }\n    b.BeginPlanning("fresh");')
if '--vertical' in sys.argv:
    driver = (driver.replace('GetMapSizeX()-42', 'GetMapSizeX()-26')
        .replace('GetMapSizeY()-26', 'GetMapSizeY()-42')
        .replace('AreaIsBuildable(tile,38,22)', 'AreaIsBuildable(tile,22,38)')
        .replace('GetTileIndex(37,21)', 'GetTileIndex(21,37)')
        .replace('GetTileIndex(28,8)', 'GetTileIndex(8,28)')
        .replace('GetTileIndex(0,8)', 'GetTileIndex(8,0)')
        .replace('GetTileIndex(reverse?37:0,8)', 'GetTileIndex(8,reverse?37:0)')
        .replace('hub.pickup.tile-20', 'hub.pickup.tile-20*AIMap.GetMapSizeX()')
        .replace('AIRail.RAILTRACK_NE_SW', 'AIRail.RAILTRACK_NW_SE'))
with tempfile.TemporaryDirectory(prefix='openttdai-dual-station-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'DualStationCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "DualStationCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'dual_station-{"vertical-" if "--vertical" in sys.argv else ""}{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'DUAL STATION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
