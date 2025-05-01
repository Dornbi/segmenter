# PRD: Google Timeline Segmenter

**Version:** 1.0
**Date:** 2025-05-01
**Author:** User Request via Gemini

## 1. Overview

This document describes the requirements for a Python program designed to process Google Maps Timeline data (`Timeline.json`). The primary goal is to read a potentially large `Timeline.json` file, filter out periods spent near designated "home" locations, and segment the remaining data into distinct "trips" or periods spent away from home. Each identified segment will be saved as a separate JSON file, preserving the original Google Timeline format.

## 2. Goals

* Parse a large `Timeline.json` file efficiently.
* Filter timeline data based on user-defined date ranges.
* Identify and filter out days where the user remained within a specified radius of one or more "home" locations.
* Group consecutive days spent *outside* all "home" location radii into distinct segments.
* Output each segment as a separate JSON file in the original format.
* Provide a clear command-line interface for configuration.

## 3. Non-Goals

* Modifying the *content* of the location data (beyond filtering and segmenting).
* Performing advanced data analysis or visualization on the segments.
* Providing a graphical user interface (GUI).
* Handling fundamentally corrupted or invalid `Timeline.json` input (program assumes valid JSON structure based on Google Takeout format).
* Real-time processing of location data.

## 4. Functional Requirements

### 4.1. Command-Line Interface (CLI)

The program shall be executed via the command line and accept the following arguments (flags):

* `--input <path>`: **Required**. Specifies the path to the input `Timeline.json` file.
* `--homeloc <spec1[;spec2;...]>`: **Required**. A semicolon-separated list defining home locations. Each `<spec>` can be:
    * `city,country-code[:radius_km]`: e.g., `"Zurich,CH:15"` or `"Paris,FR"`
    * `latitude,longitude[:radius_km]`: e.g., `"47.3769,8.5417:20"` or `"40.7128,-74.0060"`
    * If `:radius_km` is omitted, the value from `--radius` will be used for that location.
    * The program must resolve `city,country` specifications to latitude/longitude coordinates using a geocoding service.
* `--radius`: **Required**. The default radius in km. Default is **10 km**.
* `--start <YYYY-MM-DD>`: **Optional**. Specifies the inclusive start date for processing. If omitted, processing starts from the earliest record in the file.
* `--end <YYYY-MM-DD>`: **Optional**. Specifies the inclusive end date for processing. If omitted, processing continues to the latest record in the file.
* `--date <YYYY|YYYY-MM|YYYY-MM-DD>`: **Optional**. A single flag to set both start and end date implicitly:
    * `YYYY`: Sets start date to `YYYY-01-01` and end date to `YYYY-12-31`.
    * `YYYY-MM`: Sets start date to `YYYY-MM-01` and end date to the last day of `YYYY-MM`.
    * `YYYY-MM-DD`: Sets start date and end date to this specific day.
    * **Precedence:** If `--start-date` or `--end-date` are provided, they **override** any dates derived from `--date`.
* `--outputdir <path>`: **Required**. Specifies the path to the directory where the output segment JSON files will be saved. The directory will be created if it doesn't exist.

### 4.2. Input File Processing

* The program must read the `Timeline.json` file specified by `--input-file`.
* It should efficiently parse the JSON structure, focusing on the `semanticSegments` array.
* Given the potential file size (e.g., 60MB+), the program should aim to process the data iteratively (e.g., day by day or segment by segment) rather than loading the entire dataset into memory at once if feasible, although processing the entire `semanticSegments` list into memory might be necessary for grouping.

### 4.3. Date Filtering

* The program shall identify the date associated with each entry in the `semanticSegments` array (likely based on `startTime`).
* It must ignore all segments whose `startTime` falls outside the date range specified by the `--start-date`, `--end-date`, or `--date-filter` arguments.
* Date comparisons must correctly handle the provided date formats (`YYYY-MM-DD`). Timezone information in the timestamps should be considered when determining the date boundary, potentially by converting timestamps to UTC or a consistent local timezone for daily grouping.

### 4.4. Home Location Filtering

* **Geocoding:** For each home location specified as `city,country`, the program must use a geocoding service (e.g., using a library like `geopy`) to obtain its latitude and longitude. Handle potential errors during geocoding (e.g., network issues, ambiguous names).
    * Prefer geocoding services which are free to use and do not require an API key or registration, for example Nominatim or Photon.
* **Daily Location Check:** The program must process the timeline data day by day within the filtered date range. For each day:
    * Extract all geographic coordinates (`latitude, longitude`) recorded within that day. These can be found in various fields within `semanticSegments`, including `timelinePath[*].point`, `visit.placeLocation.latLng`, `activity.start.latLng`, `activity.end.latLng`, etc.
    * For each extracted point, calculate the Haversine distance to *each* specified home location's center.
    * A day is considered a "Home Day" if **all** recorded location points for that day fall **within** the specified radius of **at least one** of the home locations.
    * A day is considered an "Away Day" if **at least one** recorded location point falls **outside** the specified radii of **all** home locations.
    * Days with no identifiable location points should be ignored.
* The program must filter out and ignore all data corresponding to "Home Days".

### 4.5. Segment Identification

* After filtering by date and home location, the program must identify contiguous sequences of one or more "Away Days".
* Each such contiguous sequence constitutes a "segment" representing a trip or period away from home.
* A segment starts on the first "Away Day" after a "Home Day" (or the start of the processing window) and ends on the last consecutive "Away Day" before a "Home Day" (or the end of the processing window).

### 4.6. Output Generation

* For each identified segment:
    * Determine the segment's start date (`YYYY-MM-DD`) and end date (`YYYY-MM-DD`).
    * Collect *all* original `semanticSegments` entries from the input file whose `startTime` falls between the segment's start date (inclusive, 00:00:00) and end date (inclusive, 23:59:59).
    * Construct a new JSON object with a single top-level key `semanticSegments`, whose value is an array containing the collected segments for this trip. The structure should mirror the input `Timeline.json` format, but only contain data relevant to this specific segment.
    * Define the output filename as `Timeline.<start_date>.<end_date>.json` (e.g., `Timeline.2023-08-15.2023-08-22.json`).
    * Save this JSON object to a file with the generated name inside the directory specified by `--outputdir`.
    * Ensure the output directory exists; create it if necessary. Handle potential file writing errors (e.g., permissions).

## 5. Technical Requirements & Considerations

* **Language:** Python 3.x
* **Code:**
    * `segmenter.py`: The main file.
    * `segmenter_test.py`: File for all unit tests.
* **Libraries:**
    * `argparse`: For CLI argument parsing.
    * `json`: For JSON reading and writing.
    * `datetime`: For date/time parsing, comparison, and manipulation.
    * `math` / `geopy.distance` (or similar): For Haversine distance calculation.
    * `geopy` (or equivalent): For geocoding city/country names. Requires an internet connection unless caching is implemented. Note potential API rate limits or terms of service.
    * `os`: For directory creation and path manipulation.
* **Performance:** Be mindful of performance when processing large files. Iterative processing is preferred where possible. Geocoding adds external dependency and potential latency.
* **Error Handling:** Implement robust error handling for:
    * File not found / permission errors (input/output).
    * Invalid JSON format.
    * Invalid command-line arguments (date formats, location specs).
    * Geocoding failures (network errors, unknown locations, API limits).
    * Missing coordinate data within `semanticSegments`.
* **Timezones:** Acknowledge the presence of timezone information (`+HH:MM` offsets or `startTimeTimezoneUtcOffsetMinutes`) in the source data. Ensure date boundaries and filtering logic are consistent. Converting relevant timestamps to UTC for daily grouping is recommended for accuracy.
* **Logging:** Provide informative console output regarding progress (e.g., file being processed, dates being filtered, number of segments found) and any errors encountered.
* **Progress reporting:** Use tqdm. The progress bar shows the days processed, and additional text info shows the number of segments written to `--outputdir`.
* **Unit tests:** A single unit test file that covers the core logic (date filtering, distance calculation, segment identification).
* **Geocoding caching:** Previously located cities are stored in a geocache.json file. This is read for each invocation, and kept up to date with newly fetched cities, to improve performance and reduce reliance on external services for repeated runs with the same home locations.

## 6. Open Questions / Future Considerations

* Option to define a minimum duration for a segment to be considered valid (e.g., ignore 1-day "away" periods).


## Example Timeline.json

The first lines of sample Timeline.json:

```
{
  "semanticSegments": [
    {
      "startTime": "2009-11-11T13:00:00.000+01:00",
      "endTime": "2009-11-11T15:00:00.000+01:00",
      "timelinePath": [
        {
          "point": "47.365187°, 8.524766°",
          "time": "2009-11-11T13:28:00.000+01:00"
        }
      ]
    },
    {
      "startTime": "2009-11-11T13:28:29.000+01:00",
      "endTime": "2009-11-11T16:51:09.000+01:00",
      "startTimeTimezoneUtcOffsetMinutes": 60,
      "endTimeTimezoneUtcOffsetMinutes": 60,
      "visit": {
        "hierarchyLevel": 0,
        "probability": 0.47999998927116394,
        "topCandidate": {
          "placeId": "ChIJsecE_fYJkEcRGdMMY4AF3ko",
          "semanticType": "WORK",
          "probability": 0.9956839084625244,
          "placeLocation": {
            "latLng": "47.3653259°, 8.5247697°"
          }
        }
      }
    },
    {
      "startTime": "2009-11-11T15:00:00.000+01:00",
      "endTime": "2009-11-11T17:00:00.000+01:00",
      "timelinePath": [
        {
          "point": "47.365187°, 8.524766°",
          "time": "2009-11-11T16:51:00.000+01:00"
        }
      ]
    },
    {
      "startTime": "2009-11-11T16:51:09.000+01:00",
      "endTime": "2009-11-12T00:13:11.000+01:00",
      "startTimeTimezoneUtcOffsetMinutes": 60,
      "endTimeTimezoneUtcOffsetMinutes": 60,
      "activity": {
        "start": {
          "latLng": "47.3649775°, 8.52435°"
        },
        "end": {
          "latLng": "47.3026925°, 8.5286375°"
        },
        "distanceMeters": 6933.31982421875,
        "topCandidate": {
          "type": "UNKNOWN_ACTIVITY_TYPE",
          "probability": 0.0
        }
      }
    },
    {
      "startTime": "2009-11-11T17:00:00.000+01:00",
      "endTime": "2009-11-11T19:00:00.000+01:00",
      "timelinePath": [
        {
          "point": "47.366788°, 8.523365°",
          "time": "2009-11-11T17:37:00.000+01:00"
        },
        {
          "point": "47.370224°, 8.523996°",
          "time": "2009-11-11T18:32:00.000+01:00"
        },
        {
          "point": "47.321349°, 8.520679°",
          "time": "2009-11-11T18:42:00.000+01:00"
        },
        {
          "point": "47.302728°, 8.528617°",
          "time": "2009-11-11T18:51:00.000+01:00"
        }
      ]
    },
    {
      "startTime": "2009-11-11T21:00:00.000+01:00",
      "endTime": "2009-11-11T23:00:00.000+01:00",
      "timelinePath": [
        {
          "point": "47.303349°, 8.524562°",
          "time": "2009-11-11T21:09:00.000+01:00"
        },
        {
          "point": "47.302728°, 8.528617°",
          "time": "2009-11-11T21:55:00.000+01:00"
        }
      ]
    },
```