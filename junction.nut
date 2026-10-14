// A flying branch junction. One lane bends away from the main line, then
// crosses both running tracks on a bridge (or a naturally fitting tunnel).
function PlanSeparatedJunction(j,d,e)
{
    // Two running rails need two ramps and two crossed tiles. Only move a
    // ramp farther out when the tighter complete layout cannot be built.
    foreach(ends in [[-1,2],[-2,2],[-1,3],[-2,3]]) {
        local plan=PlanSeparatedJunctionSpan(j,d,e,ends[0],ends[1]);
        if(plan!=null) return plan;
    }
    return null;
}
function PlanSeparatedJunctionSpan(j,d,e,ramp_y,end_y)
{
    local far=e>0?j.tile:j.tile+j.side,near=far+e;
    local a=[],z=[];
    for(local x=0;x<=3;x++) a.append(far+x*d);
    for(local y=1;y<=4;y++) a.append(far+3*d-y*e);
    for(local x=4;x<=8;x++) a.append(far+x*d-4*e);
    for(local y=-3;y<ramp_y;y++) a.append(far+8*d+y*e);
    local ramp=far+8*d+ramp_y*e,end=far+8*d+end_y*e;
    a.append(ramp);a.append(end);
    for(local y=end_y+1;y<=6;y++) a.append(far+8*d+y*e);
    for(local x=0;x<=7;x++) z.append(near+x*d);
    for(local y=2;y<=6;y++) z.append(far+7*d+y*e);
    local kind=RailTunnelCost(ramp,end)>=0?"tunnel":"bridge";
    if(kind=="bridge" && SuitableRailBridge(ramp,end)<0) return null;
    local reserved={},signals=[],merges=[far+3*d,near+7*d];
    local outward=(far==j.tile ? d==j.forward : d==-j.forward);
    foreach(index,tiles in [a,z]) {
        for(local i=0;i<tiles.len();i++) {
            local tile=tiles[i];
            if(!AIMap.IsValidTile(tile)) return null;
            if(i>0 && AIMap.DistanceManhattan(tiles[i-1],tile)!=1 && !(tile==end && tiles[i-1]==ramp)) return null;
            reserved[tile] <- true;
            // Existing running rails may only be used on this lane's approach.
            local main=index==0 ? i<=3 : i<=7;
            if(main) {
                if(!AIRail.IsRailTile(tile) || AIRail.GetRailTracks(tile)!=RailPiece(tile-d,tile,tile+d) ||
                    AITile.GetSlope(tile)!=AITile.SLOPE_FLAT) return null;
            } else if(!AITile.IsBuildable(tile)) return null;
            if(i==0 || i==tiles.len()-1 || tile==ramp || tile==end) continue;
            local test=AITestMode();
            if(!main && !AIRail.BuildRail(tiles[i-1],tile,tiles[i+1])) return null;
        }
        local merge=merges[index],forward=(index==0?outward:!outward)?d:-d;
        foreach(k in [-1,1]) signals.append([merge+k*d,merge+k*d-forward]);
        local t=index==0 ? far+3*d-e : near+7*d+e;
        local step=index==0?-e:e;
        signals.append([t,(index==0?outward:!outward)?t-step:t+step]);
    }
    foreach(t in [ramp-e,end+e]) signals.append([t,outward?t-e:t+e]);
    // Reserve the structure's footprint as well as the ramps.
    for(local y=ramp_y;y<=end_y;y++) reserved[far+8*d+y*e] <- true;
    local lanes=[a,z],outbound=outward?0:1;
    if(a.top()>z.top()) {lanes=[z,a];outbound=1-outbound;}
    return {lanes=lanes,outbound=outbound,kind=kind,ramp=ramp,end=end,
        reserved=reserved,signals=signals,merges=merges,d=d};
}

function PrependJunction(path,tiles,layout)
{
    local prefix=null;
    // The searched path already contains the final prefix tile.
    for(local i=0;i<tiles.len()-1;i++)
        prefix=VibePath(tiles[i],prefix,tiles[i]==layout.end?layout.kind:null);
    local nodes=PackRailPath(path);
    for(local i=nodes.len()-1;i>=0;i--) prefix=VibePath(nodes[i][0],prefix,nodes[i][1]);
    return prefix;
}
