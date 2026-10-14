"""Controlled fleet expansion eligibility checks in OpenTTD; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'LimitsCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nLimitsCheck = \n', config)
driver = r'''
::waiting <- 0;
::states <- {};
::positions <- {};
::native_vehicle <- AIVehicle;
function OpenTTDAI::Start()
{
    this.Sleep(1);
    ::AIVehicle = {
        VS_RUNNING=native_vehicle.VS_RUNNING, VS_AT_STATION=native_vehicle.VS_AT_STATION,
        IsValidVehicle=function(id) { return id in states; },
        GetCapacity=function(id,cargo) { return 100; },
        GetState=function(id) { return states[id]; },
        GetLocation=function(id) { return positions[id]; }
    };
    local invalid_station=AIStation.STATION_INVALID;
    ::AIStation = {
        STATION_INVALID=invalid_station,
        IsValidStation=function(id) { return true; },
        GetCargoWaiting=function(id,cargo) { return waiting; }
    };
    local opt=ServiceOptimiser(TrainBuyer(PassengerCargo()));
    local today=AIDate.GetCurrentDate();
    local record={depot=100,station_a=1,station_b=2,last_station=invalid_station,expand_after=0,phase="observe",last_tile=20,stationary_since=today};
    // A goods branch can share an optimiser whose default buyer is ore.
    // Even a large backlog must not permit the first extra goods train.
    local goods=FreightCargo("GOOD");
    if(goods<0) throw "Missing goods cargo fixture";
    local goods_opt=ServiceOptimiser(TrainBuyer(FreightCargo("IORE")));
    local goods_record=clone record; goods_record.cargo <- goods;
    states[1] <- AIVehicle.VS_RUNNING; positions[1] <- 21;
    goods_opt.trains[1] <- goods_record;
    waiting=100000;
    if(goods_opt.CanExpandFleet(1,goods_record)) throw "Second goods train allowed";
    goods_record.phase="pending";
    if(goods_opt.CanExpandFleet(1,goods_record)) throw "Queued goods expansion allowed";
    local goods_restored=ServiceOptimiser(goods_opt.buyer,goods_opt.Save());
    if(goods_restored.CanExpandFleet(1,goods_restored.trains[1])) throw "Goods cap lost on reload";
    goods_opt.buyer=TrainBuyer(goods);
    delete goods_record.cargo;
    if(goods_opt.CanExpandFleet(1,goods_record)) throw "Default goods buyer expanded";
    for(local count=1;count<=4;count++) {
        states[count] <- AIVehicle.VS_RUNNING; positions[count] <- 20+count;
        opt.trains[count] <- clone record;
        waiting=count*100-1;
        if(opt.CanExpandFleet(1,opt.trains[1])!=(count==1)) throw "Insufficient backlog accepted";
        waiting=count*100;
        if(opt.CanExpandFleet(1,opt.trains[1])!=(count<4)) throw "Four-train cap or backlog failed";
    }
    delete opt.trains[4]; delete states[4];
    opt.trains[2].expand_after=today+360;
    if(opt.CanExpandFleet(1,opt.trains[1])) throw "Expansion cooldown ignored";
    opt.trains[2].expand_after=0;
    opt.trains[2].stationary_since=today-7;
    if(opt.CanExpandFleet(1,opt.trains[1])) throw "Congestion ignored";
    states[2]=AIVehicle.VS_AT_STATION;
    opt.ObserveMovement(2,opt.trains[2]);
    if(!opt.CanExpandFleet(1,opt.trains[1])) throw "Normal loading treated as congestion";
    opt.trains[2].phase="dispatch";
    if(opt.CanExpandFleet(1,opt.trains[1])) throw "Undispatched train ignored";
    opt.trains[2].expand_after=today+360;
    local saved=opt.Save();
    local restored=ServiceOptimiser(opt.buyer,saved);
    if(restored.trains[2].expand_after!=today+360) throw "Cooldown lost on reload";
    AILog.Info("LIMITS PASS: one-train goods cap, queued goods work, progressively larger backlog, cooldown, congestion, loading exclusion, dispatch and save/load.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-limits-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'LimitsCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "LimitsCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'limits-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'LIMITS PASS:' in result.stderr
        assert 'LIMITS FAIL:' not in result.stderr
