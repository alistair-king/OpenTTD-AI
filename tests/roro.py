"""Live roll-through station geometry, circulation, fallback and cleanup test."""
from pathlib import Path
import re, shutil, subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'RoroCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'terrain_type':'0', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nRoroCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    this.SetCompanyName();
    if(!PickRailType()) { AILog.Error("RORO FAIL: rail"); return; }
    EnsureMoney(AICompany.GetMaxLoanAmount());
    this.builder=RouteBuilder(4);
    local origin=null;
    for(local x=4;x<AIMap.GetMapSizeX()-42 && origin==null;x++) for(local y=4;y<AIMap.GetMapSizeY()-26 && origin==null;y++) {
        local tile=AIMap.GetTileIndex(x,y);
        if(!AreaIsBuildable(tile,38,22)) continue;
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
    // Depot construction may clear a running signal from its reverse face.
    local existing=found.line_signals[0],journal={pieces=[],structures=[],removed=[],signals=[]};
    if(!JournalSignal(journal,existing[0],existing[2],AIRail.SIGNALTYPE_NONE)) throw "Reverse-facing signal removal failed";
    if(AIRail.GetSignalType(existing[0],existing[1])!=AIRail.SIGNALTYPE_NONE ||
        AIRail.GetSignalType(existing[0],existing[2])!=AIRail.SIGNALTYPE_NONE) throw "Signal remained on depot junction";
    if(!JournalSignal(journal,existing[0],existing[1],AIRail.SIGNALTYPE_PBS_ONEWAY) ||
        !JournalSignal(journal,existing[0],existing[2],AIRail.SIGNALTYPE_NONE)) throw "Repeated signal edits failed";
    local undo={upgrade=journal};
    if(!RestoreNetworkUpgrade(undo) || AIRail.GetSignalType(existing[0],existing[1])!=AIRail.SIGNALTYPE_PBS_ONEWAY)
        throw "Signal rollback lost original state";
    // An already-built matching piece must not invalidate a flat RIRO plan.
    local partial=RollThroughStation();
    if(!partial.Plan(found.entrances[0],found.outbound,4)) throw "Partial-loop fixture planning failed";
    local piece=partial.pieces[0];
    if(!AIRail.BuildRail(piece[0],piece[1],piece[2])) throw "Partial-loop fixture building failed";
    if(!partial.PrepareTerrain()) throw "Matching owned rail rejected as an obstacle";
    if(!AIRail.RemoveRail(piece[0],piece[1],piece[2])) throw "Partial-loop fixture cleanup failed";
    // Uneven loop land: a raised corner at one end and a hollow at the other.
    local earthworks=[];
    foreach(index,entrance in found.entrances) {
        local lane=index==0 ? found.outbound : 1-found.outbound;
        local near=entrance.signals[lane],other=entrance.signals[1-lane];
        local f=near[1]-near[0],side=near[1]-other[1];
        local corner=near[1]+6*f+side;
        local original=AITile.GetCornerHeight(corner,AITile.CORNER_N);
        if(!(index==0 ? AITile.RaiseTile(corner,AITile.SLOPE_N) : AITile.LowerTile(corner,AITile.SLOPE_N)))
            throw "Loop earthwork fixture failed";
        local changed=AITile.GetCornerHeight(corner,AITile.CORNER_N);
        earthworks.append({corner=corner,original=original,changed=changed});
        local planned=RollThroughStation();
        if(!planned.Plan(entrance,lane,4) || planned.terrain.targets.len()==0) throw "Uneven loop rejected";
        if(AITile.GetCornerHeight(corner,AITile.CORNER_N)!=changed) throw "Loop planning changed land";
    }
    local probe=RollThroughStation();
    if(!probe.Plan(found.entrances[0],found.outbound,4)) throw "Clear loop plan failed";
    // The old outer return row may stay obstructed throughout circulation.
    local near=found.entrances[0].signals[found.outbound];
    local other=found.entrances[0].signals[1-found.outbound];
    local forward=near[1]-near[0],side=near[1]-other[1];
    local old_turn=near[1]+2*side;
    if(!AIRail.BuildRailDepot(old_turn,old_turn+forward)) throw "Compact footprint obstacle failed";
    if(!RollThroughStation().Plan(found.entrances[0],found.outbound,4)) throw "Loop still needs old outer return row";
    local across_min=100000,across_max=-100000;
    foreach(piece in probe.pieces) {
        local across=Abs(side)==1 ? AIMap.GetTileX(piece[1]) : AIMap.GetTileY(piece[1]);
        if(across<across_min) across_min=across;
        if(across>across_max) across_max=across;
    }
    if(across_max-across_min+1!=3) throw "RIRO footprint is not three rows wide";
    // Fail after terrain and track construction, during signal placement.
    probe.signals.append([origin,origin+1]);
    if(probe.Build()) throw "Invalid signal unexpectedly built";
    probe.signals.pop();
    foreach(change in earthworks) if(AITile.GetCornerHeight(change.corner,AITile.CORNER_N)!=change.changed)
        throw "Failed construction did not restore loop land";
    local blocked=probe.pieces[probe.pieces.len()-2][1];
    if(!AIRail.BuildRailDepot(blocked,blocked+1)) throw "Obstacle fixture failed";
    if(probe.Build()) throw "Loop unexpectedly built through an obstacle";
    foreach(piece in probe.pieces) if(piece[1]!=blocked && piece[1]!=probe.pieces[probe.pieces.len()-1][1] && AIRail.IsRailTile(piece[1]))
        throw "Failed loop left track behind";
    this.builder.BuildPreferredStations(found);
    if("roro" in found.entrances[0] || !("roro" in found.entrances[1])) throw "Independent terminus fallback failed";
    local fallback_tile=StationSiteFromEntrance(found.entrances[0],4).tile;
    local signs=0;
    foreach(id,_ in AISignList()) if(AISign.GetLocation(id)==fallback_tile && AISign.GetName(id).find("RIRO: ")==0) signs++;
    if(signs!=0) throw "Fallback created a sign";
    RiroFallbackSign(fallback_tile,"Loop tile obstructed");
    this.builder.ClearSearchSigns();
    signs=0;foreach(id,_ in AISignList()) if(AISign.GetLocation(id)==fallback_tile && AISign.GetName(id).find("RIRO: ")==0) signs++;
    if(signs!=0) throw "Fallback created a new sign";

    local goods_route=FactoryGoodsRoute(this.builder,null,"GOOD");
    if(goods_route.single_first || !goods_route.AcceptInfrastructure(found))
        throw "Goods deferred its normal return track or rejected reversing fallback";
    AITile.DemolishTile(blocked);
    found.entrances[1].roro.Restore();
    delete found.entrances[1].roro;
    this.builder.BuildPreferredStations(found);
    foreach(entrance in found.entrances) if(!("roro" in entrance)) throw "Loop not preferred on flat clear land";
    foreach(id,_ in AISignList()) if(AISign.GetLocation(id)==fallback_tile && AISign.GetName(id).find("RIRO: ")==0)
        throw "Successful RIRO retained failure sign";

    if(!goods_route.AcceptInfrastructure(found) || found.secondary.path==null)
        throw "Goods rejected complete dual-track RIRO infrastructure";
    // Simulate recovery of loop construction using only saved primitive data.
    this.Load(1,this.Save());
    foreach(pending in this.loaded_pending_stations) {
        if(!("loop_recovery" in pending)) throw "Loop recovery not saved";
        local recovery=RollThroughStation();
        recovery.built=pending.loop_recovery.pieces;
        recovery.changed_signals=pending.loop_recovery.signals;
        recovery.removed=pending.loop_recovery.removed;
        if("terrain_original" in pending.loop_recovery) recovery.terrain_original=pending.loop_recovery.terrain_original;
        if(!recovery.Restore()) throw "Loop earthwork recovery failed";
    }
    foreach(change in earthworks) if(AITile.GetCornerHeight(change.corner,AITile.CORNER_N)!=change.changed)
        throw "Saved recovery did not restore original loop land";
    foreach(entrance in found.entrances) foreach(signal in entrance.signals)
        if(AIRail.GetSignalType(signal[0],signal[1])!=AIRail.SIGNALTYPE_PBS) throw "Recovery did not restore terminus signals";
    this.builder.BuildPreferredStations(found);
    foreach(entrance in found.entrances) {
        local loop=entrance.roro;
        if(loop.signals.len()<6) throw "Exit or return signal missing";
        foreach(signal in loop.signals) {
            if(AIRail.GetSignalType(signal[0],signal[1])!=(signal.len()>2?signal[2]:AIRail.SIGNALTYPE_PBS_ONEWAY) ||
                AIRail.GetSignalType(signal[0],2*signal[0]-signal[1])!=AIRail.SIGNALTYPE_NONE) throw "Wrong one-way loop signal";
        }
        if(!ParallelRailPieces(AIRail.GetRailTracks(loop.junction))) throw "Entrance and return share a junction";
        foreach(p in loop.remove) if(AIRail.AreTilesConnected(p[0],p[1],p[2])) throw "Unwanted return-to-entrance connection";
        local f=loop.remove[0][2]-loop.junction;
        local incoming=loop.remove[1][0];
        if(!AIRail.AreTilesConnected(incoming-f,incoming,incoming+f) ||
            !AIRail.AreTilesConnected(incoming-f,incoming,loop.junction) ||
            !AIRail.AreTilesConnected(incoming,loop.junction,loop.junction+f)) throw "Entrance fan lost a platform";
        // Both entry branches must survive, independently of the return curve.
        foreach(signal in entrance.signals) {
            local f=signal[1]-signal[0];
            local cross=signal[0]-f;
            if(!AIRail.AreTilesConnected(cross,signal[0],signal[1])) throw "Platform approach lost";
        }
    }
    foreach(change in earthworks) if(AITile.GetCornerHeight(change.corner,AITile.CORNER_N)!=change.original)
        throw "Loop not levelled to station height";
    local buyer=TrainBuyer(PassengerCargo());
    local trains=[];
    for(local i=0;i<2;i++) {
        local train=buyer.BuildPassengerTrain(depot,a.tile,b.tile,7);
        if(!AIVehicle.IsValidVehicle(train)) throw "Train purchase failed";
        trains.append({id=train,stage=0,loops=[false,false]});
    }
    for(local tick=0;tick<40000;tick++) {
        local complete=true;
        foreach(train in trains) {
            local tile=AIVehicle.GetLocation(train.id);
            foreach(index,entrance in found.entrances) if(tile==entrance.roro.signals[4][0]) train.loops[index]=true;
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
        if(train.stage!=4 || !train.loops[0] || !train.loops[1]) throw "Train failed to circulate through both loops";
        AIVehicle.SendVehicleToDepot(train.id);
    }
    foreach(train in trains) {
        for(local tick=0;tick<10000 && !AIVehicle.IsStoppedInDepot(train.id);tick++) this.Sleep(1);
        if(!AIVehicle.SellVehicle(train.id)) throw "Train did not return for cleanup";
    }
    if(!AIRail.IsRailDepotTile(old_turn)) throw "Compact loop touched outer-row obstacle";
    AITile.DemolishTile(old_turn);
    AITile.DemolishTile(depot);
    this.builder.CleanupRoute(found,a,b);
    if(!this.builder.ReleasePendingStations()) throw "Earthworks restoration failed";

    AILog.Info("RORO PASS: through platforms, loop operation, train circuit and cleanup passed.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-roro-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'RoroCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "RoroCheck";', 1))
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
        (root / 'tests' / f'roro-{"vertical" if vertical else "horizontal"}-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'RORO PASS:' in result.stderr, 'Roll-through checks did not complete'
        assert 'RORO FAIL:' not in result.stderr
