"""Run OpenTTDAI in OpenTTD using a temporary config; retain diagnostic logs."""
import pathlib, re, subprocess, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
exe = pathlib.Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
src = (pathlib.Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text()
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'max_no_competitors':'1', 'town_layout':'1', 'number_towns':'3', 'terrain_type':'1', 'land_generator':'1', 'quantity_sea_lakes':'0', 'starting_year':'1950'}.items():
    src = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, src, flags=re.M)
src = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nOpenTTDAI = \n', src)
with tempfile.TemporaryDirectory(prefix='openttdai-') as folder:
    cfg = pathlib.Path(folder) / 'openttd.cfg'
    cfg.write_text(src)
    for seed in [42, 7]:
        r = subprocess.run([str(exe), '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-c', str(cfg), '-x', '-g', '-G', str(seed), '-d', 'script=4'], capture_output=True, text=True, timeout=60)
        (root / 'tests' / ('seed-%s.log' % seed)).write_text(r.stderr)
        unique = list(dict.fromkeys(re.sub(r'^\[[^]]+\] ', '', line) for line in r.stderr.splitlines()))
        print('SEED', seed, 'EXIT', r.returncode, '\n' + '\n'.join(unique[:45]), flush=True)
        assert r.returncode == 0
        assert 'is rolling.' in r.stderr, 'No train built; see log'
        assert 'Your script made an error' not in r.stderr
        assert not any(label in r.stderr for label in ['AyStar-style planner:', 'Jump planner:', 'Hierarchical planner:', 'Paired planner:']), 'Experimental planner still active'
        assert 'train is lost' not in r.stderr

        consists = re.findall(r'Carriages=(\d+), cargo=[^,]+, capacity=(\d+), length=(\d+), platform=(\d+)', r.stderr)
        assert len(consists) == r.stderr.count('is rolling.'), 'Missing consist verification'
        for carriages, passengers, length, platform in consists:
            assert int(carriages) >= 2 and int(passengers) > 0
            assert int(length) <= int(platform)
        assert 'Could not attach carriage' not in r.stderr

        junctions = re.findall(r'Route index=(\d+), route length=(\d+)', r.stderr)
        assert junctions, 'No depot junction verified'
        for index, length in junctions:
            assert 0 < int(index) < int(length) - 1
        assert r.stderr.count('Maintenance orders verified:') == r.stderr.count('is rolling.')

        qualities = re.findall(r'Selected route: tiles=(\d+), bends=(\d+)', r.stderr)
        assert qualities, 'No route quality reported'
        for tiles, bends in qualities:
            assert int(tiles) >= 5 and 0 <= int(bends) <= int(tiles)

        distances = re.findall(r'Route distances: towns=(\d+), stations=(\d+)', r.stderr)
        assert distances, 'No route distances verified'
        for towns, stations in distances:
            assert int(towns) >= 1 and int(stations) >= 1

        # Extra trains reuse existing approaches; they do not commission a new line.
        additions = len(re.findall(r'Optimiser: added a \d+-wagon train \d+', r.stderr))
        initial_routes = r.stderr.count('is rolling.') - additions
        network_routes = len(re.findall(r'Freight network: two-track .* backbone commissioned;', r.stderr)) + len(re.findall(r'Freight network: shared-track .* branch commissioned\.', r.stderr))
        single_routes = initial_routes - network_routes
        assert r.stderr.count('Straight station approaches verified at both ends.') >= initial_routes
        assert r.stderr.count('Maintenance orders verified: station A, station B, depot.') == r.stderr.count('is rolling.')

        # Passenger routes are two-track from the start; coal routes remain
        # single-first until demand justifies the return line.
        assert r.stderr.count('Single main line commissioned without signals; two-platform stations retained.') + \
            r.stderr.count('Two platforms and two connected tracks verified; station crossovers provide depot access.') >= single_routes

        planning_ticks = re.findall(r'Planning completed in (\d+) AI ticks.', r.stderr)
        assert planning_ticks, 'Missing planning timing'
        # First-route regression budget for these small fixed-seed maps.
        assert int(planning_ticks[0]) < 10000, 'First route planning exceeded regression budget'

        assert r.stderr.count('Single-track station entrances verified without signals.') + \
            r.stderr.count('Station entrances verified: two crossovers and four platform path signals.') >= single_routes

        assert r.stderr.count('Overlapping X crossovers verified at both stations.') >= initial_routes

        one_way = re.findall(r'Left-hand one-way running signals verified: count=(\d+), spacing=(\d+)', r.stderr)
        upgrades = r.stderr.count('Single-track upgrade complete:')
        assert len(one_way) >= upgrades
        assert all(int(count) >= 4 and int(spacing) >= 4 for count, spacing in one_way)

        assert r.stderr.count('Immediate post-crossover departure signal verified on left-hand track.') >= 2 * upgrades

        assert r.stderr.count('Depot approaches verified: signals on both sides of the junction.') >= upgrades
