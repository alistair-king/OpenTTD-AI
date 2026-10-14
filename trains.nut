// Renew at the existing twenty-year limit or the vehicle's lifetime, whichever is earlier.
function TrainNeedsRenewal(train)
{
    return AIVehicle.GetAge(train)>=20*365 || AIVehicle.GetAgeLeft(train)<=0;
}

class TrainBuyer
{
	cargo = 0;

	constructor(cargo)
	{
		this.cargo = cargo;
	}

	function BestEngine()
	{
		local engines = AIEngineList(AIVehicle.VT_RAIL);
		engines.Valuate(AIEngine.IsWagon);
		engines.KeepValue(0);
		engines.Valuate(AIEngine.IsBuildable);
		engines.KeepValue(1);
		engines.Valuate(AIEngine.CanRunOnRail, AIRail.GetCurrentRailType());
		engines.KeepValue(1);
		engines.Valuate(AIEngine.HasPowerOnRail, AIRail.GetCurrentRailType());
		engines.KeepValue(1);
		return this.SelectEngine(engines);
	}

	function SelectEngine(engines)
	{
		local max_power = 1;
		local max_speed = 1;
		foreach (engine, _ in engines) {
			if (!AICargo.HasCargoClass(this.cargo,AICargo.CC_PASSENGERS) && AIEngine.GetCapacity(engine)>0 &&
				AIEngine.GetCargoType(engine)!=this.cargo) continue;
			if (AIEngine.GetPower(engine) > max_power) max_power = AIEngine.GetPower(engine);
			if (AIEngine.GetMaxSpeed(engine) > max_speed) max_speed = AIEngine.GetMaxSpeed(engine);
		}
		local best = -1;
		local best_score = -1.0;
		foreach (engine, _ in engines) {
			if (!AICargo.HasCargoClass(this.cargo,AICargo.CC_PASSENGERS) && AIEngine.GetCapacity(engine)>0 &&
				AIEngine.GetCargoType(engine)!=this.cargo) continue;
			// Normalise unlike units: power and reliability each carry 40%, speed 20%.
			local score = 40.0 * AIEngine.GetPower(engine) / max_power +
				0.4 * AIEngine.GetReliability(engine) + 20.0 * AIEngine.GetMaxSpeed(engine) / max_speed;
			if (best < 0 || score > best_score || (score == best_score &&
				AIEngine.GetPrice(engine) < AIEngine.GetPrice(best))) {
				best = engine;
				best_score = score;
			}
		}
		return best;
	}

	function NewerPowerfulEngine(train, depot)
	{
		local current = AIVehicle.GetEngineType(train);
		local rail = AIRail.GetRailType(depot);
		local candidates = AIList();
		foreach (engine, _ in AIEngineList(AIVehicle.VT_RAIL)) {
			if (AIEngine.IsWagon(engine) || !AIEngine.IsBuildable(engine) ||
				AIEngine.GetDesignDate(engine) <= AIEngine.GetDesignDate(current) ||
				AIEngine.GetPower(engine) <= AIEngine.GetPower(current) ||
				!AIEngine.CanRunOnRail(engine, rail) || !AIEngine.HasPowerOnRail(engine, rail)) continue;
			candidates.AddItem(engine, 0);
		}
		return this.SelectEngine(candidates);
	}

	function MoveCarriages(source, destination)
	{
		// Move actual wagons individually, retaining articulated/multiheaded
		// locomotive parts with their engine rather than treating them as carriages.
		for (local i = 1; i < AIVehicle.GetNumWagons(source);) {
			if (!AIEngine.IsWagon(AIVehicle.GetWagonEngineType(source, i))) { i++; continue; }
			if (!AIVehicle.MoveWagon(source, i, destination, AIVehicle.GetNumWagons(destination)-1)) return false;
		}
		return true;
	}

	function ReplaceEngine(train, record)
	{
		if (!AIVehicle.IsStoppedInDepot(train) || AIVehicle.GetLocation(train) != record.depot) return -1;
		// Do not honour an old queued upgrade before the revised age threshold.
		local renewal = TrainNeedsRenewal(train);
		if (!renewal && AIVehicle.GetAge(train) < 5 * 365 && record.replacement < 0) return -1;
		local current = AIVehicle.GetEngineType(train);
		// Attempt 0: the preferred (newer, more powerful) engine. Attempt 1,
		// for 20-year renewals only: a fresh current-design engine, which fits
		// the same consist by construction. Without it, a newer engine that is
		// a tile too long for the platforms would block the renewal forever.
		for (local attempt = 0; attempt < 2; attempt++) {
			local replacement = record.replacement;
			local tried_current = false;
			if (replacement < 0 || !AIVehicle.IsValidVehicle(replacement)) {
				local engine;
				if (attempt == 0) {
					engine = this.NewerPowerfulEngine(train, record.depot);
					// Age renewal does not require a newer or more powerful design.
					if (renewal && engine < 0) {
						if (this.UsableEngineHere(current, record.depot)) {
							engine = current;
							tried_current = true;
						} else {
							local previous_type = AIRail.GetCurrentRailType();
							AIRail.SetCurrentRailType(AIRail.GetRailType(record.depot));
							engine = this.BestEngine();
							AIRail.SetCurrentRailType(previous_type);
							tried_current = engine == current;
						}
					}
					if (engine < 0 || !EnsureMoney(AIEngine.GetPrice(engine) + 10000)) return -1;
				} else {
					if (!renewal || !this.UsableEngineHere(current, record.depot)) break;
					engine = current;
					tried_current = true;
					if (!EnsureMoney(AIEngine.GetPrice(engine) + 10000)) break;
				}
				record.engine_capacity = AIVehicle.GetCapacity(train, this.cargo);
				replacement = AIVehicle.BuildVehicle(record.depot, engine);
				if (!AIVehicle.IsValidVehicle(replacement)) {
					record.replacement = -1;
					continue;
				}
				record.replacement = replacement;
			} else {
				tried_current = AIVehicle.GetEngineType(replacement) == current;
			}
			if (!AIOrder.CopyOrders(replacement, train) || !AIOrder.SetOrderFlags(replacement, 2, record.flags) ||
				!this.MoveCarriages(train, replacement) || AIVehicle.GetLength(replacement) > record.max_length ||
				AIVehicle.GetCapacity(replacement, this.cargo) < record.engine_capacity) {
				// Keep the old locomotive until all its carriages can be safely retained.
				if (!(this.MoveCarriages(replacement, train) && AIVehicle.SellVehicle(replacement))) return -1;
				record.replacement = -1;
				// A second attempt only makes sense with a different engine.
				if (tried_current) return -1;
				continue;
			}
			if (!AIVehicle.SellVehicle(train)) return -1;
			AILog.Info("Optimiser: replaced engine on train " + train + " with " +
				AIEngine.GetName(AIVehicle.GetEngineType(replacement)) + "; retained carriages. New train=" + replacement);
			return replacement;
		}
		return -1;
	}

	function UsableEngineHere(engine, depot)
	{
		return AIEngine.IsBuildable(engine) && AIEngine.CanRunOnRail(engine, AIRail.GetRailType(depot)) &&
			AIEngine.HasPowerOnRail(engine, AIRail.GetRailType(depot));
	}

	// Size a new consist from monthly demand: one wagon per wagon-load of
	// demand, clamped to the standard two-wagon minimum and the caller's
	// platform ceiling. BuildCargoTrain trims any final overflow by length.
	function SizedWagons(demand, max_wagons)
	{
		local wagon = this.BestWagon();
		if (wagon < 0 || demand <= 0) return max_wagons >= 3 ? 3 : 2;
		local cap = AIEngine.GetCapacity(wagon);
		if (cap <= 0) return max_wagons >= 3 ? 3 : 2;
		local wagons = (demand + cap - 1) / cap;
		if (wagons < 2) wagons = 2;
		if (wagons > max_wagons) wagons = max_wagons;
		return wagons;
	}

	function BestWagon(cargo_type = null)
	{
		if (cargo_type == null) cargo_type = this.cargo;
		local wagons = AIEngineList(AIVehicle.VT_RAIL);
		wagons.Valuate(AIEngine.IsWagon);
		wagons.KeepValue(1);
		wagons.Valuate(AIEngine.IsBuildable);
		wagons.KeepValue(1);
		wagons.Valuate(AIEngine.CanRunOnRail, AIRail.GetCurrentRailType());
		wagons.KeepValue(1);
		wagons.Valuate(AIEngine.GetCargoType);
		wagons.KeepValue(cargo_type);
		if (wagons.Count() == 0) return -1;
		wagons.Valuate(AIEngine.GetCapacity);
		wagons.Sort(AIList.SORT_BY_VALUE, false);
		return wagons.Begin();
	}

	function AddPassengerCarriage(train, depot, max_length)
	{
		return this.AddCargoCarriage(train,depot,max_length);
	}

	function AddCargoCarriage(train, depot, max_length)
	{
		if (!AIVehicle.IsStoppedInDepot(train) || AIVehicle.GetLocation(train) != depot) return false;
		if (AIVehicle.GetLength(train) >= max_length) return -1;
		local previous_type = AIRail.GetCurrentRailType();
		AIRail.SetCurrentRailType(AIRail.GetRailType(depot));
		local wagon_id = this.BestWagon();
		AIRail.SetCurrentRailType(previous_type);
		if (wagon_id < 0 || !EnsureMoney(AIEngine.GetPrice(wagon_id) + 10000)) return false;
		local wagon = AIVehicle.BuildVehicle(depot, wagon_id);
		if (!AIVehicle.IsValidVehicle(wagon)) return false;
		if (AIVehicle.GetLength(train) + AIVehicle.GetLength(wagon) > max_length) {
			AIVehicle.SellVehicle(wagon);
			AILog.Info("Optimiser: train " + train + " has no room for another carriage within its platforms.");
			return -1;
		}
		local before = AIVehicle.GetCapacity(train, this.cargo);
		if (!AIVehicle.MoveWagon(wagon, 0, train, AIVehicle.GetNumWagons(train) - 1)) {
			AIVehicle.SellVehicle(wagon);
			return false;
		}
		local after = AIVehicle.GetCapacity(train, this.cargo);
		if (after <= before) return false;
		AILog.Info("Optimiser: added one carriage to train " + train + ". Capacity=" + before + " -> " + after +
			", length=" + AIVehicle.GetLength(train) + ", platform=" + max_length);
		return true;
	}

	function ClonePassengerTrain(source, depot, max_length, depot_flags, wagon_count = 3)
	{
        local old_type=AIRail.GetCurrentRailType();
        AIRail.SetCurrentRailType(AIRail.GetRailType(depot));
        local train=this.BuildCargoTrain(depot,AIOrder.GetOrderDestination(source,0),
            AIOrder.GetOrderDestination(source,1),wagon_count,
            !(AICargo.HasCargoClass(this.cargo,AICargo.CC_PASSENGERS) || AICargo.HasCargoClass(this.cargo,AICargo.CC_MAIL)),false,max_length);
        AIRail.SetCurrentRailType(old_type);
        if(train>=0) AILog.Info("Optimiser: added a "+wagon_count+"-wagon train "+train+" to the same route as train "+source+".");
        return train;
    }

	function CheckOrders(train, depot)
	{
		if (AIOrder.GetOrderCount(train) != 3) return false;
		foreach (i in [2]) {
			if (!AIOrder.IsGotoDepotOrder(train, i) || AIOrder.GetOrderDestination(train, i) != depot) return false;
			if ((AIOrder.GetOrderFlags(train, i) & AIOrder.OF_STOP_IN_DEPOT) != 0) return false;
		}
		AILog.Info("Maintenance orders verified: station A, station B, depot.");
		return true;
	}

	function BuildPassengerTrain(depot, station_a, station_b, wagon_count)
	{
		return this.BuildCargoTrain(depot,station_a,station_b,wagon_count,false);
	}

	function BuildCargoTrain(depot, station_a, station_b, wagon_count, freight = true, start = true, length_limit = null)
	{
		local engine_id = this.BestEngine();
		local wagon_id = this.BestWagon();
		if (engine_id < 0 || wagon_id < 0) {
			AILog.Warning("No suitable engine or cargo wagon available yet.");
			return -1;
		}

		EnsureMoney(AIEngine.GetPrice(engine_id) + AIEngine.GetPrice(wagon_id) * wagon_count + 10000);

		local train = AIVehicle.BuildVehicle(depot, engine_id);
		if (!AIVehicle.IsValidVehicle(train)) {
			AILog.Warning("Failed to build engine: " + AIError.GetLastErrorString());
			return -1;
		}

		local attached = 0;
		local max_length = length_limit==null ? AIController.GetSetting("platform_length") * 16 : length_limit;
		for (local i = 0; i < wagon_count; i++) {
			local wagon = AIVehicle.BuildVehicle(depot, wagon_id);
			if (!AIVehicle.IsValidVehicle(wagon)) {
				AILog.Warning("Could not purchase carriage: " + AIError.GetLastErrorString());
				break;
			}
			if (AIVehicle.GetLength(train) + AIVehicle.GetLength(wagon) > max_length) {
				AIVehicle.SellVehicle(wagon);
				break;
			}
			local capacity_before = AIVehicle.GetCapacity(train, this.cargo);
			// MoveWagon inserts AFTER an existing vehicle, whose index is zero-based.
			if (!AIVehicle.MoveWagon(wagon, 0, train, AIVehicle.GetNumWagons(train) - 1)) {
				AILog.Warning("Could not attach carriage: " + AIError.GetLastErrorString());
				AIVehicle.SellVehicle(wagon);
				AIVehicle.SellVehicle(train);
				return -1;
			}
			if (AIVehicle.GetCapacity(train, this.cargo) <= capacity_before) {
				AILog.Warning("Carriage did not add cargo capacity; cancelling train.");
				AIVehicle.SellVehicle(train);
				return -1;
			}
			attached++;
		}

		local capacity = AIVehicle.GetCapacity(train, this.cargo);
		if (attached < (start ? 2 : wagon_count) || capacity <= 0 || AIVehicle.GetLength(train) > max_length) {
			AILog.Warning("Cannot assemble at least two cargo carriages within budget and platform length.");
			AIVehicle.SellVehicle(train);
			return -1;
		}
		if (!AIOrder.AppendOrder(train, station_a, AIOrder.OF_NON_STOP_INTERMEDIATE | (freight ? AIOrder.OF_FULL_LOAD : 0)) ||
			!AIOrder.AppendOrder(train, station_b, AIOrder.OF_NON_STOP_INTERMEDIATE | (freight ? AIOrder.OF_UNLOAD | AIOrder.OF_NO_LOAD : 0)) ||
			!AIOrder.AppendOrder(train, depot, AIOrder.OF_NON_STOP_INTERMEDIATE) ||
			!this.CheckOrders(train, depot) || (start && !AIVehicle.StartStopVehicle(train))) {
			AILog.Warning("Could not start train service: " + AIError.GetLastErrorString());
			AIVehicle.SellVehicle(train);
			return -1;
		}
		AILog.Info("Train " + train + " is rolling. Carriages=" + attached + ", cargo=" + AICargo.GetName(this.cargo) + ", capacity=" + capacity +
			", length=" + AIVehicle.GetLength(train) + ", platform=" + max_length);
		return train;
	}
}
