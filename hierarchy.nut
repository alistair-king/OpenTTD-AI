// Coarse A* guides the detailed railway search; sampled cells are hints,
// never proof of rail connectivity. Failed refinement falls back to full A*.
class RailHierarchy
{
    size=8;
    width=0;
    height=0;
    samples=null;
    constructor() { width=AIMap.GetMapSizeX()/size; height=AIMap.GetMapSizeY()/size; samples={}; }
    function Cell(tile) { return AIMap.GetTileX(tile)/size+(AIMap.GetTileY(tile)/size)*width; }
    function Sample(cell)
    {
        if(cell in samples) return samples[cell];
        local x=(cell%width)*size, y=(cell/width)*size;
        local penalty=0, low=10000, high=0;
        foreach(dx in [2,5]) foreach(dy in [2,5]) {
            local tile=AIMap.GetTileIndex(x+dx,y+dy);
            local h=AITile.GetMaxHeight(tile);
            if(h<low) low=h; if(h>high) high=h;
            if(AITile.IsWaterTile(tile)) penalty+=100;
            else if(!AITile.IsBuildable(tile)) penalty+=150;
        }
        local result={cost=penalty+(high-low)*80,height=(low+high)/2};
        samples[cell] <- result; return result;
    }
    function Plan(a,b)
    {
        local start=Cell(a), goal=Cell(b), open=MinHeap(), best={};
        open.Push({cell=start,g=0,h=0,previous_node=null}); best[start] <- 0;
        for(local count=0;count<1024 && open.Count()>0;count++) {
            local node=open.Pop();
            if(node.g!=best[node.cell]) continue;
            if(node.cell==goal) {
                local path=[];
                while(node!=null) { path.append(node.cell); node=node.previous_node; }
                return path;
            }
            local x=node.cell%width, y=node.cell/width;
            foreach(d in [[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]]) {
                local nx=x+d[0], ny=y+d[1];
                if(nx<0 || ny<0 || nx>=width || ny>=height) continue;
                local cell=nx+ny*width, sample=Sample(cell);
                local g=node.g+(d[0]!=0 && d[1]!=0 ? 1120:800)+sample.cost+Abs(sample.height-Sample(node.cell).height)*80;
                if(cell in best && best[cell]<=g) continue;
                best[cell] <- g;
                local dx=Abs(nx-goal%width), dy=Abs(ny-goal/width);
                local h=800*(dx>dy ? dx:dy)+320*(dx<dy ? dx:dy);
                open.Push({cell=cell,g=g,h=h,previous_node=node});
            }
        }
        return null;
    }
    function Corridor(path,radius)
    {
        local cells={};
        foreach(cell in path) for(local dx=-radius;dx<=radius;dx++) for(local dy=-radius;dy<=radius;dy++) {
            local x=cell%width+dx, y=cell/width+dy;
            if(x>=0 && y>=0 && x<width && y<height) cells[x+y*width] <- true;
        }
        return cells;
    }
}
