"""Live roll-through station geometry, circulation, fallback and cleanup test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'FleetUpgradeCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'2050', 'tree_placer':'0', 'max_loan':'2000000', 'inflation':'false'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nFleetUpgradeCheck = \n', config)
config = re.sub(r'^starting_year = .*$', 'starting_year = 2050', config, flags=re.M)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    AICompany.SetAutoRenewStatus(false);
    if(!PickRailType()) { AILog.Error("RORO FAIL: rail"); return; }
    local oldest=1;
    AIRail.SetCurrentRailType(oldest);
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22) || AITile.GetMinHeight(tile)<2) continue;
        local test=AITestMode();
        if(AITile.LevelTiles(tile,tile+AIMap.GetTileIndex(37,21))) origin=tile;
    }
    if(origin==null) { AILog.Error("RORO FAIL: no fixture"); return; }
    if(!AITile.LevelTiles(origin,origin+AIMap.GetTileIndex(37,21))) { AILog.Error("RORO FAIL: levelling: "+AIError.GetLastErrorString()); return; }
    local w=AIMap.GetMapSizeX();
    local a={tile=origin+AIMap.GetTileIndex(5,8),dir=AIRail.RAILTRACK_NE_SW};
    local b={tile=origin+AIMap.GetTileIndex(29,8),dir=AIRail.RAILTRACK_NE_SW};
    if(!this.builder.BuildStation(a) || !this.builder.BuildStation(b)) { AILog.Error("RORO FAIL: stations: "+AIError.GetLastErrorString()); return; }
    this.builder.pending_stations=[clone a,clone b];
    foreach(site in [a,b]) {
        local size=StationFootprint(site.dir,4);
        local axis=site.dir==AIRail.RAILTRACK_NE_SW ? 1:AIMap.GetMapSizeX();
        local exits=StationExits(site.tile,site.dir,4);
        foreach(sign in [-1,1]) {
            local target=site.tile+sign*4*axis;
            local facing=0;
            foreach(exit in exits) if(StationExitFacesTarget(site,exit,target,4)) {
                facing++;
                if(exit[0]-exit[1]!=sign*axis) throw "Station mouth not flipped towards destination";
            }
            if(facing!=1) throw "Opposite-facing station accepted";
        }
    }
    local found=this.builder.FindPathBetween(a,b);
    if(found==null) throw "Flat route not found";
    if(!this.builder.BuildPath(found) || !this.builder.BuildPath(found.secondary) ||
        !this.builder.BuildStationEntrances(found)) { AILog.Error("RORO FAIL: construction"); return; }
    local depot=this.builder.BuildDepot(found.depot_site);
    if(!AIRail.IsRailDepotTile(depot) || !this.builder.BuildLineSignals(found)) { AILog.Error("RORO FAIL: depot/signals"); return; }
    // Reproduce the old assembly depot's missing exit curve, then repair it
    // without changing the surrounding one-way signals.
    local ds=found.depot_site;
    if(!AIRail.RemoveRail(ds.after,ds.front,depot)) throw "Missing-curve fixture failed";
    RailwayUpgrades().RepairDepotConnections({tile=depot,front=ds.front});
    if(!AIRail.AreTilesConnected(ds.before,ds.front,depot) || !AIRail.AreTilesConnected(ds.after,ds.front,depot)) throw "Depot exit not repaired";
    this.builder.BuildPreferredStations(found);

    local buyer=TrainBuyer(PassengerCargo());
    local trains=[];
    for(local i=0;i<2;i++) {
        local train=TrainBuyer(i==0?PassengerCargo():FreightCargo("COAL")).BuildCargoTrain(depot,a.tile,b.tile,6,false);
        if(!AIVehicle.IsValidVehicle(train)) throw "Train purchase failed";
        trains.append({id=train,stage=0,loops=[false,false]});
    }
    this.optimiser=ServiceOptimiser(buyer);
    foreach(i,t in trains) {
        this.optimiser.Register(t.id,{depot=depot,station_a=a.tile,station_b=b.tile},4);
        this.optimiser.trains[t.id].cargo=i==0?PassengerCargo():FreightCargo("COAL");
    }
    local owner={optimiser=this.optimiser,services={}};
    foreach(t in trains) owner.services[t.id] <- {depot=depot};
    this.rail_upgrades=RailwayUpgrades();this.rail_upgrades.Bind([owner]);
    local speeds={[1]=100,[2]=200,[3]=300},mixed={[1]=true,[3]=true};
    if(!this.rail_upgrades.MigrationTarget(3,speeds,mixed) ||
        this.rail_upgrades.MigrationTarget(2,speeds,mixed) ||
        this.rail_upgrades.MigrationTarget(3,speeds,{[3]=true})) throw "Mixed target policy failed";
    // Queued carriage/engine work must not veto a complete fleet upgrade.
    this.optimiser.trains[trains[0].id].phase="pending";
    this.optimiser.trains[trains[1].id].phase="engine";
    local flags=AIOrder.GetOrderFlags(trains[1].id,2);
    if(!AIOrder.SetOrderFlags(trains[1].id,2,flags|AIOrder.OF_STOP_IN_DEPOT)) throw "Queued engine fixture";
    local old_ids=[];foreach(t in trains) old_ids.append(t.id);
    local target=-1;foreach(type,_ in AIRailTypeList()) if(type>target) target=type;
    local restored=false,started=false,aborted=false,retried=false,last_phase="",last_day=-1000;
    for(local tick=0;tick<20000;tick++) {
        this.rail_upgrades.Step(true);
        if(this.rail_upgrades.Busy()) {
            local m=this.rail_upgrades.state.job.migration;
            if(m.phase!=last_phase || AIDate.GetCurrentDate()-last_day>60) {
                AILog.Info("MIGRATION TEST phase="+m.phase+", index="+("index" in m?m.index:0)+", day="+AIDate.GetCurrentDate());
                foreach(e in m.trains) AILog.Info("TEST train="+e.old+", tile="+AIVehicle.GetLocation(e.old)+", depot="+e.depot+", state="+AIVehicle.GetState(e.old));
                foreach(id,_ in AIVehicleList()) AILog.Info("ALL TRAIN "+id+" state="+AIVehicle.GetState(id)+" engine="+AIVehicle.GetEngineType(id));
                last_phase=m.phase;last_day=AIDate.GetCurrentDate();
            }
        }
        if(this.rail_upgrades.Busy()) {
            started=true;
            if(!aborted && this.rail_upgrades.state.job.migration.phase=="convert" &&
                this.rail_upgrades.state.job.migration.index>0) {
                this.rail_upgrades.state.job.migration.phase="rollback";
                this.rail_upgrades.state.job.migration.index=0;aborted=true;
            }
            if(retried && !restored && this.rail_upgrades.state.job.migration.phase=="recover_build" &&
                this.rail_upgrades.state.job.migration.trains[0].attached>0) {
                this.Load(1,this.Save());
                this.rail_upgrades=RailwayUpgrades(this.loaded_rail_upgrades);
                this.optimiser=ServiceOptimiser(buyer,this.loaded_services);owner.optimiser=this.optimiser;
                this.rail_upgrades.Bind([owner]);restored=true;
            }
        }
        if(started && !this.rail_upgrades.Busy()) {
            if(aborted && !retried) {
                foreach(id in old_ids) if(!AIVehicle.IsValidVehicle(id) || AIVehicle.IsStoppedInDepot(id)) throw "Rollback lost or held train";
                if(AIRail.GetRailType(depot)!=oldest) throw "Rollback lost depot";
                this.rail_upgrades.state.month=-1;this.rail_upgrades.state.seeds=[];
                retried=true;started=false;continue;
            }
            break;
        }
        this.Sleep(5);
    }
    if(!restored || this.rail_upgrades.Busy()) throw "Migration failed to complete/save-load";

    local scan=RailwayRetirement(),job={front=[depot],seen={},tiles=[],scan=0,ready=false};
    while(!job.ready) scan.Scan(job);
    foreach(p in job.tiles) if(AIRail.GetRailType(p.tile)!=target) throw "Track not migrated";
    trains=[];
    foreach(id,r in this.optimiser.trains) {
        if(!(id in owner.services)) throw "Lost source service mapping";
        if(!AIEngine.HasPowerOnRail(AIVehicle.GetEngineType(id),target)) throw "Wrong replacement engine";
        if(AIVehicle.GetCapacity(id,r.cargo)<=0 || AIVehicle.GetLength(id)>r.max_length) throw "Wrong replacement consist";
        if(AIOrder.GetOrderDestination(id,2)!=depot || (AIOrder.GetOrderFlags(id,2)&AIOrder.OF_STOP_IN_DEPOT)!=0) throw "Lost orders";
        trains.append({id=id,stage=0,loops=[false,false]});
    }
    if(trains.len()!=2) throw "Lost service record";
    AILog.Info("UPGRADE PASS: mixed cargo fleet migrated to maglev; rollback and mid-consist save/load passed.");
    for(local tick=0;tick<40000;tick++) {
        local complete=true;
        foreach(train in trains) {
            local tile=AIVehicle.GetLocation(train.id);
            foreach(index,entrance in found.entrances) if("roro" in entrance && tile==entrance.roro.signals[4][0]) train.loops[index]=true;
            local station=AIStation.GetStationID(tile);
            if(train.stage==0 && station==AIStation.GetStationID(a.tile)) train.stage=1;
            else if(train.stage==1 && station==AIStation.GetStationID(b.tile)) train.stage=2;
            else if(train.stage==2 && tile==depot) train.stage=3;
            else if(train.stage==3 && station==AIStation.GetStationID(a.tile)) train.stage=4;
            if(train.stage<4) complete=false;
        }
        if(complete) break;
        this.Sleep(1);
    }
    foreach(train in trains) {
        if(train.stage!=4) throw "Train failed to circulate through both loops";
        AIVehicle.SendVehicleToDepot(train.id);
    }
    foreach(train in trains) {
        for(local tick=0;tick<10000 && !AIVehicle.IsStoppedInDepot(train.id);tick++) this.Sleep(1);
        if(!AIVehicle.SellVehicle(train.id)) throw "Train did not return for cleanup";
    }
    AITile.DemolishTile(depot);
    this.builder.CleanupRoute(found,a,b);
    if(!this.builder.ReleasePendingStations()) throw "Earthworks restoration failed";

    AILog.Info("RORO PASS: through platforms, loop operation, train circuit and cleanup passed.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-upgrade-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'FleetUpgradeCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "FleetUpgradeCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    template = main.read_text()
    for seed, vertical in [(42,False),(7,False),(42,True),(7,True)]:
        content=template
        if vertical:
            content=content.replace('GetMapSizeX()-42','GetMapSizeX()-26').replace('GetMapSizeY()-26','GetMapSizeY()-42').replace('tile,38,22','tile,22,38').replace('(37,21)','(21,37)').replace('(5,8)','(8,5)').replace('(29,8)','(8,29)').replace('dir=AIRail.RAILTRACK_NE_SW','dir=AIRail.RAILTRACK_NW_SE')
        main.write_text(content)
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=300000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'fleet-upgrade-{"vertical" if vertical else "horizontal"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RORO PASS:' in result.stderr and 'UPGRADE PASS:' in result.stderr, 'Roll-through checks did not complete'
        assert 'RORO FAIL:' not in result.stderr
