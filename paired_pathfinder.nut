// Bounded weighted joint search (not a shortest-path guarantee): both frontiers move together, with short waits for
// inner/outer bends. Individual rail legality stays in RailPathFinder.
class PairedPathFinder
{
    lanes = null;
    open = null;
    best = null;
    expanded = 0;
    last_tile = 0;

    constructor(start, goal, start2, goal2, reserved)
    {
        this.lanes = [RailPathFinder(), RailPathFinder()];
        this.lanes[0].InitializePath([start], [goal], reserved);
        this.lanes[1].InitializePath([start2], [goal2], reserved);
        this.open = MinHeap(); this.best = {};
        local a=this.lanes[0]._open.Pop(), b=this.lanes[1]._open.Pop();
        local node={a=a,b=b,used_a={},used_b={},skew=0,g=0,h=(a.h+b.h)*3/2};
        this.open.Push(node); this.best[this.Key(node)] <- 0;
    }

    function Key(node)
    {
        return this.lanes[0]._Key(node.a)+"/"+this.lanes[1]._Key(node.b)+"/"+node.skew;
    }

    function Moves(pf, node)
    {
        local moves=[node];
        if (node.tile==pf._goal) return moves;
        // Independent pruning is invalid here: the other frontier matters.
        pf._open=MinHeap(); pf._best_g={};
        pf._Expand(node);
        while(pf._open.Count()>0) {
            local next=pf._open.Pop();
            if(next.tile in pf._approaches && next.tile-next.from!=pf._approaches[next.tile]) continue;
            if(next.tile==pf._goal && !pf._CanConnect(next,pf._goal_station)) continue;
            local out=pf._goal-pf._goal_station;
            local approach=pf._goal+2*out;
            local target=next.tile in pf._approaches && next.tile-next.from==-out ? pf._goal:approach;
            local dx=Abs(AIMap.GetTileX(next.tile)-AIMap.GetTileX(target));
            local dy=Abs(AIMap.GetTileY(next.tile)-AIMap.GetTileY(target));
            next.h=(dx>dy ? dx*100+dy*40 : dy*100+dx*40)+(target==approach ? 200:0);
            moves.append(next);
        }
        return moves;
    }

    function Compatible(tile, mask, other)
    {
        if (!(tile in other)) return true;
        return mask!=255 && other[tile]!=255 && (mask & other[tile])==0 &&
            ParallelRailPieces(mask | other[tile]) && AITile.GetSlope(tile)==AITile.SLOPE_FLAT;
    }

    function Advance(node, next, used)
    {
        if(node==next) return used;
        if(next.tile in used) return null;
        local result=clone used;
        if(IsStructureSpan(node.tile,next.tile)) {
            local distance=AIMap.DistanceManhattan(node.tile,next.tile);
            local step=(next.tile-node.tile)/distance;
            for(local i=0;i<=distance;i++) {
                local tile=node.tile+i*step;
                if(tile in result) return null;
                result[tile] <- 255;
            }
        } else if(node.previous_node==null || !IsStructureSpan(node.previous_node.tile,node.tile)) {
            if(node.tile in result) return null;
            result[node.tile] <- RailPiece(node.from,node.tile,next.tile);
        }
        return result;
    }

    function Finish(pf,node,used)
    {
        if(!pf._CanConnect(node,pf._goal_station)) return null;
        local result=clone used;
        if(node.previous_node==null || !IsStructureSpan(node.previous_node.tile,node.tile))
            result[node.tile] <- RailPiece(node.from,node.tile,pf._goal_station);
        return result;
    }

    function Disjoint(a,b)
    {
        foreach(tile,mask in a) if(!this.Compatible(tile,mask,b)) return false;
        return true;
    }

    // false = pending, null = exhausted; caller also imposes a total budget.
    function FindPath(iterations)
    {
        while(iterations-- > 0 && this.open.Count()>0) {
            local node=this.open.Pop();
            if(node.g!=this.best[this.Key(node)]) continue;
            this.expanded++; this.last_tile=node.a.tile;
            if(node.a.tile==this.lanes[0]._goal && node.b.tile==this.lanes[1]._goal) {
                local a=this.Finish(this.lanes[0],node.a,node.used_a);
                local b=this.Finish(this.lanes[1],node.b,node.used_b);
                if(a!=null && b!=null && this.Disjoint(a,b))
                    return {path=this.lanes[0]._BuildPath(node.a),path2=this.lanes[1]._BuildPath(node.b)};
            }
            local moves_a=this.Moves(this.lanes[0],node.a);
            local moves_b=this.Moves(this.lanes[1],node.b);
            foreach(a in moves_a) foreach(b in moves_b) {
                if(a==node.a && b==node.b) continue;
                local distance=AIMap.DistanceManhattan(a.tile,b.tile);
                if(distance>2 || (a.tile==node.b.tile && b.tile==node.a.tile)) continue;
                local skew=node.skew+(a==node.a ? 0:1)-(b==node.b ? 0:1);
                if(Abs(skew)>4) continue;
                // A corner piece on a diagonal is physically shorter than a
                // full straight tile. Grid Manhattan distance alone favours Ls.
                // Keep spacing cost small: close diagonals alternate 0/2 tiles.
                local g=node.g+a.g-node.a.g+b.g-node.b.g+(distance>1 ? 10:0)
                    -(a!=node.a && a.hx!=0 && a.hy!=0 ? 30:0)
                    -(b!=node.b && b.hx!=0 && b.hy!=0 ? 30:0);
                local candidate={a=a,b=b,skew=skew,g=g,h=(a.h+b.h)*3/2,used_a=null,used_b=null};
                local key=this.Key(candidate);
                if(key in this.best && g>=this.best[key]) continue;
                local used_a=this.Advance(node.a,a,node.used_a);
                local used_b=this.Advance(node.b,b,node.used_b);
                if(used_a==null || used_b==null || !this.Disjoint(used_a,used_b)) continue;
                candidate.used_a=used_a; candidate.used_b=used_b;
                this.best[key] <- g; this.open.Push(candidate);
            }
        }
        return this.open.Count()==0 ? null:false;
    }
}
