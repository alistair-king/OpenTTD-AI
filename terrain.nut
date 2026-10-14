// Intensive landscaping is funded from retained earnings, never new debt.
function EarthworksFinanciallyReady(loan,cash,reserve_cost=0)
{
    return loan==0 && cash>=500000+reserve_cost;
}
function IntensiveEarthworksAllowed(reserve_cost=0)
{
    return EarthworksFinanciallyReady(AICompany.GetLoanAmount(),
        AICompany.GetBankBalance(AICompany.COMPANY_SELF),reserve_cost);
}

// Corner-height planning for small cuttings and embankments beside a route.
// A corner is addressed as the north corner of its tile; adjacent tiles share it.
class PairedTerrain
{
    failure_reason="Earthworks failed";
    failure_detail="";
    function Fail(reason,detail) {
        this.failure_reason=reason;this.failure_detail=detail;
        AILog.Info("Earthworks: "+reason+"; "+detail);
        return false;
    }

	targets = null;
	original = null;
	protected_corners = null;
	desired = null;
	restore_failed = false;
	max_change = 2;
	max_corners = 48;
	max_cost = 20000;

	constructor(max_change = 2, max_corners = 48, max_cost = 20000)
	{
        if(!IntensiveEarthworksAllowed()) {
            if(max_change>1) max_change=1;
            if(max_corners>16) max_corners=16;
            if(max_cost>5000) max_cost=5000;
        }
		this.max_change=max_change; this.max_corners=max_corners; this.max_cost=max_cost;
		targets = {};
		original = {};
		protected_corners = {};
		desired = {};
	}

	function Corners(tile)
	{
		local w = AIMap.GetMapSizeX();
		return [tile, tile + 1, tile + w, tile + w + 1];
	}

	function Protect(tiles)
	{
		foreach (tile in tiles) foreach (corner in this.Corners(tile)) this.protected_corners[corner] <- true;
	}

	function Height(corner)
	{
		return corner in this.targets ? this.targets[corner] : AITile.GetCornerHeight(corner, AITile.CORNER_N);
	}

	function Safe(corner)
	{
		local x = AIMap.GetTileX(corner);
		local y = AIMap.GetTileY(corner);
		if (x < 2 || y < 2 || x >= AIMap.GetMapSizeX() - 2 || y >= AIMap.GetMapSizeY() - 2) return false;
		if (corner in this.protected_corners) return false;
		local w = AIMap.GetMapSizeX();
		foreach (tile in [corner, corner-1, corner-w, corner-w-1]) {
			if (!AITile.IsBuildable(tile) || AITile.IsWaterTile(tile) ||
				AITile.HasTransportType(tile, AITile.TRANSPORT_ROAD) ||
				AITile.HasTransportType(tile, AITile.TRANSPORT_RAIL)) return false;
		}
		return true;
	}

	function SetHeight(corner, height)
	{
		local queue = [[corner, height]];
		local w = AIMap.GetMapSizeX();
		for (local i = 0; i < queue.len(); i++) {
			local c = queue[i][0];
			local h = queue[i][1];
			if (this.Height(c) == h) continue;
			if (!this.Safe(c) || h < 1 || Abs(h - AITile.GetCornerHeight(c, AITile.CORNER_N)) > this.max_change) return false;
			if (c in this.desired && this.desired[c] != h) return false;
			this.targets[c] <- h;
			if (this.targets.len() > this.max_corners || queue.len() > 256) return false;
			// Include propagated slope changes in the plan and in its safety/budget limits.
			foreach (next in [c-1, c+1, c-w, c+w]) {
				local nh = this.Height(next);
				if (nh > h+1) queue.append([next, h+1]);
				else if (nh < h-1) queue.append([next, h-1]);
			}
		}
		return true;
	}

	function Match(tile, adjacent)
	{
		local saved = clone this.targets;
		local constraints = clone this.desired;
		local source = this.Corners(tile);
		local destination = this.Corners(adjacent);
		for (local i = 0; i < 4; i++) {
			local h = AITile.GetCornerHeight(source[i], AITile.CORNER_N);
			if (!this.SetHeight(destination[i], h)) {
				this.targets = saved;
				this.desired = constraints;
				return false;
			}
			this.desired[destination[i]] <- h;
		}
		return true;
	}

	function Matched(pairs, path)
	{
		local occupied = {};
		foreach (index, tile in path) occupied[tile] <- index;
		local count = 0;
		foreach (pair in pairs) {
			if (!(pair[1] in occupied)) continue;
			local index = occupied[pair[1]];
			if (index == 0 || index == path.len()-1) continue;
			local travel = path[index] - path[index-1];
			if (Abs(travel) != Abs(pair[2]) || path[index+1] - path[index] != travel) continue;
			local a = this.Corners(pair[0]);
			local b = this.Corners(pair[1]);
			local equal = true;
			for (local i = 0; i < 4; i++)
				if (AITile.GetCornerHeight(a[i], AITile.CORNER_N) != AITile.GetCornerHeight(b[i], AITile.CORNER_N)) equal = false;
			if (equal) count++;
		}
		return count;
	}

	function MoveTo(heights)
	{
		// A valid target height field lets single-corner commands propagate only
		// towards the target, never beyond it. Re-read after every command.
		foreach (corner, height in heights) {
			for (local step = 0; step < 4; step++) {
				local current = AITile.GetCornerHeight(corner, AITile.CORNER_N);
				if (current == height) break;
				if (!(current < height ? AITile.RaiseTile(corner, AITile.SLOPE_N) :
					AITile.LowerTile(corner, AITile.SLOPE_N)))
                    return this.Fail("Terrain command rejected","tile="+corner+", target="+height+", error="+AIError.GetLastErrorString());
			}
		}
		foreach (corner, height in heights)
			if (AITile.GetCornerHeight(corner, AITile.CORNER_N) != height)
                return this.Fail("Height target not reached","tile="+corner+", target="+height);
		return true;
	}

	function Apply()
	{
        this.failure_reason="Earthworks failed";this.failure_detail="";
		if (this.targets.len() == 0) return true;
        // Recheck at execution: plans may predate spending, borrowing or loading.
        local changed=0,intensive=false;
        foreach(corner,height in this.targets) {
            local delta=Abs(height-AITile.GetCornerHeight(corner,AITile.CORNER_N));
            if(delta>0) changed++;
            if(delta>1) intensive=true;
        }
        if(changed>16) intensive=true;
        if(intensive && !IntensiveEarthworksAllowed())
            return this.Fail("Wait for debt-free cash","intensive work needs no loan and at least 500000 cash");
		local cost = 0;
		foreach (corner, height in this.targets) {
			local current = AITile.GetCornerHeight(corner, AITile.CORNER_N);
			this.original[corner] <- current;
			if (current == height) continue;
			local test = AITestMode();
			local accounting = AIAccounting();
			if (!(current < height ? AITile.RaiseTile(corner, AITile.SLOPE_N) :
				AITile.LowerTile(corner, AITile.SLOPE_N)))
                return this.Fail("Terrain test rejected","tile="+corner+", target="+height+", error="+AIError.GetLastErrorString());
			cost += accounting.GetCosts() * Abs(height-current);
		}
		// Keep enough for the railway and a rollback; no large landscape projects.
        if(cost>this.max_cost) return this.Fail("Earthworks cost limit","estimate="+cost+", limit="+this.max_cost);
        if(cost>5000) intensive=true;
        local required=intensive ? 500000+2*cost : 80000+2*cost;
        if(intensive) {
            if(!IntensiveEarthworksAllowed(2*cost))
                return this.Fail("Wait for debt-free cash","estimate="+cost+", required="+required+
                    ", cash="+AICompany.GetBankBalance(AICompany.COMPANY_SELF)+", loan="+AICompany.GetLoanAmount());
        } else EnsureMoney(required);
        local cash=AICompany.GetBankBalance(AICompany.COMPANY_SELF);
        if(cash<required) return this.Fail("Earthworks cash reserve","estimate="+cost+", required="+required+", cash="+cash);
		if (this.MoveTo(this.targets)) return true;
        local reason=this.failure_reason,detail=this.failure_detail;
		this.restore_failed = !this.Restore();
        this.failure_reason=reason;this.failure_detail=detail;
		return false;
	}

	function Restore()
	{
		if (this.MoveTo(this.original)) return true;
		AILog.Warning("Could not fully restore a small earthwork; keeping the modified terrain.");
		return false;
	}
}
