import os
import subprocess
import xml.etree.ElementTree as ET
import pandas as pd
from pathlib import Path
import urllib.request
import seeds
import random
random.seed(seeds.seed_random)

#########################################
# MANHATTAN GRID SIMULATION FUNCTIONS
#########################################

def fix_manhattan_simulation(num_vehicles=10, total_time=100, time_step=0.1,
                           grid_number=5, grid_length=300):
    """
    Create a Manhattan grid simulation with correct edge IDs to avoid routing errors

    Parameters:
    ----------
    num_vehicles : int
        Number of vehicles in the simulation (default: 10)
    total_time : int
        Total simulation time in seconds (default: 100)
    time_step : float
        Simulation time step in seconds (default: 0.1)
    grid_number : int
        Number of blocks in the Manhattan grid (default: 5)
    grid_length : int
        Length of each road segment in meters (default: 300)

    Returns:
    -------
    tuple
        (output_directory, dataframe) - Path to the output directory and vehicle movement DataFrame
    """
    # Create 'sumo' directory if it doesn't exist
    output_dir = Path("sumo_manhattan")
    output_dir.mkdir(exist_ok=True)

    # File paths
    net_file = output_dir / "manhattan.net.xml"
    routes_file = output_dir / "manhattan.rou.xml"
    config_file = output_dir / "manhattan.sumocfg"
    trace_file = output_dir / "trace.xml"

    # Generate Manhattan grid network
    netgenerate_cmd = [
        "netgenerate",
        "--grid",
        f"--grid.number={grid_number}",
        f"--grid.length={grid_length}",
        "--no-turnarounds=true",
        f"--output-file={net_file}"
    ]

    try:
        subprocess.run(netgenerate_cmd, check=True)
        print(f"Manhattan grid network generated with {grid_number}x{grid_number} blocks")
    except subprocess.CalledProcessError as e:
        print(f"Error generating network: {e}")
        return None, None

    # Extract actual edge IDs from the network file to prevent unknown edge errors
    edge_ids = []
    try:
        tree = ET.parse(net_file)
        root = tree.getroot()
        # Extract edge IDs from the network file
        for edge in root.findall('.//edge'):
            edge_id = edge.get('id')
            if edge_id and not edge_id.startswith(':'):  # Skip internal edges
                edge_ids.append(edge_id)

        if not edge_ids:
            print("No valid edges found in the network file.")
            return None, None

        print(f"Found {len(edge_ids)} valid edges in the network file.")
    except Exception as e:
        print(f"Error parsing network file: {e}")
        return None, None

    # Create routes file with valid edge IDs
    with open(routes_file, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<routes>\n')
        f.write('    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="13.89" length="5" minGap="2.5"/>\n')

        # Make sure we have at least 2 different edges for routes
        if len(edge_ids) >= 2:
            from_edge = edge_ids[0]
            to_edge = edge_ids[1]

            # First check if edges are connected by creating a trip file
            trip_file = output_dir / "trip.trip.xml"
            with open(trip_file, 'w') as trip_f:
                trip_f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                trip_f.write('<routes>\n')
                trip_f.write(f'    <trip id="trip0" depart="0" from="{from_edge}" to="{to_edge}"/>\n')
                trip_f.write('</routes>\n')

            # Use DUAROUTER to verify and create a valid route
            duarouter_cmd = [
                "duarouter",
                "--trip-files", str(trip_file),
                "--net-file", str(net_file),
                "--output-file", str(output_dir / "valid_route.rou.xml"),
                "--ignore-errors"
            ]

            try:
                subprocess.run(duarouter_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                print("Valid route created using DUAROUTER")

                # Parse the valid route file to get the correct edge sequence
                valid_route = []
                route_tree = ET.parse(output_dir / "valid_route.rou.xml")
                route_root = route_tree.getroot()
                for route in route_root.findall('.//route'):
                    edges = route.get('edges')
                    if edges:
                        valid_route = edges.split()
                        break

                if not valid_route:
                    print("No valid route found. Using alternative approach.")
                    # Find two connected edges (this is a simplification)
                    for i in range(min(10, len(edge_ids) - 1)):
                        valid_route = [edge_ids[i], edge_ids[i+1]]
                        break
            except:
                print("Error with DUAROUTER. Using alternative approach.")
                # Just use two edges without guaranteeing connectivity
                valid_route = [edge_ids[0], edge_ids[1]]

            # Write flow with valid route
            f.write(f'    <flow id="flow0" type="car" begin="0" end="{total_time}" number="{num_vehicles}" departLane="random" departSpeed="max">\n')
            f.write(f'        <route edges="{" ".join(valid_route)}"/>\n')
            f.write('    </flow>\n')
        else:
            print("Not enough edges for a valid route. Creating individual vehicles on single edges.")
            # Fallback: create vehicles on individual edges
            for i in range(min(num_vehicles, len(edge_ids))):
                f.write(f'    <vehicle id="v{i}" type="car" depart="{i * (total_time / num_vehicles)}" departLane="random" departSpeed="max">\n')
                f.write(f'        <route edges="{edge_ids[i % len(edge_ids)]}"/>\n')
                f.write('    </vehicle>\n')

        f.write('</routes>\n')

    # Create SUMO configuration file
    with open(config_file, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<configuration>\n')
        f.write('    <input>\n')
        f.write(f'        <net-file value="{net_file.name}"/>\n')
        f.write(f'        <route-files value="{routes_file.name}"/>\n')
        f.write('    </input>\n')
        f.write('    <time>\n')
        f.write('        <begin value="0"/>\n')
        f.write(f'        <end value="{total_time}"/>\n')
        f.write(f'        <step-length value="{time_step}"/>\n')
        f.write('    </time>\n')
        f.write('    <o>\n')
        f.write('        <fcd-output value="trace.xml"/>\n')
        f.write('    </o>\n')
        f.write('</configuration>\n')

    # Run SUMO simulation
    sumo_cmd = [
        "C:\\Program Files (x86)\\Eclipse\\Sumo\\bin\\sumo",
        "-c", str(config_file),
        f"--seed={seeds.seed_random}" # Aggiungi questa riga per impostare un seed fisso
    ]

    try:
        subprocess.run(sumo_cmd, check=True)
        print(f"Manhattan grid simulation completed successfully")

        # Extract dataframe from trace file if it exists
        if trace_file.exists():
            df = extract_trace_dataframe(trace_file)
            return str(output_dir), df
        else:
            print(f"Warning: Trace file not found at {trace_file}")
            return str(output_dir), None

    except subprocess.CalledProcessError as e:
        print(f"Error running simulation: {e}")
        return None, None

def run_manhattan_simulation_and_get_dataframe(num_vehicles=50, total_time=100, time_step=1.0,
                                             grid_number=5, grid_length=300):
    """
    Wrapper function to run a Manhattan simulation and return the trace DataFrame

    Parameters:
    ----------
    num_vehicles : int
        Number of vehicles in the simulation (default: 50)
    total_time : int
        Total simulation time in seconds (default: 100)
    time_step : float
        Simulation time step in seconds (default: 1.0)
    grid_number : int
        Number of blocks in the Manhattan grid (default: 5)
    grid_length : int
        Length of each road segment in meters (default: 300)

    Returns:
    -------
    pandas.DataFrame
        DataFrame containing vehicle ID, x position, y position, speed, and time step
    """
    output_path, df = fix_manhattan_simulation(
        num_vehicles=num_vehicles,
        total_time=total_time,
        time_step=time_step,
        grid_number=grid_number,
        grid_length=grid_length
    )

    if output_path and df is not None and not df.empty:
        print(f"Simulation results available at: {output_path}")
        print(f"DataFrame shape: {df.shape}")

        # Save DataFrame to CSV
        csv_path = Path(output_path) / "vehicle_data.csv"
        df.to_csv(csv_path, index=False)
        print(f"DataFrame saved to: {csv_path}")

        return df
    else:
        print("Failed to generate or extract simulation data")
        return pd.DataFrame()

#########################################
# REAL-WORLD CITY TRAFFIC FUNCTIONS
#########################################

def extract_city_traffic(city_name, country_code, bbox=None, simulation_time=3600, time_step=1.0, num_vehicles=100):
    """
    Extract traffic simulation from a real-world city using OpenStreetMap data

    Parameters:
    ----------
    city_name : str
        Name of the city (e.g., "Rome", "Paris", "Tokyo")
    country_code : str
        ISO country code (e.g., "it", "fr", "jp")
    bbox : tuple, optional
        Bounding box coordinates (min_lon, min_lat, max_lon, max_lat) to limit the area
        If None, will try to get a central area of the city
    simulation_time : int
        Total simulation time in seconds (default: 3600 = 1 hour)
    time_step : float
        Simulation time step in seconds (default: 1.0)
    num_vehicles : int
        Number of vehicles to simulate (default: 100)

    Returns:
    -------
    tuple
        (output_directory, dataframe) - Path to the output directory and vehicle movement DataFrame
    """
    # Create output directory named after the city
    output_dir = Path(f"sumo_{city_name.lower().replace(' ', '_')}")
    output_dir.mkdir(exist_ok=True)

    # File paths
    osm_file = output_dir / f"{city_name.lower().replace(' ', '_')}.osm"
    net_file = output_dir / f"{city_name.lower().replace(' ', '_')}.net.xml"
    poly_file = output_dir / f"{city_name.lower().replace(' ', '_')}.poly.xml"
    routes_file = output_dir / f"{city_name.lower().replace(' ', '_')}.rou.xml"
    trips_file = output_dir / f"{city_name.lower().replace(' ', '_')}.trips.xml"
    config_file = output_dir / f"{city_name.lower().replace(' ', '_')}.sumocfg"
    trace_file = output_dir / "trace.xml"

    # Step 1: Download OpenStreetMap data if not already available
    if not osm_file.exists():
        print(f"Downloading OpenStreetMap data for {city_name}, {country_code}...")

        # If bbox is not provided, use Nominatim to get city boundaries
        if bbox is None:
            try:
                from geopy.geocoders import Nominatim

                geolocator = Nominatim(user_agent="sumo_traffic_extractor")
                location = geolocator.geocode(f"{city_name}, {country_code}", exactly_one=True)

                if location:
                    # Create a small bounding box around the city center (approximately 2km x 2km)
                    # This is a simplification - for real use cases, you might want to determine
                    # better boundaries or let the user specify them
                    center_lat = location.latitude
                    center_lon = location.longitude

                    # Rough conversion: 0.01 degree ≈ 1km at equator (less at higher latitudes)
                    bbox = (
                        center_lon - 0.01,  # min_lon
                        center_lat - 0.01,  # min_lat
                        center_lon + 0.01,  # max_lon
                        center_lat + 0.01   # max_lat
                    )

                    print(f"Generated bounding box around {city_name} center: {bbox}")
                else:
                    raise ValueError(f"Could not geocode {city_name}, {country_code}")
            except Exception as e:
                print(f"Error geocoding city: {e}")
                print("Please provide a bounding box manually.")
                return None, None

        # Download OSM data using the bounding box
        osm_api_url = f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

        try:
            print(f"Downloading OSM data from: {osm_api_url}")
            urllib.request.urlretrieve(osm_api_url, osm_file)
            print(f"OSM data downloaded to {osm_file}")
        except Exception as e:
            print(f"Error downloading OSM data: {e}")

            # Alternative: Try using osmget tool (part of SUMO)
            try:
                osmget_cmd = [
                    "osmget",
                    f"--bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                    f"--output-file={osm_file}"
                ]
                subprocess.run(osmget_cmd, check=True)
                print(f"OSM data downloaded using osmget")
            except Exception as e2:
                print(f"Error using osmget: {e2}")
                return None, None

    # Step 2: Convert OSM data to SUMO network
    if not net_file.exists():
        print("Converting OSM data to SUMO network...")
        netconvert_cmd = [
            "netconvert",
            "--osm", str(osm_file),
            "--output-file", str(net_file),
            "--geometry.remove",  # Simplify geometry
            "--roundabouts.guess",  # Guess roundabouts
            "--ramps.guess",  # Guess ramps
            "--junctions.join",  # Join junctions
            "--tls.guess-signals",  # Guess traffic lights
            "--tls.discard-simple",  # Remove traffic lights at simple intersections
            "--edges.join",  # Join edges
            "--remove-edges.isolated"  # Remove isolated edges
        ]

        try:
            subprocess.run(netconvert_cmd, check=True)
            print(f"SUMO network created at {net_file}")
        except subprocess.CalledProcessError as e:
            print(f"Error creating SUMO network: {e}")
            return None, None

    # Step 3: Generate polygons for buildings and other city features (optional)
    if not poly_file.exists():
        print("Generating city polygons...")
        polyconvert_cmd = [
            "polyconvert",
            "--osm", str(osm_file),
            "--net", str(net_file),
            "--output-file", str(poly_file),
            "--osm.keep-full-type"
        ]

        try:
            subprocess.run(polyconvert_cmd, check=True)
            print(f"City polygons created at {poly_file}")
        except subprocess.CalledProcessError as e:
            print(f"Error creating polygons (non-critical): {e}")
            # Continue even if polygon creation fails

    # Step 4: Generate random trips
    print(f"Generating random trips with {num_vehicles} vehicles...")

    # First check if there are enough edges in the network
    try:
        tree = ET.parse(net_file)
        root = tree.getroot()

        # Count normal edges (not internal)
        edge_count = 0
        edge_ids = []
        for edge in root.findall('.//edge'):
            edge_id = edge.get('id')
            if edge_id and not edge_id.startswith(':'):
                edge_count += 1
                edge_ids.append(edge_id)

        print(f"Found {edge_count} edges in the network")

        if edge_count < 2:
            print("Not enough edges in the network for vehicle routing")
            return None, None

    except Exception as e:
        print(f"Error analyzing network: {e}")
        return None, None

    # Generate random trips using SUMO's randomTrips.py
    try:
        # Path to randomTrips.py (this might need to be adjusted based on SUMO installation)
        random_trips_script = Path(os.environ.get("SUMO_HOME", "/usr/share/sumo")) / "tools" / "randomTrips.py"

        if not random_trips_script.exists():
            print(f"Could not find randomTrips.py at {random_trips_script}")
            print("Please set SUMO_HOME environment variable or provide the correct path")

            # Fallback: try to find it in common locations
            possible_paths = [
                Path("/usr/share/sumo/tools/randomTrips.py"),
                Path("/usr/local/share/sumo/tools/randomTrips.py"),
                Path("/opt/sumo/tools/randomTrips.py"),
                Path("C:/Program Files (x86)/Eclipse/Sumo/tools/randomTrips.py"),
                Path("C:/Program Files/Eclipse/Sumo/tools/randomTrips.py")
            ]

            for path in possible_paths:
                if path.exists():
                    random_trips_script = path
                    break

            if not random_trips_script.exists():
                print("Could not find randomTrips.py. Creating simple trips manually.")

                # Create simple trips manually
                with open(trips_file, 'w') as f:
                    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                    f.write('<routes>\n')

                    for i in range(num_vehicles):
                        from_edge = edge_ids[i % len(edge_ids)]
                        to_edge = edge_ids[(i + 1) % len(edge_ids)]
                        depart_time = i * (simulation_time / num_vehicles)

                        f.write(f'    <trip id="v{i}" depart="{depart_time}" from="{from_edge}" to="{to_edge}"/>\n')

                    f.write('</routes>\n')

                routes_file = trips_file  # Use trips file as routes file
            else:
                print(f"Found randomTrips.py at {random_trips_script}")

        if random_trips_script.exists():
            random_trips_cmd = [
                "python", str(random_trips_script),
                "-n", str(net_file),
                "-o", str(trips_file),
                "-r", str(routes_file),
                "-e", str(simulation_time),
                "-p", str(simulation_time / num_vehicles),  # Period between departures
                "--random",  # usa comunque random, ma…
                "--seed", str(seeds.seed_random),
                "--trip-attributes=departLane=\"random\" departSpeed=\"max\""
            ]

            subprocess.run(random_trips_cmd, check=True)
            print(f"Random trips generated at {trips_file} and routes at {routes_file}")
    except Exception as e:
        print(f"Error generating trips: {e}")
        return None, None

    # Step 5: Create SUMO configuration file
    print("Creating SUMO configuration file...")
    with open(config_file, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<configuration>\n')
        f.write('    <input>\n')
        f.write(f'        <net-file value="{net_file.name}"/>\n')
        f.write(f'        <route-files value="{routes_file.name}"/>\n')
        if poly_file.exists():
            f.write(f'        <additional-files value="{poly_file.name}"/>\n')
        f.write('    </input>\n')
        f.write('    <time>\n')
        f.write('        <begin value="0"/>\n')
        f.write(f'        <end value="{simulation_time}"/>\n')
        f.write(f'        <step-length value="{time_step}"/>\n')
        f.write('    </time>\n')
        f.write('    <o>\n')
        f.write('        <fcd-output value="trace.xml"/>\n')
        f.write('    </o>\n')
        f.write('</configuration>\n')

    # Step 6: Run the simulation
    print("Running SUMO simulation...")
    sumo_cmd = [
            "sumo",
            "-c", str(config_file),
            f"--seed={seeds.seed_random}"
    ]

    try:
        subprocess.run(sumo_cmd, check=True)
        print("Simulation completed successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error running simulation: {e}")
        return None, None

    # Step 7: Extract DataFrame from trace file
    print("Extracting vehicle data to DataFrame...")
    if not trace_file.exists():
        print(f"Trace file not found: {trace_file}")
        return str(output_dir), None

    df = extract_trace_dataframe(trace_file)

    # Save DataFrame to CSV
    if not df.empty:
        csv_path = output_dir / "vehicle_data.csv"
        df.to_csv(csv_path, index=False)
        print(f"Vehicle data saved to {csv_path}")

    return str(output_dir), df

#########################################
# SHARED UTILITY FUNCTIONS
#########################################

def extract_trace_dataframe(trace_file_path):
    """
    Extract vehicle data from a SUMO trace file into a pandas DataFrame

    Parameters:
    ----------
    trace_file_path : str or Path
        Path to the SUMO trace file (FCD output format)

    Returns:
    -------
    pandas.DataFrame
        DataFrame containing vehicle ID, x position, y position, speed, and time step
    """
    # Convert to Path object if string
    trace_path = Path(trace_file_path)

    # Check if file exists
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    # Prepare lists to store data
    data = []

    try:
        # Parse XML file
        tree = ET.parse(trace_path)
        root = tree.getroot()

        # Iterate through timesteps
        for timestep in root.findall('.//timestep'):
            time = float(timestep.get('time'))

            # Iterate through vehicles at this timestep
            for vehicle in timestep.findall('.//vehicle'):
                vehicle_id = vehicle.get('id')

                # Modifica per estrarre solo il numero dalla stringa "flow0.X"
                if "flow" in vehicle_id:
                    vehicle_id = vehicle_id.split(".")[-1]  # Estrae solo il numero dopo il punto

                x = float(vehicle.get('x'))
                y = float(vehicle.get('y'))
                speed = float(vehicle.get('speed'))

                # Add row to data
                data.append({
                    'id': vehicle_id,
                    'position_x': x,
                    'position_y': y,
                    'speed': speed,
                    'time': time
                })

        # Create DataFrame from collected data
        df = pd.DataFrame(data)

        # Optimize DataFrame memory usage
        for col in df.columns:
            if df[col].dtype == 'float64':
                df[col] = pd.to_numeric(df[col], downcast='float')

        print(f"Successfully extracted data for {df['id'].nunique()} vehicles across {df['time'].nunique()} time steps")
        return df

    except Exception as e:
        print(f"Error extracting data from trace file: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error

#########################################
# MAIN EXECUTION EXAMPLES
#########################################

if __name__ == "__main__":
    # Example 1: Manhattan Grid Simulation
    print("\n=== Running Manhattan Grid Simulation ===\n")
    manhattan_df = run_manhattan_simulation_and_get_dataframe(
        num_vehicles=50,
        total_time=100,
        time_step=1.0,
        grid_number=5,
        grid_length=200
    )

    if not manhattan_df.empty:
        print("\nManhattan Grid Simulation Complete")
        print(f"Total vehicles: {manhattan_df['id'].nunique()}")
        print(f"Time steps: {manhattan_df['time'].nunique()}")
        print("\nFirst 5 rows:")
        print(manhattan_df.head())

    # Example 2: Real City Traffic - Rome
    print("\n=== Running Rome City Traffic Simulation ===\n")
    # Small area in central Rome
    rome_bbox = (12.4800, 41.8950, 12.4950, 41.9050)

    rome_output_path, rome_df = extract_city_traffic(
        city_name="Rome",
        country_code="it",
        bbox=rome_bbox,
        simulation_time=60,  # 5 minutes for faster execution
        time_step=0.1,
        num_vehicles=10
    )

    if rome_output_path and rome_df is not None and not rome_df.empty:
        print("\nRome Traffic Simulation Complete")
        print(f"Total vehicles: {rome_df['id'].nunique()}")
        print(f"Time steps: {rome_df['time'].nunique()}")
        print("\nFirst 5 rows:")
        print(rome_df.head())
