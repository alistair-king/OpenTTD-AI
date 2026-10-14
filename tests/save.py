"""Real OpenTTD save/reload regression for pending stations, earthworks and search signs."""
from pathlib import Path
import re, shutil, subprocess, tempfile, selectors, time, socket
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'SaveCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'6', 'map_y':'6', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nSaveCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(this.loaded_pending_stations!=null) {
        if(this.loaded_planning_history==null || !("probe" in this.loaded_planning_history) || this.loaded_planning_history.probe.count!=3) throw "Planning cooldown lost in save";
        if(this.loaded_pending_stations.len()!=1) throw "Missing saved reservation";
        local record=this.loaded_pending_stations[0];
        if("spacing_score" in record || "earthwork" in record || !("earthwork_original" in record)) throw "Wrong saved fields";
        this.builder=RouteBuilder(4); this.builder.pending_stations=this.loaded_pending_stations;
        local original=clone record.earthwork_original;
        if(!this.builder.ReleasePendingStations()) throw "Reload cleanup failed";
        foreach(tile,height in original) if(AITile.GetCornerHeight(tile,AITile.CORNER_N)!=height) throw "Reload terrain mismatch";
        this.builder.ClearSearchSigns();
        local ordinary=false;
        foreach(id,_ in AISignList()) {
            local name=AISign.GetName(id);
            if(name=="Keep my sign") ordinary=true;
            if(name.find("[VT search] ")==0) throw "Search sign left behind";
        }
        if(!ordinary) throw "Unrelated sign removed";
        AILog.Info("SAVE RELOAD PASS");
        while(true) this.Sleep(1);
    }
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
    if (center == null) { AILog.Error("STATIONTERRAIN FAIL: no fixture"); return; }
    if(!PickRailType()) throw "No rail type";
    local w=AIMap.GetMapSizeX();
    local anchor=center-3-3*w;
    AITile.LevelTiles(anchor,center+5+3*w);
    local site={tile=center-2-w,dir=AIRail.RAILTRACK_NE_SW};
    local target=center+7;
    foreach(change in [1,-1,2,-2]) {
        local height=AITile.GetCornerHeight(center,AITile.CORNER_N);
        for(local n=0;n<Abs(change);n++) if(!(change>0 ? AITile.RaiseTile(center,AITile.SLOPE_N) : AITile.LowerTile(center,AITile.SLOPE_N))) throw "Fixture slope failed";
        this.builder=RouteBuilder(4);
        local snapshot={};
        for(local dx=-6;dx<=6;dx++) for(local dy=-6;dy<=6;dy++) {
            local tile=center+dx+dy*w;
            snapshot[tile] <- AITile.GetCornerHeight(tile,AITile.CORNER_N);
        }
        local plan=this.builder.StationEarthwork(site,target);
        if(plan==null) throw "No levelling plan";
        site.earthwork <- plan;
        this.builder.planning_history["probe"] <- {count=3,after=AIDate.GetCurrentDate()+730};
        site.spacing_score <- 12.75; // Real station ranking is a float: never persist it.
        local pending=clone site;
        this.builder.pending_stations.append(pending);
        if(!this.builder.PrepareStation(site,pending) || !this.builder.BuildStation(site)) throw "Station preparation/build failed";
        if(AITile.GetCornerHeight(center,AITile.CORNER_N)!=height) throw "Station not levelled";
        if(!this.builder.VerifyStation(site) || !this.builder.CanStationThroat(plan.exit,this.builder.PlatformOffset(site))) throw "Station entrance unusable";
        this.builder.SearchSign(site.tile,"Test search");
        AISign.BuildSign(site.tile+2,"Keep my sign");
        AILog.Info("SAVE READY");
        while(true) this.Sleep(1);
    }
}
'''

with tempfile.TemporaryDirectory(prefix='openttdai-save-') as td:
    folder=Path(td)
    ai=folder/'ai'/'SaveCheck'; ai.mkdir(parents=True)
    for source in root.glob('*.nut'): shutil.copy2(source,ai/source.name)
    info=ai/'info.nut'; info.write_text(info.read_text().replace('return "OpenTTDAI";','return "SaveCheck";',1))
    main=ai/'main.nut'; main.write_text(main.read_text().replace('function OpenTTDAI::Start()','function OpenTTDAI::UnusedStart()')+driver)
    config=re.sub(r'^min_active_clients = .*$', 'min_active_clients = 0',config,flags=re.M)
    cfg=folder/'openttd.cfg'; cfg.write_text(config)
    for seed in [42,7]:
        save=folder/f'roundtrip-{seed}.sav'
        for loading in [False,True]:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            command=[str(exe),'-D',f'127.0.0.1:{port}','-c',str(cfg),'-x','-v','dedicated','-s','null','-m','null','-d','script=4,sl=3']
            command+=['-g',str(save)] if loading else ['-g','-G',str(seed)]
            process=subprocess.Popen(command,cwd=folder,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0)
            output=b''; saved_at=None; success=False
            selector=selectors.DefaultSelector(); selector.register(process.stdout,selectors.EVENT_READ)
            deadline=time.monotonic()+60
            try:
                while time.monotonic()<deadline:
                    for key,_ in selector.select(.1):
                        chunk=key.fileobj.read(65536)
                        if chunk: output+=chunk
                    text=output.decode(errors='replace')
                    if 'Your script made an error' in text or 'unsupported type' in text: break
                    if loading and 'SAVE RELOAD PASS' in text: success=True; break
                    if not loading and 'SAVE READY' in text and saved_at is None:
                        process.stdin.write(('save '+str(save.with_suffix(''))+'\n').encode()); process.stdin.flush(); saved_at=time.monotonic()
                    if saved_at and save.exists() and save.stat().st_size>0 and time.monotonic()-saved_at>1:
                        success=True; break
                    if process.poll() is not None: break
            finally:
                if process.poll() is None:
                    process.stdin.write(b'quit\n'); process.stdin.flush()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                output+=process.stdout.read() or b''
                selector.close()
            text=output.decode(errors='replace')
            (root/'tests'/f'save-{seed}-{loading}.log').write_text(text)
            print(seed,'reload' if loading else 'save',text[-2500:],flush=True)
            assert success and 'unsupported type' not in text and 'Your script made an error' not in text, 'Real save/reload failed'
