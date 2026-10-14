"""Isolated two-train traffic test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'ProductionCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'8', 'map_y':'8', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'0', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950', 'max_loan':'500000', 'industry_density':'4', 'industry_cargo_scale':'1000'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nProductionCheck = \n', config)
driver = r'''
function OpenTTDAI::Start()
{
    this.Sleep(1);
    if(!PickRailType()) throw "No rails";
    local coal=CoalRoutes(RouteBuilder(4));
    local sources=[],targets=[];
    foreach(i,_ in AIIndustryList()) {
        if(AIIndustry.GetLastMonthProduction(i,coal.cargo)>0) sources.append(i);
        if(AIIndustry.IsCargoAccepted(i,coal.cargo)==AIIndustry.CAS_ACCEPTED &&
            AIIndustryType.GetProducedCargo(AIIndustry.GetIndustryType(i)).Count()==0) targets.append(i);
    }
    local choices=0, mines={};
    for(local attempt=0;attempt<1000;attempt++) {
        local expected=-1;
        foreach(source in sources) foreach(target in targets) {
            local distance=AIMap.DistanceManhattan(AIIndustry.GetLocation(source),AIIndustry.GetLocation(target));
            if(distance<30 || distance>120 || source+":"+target in coal.attempted) continue;
            local output=AIIndustry.GetLastMonthProduction(source,coal.cargo);
            if(output>=100 && output>expected) expected=output;
        }
        local pair=coal.PickPair();
        if(expected<0) { if(pair!=null) throw "Exhausted pairs selected"; break; }
        if(pair==null || AIIndustry.GetLastMonthProduction(pair[0],coal.cargo)!=expected) throw "Skipped higher-output mine";
        choices++; mines[pair[0]] <- true;
        coal.attempted[pair[0]+":"+pair[1]] <- true;
    }
    if(choices<2 || mines.len()<2) throw "Insufficient selection fixture";
    // Keep real industry locations/acceptance, but exercise the exact output boundary.
    ::production_native <- AIIndustry;
    ::boundary_output <- 100;
    ::AIIndustry <- {
        IsValidIndustry=production_native.IsValidIndustry,
        GetLastMonthProduction=function(i,c) { return production_native.GetLastMonthProduction(i,c)>0 ? boundary_output : 0; },
        IsCargoAccepted=production_native.IsCargoAccepted,
        CAS_ACCEPTED=production_native.CAS_ACCEPTED,
        GetIndustryType=production_native.GetIndustryType,
        GetLocation=production_native.GetLocation,
        GetAmountOfStationsAround=production_native.GetAmountOfStationsAround
    };
    coal.attempted={};
    foreach(output in [100,101]) {
        boundary_output=output;
        if(coal.PickPair()==null) throw "Eligible boundary production rejected";
    }
    boundary_output=99;
    if(coal.PickPair()!=null) throw "Low-production mine selected";
    if(coal.TryBuild() || coal.phase) throw "Low-production mines blocked passenger transition";
    local restored=CoalRoutes(coal.builder,coal.Save());
    if(restored.phase) throw "Passenger transition lost after reload";
    ::AIIndustry <- production_native;
    // Controlled public station ownership and production snapshots exercise both cargo chains.
    ::competition_outputs <- [300,200];
    ::competition_owner <- 1;
    ::competition_count <- 1;
    ::competition_steel <- -1;
    ::AIIndustryList <- function() { return {[0]=0,[1]=0,[2]=0}; };
    ::AITileList_IndustryProducing <- function(i,r) { local tiles={}; if(i==0) tiles[100] <- 0; return tiles; };
    ::AITile <- { IsStationTile=function(t) { return true; }, GetOwner=function(t) { return competition_owner; } };
    ::AICompany <- { COMPANY_SELF=0, COMPANY_INVALID=-1, ResolveCompanyID=function(c) { return c; } };
    ::AIIndustryType <- { GetProducedCargo=function(t) {
        local outputs=AIList();
        if(competition_steel>=0) outputs.AddItem(competition_steel,0);
        return outputs;
    } };
    ::AIIndustry <- {
        CAS_ACCEPTED=1,
        IsValidIndustry=function(i) { return i>=0 && i<3; },
        GetLastMonthProduction=function(i,c) { return i<2 ? competition_outputs[i] : 0; },
        IsCargoAccepted=function(i,c) { return i==2 ? 1 : 0; },
        GetIndustryType=function(i) { return 0; },
        GetLocation=function(i) { return AIMap.GetTileIndex(20+i*35,20); },
        GetAmountOfStationsAround=function(i) { return i==0 ? competition_count : 0; }
    };
    foreach(label in ["COAL","IORE"]) {
        competition_steel=label=="IORE" ? FreightCargo("STEL") : -1;
        local freight=CoalRoutes(RouteBuilder(4),null,label);
        competition_outputs=[300,200]; competition_owner=1; competition_count=1;
        if(freight.PickPair()[0]!=1) throw "Served 300 should lose to unserved 200";
        competition_outputs=[500,200];
        if(freight.PickPair()[0]!=0) throw "Served 500 should beat unserved 200";
        competition_count=7;
        if(freight.PickPair()[0]!=0) throw "Discount incorrectly compounded per station";
        competition_outputs=[300,200]; competition_owner=0;
        if(freight.PickPair()[0]!=0) throw "Own station was penalised";
        competition_owner=-1;
        if(freight.PickPair()[0]!=0) throw "Unowned station was penalised";
        competition_owner=1; competition_outputs=[101,0];
        if(freight.PickPair()[0]!=0) throw "Competition changed actual production eligibility";
    }
    AILog.Info("PRODUCTION PASS: highest eligible monthly output first, then lesser mines, failed-pair exclusions preserved.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-production-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'ProductionCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "ProductionCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=600000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'production-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'PRODUCTION PASS:' in result.stderr
        assert 'Your script made an error' not in result.stderr
