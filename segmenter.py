#!/usr/bin/env python3
import argparse
import json
import os
import sys
import logging
from datetime import datetime, timedelta, date, timezone
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
import calendar
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from collections import defaultdict
from tqdm import tqdm
import time

# --- Constants ---
DEFAULT_RADIUS_KM = 10.0
GEOCACHE_FILENAME = "geocache.json"
NOMINATIM_USER_AGENT = "google_timeline_segmenter/1.0"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def parse_datetime_utc(dt_str):
    """Parses various datetime strings and returns a timezone-aware datetime object in UTC."""
    if not dt_str:
        return None
    try:
        # dateutil.parser handles ISO 8601 with timezone offsets well
        dt = date_parser.isoparse(dt_str)
        # Convert to UTC
        return dt.astimezone(timezone.utc)
    except ValueError:
        logger.warning(f"Could not parse datetime string: {dt_str}")
        return None

def parse_lat_lng(lat_lng_str):
    """Parses 'lat°, lon°' string into (latitude, longitude) tuple."""
    if not isinstance(lat_lng_str, str):
        logger.debug(f"Invalid lat/lng format (not a string): {lat_lng_str}")
        return None
    try:
        parts = lat_lng_str.replace('°', '').split(',')
        if len(parts) == 2:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            # Basic validation for realistic coordinates
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
            else:
                logger.warning(f"Coordinates out of range: {lat_lng_str}")
                return None
        else:
             logger.warning(f"Could not parse lat/lng string: {lat_lng_str}")
             return None
    except (ValueError, AttributeError) as e:
        logger.warning(f"Error parsing lat/lng string '{lat_lng_str}': {e}")
        return None

def get_coordinates_from_segment(segment):
    """Extracts all unique coordinate pairs (lat, lon) from a semantic segment."""
    coords = set()

    # 1. timelinePath points
    if 'timelinePath' in segment and isinstance(segment['timelinePath'], list):
        for item in segment['timelinePath']:
            if isinstance(item, dict) and 'point' in item:
                point = parse_lat_lng(item.get('point'))
                if point:
                    coords.add(point)

    # 2. visit location
    if 'visit' in segment and isinstance(segment['visit'], dict):
        visit = segment['visit']
        # Check topCandidate first
        if 'topCandidate' in visit and isinstance(visit['topCandidate'], dict) and \
           'placeLocation' in visit['topCandidate'] and isinstance(visit['topCandidate']['placeLocation'], dict) and \
           'latLng' in visit['topCandidate']['placeLocation']:
            point = parse_lat_lng(visit['topCandidate']['placeLocation'].get('latLng'))
            if point:
                coords.add(point)
        # Fallback to simplified visit location (older formats?)
        elif 'placeLocation' in visit and isinstance(visit['placeLocation'], dict) and 'latLng' in visit['placeLocation']:
             point = parse_lat_lng(visit['placeLocation'].get('latLng'))
             if point:
                 coords.add(point)

    # 3. activity start/end locations
    if 'activity' in segment and isinstance(segment['activity'], dict):
        activity = segment['activity']
        if 'start' in activity and isinstance(activity['start'], dict) and 'latLng' in activity['start']:
            point = parse_lat_lng(activity['start'].get('latLng'))
            if point:
                coords.add(point)
        if 'end' in activity and isinstance(activity['end'], dict) and 'latLng' in activity['end']:
            point = parse_lat_lng(activity['end'].get('latLng'))
            if point:
                coords.add(point)

    # Add checks for other potential location fields if needed based on schema variations
    # e.g., segment.get('startLocation', {}).get('latLng')
    # e.g., segment.get('endLocation', {}).get('latLng')

    return list(coords)

def is_point_near_home(point_lat, point_lon, home_locations):
    """Checks if a point is within the radius of ANY home location."""
    for home_lat, home_lon, radius_km in home_locations:
        try:
            distance_km = geodesic((point_lat, point_lon), (home_lat, home_lon)).km
            if distance_km <= radius_km:
                return True
        except ValueError as e:
            logger.warning(f"Could not calculate distance for point ({point_lat}, {point_lon}) and home ({home_lat}, {home_lon}): {e}")
            continue # Skip this home location if distance calc fails
    return False

def load_geocache(filename=GEOCACHE_FILENAME):
    """Loads the geocoding cache from a JSON file."""
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.warning(f"Could not load geocache file '{filename}': {e}")
    return {}

def save_geocache(cache, filename=GEOCACHE_FILENAME):
    """Saves the geocoding cache to a JSON file."""
    try:
        with open(filename, 'w') as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        logger.error(f"Could not save geocache file '{filename}': {e}")

def geocode_location(spec, default_radius_km, geolocator, cache):
    """
    Parses a home location spec, geocodes if necessary (using cache),
    and returns (latitude, longitude, radius_km).
    """
    spec = spec.strip()
    radius_override = None
    location_part = spec

    if ':' in spec:
        parts = spec.rsplit(':', 1)
        try:
            radius_override = float(parts[1])
            location_part = parts[0].strip()
        except ValueError:
            logger.error(f"Invalid radius format in spec: '{spec}'. Using default/global radius.")
            # Proceed with location_part as the whole spec if radius parse fails

    radius = radius_override if radius_override is not None else default_radius_km

    # Try parsing as lat,lon first
    try:
        lat_lon_parts = location_part.split(',')
        if len(lat_lon_parts) == 2:
            lat = float(lat_lon_parts[0].strip())
            lon = float(lat_lon_parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                 logger.info(f"Parsed '{location_part}' as coordinates: ({lat}, {lon}) with radius {radius} km.")
                 return lat, lon, radius
            else:
                # Fall through to geocoding if coords are invalid range
                logger.warning(f"Coordinates '{location_part}' out of range, attempting geocode.")
                pass # Fall through
        # Else, fall through to geocoding
    except ValueError:
        # Not lat,lon format, assume city,country
        pass

    # Assume city,country format and geocode
    query = location_part # Use the potentially radius-stripped part
    # Normalize the query for cache key consistency (remove spaces, lower case)
    # This helps match keys derived from "Zurich,CH" and " ZURICH , ch "
    normalized_query_key = query.replace(' ', '').lower()
    
    # Use the normalized key for cache lookup
    if normalized_query_key in cache:
        # logger.info(f"Using cached location for '{query}': {cache[normalized_query_key]}") # Original log used query
        logger.info(f"Using cached location for '{query}' (key='{normalized_query_key}'): {cache[normalized_query_key]}") # Log includes key
        lat, lon = cache[normalized_query_key]
        return lat, lon, radius

    logger.info(f"Geocoding '{query}'...")
    try:
        # Add timeout and retry mechanism
        for attempt in range(3):
            try:
                location = geolocator.geocode(query, exactly_one=True, timeout=10)
                if location:
                    lat, lon = location.latitude, location.longitude
                    logger.info(f"Geocoded '{query}' to: ({lat}, {lon}) with radius {radius} km.")
                    cache[normalized_query_key] = (lat, lon) # Update cache
                    return lat, lon, radius
                else:
                    logger.error(f"Could not geocode '{query}'. Location not found.")
                    return None
            except GeocoderTimedOut:
                logger.warning(f"Geocoder timed out for '{query}'. Retrying ({attempt+1}/3)...")
                time.sleep(2) # Wait before retry
            except GeocoderServiceError as e:
                 logger.error(f"Geocoder service error for '{query}': {e}. Stopping attempts for this location.")
                 return None # Service error, don't retry

        logger.error(f"Geocoding failed for '{query}' after multiple retries.")
        return None

    except Exception as e:
        logger.error(f"An unexpected error occurred during geocoding for '{query}': {e}")
        return None


def parse_home_locations(homeloc_specs_str, default_radius_km, geolocator, cache):
    """Parses the semicolon-separated list of home location specs."""
    home_locations = []
    specs = [spec.strip() for spec in homeloc_specs_str.split(';') if spec.strip()]
    if not specs:
        logger.error("No home locations specified. Use --homeloc.")
        return None

    for spec in specs:
        location_data = geocode_location(spec, default_radius_km, geolocator, cache)
        if location_data:
            home_locations.append(location_data)
        else:
            # Error already logged in geocode_location
            # Decide if processing should stop if one location fails
            logger.warning(f"Failed to process home location spec: '{spec}'. Skipping it.")
            # return None # Uncomment this to make any geocoding failure fatal

    if not home_locations:
         logger.error("Could not resolve any valid home locations.")
         return None # No valid homes, cannot proceed

    return home_locations

def parse_date_args(args):
    """Determines the start and end date for processing based on CLI args."""
    start_date_arg = args.start
    end_date_arg = args.end
    date_filter_arg = args.date

    start_date = None
    end_date = None

    # Process --date first
    if date_filter_arg:
        try:
            if len(date_filter_arg) == 4:  # YYYY
                year = int(date_filter_arg)
                start_date = date(year, 1, 1)
                end_date = date(year, 12, 31)
            elif len(date_filter_arg) == 7 and date_filter_arg[4] == '-':  # YYYY-MM
                year, month = map(int, date_filter_arg.split('-'))
                start_date = date(year, month, 1)
                _, last_day = calendar.monthrange(year, month)
                end_date = date(year, month, last_day)
            elif len(date_filter_arg) == 10:  # YYYY-MM-DD
                dt = datetime.strptime(date_filter_arg, '%Y-%m-%d').date()
                start_date = dt
                end_date = dt
            else:
                raise ValueError("Invalid format for --date")
            logger.info(f"Date filter '{date_filter_arg}' interpreted as range: {start_date} to {end_date}")
        except ValueError as e:
            logger.error(f"Invalid --date format: {date_filter_arg}. Use YYYY, YYYY-MM, or YYYY-MM-DD. Error: {e}")
            return None, None

    # Apply --start and --end, overriding --date if provided
    if start_date_arg:
        try:
            start_date_override = datetime.strptime(start_date_arg, '%Y-%m-%d').date()
            if start_date and start_date_override != start_date:
                 logger.info(f"--start '{start_date_arg}' overrides date derived from --date.")
            start_date = start_date_override
        except ValueError:
            logger.error(f"Invalid --start date format: {start_date_arg}. Use YYYY-MM-DD.")
            return None, None

    if end_date_arg:
        try:
            end_date_override = datetime.strptime(end_date_arg, '%Y-%m-%d').date()
            if end_date and end_date_override != end_date:
                logger.info(f"--end '{end_date_arg}' overrides date derived from --date.")
            end_date = end_date_override
        except ValueError:
            logger.error(f"Invalid --end date format: {end_date_arg}. Use YYYY-MM-DD.")
            return None, None

    # Validate final date range
    if start_date and end_date and start_date > end_date:
        logger.error(f"Start date ({start_date}) cannot be after end date ({end_date}).")
        return None, None

    logger.info(f"Final processing date range: Start={start_date or 'Earliest'}, End={end_date or 'Latest'}")
    return start_date, end_date

# --- Main Processing Logic ---

def process_timeline(args):
    """Main function to process the timeline data."""
    # 1. Load Geocache
    geocache = load_geocache()
    initial_cache_size = len(geocache)

    # 2. Initialize Geocoder
    try:
        geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)
    except Exception as e:
        logger.error(f"Failed to initialize Nominatim geocoder: {e}")
        return False

    # 3. Parse Home Locations
    home_locations = parse_home_locations(args.homeloc, args.radius, geolocator, geocache)
    if home_locations is None:
        return False # Error already logged

    # 4. Save updated Geocache if changed
    if len(geocache) > initial_cache_size:
        save_geocache(geocache)

    # 5. Parse Date Range
    start_date, end_date = parse_date_args(args)
    # Allow processing even if start/end dates are None (process whole file)

    # 6. Create Output Directory
    output_dir = args.outputdir
    try:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Output directory: {output_dir}")
    except OSError as e:
        logger.error(f"Could not create output directory '{output_dir}': {e}")
        return False

    # 7. Load Input Timeline JSON
    input_file = args.input
    logger.info(f"Loading timeline data from: {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            # Load the entire structure once. Iterating through a huge JSON
            # without loading it all is complex. Assume file fits in memory.
            timeline_data = json.load(f)
            if "semanticSegments" not in timeline_data or not isinstance(timeline_data["semanticSegments"], list):
                 logger.error("Invalid Timeline JSON structure: Missing or invalid 'semanticSegments' list.")
                 return False
            all_segments = timeline_data["semanticSegments"]
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file}")
        return False
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from '{input_file}': {e}")
        return False
    except IOError as e:
        logger.error(f"Could not read input file '{input_file}': {e}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred loading the timeline file: {e}")
        return False

    logger.info(f"Loaded {len(all_segments)} total semantic segments.")

    # 8. Group Segments by Day (UTC) and Filter by Date Range
    daily_segments = defaultdict(list)
    min_date_found, max_date_found = None, None

    logger.info("Grouping segments by day (UTC)...")
    for segment in tqdm(all_segments, desc="Processing segments"):
        start_time_str = segment.get("startTime")
        if not start_time_str:
            # logger.warning("Segment missing startTime, skipping.") # Too verbose
            continue

        start_dt_utc = parse_datetime_utc(start_time_str)
        if not start_dt_utc:
            # logger.warning(f"Could not parse startTime '{start_time_str}', skipping segment.") # Too verbose
            continue

        segment_date = start_dt_utc.date()

        # Update overall date range found in file
        if min_date_found is None or segment_date < min_date_found:
            min_date_found = segment_date
        if max_date_found is None or segment_date > max_date_found:
            max_date_found = segment_date

        # Apply date filtering
        if start_date and segment_date < start_date:
            continue
        if end_date and segment_date > end_date:
            continue

        daily_segments[segment_date].append(segment)

    if not daily_segments:
        logger.warning("No segments found within the specified date range.")
        return True # Not an error, just no data to process

    # Use the actual range of data found if file limits are wider than specified range
    effective_start_date = start_date if start_date else min_date_found
    effective_end_date = end_date if end_date else max_date_found
    logger.info(f"Processing data between {effective_start_date} and {effective_end_date}")

    # 9. Classify Each Day (Home/Away)
    day_status = {}
    sorted_dates = sorted(daily_segments.keys())

    logger.info("Classifying days (Home/Away)...")
    for day in tqdm(sorted_dates, desc="Classifying days"):
        segments_for_day = daily_segments[day]
        all_coords_for_day = []
        for segment in segments_for_day:
            all_coords_for_day.extend(get_coordinates_from_segment(segment))

        if not all_coords_for_day:
            day_status[day] = "no_data"
            # logger.debug(f"Day {day}: No coordinate data found.")
            continue

        is_home_day = True
        for lat, lon in all_coords_for_day:
            if not is_point_near_home(lat, lon, home_locations):
                is_home_day = False
                break # Found a point outside all home radii, it's an away day

        day_status[day] = "home" if is_home_day else "away"
        # logger.debug(f"Day {day}: Classified as {day_status[day]}")


    # 10. Identify Contiguous "Away" Segments
    trips = []
    current_trip_start = None
    last_processed_date = None # Keep track for end-of-range segment closing

    logger.info("Identifying 'Away' segments (trips)...")
    all_relevant_dates = sorted(day_status.keys()) # Dates within range and with data

    for current_date in all_relevant_dates:
        status = day_status[current_date]

        if status == "away":
            if current_trip_start is None:
                current_trip_start = current_date # Start of a new trip
        elif status == "home" or status == "no_data": # Treat no_data as breaking continuity
            if current_trip_start is not None:
                # End of the current trip (ended on the previous day)
                trips.append((current_trip_start, last_processed_date))
                current_trip_start = None

        last_processed_date = current_date

    # Check if a trip was ongoing at the end of the processed range
    if current_trip_start is not None:
        trips.append((current_trip_start, last_processed_date))

    logger.info(f"Identified {len(trips)} potential trips.")

    # 11. Generate Output JSON Files for Each Trip
    segments_written = 0
    if not trips:
        logger.info("No 'Away' segments found to write.")
        return True

    logger.info("Writing trip segments to output files...")
    # Initialize tqdm for writing segments
    pbar_write = tqdm(total=len(trips), desc="Writing segments")

    for trip_start_date, trip_end_date in trips:
        trip_segments = []
        current_date = trip_start_date
        while current_date <= trip_end_date:
             if current_date in daily_segments: # Only include days we actually have segments for
                 trip_segments.extend(daily_segments[current_date])
             current_date += timedelta(days=1)

        if not trip_segments:
            logger.warning(f"No segments found for trip {trip_start_date} to {trip_end_date}, skipping output file.")
            pbar_write.update(1)
            pbar_write.set_postfix_str(f"{segments_written} files written")
            continue

        # Sort segments by startTime just in case
        trip_segments.sort(key=lambda s: parse_datetime_utc(s.get("startTime", "")))

        output_filename = os.path.join(output_dir, f"Timeline.{trip_start_date}.{trip_end_date}.json")
        output_data = {"semanticSegments": trip_segments}

        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(output_data, f) # No indent for smaller file size
            segments_written += 1
            # logger.info(f"Saved trip: {output_filename}")
        except IOError as e:
            logger.error(f"Could not write output file '{output_filename}': {e}")
        except Exception as e:
             logger.error(f"An unexpected error occurred writing '{output_filename}': {e}")

        pbar_write.update(1)
        pbar_write.set_postfix_str(f"{segments_written} files written")


    pbar_write.close()
    logger.info(f"Successfully wrote {segments_written} trip segment files to '{output_dir}'.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Segment Google Maps Timeline data into trips away from home locations.")

    parser.add_argument("--input", required=True, help="Path to the input Timeline.json file.")
    parser.add_argument("--homeloc", required=True,
                        help="Semicolon-separated list of home locations. "
                             "Each spec: 'city,country-code[:radius_km]' or 'latitude,longitude[:radius_km]'. "
                             "E.g., \"Zurich,CH:15;40.7128,-74.0060\"")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS_KM,
                        help=f"Default radius in km if not specified in --homeloc spec. Default: {DEFAULT_RADIUS_KM} km.")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD, inclusive). Overrides --date.")
    parser.add_argument("--end", help="End date (YYYY-MM-DD, inclusive). Overrides --date.")
    parser.add_argument("--date",
                        help="Set start/end implicitly (YYYY, YYYY-MM, YYYY-MM-DD). Overridden by --start/--end.")
    parser.add_argument("--outputdir", required=True, help="Directory to save output segment JSON files.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG) # Adjust root logger as well if needed
        # Might need to adjust geopy logging level too if it's noisy
        logging.getLogger('geopy').setLevel(logging.INFO)
        logger.debug("Debug logging enabled.")

    if process_timeline(args):
        logger.info("Processing completed successfully.")
        sys.exit(0)
    else:
        logger.error("Processing failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()