class VibePath
{
	_tile = 0;
	_parent = null;
	_structure = null;

	constructor(tile, previous_node, structure = null)
	{
		this._tile = tile;
		this._parent = previous_node;
		this._structure = structure;
	}

	function GetTile() { return this._tile; }
	function GetStructure() { return this._structure; }
	function GetParent() { return this._parent; }
}

class MinHeap
{
	_items = null;
	_weight = 1;

	constructor(weight = 1)
	{
		this._weight = weight;
		this._items = [];
	}

	function Count()
	{
		return this._items.len();
	}

	function Push(node)
	{
		this._items.append(node);
		this._SiftUp(this._items.len() - 1);
	}

	function Pop()
	{
		if (this._items.len() == 0) return null;
		local top = this._items[0];
		local last = this._items.pop();
		if (this._items.len() > 0) {
			this._items[0] = last;
			this._SiftDown(0);
		}
		return top;
	}

	function _Less(a, b)
	{
		local fa = a.g + this._weight * a.h;
		local fb = b.g + this._weight * b.h;
		if (fa < fb) return true;
		if (fa > fb) return false;
		return a.h < b.h;
	}

	function _SiftUp(i)
	{
		while (i > 0) {
			local p = (i - 1) >> 1;
			if (!this._Less(this._items[i], this._items[p])) break;
			local tmp = this._items[i];
			this._items[i] = this._items[p];
			this._items[p] = tmp;
			i = p;
		}
	}

	function _SiftDown(i)
	{
		local n = this._items.len();
		while (true) {
			local l = (i << 1) + 1;
			local r = l + 1;
			local best = i;
			if (l < n && this._Less(this._items[l], this._items[best])) best = l;
			if (r < n && this._Less(this._items[r], this._items[best])) best = r;
			if (best == i) break;
			local tmp = this._items[i];
			this._items[i] = this._items[best];
			this._items[best] = tmp;
			i = best;
		}
	}
}

class RailPathFinder
{
    _shorter_tunnel_checks = null;
	_open = null;
	_best_g = null;
	_goal = 0;
	_start = 0;
	_approaches = null;
	_goal_station = 0;
    _goal_entry = 0;
    _entrance_guidance = true;
    _goal_tail = null;
	_reserved = null;
	_reusable = null;
	_virtual_pieces = null;
	_hierarchy = null;
	_jump = false;
	_aystar = false;
	_closed = null;
	_jump_steps = 0;
	_occupied = null;
	_corridor = null;
	_track_checks = null;
	_bridge_checks = null;
	_tunnel_checks = null;
	_heights = null;
	_closest_node = null;
	_nearest_goal = 0;
	_spread = 0;
	_expanded = 0;
	_last_tile = 0;
	_rail_failures = 0;
	_fast = false;
	_done = false;
	_result = null;
	cost = null;
    _start_run = 3;
    _forbid_right_angles = true;
    _junction_reuse = false;

	constructor()
	{
		// Prefer sustained headings (including straight diagonals) over repeated zigzags.
        // Keep close_turn zero: no extra run-history states or hard turn-spacing rule.
        this._forbid_right_angles=!AIGameSettings.IsValid("pf.forbid_90_deg") || AIGameSettings.GetValue("pf.forbid_90_deg")!=0;
		this.cost = { tile = 100, turn = 50, height_change = 55, close_turn = 0, max_cost = 2000000 };
	}

	function InitializePath(sources, goals, reserved = null, preferred = null, occupied = null, fast = false, checks = null)
	{
		this._closest_node = null;
		this._nearest_goal = AIMap.DistanceManhattan(sources[0][0], goals[0][0]);
		this._spread = 0;
		this._expanded = 0;
		this._jump_steps = 0;
		this._rail_failures = 0;
		this._last_tile = sources[0][0];
		this._track_checks = checks == null ? {} : checks;
		this._bridge_checks = {};
		this._tunnel_checks = {};
        this._shorter_tunnel_checks = {};
		this._heights = {};
		this._fast = fast && preferred != null;
		this._occupied = occupied == null ? {} : occupied;
		this._corridor = null;
		if (preferred != null) {
			this._corridor = {};
			foreach (tile in preferred) {
				for (local x = -2; x <= 2; x++) for (local y = -2; y <= 2; y++) {
					local tx = AIMap.GetTileX(tile) + x;
					local ty = AIMap.GetTileY(tile) + y;
					if (tx >= 0 && ty >= 0 && tx < AIMap.GetMapSizeX() && ty < AIMap.GetMapSizeY()) {
						local near = AIMap.GetTileIndex(tx, ty);
						local distance = Abs(x) + Abs(y);
						if (!(near in this._corridor) || distance < this._corridor[near]) this._corridor[near] <- distance;
					}
				}
			}
		}
		this._reserved = {};
		if (reserved != null) foreach (tile in reserved) this._reserved[tile] <- true;
		this._open = MinHeap(this._aystar ? 1.5 : 1);
		this._closed = {};
		this._best_g = {};
		this._done = false;
		this._result = null;
		this._goal = goals[0][0];
		this._goal_station = goals[0][1];
        local goal_out=this._goal-this._goal_station;
        // The last three ground tiles require a straight arrival from outside.
        this._goal_entry=this._goal+3*goal_out;
        this._goal_tail={};
        for(local i=0;i<3;i++) this._goal_tail[this._goal+i*goal_out] <- i;
		this._approaches = {};
		// Reserve straight station throats for signals and both crossover diagonals.
		foreach (endpoint in [sources[0], goals[0]]) {
			local out = endpoint[0] - endpoint[1];
			local travel = endpoint[0] == sources[0][0] ? out : -out;
			for (local i = 0; i < (endpoint[0]==sources[0][0]?this._start_run:3); i++) this._approaches[endpoint[0] + i * out] <- travel;
		}

		local start = sources[0][0];
		this._start = start;
		local h = this._GoalEstimate(start,sources[0][1]);
		local from = sources[0][1];
		local hx = AIMap.GetTileX(start) - AIMap.GetTileX(from);
		local hy = AIMap.GetTileY(start) - AIMap.GetTileY(from);
		local initial = { tile = start, from = from, hx = hx, hy = hy, straight = 2, previous_node = null, g = 0, h = h };
		if(this._aystar) initial.h=this._Estimate(initial);
		this._open.Push(initial);
		this._best_g[this._Key(initial)] <- 0;
	}

	function HalfPrefix()
	{
		local tiles = [];
		local node = this._closest_node;
		while (node != null) { tiles.append(node.tile); node = node.previous_node; }
		tiles.reverse();
		if (tiles.len() < 8) return null;
		local end = (tiles.len()+1)/2;
		// Keep a ground prefix before any bridge; a jump needs its ramp context.
		for (local i = 1; i < end; i++) if (AIMap.DistanceManhattan(tiles[i-1], tiles[i]) != 1) { end = i-1; break; }
		return end >= 2 ? tiles.slice(0, end) : null;
	}

	function SeedPrefix(tiles)
	{
		if (tiles == null || tiles.len() < 2 || tiles[0] != this._start) return false;
		local node = this._open.Pop();
		for (local i = 1; i < tiles.len(); i++) {
			local next = tiles[i];
            if(IsStructureSpan(node.tile,next)) {
                local kind=BuiltRailSpanKind(node.tile,next);
                local distance=AIMap.DistanceManhattan(node.tile,next);
                local step=(next-node.tile)/distance;
                local heading=this._Heading(node.tile,next);
                if(kind==null || this._reusable==null || !(node.tile in this._reusable) || !(next in this._reusable) ||
                    node.tile-node.from!=step || heading[0]!=node.hx || heading[1]!=node.hy) return false;
                for(local j=1;j<=distance;j++) {
                    local t=node.tile+j*step;
                    if(t in this._reserved || t in this._occupied) return false;
                }
                local g=node.g+distance*this.cost.tile+this.HeightCost(node.tile,next);
                for(local j=0;j<distance;j++) this._reserved[node.tile+j*step] <- true;
                node={tile=next,from=next-step,hx=heading[0],hy=heading[1],straight=2,
                    previous_node=node,structure=kind,g=g,h=this._GoalEstimate(next,next-step)};
                this._best_g[this._Key(node)] <- g;
                continue;
            }
			if (next in this._reserved || !AIMap.IsValidTile(next) || !this._CanConnect(node, next)) return false;
			if (!AITile.IsBuildable(next) && !AITile.HasTransportType(next, AITile.TRANSPORT_ROAD)) {
				if (!((next in this._occupied) || (this._reusable!=null && next in this._reusable)) ||
                    !(AIRail.IsRailTile(next) || AIBridge.IsBridgeTile(next) || AITunnel.IsTunnelTile(next)) ||
					AITile.GetOwner(next) != AICompany.ResolveCompanyID(AICompany.COMPANY_SELF) ||
					AIRail.GetRailType(next) != AIRail.GetCurrentRailType()) return false;
			}
			local heading = this._Heading(node.from, next);
			local turned = heading[0] != node.hx || heading[1] != node.hy;
			local straight = turned ? 0 : (node.straight < 2 ? node.straight+1 : 2);
			local g = node.g + this.cost.tile + (turned ? this.cost.turn : 0) + this.HeightCost(node.tile,next);
			if (turned && node.straight < 2) g += (2-node.straight)*this.cost.close_turn;
			if (this._corridor != null) g += next in this._corridor ? 40*this._corridor[next] : 200;
			// The retained prefix is committed for this search; don't loop back into it.
			this._reserved[node.tile] <- true;
			node = { tile=next, from=node.tile, hx=heading[0], hy=heading[1], straight=straight,
				previous_node=node, g=g, h=this._GoalEstimate(next,node.tile) };
			this._best_g[this._Key(node)] <- g;
		}
		this._open.Push(node);
		return true;
	}

	function FindPath(iterations)
	{
		if (this._done) return this._result;

		local left = iterations < 0 ? 2147483647 : iterations;
		while (left > 0 && this._open.Count() > 0) {
			left--;
			local node = this._open.Pop();
			local key = this._Key(node);
			if (node.g > this._best_g[key]) continue;
            if(this._aystar) {
                if(key in this._closed) continue;
                this._closed[key] <- true;
            }
			this._expanded++;
			this._last_tile = node.tile;
			local distance = AIMap.DistanceManhattan(node.tile, this._goal);
			local spread = AIMap.DistanceManhattan(node.tile, this._start);
			if (this._closest_node == null || distance < this._nearest_goal) {
				this._nearest_goal = distance;
				this._closest_node = node;
			}
			if (spread > this._spread) this._spread = spread;

			if (node.tile == this._goal && this._CanConnect(node, this._goal_station)) {
				this._done = true;
				this._result = this._BuildPath(node);
				return this._result;
			}

			if (node.g > this.cost.max_cost) continue;
			this._Expand(node);
		}

		if (this._open.Count() == 0) {
			this._done = true;
			this._result = null;
			return null;
		}
		return false;
	}

    function _GoalEstimate(tile,from)
    {
        if(!this._entrance_guidance) return AIMap.DistanceManhattan(tile,this._goal)*this.cost.tile;
        // Once correctly aligned inside the throat, only the remaining straight
        // steps count. Otherwise every legal route must reach its outer entry
        // before covering those three steps. Manhattan distance remains a lower
        // bound for ground rail, bridges and tunnels; other costs are nonnegative.
        if(tile in this._goal_tail && tile-from==this._goal_station-this._goal)
            return this._goal_tail[tile]*this.cost.tile;
        return (AIMap.DistanceManhattan(tile,this._goal_entry)+3)*this.cost.tile;
    }

    function _Estimate(node)
    {
        // Aim for the outer approach until aligned to enter the station.
        local out=this._goal-this._goal_station;
        local approach=this._goal+2*out;
        local aligned=node.tile in this._approaches && node.tile-node.from==-out;
        local target=aligned ? this._goal : approach;
        local dx=Abs(AIMap.GetTileX(node.tile)-AIMap.GetTileX(target));
        local dy=Abs(AIMap.GetTileY(node.tile)-AIMap.GetTileY(target));
        return (dx>dy ? dx*100+dy*40 : dy*100+dx*40)+(aligned ? 0:200);
    }

	function _Key(node)
	{
        // Heading still controls legal turns. Straight-run history only changes
        // future costs with close-turn penalties, or expansion with jump search.
        // Ordinary A* with no spacing penalty can merge those equivalent states.
        local spacing=(this.cost.close_turn!=0 || this._jump) ? ":"+node.straight : "";
		return node.tile + ":" + node.from + ":" + node.hx + ":" + node.hy + spacing + ((node.previous_node != null && AIMap.DistanceManhattan(node.previous_node.tile, node.tile) > 1) ? ("structure" in node ? ":"+node.structure : ":bridge") : "");
	}

	function _Height(tile)
	{
		if (this._heights == null) this._heights = {};
		// Use the top of the tile, including a level rail foundation on a slope.
		if (!(tile in this._heights)) this._heights[tile] <- AITile.GetMaxHeight(tile);
		return this._heights[tile];
	}

	function HeightCost(from, to, structure = null)
	{
		if (IsStructureSpan(from,to)) {
			if (structure=="tunnel") return 0;
			// The bridge deck is level: only charge for its entrance/exit ramps,
			// never for the hills or water underneath the span.
			local deck = this._Height(from) + (AITile.GetSlope(from)==AITile.SLOPE_FLAT ? 1 : 0);
			return (Abs(deck-this._Height(from)) + Abs(deck-this._Height(to))) * this.cost.height_change;
		}
		return Abs(this._Height(to)-this._Height(from)) * this.cost.height_change;
	}

	function _Heading(from, next)
	{
		local dx = AIMap.GetTileX(next) - AIMap.GetTileX(from);
		local dy = AIMap.GetTileY(next) - AIMap.GetTileY(from);
		return [dx == 0 ? 0 : (dx > 0 ? 1 : -1), dy == 0 ? 0 : (dy > 0 ? 1 : -1)];
	}

	function _CanConnect(node, next)
	{
		if (!AIMap.IsValidTile(next) || next == node.from) return false;
		if (AIMap.DistanceManhattan(node.tile, next) != 1) return false;
		if (node.tile in this._approaches) {
			local travel = this._approaches[node.tile];
			if (node.tile - node.from != travel || next - node.tile != travel) return false;
		}
		// The first outside tile at either station must follow the platform axis.
		if ((node.tile == this._start || node.tile == this._goal) &&
			next - node.tile != node.tile - node.from) return false;
		local heading = this._Heading(node.from, next);
		// Alternating corner pieces can form a straight diagonal. Compare the
		// actual track headings, not whether the grid step changed axis.
		local dot=node.hx * heading[0] + node.hy * heading[1];
        if (dot<0 || (dot==0 && this._forbid_right_angles)) return false;
		if (node.tile in this._occupied) {
			local existing = this._occupied[node.tile];
			local piece = RailPiece(node.from, node.tile, next);
			// Only opposite corner pieces are independent: no merges or crossings.
			if ((existing & piece) != 0 || !ParallelRailPieces(existing | piece) ||
				AITile.GetSlope(node.tile) != AITile.SLOPE_FLAT) return false;
		}
		// A bridge already supplies the straight track on its landing ramp.
		if (node.previous_node != null && AIMap.DistanceManhattan(node.previous_node.tile, node.tile) > 1)
			return next - node.tile == node.tile - node.from;
        if(this._reusable!=null && node.tile in this._reusable) {
            if(this._virtual_pieces!=null && RailTripleKey([node.from,node.tile,next]) in this._virtual_pieces) return true;
            if(AIRail.AreTilesConnected(node.from,node.tile,next)) return true;
            if(this._junction_reuse && AITile.GetSlope(node.tile)==AITile.SLOPE_FLAT) return true;
        }
		local key = node.from + ":" + node.tile + ":" + next;
		if (key in this._track_checks) return this._track_checks[key];
		local test = AITestMode();
		local allowed = AIRail.BuildRail(node.from, node.tile, next);
		if (!allowed) this._rail_failures++;
		this._track_checks[key] <- allowed;
		return allowed;
	}

	function _ExpandBridges(node)
	{
		// Only branch at an obstacle, and never consume a station throat.
		if (node.tile in this._approaches || node.tile in this._occupied ||
			!AITile.IsBuildable(node.tile) ||
			(node.previous_node != null && AIMap.DistanceManhattan(node.previous_node.tile, node.tile) > 1)) return;
		local step = node.tile - node.from;
		local near = node.tile + step;
		if (!AIMap.IsValidTile(near) || AIMap.DistanceManhattan(node.tile, near) != 1) return;
		local heading = this._Heading(node.tile, near);
		if (heading[0] != node.hx || heading[1] != node.hy) return;
		if (AITile.IsBuildable(near) && this._CanConnect(node, near) &&
			AITile.GetMaxHeight(near) >= AITile.GetMaxHeight(node.tile)) return;
		for (local distance = 2; distance <= 12; distance++) {
			local end = node.tile + distance * step;
			if (!AIMap.IsValidTile(end) || AIMap.DistanceManhattan(node.tile, end) != distance) break;
			local blocked = false;
			for (local j = 0; j <= distance; j++) {
				local tile = node.tile + j * step;
				if (tile in this._reserved || tile in this._occupied || tile in this._approaches) { blocked = true; break; }
			}
			if (blocked) break;
			if (!AITile.IsBuildable(end)) continue;
			local exit_tile = end + step;
			if (!AIMap.IsValidTile(exit_tile) || AIMap.DistanceManhattan(end, exit_tile) != 1 ||
				exit_tile in this._reserved || exit_tile in this._occupied || exit_tile in this._approaches ||
				!AITile.IsBuildable(exit_tile)) continue;
			local check = node.tile + ":" + end;
			if (!(check in this._bridge_checks)) this._bridge_checks[check] <- SuitableRailBridge(node.tile, end);
			if (this._bridge_checks[check] == -1 || !this._StructureExitClear(end,step)) continue;
            if(this._fast && !(end in this._corridor)) return;
			local g = node.g + distance * (this.cost.tile + 50) + 600 + this.HeightCost(node.tile,end);
			if (this._corridor != null) g += end in this._corridor ? 40*this._corridor[end] : 200;
			local candidate = { tile=end, from=end-step, hx=heading[0], hy=heading[1], straight=2,
				previous_node=node, structure="bridge", g=g, h=this._GoalEstimate(end,end-step) };
			if(this._aystar) candidate.h=this._Estimate(candidate);
			local key = this._Key(candidate);
            if(this._aystar && key in this._closed) return;
			// Keep bridge-arrival states separate from ordinary rail on a ramp.
			if (key in this._best_g && this._best_g[key] <= g) return;
			this._best_g[key] <- g;
			this._open.Push(candidate);
            // A longer span must not bypass this usable landing.
            return;
		}
	}

    function _StructureExitClear(end,step)
    {
        local exit=end+step,next=exit+step;
        if(!AIMap.IsValidTile(next) || AIMap.DistanceManhattan(end,next)!=2 ||
            exit in this._reserved || exit in this._occupied || exit in this._approaches ||
            !AITile.IsBuildable(exit)) return false;
        local test=AITestMode();
        return AIRail.BuildRail(end,exit,next);
    }

    // Tunnel exits are fixed by the terrain. If surface rail can reach a later
    // portal that exits within the same hill, defer to that shorter crossing.
    function _ShorterTunnelAhead(start,end,step)
    {
        local distance=AIMap.DistanceManhattan(start,end);
        for(local i=0;i<distance-2;i++) {
            local tile=start+i*step,next=tile+step;
            if(tile in this._reserved || tile in this._occupied || tile in this._approaches ||
                !AITile.IsBuildable(tile) || !AITile.IsBuildable(next)) return false;
            {
                local test=AITestMode();
                if(!AIRail.BuildRail(tile-step,tile,next)) return false;
            }
            if(next in this._reserved || next in this._occupied || next in this._approaches) return false;
            local shorter_end=AITunnel.GetOtherTunnelEnd(next);
            if(!AIMap.IsValidTile(shorter_end)) continue;
            local shorter=AIMap.DistanceManhattan(next,shorter_end);
            if(shorter<2 || next+shorter*step!=shorter_end || i+1+shorter>distance ||
                (this._fast && !(shorter_end in this._corridor)) ||
                !this._StructureExitClear(shorter_end,step)) continue;
            local blocked=false;
            for(local j=0;j<=shorter;j++) {
                local t=next+j*step;
                if(t in this._reserved || t in this._occupied || t in this._approaches) {blocked=true;break;}
            }
            if(!blocked && RailTunnelCost(next,shorter_end)>=0) return true;
        }
        return false;
    }

	function _ExpandTunnel(node)
	{
		if (node.tile in this._approaches || node.tile in this._occupied || !AITile.IsBuildable(node.tile) ||
			AITile.GetSlope(node.tile)==AITile.SLOPE_FLAT ||
			(node.previous_node!=null && IsStructureSpan(node.previous_node.tile,node.tile))) return;
		if (!(node.tile in this._tunnel_checks)) {
			local end=AITunnel.GetOtherTunnelEnd(node.tile);
			local cost=AIMap.IsValidTile(end) && AIMap.DistanceManhattan(node.tile,end)<=32 ? RailTunnelCost(node.tile,end) : -1;
			this._tunnel_checks[node.tile] <- { end=end, cost=cost };
		}
		local tunnel=this._tunnel_checks[node.tile];
		if(tunnel.cost<0) return;
		local end=tunnel.end;
		local distance=AIMap.DistanceManhattan(node.tile,end);
		local step=node.tile-node.from;
		if(distance<2 || node.tile+distance*step!=end) return;
		local heading=this._Heading(node.tile,end);
		if(heading[0]!=node.hx || heading[1]!=node.hy) return;
		local exit_tile=end+step;
		if(!AIMap.IsValidTile(exit_tile) || AIMap.DistanceManhattan(end,exit_tile)!=1 ||
			!AITile.IsBuildable(end) || !AITile.IsBuildable(exit_tile) ||
			exit_tile in this._reserved || exit_tile in this._approaches || exit_tile in this._occupied ||
			(this._fast && !(end in this._corridor))) return;
		for(local i=0;i<=distance;i++) {
			local tile=node.tile+i*step;
			if(tile in this._reserved || tile in this._approaches || tile in this._occupied) return;
		}
        if(!this._StructureExitClear(end,step)) return;
        if(!(node.tile in this._shorter_tunnel_checks))
            this._shorter_tunnel_checks[node.tile] <- this._ShorterTunnelAhead(node.tile,end,step);
        if(this._shorter_tunnel_checks[node.tile]) return;
		local g=node.g+distance*this.cost.tile+800+tunnel.cost/100;
		if(this._corridor!=null) g+=end in this._corridor ? 40*this._corridor[end] : 200;
		local candidate={tile=end,from=end-step,hx=heading[0],hy=heading[1],straight=2,previous_node=node,
			structure="tunnel",g=g,h=this._GoalEstimate(end,end-step)};
		if(this._aystar) candidate.h=this._Estimate(candidate);
		local key=this._Key(candidate);
        if(this._aystar && key in this._closed) return;
		if(key in this._best_g && this._best_g[key]<=g) return;
		this._best_g[key] <- g;
		this._open.Push(candidate);
	}

    // JPS-inspired pruning only in open, level terrain. Railway turn costs
    // invalidate standard JPS symmetry rules; a bounded trial always has A* fallback.
    function _JumpClear(tile)
    {
        local x=AIMap.GetTileX(tile), y=AIMap.GetTileY(tile);
        if(x<1 || y<1 || x>=AIMap.GetMapSizeX()-1 || y>=AIMap.GetMapSizeY()-1) return false;
        local height=this._Height(tile);
        for(local dx=-1;dx<=1;dx++) for(local dy=-1;dy<=1;dy++) {
            local t=AIMap.GetTileIndex(x+dx,y+dy);
            if(t in this._reserved || t in this._occupied || t in this._approaches ||
                !AITile.IsBuildable(t) || AITile.IsWaterTile(t) ||
                AITile.HasTransportType(t,AITile.TRANSPORT_ROAD) ||
                AITile.GetSlope(t)!=AITile.SLOPE_FLAT || this._Height(t)!=height) return false;
        }
        return true;
    }

    function _JumpAhead(candidate)
    {
        for(local length=0;length<7;length++) {
            if(candidate.straight<2 || !this._JumpClear(candidate.tile)) break;
            local dx=AIMap.GetTileX(this._goal)-AIMap.GetTileX(candidate.tile);
            local dy=AIMap.GetTileY(this._goal)-AIMap.GetTileY(candidate.tile);
            // Keep branch points where a straight or diagonal approach can begin.
            if(Abs(dx)+Abs(dy)<=6 || (candidate.hx!=0 && Abs(dx)<=2) ||
                (candidate.hy!=0 && Abs(dy)<=2) ||
                ((candidate.hx==0 || candidate.hy==0) && Abs(Abs(dx)-Abs(dy))<=1)) break;
            local step=candidate.tile-candidate.from;
            local next_step=(candidate.hx!=0 && candidate.hy!=0) ?
                (Abs(step)==1 ? candidate.hy*AIMap.GetMapSizeX() : candidate.hx) : step;
            local next=candidate.tile+next_step;
            if(!AIMap.IsValidTile(next) || !this._JumpClear(next)) break;
            if(this._hierarchy!=null && !((AIMap.GetTileX(next)/8+(AIMap.GetTileY(next)/8)*(AIMap.GetMapSizeX()/8)) in this._hierarchy)) break;
            if(this._fast && !(next in this._corridor)) break;
            local heading=this._Heading(candidate.from,next);
            if(heading[0]!=candidate.hx || heading[1]!=candidate.hy || !this._CanConnect(candidate,next)) break;
            local g=candidate.g+this.cost.tile;
            if(this._corridor!=null) g+=next in this._corridor ? 40*this._corridor[next] : 200;
            local next_node={tile=next,from=candidate.tile,hx=heading[0],hy=heading[1],straight=2,
                previous_node=candidate,g=g,h=this._GoalEstimate(next,candidate.tile)};
            local key=this._Key(next_node);
            if(key in this._best_g && this._best_g[key]<=g) break;
            candidate=next_node;
            this._jump_steps++;
        }
        return candidate;
    }

	function _Expand(node)
	{
		this._ExpandBridges(node);
		this._ExpandTunnel(node);
		local offsets = [1, -1, AIMap.GetMapSizeX(), -AIMap.GetMapSizeX()];
		foreach (off in offsets) {
			local next = node.tile + off;
			if (next in this._reserved) continue;
			if(this._hierarchy!=null && !((AIMap.GetTileX(next)/8+(AIMap.GetTileY(next)/8)*(AIMap.GetMapSizeX()/8)) in this._hierarchy)) continue;
			if (!AIMap.IsValidTile(next)) continue;
			if (this._fast && !(next in this._corridor)) continue;
			if (!AITile.IsBuildable(next) && !AITile.HasTransportType(next, AITile.TRANSPORT_ROAD)) {
				if (!((next in this._occupied) || (this._reusable!=null && next in this._reusable)) || !AIRail.IsRailTile(next) ||
					AITile.GetOwner(next) != AICompany.ResolveCompanyID(AICompany.COMPANY_SELF) ||
					AIRail.GetRailType(next) != AIRail.GetCurrentRailType()) continue;
			}
			local heading = this._Heading(node.from, next);
			local turned = heading[0] != node.hx || heading[1] != node.hy;
			local straight = turned ? 0 : (node.straight < 2 ? node.straight + 1 : 2);
			local g = node.g + this.cost.tile + (turned ? this.cost.turn : 0) + this.HeightCost(node.tile,next);
			if (turned && node.straight < 2) g += (2 - node.straight) * this.cost.close_turn;
			if (this._corridor != null) g += next in this._corridor ? 40 * this._corridor[next] : 200;
			local h = this._GoalEstimate(next,node.tile);
			local candidate = { tile = next, from = node.tile, hx = heading[0], hy = heading[1], straight = straight, previous_node = node, g = g, h = h };
			if(this._aystar) candidate.h=this._Estimate(candidate);
			local key = this._Key(candidate);
            if(this._aystar && key in this._closed) continue;
			if (key in this._best_g && g >= this._best_g[key]) continue;
			if (!this._CanConnect(node, next)) continue;
            if(this._jump) candidate=this._JumpAhead(candidate);
            key=this._Key(candidate);
            if(this._aystar && key in this._closed) continue;
            if(key in this._best_g && this._best_g[key]<=candidate.g) continue;
            this._best_g[key] <- candidate.g;
			this._open.Push(candidate);
		}
	}

    // Bounded local cleanup: weighted A* can reach the goal through a short
    // sideways excursion even when a direct alignment also builds. Keep all
    // station throats, structures and already-built sections intact.
    function StraightenPath(path)
    {
        local nodes=[];
        for(local p=path;p!=null;p=p.GetParent()) nodes.append({tile=p.GetTile(),structure=p.GetStructure()});
        nodes.reverse();
        local trials=0,changes=0,deadline=AIController.GetTick()+20;
        for(local i=3;i<nodes.len()-4 && trials<64 && changes<4;i++) {
            if(AIController.GetTick()>deadline) break;
            for(local j=i+3;j<nodes.len()-2 && j<=i+12 && trials<64;j++) {
                local a=nodes[i].tile,z=nodes[j].tile;
                local dx=AIMap.GetTileX(z)-AIMap.GetTileX(a),dy=AIMap.GetTileY(z)-AIMap.GetTileY(a);
                if((dx!=0 && dy!=0 && Abs(dx)!=Abs(dy)) || Abs(dx)+Abs(dy)>j-i) continue;
                local safe=true;
                for(local k=i-1;k<=j+1;k++) if(nodes[k].structure!=null ||
                    AIMap.DistanceManhattan(nodes[k-1].tile,nodes[k].tile)!=1 ||
                    nodes[k].tile in this._reserved || AIRail.IsRailTile(nodes[k].tile)) {safe=false;break;}
                if(!safe) continue;
                local accepted=false;
                foreach(x_first in [true,false]) {
                    local middle=[nodes[i]],x=AIMap.GetTileX(a),y=AIMap.GetTileY(a);
                    local sx=dx<0?-1:1,sy=dy<0?-1:1,nx=Abs(dx),ny=Abs(dy),axis=x_first;
                    while(nx>0 || ny>0) {
                        if(nx>0 && (ny==0 || axis)) {x+=sx;nx--;}
                        else {y+=sy;ny--;}
                        axis=!axis;
                        middle.append({tile=AIMap.GetTileIndex(x,y),structure=null});
                    }
                    if(middle.len()<2) continue;
                    if(trials>=64 || AIController.GetTick()>deadline) return this._PathFromNodes(nodes,path,changes);
                    local candidate=nodes.slice(0,i);
                    candidate.extend(middle);candidate.extend(nodes.slice(j+1));
                    local end=i+middle.len(),old_cost=this._LocalShapeCost(nodes,i-1,j+1),new_cost=this._LocalShapeCost(candidate,i-1,end);
                    if(new_cost>=old_cost) continue;
                    trials++;
                    local counts={};foreach(n in candidate) {if(n.tile in counts) counts[n.tile]++;else counts[n.tile] <- 1;}
                    safe=true;
                    for(local k=i-1;k<=end;k++) {
                        local tile=candidate[k].tile;
                        if(tile in this._reserved || (!AITile.IsBuildable(tile) && !AITile.HasTransportType(tile,AITile.TRANSPORT_ROAD) && !(tile in this._occupied))) {safe=false;break;}
                        // Do not intersect another part of this same proposed line.
                        if(counts[tile]>1) {safe=false;break;}
                        local h=this._Heading(candidate[k-2].tile,tile);
                        local node={tile=tile,from=candidate[k-1].tile,hx=h[0],hy=h[1],previous_node=null};
                        if(!this._CanConnect(node,candidate[k+1].tile)) {safe=false;break;}
                    }
                    if(safe) {nodes=candidate;changes++;accepted=true;break;}
                }
                if(accepted) break;
            }
        }
        return this._PathFromNodes(nodes,path,changes);
    }
    function _PathFromNodes(nodes,path,changes)
    {
        if(changes==0) return path;
        local result=null;
        foreach(n in nodes) result=VibePath(n.tile,result,n.structure);
        AILog.Info("Pathfinder: removed "+changes+" unnecessary short track detours.");
        return result;
    }
    function _LocalShapeCost(nodes,first,last)
    {
        local cost=0;
        for(local k=first;k<=last;k++) {
            local before=this._Heading(nodes[k-2].tile,nodes[k].tile);
            local after=this._Heading(nodes[k-1].tile,nodes[k+1].tile);
            cost+=this.cost.tile+this.HeightCost(nodes[k].tile,nodes[k+1].tile);
            if(before[0]!=after[0] || before[1]!=after[1]) cost+=this.cost.turn;
        }
        return cost;
    }

	function _BuildPath(node)
	{
		local path = null;
		while (node != null) {
			path = VibePath(node.tile, path, "structure" in node ? node.structure : null);
			node = node.previous_node;
		}
		local reversed = null;
		while (path != null) {
			reversed = VibePath(path.GetTile(), reversed, path.GetStructure());
			path = path.GetParent();
		}
		return reversed;
	}
}
