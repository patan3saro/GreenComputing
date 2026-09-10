"""
Mobility Manager — SUMO-based real-world vehicular traffic generation.

Paper-compliant defaults:
  - City: Rome (downtown bbox from Tab. I)
  - Average speed: ~13.1 km/h (matches `limitedtimes23`)
  - Vehicles count range: 10 to 200 (Tab. I), with headroom up to ~500
    for sensitivity analysis on a single macro-cell.

Design notes:
  - The mobility cache is keyed by (city, bbox, num_vehicles, seed); each
    combination lives in its own folder.
  - Vehicles are generated for `sim_time + INSERTION_BUFFER` so that the
    requested `num_vehicles` are concurrent during the simulated window.
  - OSM download has retry and a 30 s timeout; the SUMO binary and SUMO_HOME
    are searched in the Linux, macOS and Windows default locations.
  - Trajectories with zero variance over time (stuck vehicles) are dropped.

Function entry point used by `main.py`:
    extract_city_traffic(random_seed, city_name, country_code, bbox,
                          simulation_time, time_step, num_vehicles,
                          force_regenerate=False)
"""

import os
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd


# ----------------------------------------------------------------------
#                       Constants
# ----------------------------------------------------------------------

# Paper Tab. I: Rome downtown bbox
# Paper Tab. I: Rome downtown bbox. The original area (12.4779-12.4971,
# 41.8928-41.9072, ~1.6km x 1.6km) triggers a known assertion in SUMO 1.18
# (NBNodesEdgesSorter at NBAlgorithms.h:193) on complex geometries near the
# historical center. We use a slightly reduced bbox that preserves the
# Rome-center semantics while avoiding the degenerate geometry. Override
# with `bbox=...` in `extract_city_traffic(...)` if a newer SUMO is used.
DEFAULT_ROME_BBOX = (12.4750, 41.8950, 12.4830, 41.9020)

# SUMO needs time to insert all vehicles before they all become concurrent.
# Without this buffer, with sim_time < 5 s and N=200, only a fraction of
# vehicles actually appear in the simulated window.
INSERTION_BUFFER_S = 120.0   # 2 minutes of warm-up

# Cap on max requested vehicles, beyond which a single macro-cell scenario
# becomes physically implausible (paper assumes single gNB, downtown Rome).
MAX_SUPPORTED_VEHICLES = 500

# OSM download
OSM_DOWNLOAD_TIMEOUT_S = 30
OSM_DOWNLOAD_RETRIES = 3


# ----------------------------------------------------------------------
#                       SUMO binary resolution
# ----------------------------------------------------------------------
def _find_sumo_binary():
    """
    Locate SUMO executable across platforms.
    Priority:
      1. `SUMO_HOME` env var
      2. PATH
      3. Common install paths (Homebrew, apt, Windows Eclipse)
    """
    candidates = []

    if "SUMO_HOME" in os.environ:
        candidates.append(Path(os.environ["SUMO_HOME"]) / "bin" / "sumo")

    candidates.extend([
        Path("/opt/homebrew/bin/sumo"),
        Path("/usr/local/bin/sumo"),
        Path("/usr/bin/sumo"),
        Path("/opt/sumo/bin/sumo"),
        Path("C:/Program Files (x86)/Eclipse/Sumo/bin/sumo.exe"),
        Path("C:/Program Files/Eclipse/Sumo/bin/sumo.exe"),
    ])

    for c in candidates:
        if c.exists():
            return str(c)

    # last resort: rely on PATH
    if shutil.which("sumo"):
        return "sumo"

    raise RuntimeError(
        "Could not locate the SUMO binary. Set the SUMO_HOME environment "
        "variable, install SUMO, or add it to PATH."
    )


def _find_random_trips_script():
    """Locate randomTrips.py from SUMO tools."""
    candidates = []
    if "SUMO_HOME" in os.environ:
        candidates.append(Path(os.environ["SUMO_HOME"]) / "tools" / "randomTrips.py")
    candidates.extend([
        Path("/opt/homebrew/share/sumo/tools/randomTrips.py"),
        Path("/usr/share/sumo/tools/randomTrips.py"),
        Path("/usr/local/share/sumo/tools/randomTrips.py"),
        Path("/opt/sumo/tools/randomTrips.py"),
        Path("C:/Program Files (x86)/Eclipse/Sumo/tools/randomTrips.py"),
        Path("C:/Program Files/Eclipse/Sumo/tools/randomTrips.py"),
    ])
    for c in candidates:
        if c.exists():
            return str(c)
    raise RuntimeError(
        "Could not locate randomTrips.py. Set SUMO_HOME or install SUMO tools."
    )


# ----------------------------------------------------------------------
#                       Cache directory
# ----------------------------------------------------------------------
def _cache_dir_for(city_name, bbox, num_vehicles, seed):
    """
    Cache directory keyed by all parameters that affect the trace.
    Each (city, bbox, N, seed) combination lives in its own folder.
    """
    bbox_tag = "{:.4f}_{:.4f}_{:.4f}_{:.4f}".format(*bbox)
    return Path(
        f"sumo_{city_name.lower().replace(' ', '_')}"
        f"_bb{bbox_tag}"
        f"_v{num_vehicles}"
        f"_s{seed}"
    )


# ----------------------------------------------------------------------
#                       OSM download with retry
# ----------------------------------------------------------------------
def _download_osm(bbox, osm_file):
    url = (
        f"https://overpass-api.de/api/map?"
        f"bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    )
    last_err = None
    for attempt in range(1, OSM_DOWNLOAD_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vcc-sim/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(osm_file, "wb") as f:
                f.write(resp.read())
            return True
        except Exception as e:
            last_err = e
            print(f"[OSM] attempt {attempt}/{OSM_DOWNLOAD_RETRIES} failed: {e}")
    print(f"[OSM] download failed after {OSM_DOWNLOAD_RETRIES} attempts: {last_err}")
    return False


# ----------------------------------------------------------------------
#                       Vehicle ID parsing
# ----------------------------------------------------------------------
_VEHICLE_ID_RX = re.compile(r"(\d+)\s*$")


def _parse_vehicle_id(raw_id):
    """
    Extract a stable integer id from a SUMO vehicle id like
    'flow0.5', 'trip_v12', 'veh_123', etc. Falls back to a hash if no
    trailing digits are found.
    """
    if raw_id is None:
        return -1
    m = _VEHICLE_ID_RX.search(str(raw_id))
    if m:
        return int(m.group(1))
    return abs(hash(raw_id)) % (10 ** 9)


# ----------------------------------------------------------------------
#                       Stuck-vehicle filter
# ----------------------------------------------------------------------
def _drop_stuck_vehicles(df, min_displacement_m=1.0):
    """
    Remove vehicles whose total displacement across the trace is below
    `min_displacement_m`. These are typically stuck/deadlocked or never
    inserted in the network.
    """
    if df.empty:
        return df
    ranges = df.groupby('id').agg(
        x_span=('position_x', lambda s: s.max() - s.min()),
        y_span=('position_y', lambda s: s.max() - s.min()),
    )
    keep_ids = ranges[(ranges['x_span'] + ranges['y_span']) >= min_displacement_m].index
    return df[df['id'].isin(keep_ids)].reset_index(drop=True)


# ----------------------------------------------------------------------
#                       FCD trace -> DataFrame
# ----------------------------------------------------------------------
def extract_trace_dataframe(trace_file_path):
    """
    Parse a SUMO FCD-output XML and return a DataFrame with columns:
        id, position_x, position_y, speed, time
    Time is in SECONDS.
    """
    trace_path = Path(trace_file_path)
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    data = []
    try:
        tree = ET.parse(trace_path)
        root = tree.getroot()
        for timestep in root.findall('.//timestep'):
            t = float(timestep.get('time'))
            for vehicle in timestep.findall('.//vehicle'):
                vid = _parse_vehicle_id(vehicle.get('id'))
                data.append({
                    'id': vid,
                    'position_x': float(vehicle.get('x')),
                    'position_y': float(vehicle.get('y')),
                    'speed': float(vehicle.get('speed')),
                    'time': t,
                })
    except Exception as e:
        print(f"[trace] error parsing {trace_path}: {e}")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    if df.empty:
        return df

    # Memory optimization
    for col in df.select_dtypes(include='float64').columns:
        df[col] = pd.to_numeric(df[col], downcast='float')

    df = _drop_stuck_vehicles(df)

    return df


# ----------------------------------------------------------------------
#                       Main entry point
# ----------------------------------------------------------------------
def extract_city_traffic(
    random_seed,
    city_name,
    country_code,
    bbox=None,
    simulation_time=3600,
    time_step=0.1,
    num_vehicles=100,
    force_regenerate=False,
):
    """
    Generate (or load from cache) SUMO mobility traces for a city.

    Parameters
    ----------
    random_seed : int
        Seed forwarded to netgenerate, duarouter, randomTrips, sumo, so the
        whole pipeline is reproducible.
    city_name : str
        e.g. "Rome".
    country_code : str
        e.g. "it" (currently unused but kept for API compatibility).
    bbox : tuple or None
        (min_lon, min_lat, max_lon, max_lat). If None, defaults to Rome
        downtown (Tab. I).
    simulation_time : float
        Total SUMO simulation time in SECONDS that the controller wants to
        consume. Internally, SUMO is run for `simulation_time + INSERTION_BUFFER`
        to ensure all `num_vehicles` are concurrent during the window of
        interest.
    time_step : float
        SUMO step length in seconds (default 0.1 s = 10 Hz, matches the ETSI
        CAM beacon rate).
    num_vehicles : int
        Target number of distinct vehicles in the trace. Capped at
        MAX_SUPPORTED_VEHICLES = 500 for a single-macro-cell scenario.
    force_regenerate : bool
        If True, ignore any cached files and rebuild from scratch.

    Returns
    -------
    (output_dir, df) : (str, pd.DataFrame or None)
        Cache directory where intermediate files live, and the mobility
        DataFrame. df has columns: id, position_x, position_y, speed, time.
    """
    if num_vehicles > MAX_SUPPORTED_VEHICLES:
        print(
            f"[mobility] num_vehicles={num_vehicles} exceeds the macro-cell "
            f"upper bound ({MAX_SUPPORTED_VEHICLES}); capping."
        )
        num_vehicles = MAX_SUPPORTED_VEHICLES

    if bbox is None:
        bbox = DEFAULT_ROME_BBOX

    output_dir = _cache_dir_for(city_name, bbox, num_vehicles, random_seed)

    # Cached DataFrame -> return immediately
    csv_path = output_dir / "vehicle_data.csv"
    if csv_path.exists() and not force_regenerate:
        try:
            df = pd.read_csv(csv_path)
            print(f"[mobility] cache hit: {csv_path} ({df['id'].nunique()} vehicles)")
            return str(output_dir), df
        except Exception:
            pass   # fall through to regenerate

    # Wipe inconsistent partial state if forcing
    if force_regenerate and output_dir.exists():
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    osm_file = output_dir / "map.osm"
    net_file = output_dir / "map.net.xml"
    trips_file = output_dir / "trips.trips.xml"
    routes_file = output_dir / "routes.rou.xml"
    config_file = output_dir / "scene.sumocfg"
    trace_file = output_dir / "trace.xml"

    # -------------------- OSM download --------------------
    # The OSM map for a given bbox is identical across all (num_vehicles,
    # seed) combinations. Cache it ONCE in a shared directory keyed only by
    # the bbox; then symlink (or copy) into the per-run directory. This
    # avoids hammering Overpass with O(N_vehicles * N_seeds) identical
    # downloads, which triggers rate-limiting (HTTP 429) and IP bans.
    if not osm_file.exists():
        bbox_tag = "{:.4f}_{:.4f}_{:.4f}_{:.4f}".format(*bbox)
        shared_dir = Path(f"_osm_cache/{bbox_tag}")
        shared_dir.mkdir(parents=True, exist_ok=True)
        shared_osm = shared_dir / "map.osm"

        if not shared_osm.exists():
            ok = _download_osm(bbox, shared_osm)
            if not ok:
                return str(output_dir), None

        # Link or copy into the per-run dir so downstream tools find it.
        # Hardened contro la race parallela "<a> and <b> are the same file":
        # se un altro worker ha gia' creato osm_file, non riproviamo a copiarlo
        # su se stesso (era la causa dei run falliti sotto --workers alti).
        try:
            os.symlink(shared_osm.resolve(), osm_file)
        except FileExistsError:
            pass
        except (OSError, NotImplementedError):
            try:
                if not osm_file.exists():
                    shutil.copy2(shared_osm, osm_file)
            except shutil.SameFileError:
                pass

    # -------------------- netconvert ----------------------
    if not net_file.exists():
        netconvert_cmd = [
            "netconvert",
            "--osm", str(osm_file),
            "--output-file", str(net_file),
            # SUMO 1.18 stability flags: avoid the NBNodesEdgesSorter
            # assertion that fires on degenerate junction geometries.
            "--keep-edges.by-vclass", "passenger",
            "--remove-edges.by-vclass", "rail,tram",
            "--remove-edges.isolated",
            "--no-internal-links",
            "--tls.discard-simple",
            # Bbox grandi possono contenere giunzioni la cui geometria fa
            # fallire il calcolo dei turnaround (assertion getConvAngle in
            # NBNodesEdgesSorter, SIGABRT). Questi flag evitano quel percorso:
            "--no-turnarounds",
            "--junctions.join",
            "--geometry.remove",
            f"--seed={random_seed}",
        ]
        try:
            subprocess.run(netconvert_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[netconvert] failed: {e}")
            return str(output_dir), None

    # Pre-check: enough edges for routing?
    try:
        tree = ET.parse(net_file)
        edge_count = sum(
            1 for edge in tree.getroot().findall('.//edge')
            if (edge.get('id') or "").startswith(":") is False and edge.get('id')
        )
        if edge_count < 2:
            print(f"[network] only {edge_count} edges; cannot route.")
            return str(output_dir), None
    except Exception as e:
        print(f"[network] parsing failed: {e}")
        return str(output_dir), None

    # -------------------- randomTrips ---------------------
    # Per avere num_vehicles CONCORRENTI servono due cose: (1) un backlog di
    # trip sempre pronto all'inserimento, (2) un cap sui concorrenti via
    # --max-num-vehicles (nel comando sumo). Qui SOVRA-produciamo i trip
    # (OVERSUPPLY x) con periodo piccolo: SUMO ne tiene num_vehicles in rete e
    # ritarda gli altri. Senza sovra-produzione (period = total/num) se ne
    # inseriscono solo num_vehicles in tutto -> a regime ne resta una frazione.
    total_sumo_time = max(simulation_time, 1.0) + INSERTION_BUFFER_S
    OVERSUPPLY = 8
    if num_vehicles > 0:
        period = total_sumo_time / (num_vehicles * OVERSUPPLY)
        period = max(period, 0.05)        # non scendere sotto mezzo step
    else:
        period = 1.0

    random_trips_script = _find_random_trips_script()
    random_trips_cmd = [
        "python", random_trips_script,
        "-n", str(net_file),
        "-o", str(trips_file),
        "-r", str(routes_file),
        "-e", str(total_sumo_time),
        "-p", f"{period:.6f}",
        "--seed", str(random_seed),
        # Riempimento RAPIDO: niente fringe-factor alto (forzava l'ingresso solo
        # dai bordi -> i veicoli entravano in fila e la rete si riempiva in
        # ~2 min). Con fringe-factor 1 e posizioni di partenza/arrivo casuali i
        # veicoli compaiono distribuiti nella rete e il pool sale a regime in
        # pochi secondi.
        "--fringe-factor", "1",
        "--random-departpos",
        "--random-arrivalpos",
        "--trip-attributes", 'departLane="random" departSpeed="max"',
    ]
    try:
        subprocess.run(random_trips_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[randomTrips] failed: {e}")
        return str(output_dir), None

    # -------------------- SUMO config ---------------------
    with open(config_file, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<configuration>\n')
        f.write('    <input>\n')
        f.write(f'        <net-file value="{net_file.name}"/>\n')
        f.write(f'        <route-files value="{routes_file.name}"/>\n')
        f.write('    </input>\n')
        f.write('    <time>\n')
        f.write('        <begin value="0"/>\n')
        f.write(f'        <end value="{total_sumo_time}"/>\n')
        f.write(f'        <step-length value="{time_step}"/>\n')
        f.write('    </time>\n')
        f.write('    <output>\n')
        f.write(f'        <fcd-output value="{trace_file.name}"/>\n')
        f.write('    </output>\n')
        f.write('</configuration>\n')

    # -------------------- SUMO simulation -----------------
    sumo_bin = _find_sumo_binary()
    sumo_cmd = [sumo_bin, "-c", str(config_file), f"--seed={random_seed}"]
    if num_vehicles > 0:
        # Cappa i veicoli CONCORRENTI a num_vehicles: gli inserimenti in eccesso
        # vengono ritardati (non persi, grazie a max-depart-delay alto). Cosi'
        # la rete tiene ~num_vehicles veicoli per tutta la finestra a regime.
        # NB: oltre la capacita' fisica della rete subentra congestione/teleport,
        # quindi il numero forzabile e' limitato dalla strada del bbox.
        sumo_cmd += [
            "--max-num-vehicles", str(int(num_vehicles)),
            "--max-depart-delay", "3600",
        ]
    try:
        subprocess.run(sumo_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[sumo] simulation failed: {e}")
        return str(output_dir), None

    # -------------------- Trace -> DataFrame --------------
    if not trace_file.exists():
        print(f"[trace] file not generated at {trace_file}")
        return str(output_dir), None

    df = extract_trace_dataframe(trace_file)
    if df.empty:
        return str(output_dir), df

    # Persist to CSV cache
    df.to_csv(csv_path, index=False)
    print(
        f"[mobility] cached {csv_path}: "
        f"{df['id'].nunique()} vehicles across {df['time'].nunique()} steps"
    )

    return str(output_dir), df
