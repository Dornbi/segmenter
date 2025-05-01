import unittest
from unittest.mock import patch, MagicMock, mock_open, call
import json
import os
from datetime import date, datetime, timezone, timedelta
from segmenter import (
    parse_datetime_utc, parse_lat_lng, get_coordinates_from_segment,
    is_point_near_home, geocode_location, parse_home_locations, parse_date_args,
    process_timeline, DEFAULT_RADIUS_KM, GEOCACHE_FILENAME
)
# Mock geopy classes before they are potentially imported by the module under test
from geopy.geocoders import Nominatim
from geopy.location import Location
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

class MockArgs:
    def __init__(self, **kwargs):
        self.input = kwargs.get('input')
        self.homeloc = kwargs.get('homeloc')
        self.radius = kwargs.get('radius', DEFAULT_RADIUS_KM)
        self.start = kwargs.get('start')
        self.end = kwargs.get('end')
        self.date = kwargs.get('date')
        self.outputdir = kwargs.get('outputdir')
        self.verbose = kwargs.get('verbose', False)

# Sample segment data for testing
SAMPLE_SEGMENT_VISIT = {
    "startTime": "2023-08-15T10:00:00.000+02:00", # UTC: 2023-08-15T08:00:00Z
    "endTime": "2023-08-15T12:00:00.000+02:00",
    "visit": {
        "topCandidate": {
            "placeLocation": {
                "latLng": "47.3769°, 8.5417°" # Zurich HB
            }
        }
    }
}
SAMPLE_SEGMENT_ACTIVITY = {
    "startTime": "2023-08-16T14:00:00Z", # UTC
    "endTime": "2023-08-16T15:00:00Z",
    "activity": {
        "start": {"latLng": "48.8584°, 2.2945°"}, # Eiffel Tower
        "end": {"latLng": "48.8606°, 2.3376°"}   # Louvre
    }
}
SAMPLE_SEGMENT_PATH = {
    "startTime": "2023-08-17T09:30:00.000+01:00", # UTC: 2023-08-17T08:30:00Z
    "endTime": "2023-08-17T09:45:00.000+01:00",
    "timelinePath": [
        {"point": "51.5074°, -0.1278°", "time": "..."} # London Center
    ]
}
SAMPLE_SEGMENT_NO_COORDS = {
    "startTime": "2023-08-18T11:00:00Z",
    "endTime": "2023-08-18T12:00:00Z",
    "activity": {"type": "STILL"}
}
SAMPLE_SEGMENT_MIXED = {
    "startTime": "2023-08-19T10:00:00Z",
    "endTime": "2023-08-19T18:00:00Z",
     "visit": { "placeLocation": { "latLng": "40.7128°, -74.0060°" } }, # NYC
     "activity": { "start": {"latLng": "40.7128°, -74.0060°"}, "end": {"latLng": "40.7580°, -73.9855°"} }, # Times Sq
     "timelinePath": [ {"point": "40.7128°, -74.0060°"}, {"point": "40.7580°, -73.9855°"} ]
}

class TestTimelineSegmenter(unittest.TestCase):

    def test_parse_datetime_utc(self):
        self.assertEqual(parse_datetime_utc("2023-08-15T10:00:00.000+02:00"), datetime(2023, 8, 15, 8, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(parse_datetime_utc("2023-08-16T14:00:00Z"), datetime(2023, 8, 16, 14, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(parse_datetime_utc("2023-08-17T09:30:00.000-07:00"), datetime(2023, 8, 17, 16, 30, 0, tzinfo=timezone.utc))
        self.assertIsNone(parse_datetime_utc("invalid date string"))
        self.assertIsNone(parse_datetime_utc(None))

    def test_parse_lat_lng(self):
        self.assertEqual(parse_lat_lng("47.3769°, 8.5417°"), (47.3769, 8.5417))
        self.assertEqual(parse_lat_lng(" -33.8688°, 151.2093° "), (-33.8688, 151.2093))
        self.assertIsNone(parse_lat_lng("invalid"))
        self.assertIsNone(parse_lat_lng("91.0°, 8.0°")) # Invalid latitude
        self.assertIsNone(parse_lat_lng("45.0°, 181.0°")) # Invalid longitude
        self.assertIsNone(parse_lat_lng(None))
        self.assertIsNone(parse_lat_lng(123.45)) # Not a string

    def test_get_coordinates_from_segment(self):
        coords_visit = get_coordinates_from_segment(SAMPLE_SEGMENT_VISIT)
        self.assertCountEqual(coords_visit, [(47.3769, 8.5417)])

        coords_activity = get_coordinates_from_segment(SAMPLE_SEGMENT_ACTIVITY)
        self.assertCountEqual(coords_activity, [(48.8584, 2.2945), (48.8606, 2.3376)])

        coords_path = get_coordinates_from_segment(SAMPLE_SEGMENT_PATH)
        self.assertCountEqual(coords_path, [(51.5074, -0.1278)])

        coords_no = get_coordinates_from_segment(SAMPLE_SEGMENT_NO_COORDS)
        self.assertCountEqual(coords_no, [])

        coords_mixed = get_coordinates_from_segment(SAMPLE_SEGMENT_MIXED)
        self.assertCountEqual(coords_mixed, [(40.7128, -74.0060), (40.7580, -73.9855)]) # Checks duplicates removed

        # Test robustness against missing keys
        self.assertCountEqual(get_coordinates_from_segment({"startTime": "...", "visit": {}}), [])
        self.assertCountEqual(get_coordinates_from_segment({"startTime": "...", "activity": {"start": {}}}), [])
        self.assertCountEqual(get_coordinates_from_segment({"startTime": "...", "timelinePath": [{}]}), [])

    @patch('segmenter.geodesic')
    def test_is_point_near_home(self, mock_geodesic):
        home_locations = [
            (47.37, 8.54, 10.0), # Home 1 (Zurich)
            (40.71, -74.00, 15.0) # Home 2 (NYC)
        ]

        # Mock distance calculations
        def geodesic_side_effect(p1, p2):
            mock_dist = MagicMock()
            if p2 == (47.37, 8.54): # To Home 1
                if p1 == (47.3769, 8.5417): mock_dist.km = 1.0 # Close to Home 1
                elif p1 == (48.85, 2.29): mock_dist.km = 500.0 # Far from Home 1
                else: mock_dist.km = 999 # Default far
            elif p2 == (40.71, -74.00): # To Home 2
                if p1 == (40.7128, -74.0060): mock_dist.km = 1.0 # Close to Home 2
                elif p1 == (47.37, 8.54): mock_dist.km = 6000.0 # Far from Home 2
                else: mock_dist.km = 999 # Default far
            else:
                mock_dist.km = 999 # Default far
            return mock_dist

        mock_geodesic.side_effect = geodesic_side_effect

        # Test cases
        self.assertTrue(is_point_near_home(47.3769, 8.5417, home_locations)) # Near Home 1
        self.assertTrue(is_point_near_home(40.7128, -74.0060, home_locations)) # Near Home 2
        self.assertFalse(is_point_near_home(48.85, 2.29, home_locations)) # Far from both

        # Test empty home locations
        self.assertFalse(is_point_near_home(47.3769, 8.5417, []))

    @patch('segmenter.Nominatim')
    def test_geocode_location(self, MockNominatim):
        mock_geolocator = MockNominatim.return_value
        mock_location = Location("Zurich, CH", (47.3769, 8.5417, 0.0)) # lat, lon, alt
        mock_geolocator.geocode.return_value = mock_location
        cache = {}

        # 1. City, Country - Cache Miss
        result = geocode_location("Zurich,CH", 10.0, mock_geolocator, cache)
        self.assertEqual(result, (47.3769, 8.5417, 10.0))
        mock_geolocator.geocode.assert_called_once_with("Zurich,CH", exactly_one=True, timeout=10)
        self.assertIn("zurich,ch", cache)
        self.assertEqual(cache["zurich,ch"], (47.3769, 8.5417))

        # 2. City, Country - Cache Hit
        mock_geolocator.geocode.reset_mock()
        result = geocode_location(" ZURICH , ch ", 10.0, mock_geolocator, cache) # Test trimming/case
        self.assertEqual(result, (47.3769, 8.5417, 10.0))
        mock_geolocator.geocode.assert_not_called() # Should use cache

        # 3. Lat, Lon - No Geocoding
        mock_geolocator.geocode.reset_mock()
        cache = {}
        result = geocode_location("40.7128, -74.0060", 10.0, mock_geolocator, cache)
        self.assertEqual(result, (40.7128, -74.0060, 10.0))
        mock_geolocator.geocode.assert_not_called()
        self.assertEqual(cache, {}) # Cache not used for lat/lon

        # 4. City, Country with Radius Override
        mock_geolocator.geocode.reset_mock()
        cache = {}
        result = geocode_location("Paris,FR:15.5", 10.0, mock_geolocator, cache)
        mock_location_paris = Location("Paris, FR", (48.8566, 2.3522, 0.0))
        mock_geolocator.geocode.return_value = mock_location_paris
        self.assertEqual(result, (48.8566, 2.3522, 15.5))
        mock_geolocator.geocode.assert_called_once_with("Paris,FR", exactly_one=True, timeout=10)
        self.assertIn("paris,fr", cache)

        # 5. Lat, Lon with Radius Override
        mock_geolocator.geocode.reset_mock()
        cache = {}
        result = geocode_location(" 51.5, -0.1 : 5 ", 10.0, mock_geolocator, cache)
        self.assertEqual(result, (51.5, -0.1, 5.0))
        mock_geolocator.geocode.assert_not_called()

        # 6. Geocoding Fails (Not Found)
        mock_geolocator.geocode.reset_mock()
        mock_geolocator.geocode.return_value = None
        cache = {}
        result = geocode_location("NonExistentPlace,XY", 10.0, mock_geolocator, cache)
        self.assertIsNone(result)
        mock_geolocator.geocode.assert_called_once_with("NonExistentPlace,XY", exactly_one=True, timeout=10)
        self.assertNotIn("nonexistentplace,xy", cache) # Don't cache failures

        # 7. Geocoding Fails (Timeout with Retries)
        mock_geolocator.geocode.reset_mock()
        mock_geolocator.geocode.side_effect = [GeocoderTimedOut, GeocoderTimedOut, mock_location]
        with patch('time.sleep', return_value=None): # Mock sleep to speed up test
             result = geocode_location("TimeoutCity,TC", 10.0, mock_geolocator, cache)
        self.assertEqual(result, (47.3769, 8.5417, 10.0)) # Should succeed on 3rd try
        self.assertEqual(mock_geolocator.geocode.call_count, 3)
        self.assertIn("timeoutcity,tc", cache)

        # 8. Geocoding Fails (Service Error)
        mock_geolocator.geocode.reset_mock()
        mock_geolocator.geocode.side_effect = GeocoderServiceError
        result = geocode_location("ServiceErrorCity,SC", 10.0, mock_geolocator, cache)
        self.assertIsNone(result)
        self.assertEqual(mock_geolocator.geocode.call_count, 1) # Should not retry service error

        # 9. Invalid radius format
        mock_geolocator.geocode.reset_mock()
        mock_geolocator.geocode.return_value = mock_location
        result = geocode_location("Zurich,CH:abc", 10.0, mock_geolocator, cache)
        # Should still geocode location but use default radius
        self.assertEqual(result, (47.3769, 8.5417, 10.0))
        mock_geolocator.geocode.assert_called_once_with("Zurich,CH:abc", exactly_one=True, timeout=10) # Uses full string if radius parse fails


    @patch('segmenter.geocode_location')
    def test_parse_home_locations(self, mock_geocode):
        cache = {}
        mock_geolocator = MagicMock()

        def geocode_side_effect(spec, default_radius, geolocator, cache):
            if spec == "Zurich,CH": return (47.37, 8.54, 10.0)
            if spec == "40.7,-74.0:15": return (40.7, -74.0, 15.0)
            if spec == "Fail,XY": return None
            return None
        mock_geocode.side_effect = geocode_side_effect

        # Valid mix
        specs = " Zurich,CH ; 40.7,-74.0:15 "
        result = parse_home_locations(specs, 10.0, mock_geolocator, cache)
        self.assertCountEqual(result, [(47.37, 8.54, 10.0), (40.7, -74.0, 15.0)])
        self.assertEqual(mock_geocode.call_count, 2)
        calls = [call("Zurich,CH", 10.0, mock_geolocator, cache),
                 call("40.7,-74.0:15", 10.0, mock_geolocator, cache)]
        mock_geocode.assert_has_calls(calls, any_order=True)

        # With a failure (should skip the failed one)
        mock_geocode.reset_mock()
        specs = "Zurich,CH;Fail,XY;40.7,-74.0:15"
        result = parse_home_locations(specs, 10.0, mock_geolocator, cache)
        self.assertCountEqual(result, [(47.37, 8.54, 10.0), (40.7, -74.0, 15.0)])
        self.assertEqual(mock_geocode.call_count, 3)

        # Only failures
        mock_geocode.reset_mock()
        specs = "Fail,XY;AnotherFail,ZZ"
        result = parse_home_locations(specs, 10.0, mock_geolocator, cache)
        self.assertIsNone(result)
        self.assertEqual(mock_geocode.call_count, 2)

        # Empty spec string
        mock_geocode.reset_mock()
        specs = " ; ; "
        result = parse_home_locations(specs, 10.0, mock_geolocator, cache)
        self.assertIsNone(result)
        mock_geocode.assert_not_called()

    def test_parse_date_args(self):
        # 1. Only --date=YYYY
        args = MockArgs(date="2023")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2023, 1, 1))
        self.assertEqual(end, date(2023, 12, 31))

        # 2. Only --date=YYYY-MM
        args = MockArgs(date="2023-02")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2023, 2, 1))
        self.assertEqual(end, date(2023, 2, 28)) # Handles leap year implicitly via calendar

        # 3. Only --date=YYYY-MM (Leap Year Feb)
        args = MockArgs(date="2024-02")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2024, 2, 1))
        self.assertEqual(end, date(2024, 2, 29))

        # 4. Only --date=YYYY-MM-DD
        args = MockArgs(date="2023-08-15")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2023, 8, 15))
        self.assertEqual(end, date(2023, 8, 15))

        # 5. Only --start and --end
        args = MockArgs(start="2023-03-01", end="2023-05-31")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2023, 3, 1))
        self.assertEqual(end, date(2023, 5, 31))

        # 6. --start/--end override --date
        args = MockArgs(date="2023", start="2023-02-10", end="2023-11-20")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2023, 2, 10))
        self.assertEqual(end, date(2023, 11, 20))

        # 7. Only --start
        args = MockArgs(start="2023-01-15")
        start, end = parse_date_args(args)
        self.assertEqual(start, date(2023, 1, 15))
        self.assertIsNone(end) # No end date specified

        # 8. Only --end
        args = MockArgs(end="2023-12-15")
        start, end = parse_date_args(args)
        self.assertIsNone(start) # No start date specified
        self.assertEqual(end, date(2023, 12, 15))

        # 9. No date args
        args = MockArgs()
        start, end = parse_date_args(args)
        self.assertIsNone(start)
        self.assertIsNone(end)

        # 10. Invalid date format
        args = MockArgs(date="2023/01/01")
        start, end = parse_date_args(args)
        self.assertIsNone(start)
        self.assertIsNone(end)

        args = MockArgs(start="01-02-2023")
        start, end = parse_date_args(args)
        self.assertIsNone(start)
        self.assertIsNone(end)

        # 11. Start after End
        args = MockArgs(start="2023-06-01", end="2023-05-01")
        start, end = parse_date_args(args)
        self.assertIsNone(start)
        self.assertIsNone(end)


    @patch('segmenter.os.path.exists')
    @patch('segmenter.os.makedirs')
    @patch('segmenter.open', new_callable=mock_open)
    @patch('segmenter.json.load')
    @patch('segmenter.json.dump')
    @patch('segmenter.parse_home_locations')
    @patch('segmenter.parse_date_args')
    @patch('segmenter.is_point_near_home')
    @patch('segmenter.load_geocache')
    @patch('segmenter.save_geocache')
    @patch('segmenter.Nominatim') # Mock geolocator init
    @patch('segmenter.tqdm', lambda x, **kwargs: x) # Disable tqdm for tests
    def test_process_timeline_integration(self, MockNominatim, mock_save_cache, mock_load_cache,
                                          mock_is_near, mock_parse_dates, mock_parse_homes,
                                          mock_json_dump, mock_json_load, mock_open_func,
                                          mock_makedirs, mock_exists):

        # --- Setup Mocks ---
        mock_exists.return_value = True # Assume output dir exists or is created
        mock_load_cache.return_value = {} # Start with empty geocache
        mock_parse_dates.return_value = (date(2023, 8, 15), date(2023, 8, 19)) # Date range
        mock_home = (47.0, 8.0, 10.0) # Simplified home location
        mock_parse_homes.return_value = [mock_home] # Parsed home locations

        # Mock input data
        mock_input_data = {
            "semanticSegments": [
                # Day 1 (Aug 15) - Home (near 47, 8)
                {"startTime": "2023-08-15T10:00:00Z", "visit": {"placeLocation": {"latLng": "47.01, 8.01"}}},
                {"startTime": "2023-08-15T15:00:00Z", "visit": {"placeLocation": {"latLng": "47.05, 7.95"}}},
                # Day 2 (Aug 16) - Away (far from 47, 8)
                {"startTime": "2023-08-16T09:00:00Z", "activity": {"start": {"latLng": "50.0, 1.0"}}},
                {"startTime": "2023-08-16T14:00:00Z", "visit": {"placeLocation": {"latLng": "50.1, 1.1"}}},
                # Day 3 (Aug 17) - Away
                {"startTime": "2023-08-17T11:00:00Z", "visit": {"placeLocation": {"latLng": "50.2, 1.2"}}},
                # Day 4 (Aug 18) - Home
                {"startTime": "2023-08-18T10:00:00Z", "visit": {"placeLocation": {"latLng": "47.02, 8.02"}}},
                # Day 5 (Aug 19) - Away
                {"startTime": "2023-08-19T12:00:00Z", "visit": {"placeLocation": {"latLng": "51.0, 0.0"}}},
                # Outside date range
                {"startTime": "2023-08-20T10:00:00Z", "visit": {"placeLocation": {"latLng": "47.0, 8.0"}}},
                {"startTime": "2023-08-14T10:00:00Z", "visit": {"placeLocation": {"latLng": "47.0, 8.0"}}},
            ]
        }
        mock_json_load.return_value = mock_input_data

        # Mock is_point_near_home logic
        def near_home_side_effect(lat, lon, homes):
            # Roughly check if latitude is near 47 for simplicity
            return 46.9 < lat < 47.1
        mock_is_near.side_effect = near_home_side_effect

        args = MockArgs(input='dummy_input.json', homeloc='Zurich,CH', outputdir='out_dir')

        # --- Run ---
        result = process_timeline(args)

        # --- Assertions ---
        self.assertTrue(result) # Should succeed

        # Check input file read
        mock_open_func.assert_any_call('dummy_input.json', 'r', encoding='utf-8')
        mock_json_load.assert_called_once()

        # Check home location parsing
        mock_parse_homes.assert_called_once()

        # Check date parsing
        mock_parse_dates.assert_called_once()

        # Check output directory creation
        mock_makedirs.assert_called_with('out_dir', exist_ok=True)

        # Check near_home calls (should be called for points on days 15, 16, 17, 18, 19)
        # Day 15: (47.01, 8.01), (47.05, 7.95) -> both near -> Home Day
        # Day 16: (50.0, 1.0), (50.1, 1.1) -> both far -> Away Day
        # Day 17: (50.2, 1.2) -> far -> Away Day
        # Day 18: (47.02, 8.02) -> near -> Home Day
        # Day 19: (51.0, 0.0) -> far -> Away Day
        # Expected trips: Aug 16-17, Aug 19-19

        # Check output file writes
        # Trip 1: Aug 16 - Aug 17
        expected_output1_filename = os.path.join('out_dir', 'Timeline.2023-08-16.2023-08-17.json')
        expected_output1_data = {"semanticSegments": [
             {"startTime": "2023-08-16T09:00:00Z", "activity": {"start": {"latLng": "50.0, 1.0"}}},
             {"startTime": "2023-08-16T14:00:00Z", "visit": {"placeLocation": {"latLng": "50.1, 1.1"}}},
             {"startTime": "2023-08-17T11:00:00Z", "visit": {"placeLocation": {"latLng": "50.2, 1.2"}}},
        ]}
        # Trip 2: Aug 19 - Aug 19
        expected_output2_filename = os.path.join('out_dir', 'Timeline.2023-08-19.2023-08-19.json')
        expected_output2_data = {"semanticSegments": [
            {"startTime": "2023-08-19T12:00:00Z", "visit": {"placeLocation": {"latLng": "51.0, 0.0"}}},
        ]}

        # Check if mock_open was called for output files and json.dump was called with correct data
        output_calls = []
        dump_calls = []
        for mock_call in mock_open_func.call_args_list:
             if mock_call[0][0] == expected_output1_filename and mock_call[0][1] == 'w':
                 output_calls.append(mock_call)
             if mock_call[0][0] == expected_output2_filename and mock_call[0][1] == 'w':
                 output_calls.append(mock_call)

        for mock_call in mock_json_dump.call_args_list:
             if mock_call[0][0] == expected_output1_data:
                 dump_calls.append(mock_call)
             if mock_call[0][0] == expected_output2_data:
                 dump_calls.append(mock_call)

        self.assertEqual(len(output_calls), 2, "Should have opened two output files for writing")
        self.assertEqual(len(dump_calls), 2, "Should have dumped data for two segments")

        # Verify the content passed to json.dump for one of the files (deep compare is tricky with dict order)
        # We check that the expected data structures were arguments to json.dump
        # This relies on the order of calls matching the expected segment order
        self.assertEqual(mock_json_dump.call_args_list[0][0][0], expected_output1_data)
        self.assertEqual(mock_json_dump.call_args_list[1][0][0], expected_output2_data)

        # Check cache saving (if geocoding happened - mock parse_home_locations bypasses it here)
        # If we tested geocoding within process_timeline, we'd check save_geocache here.


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)