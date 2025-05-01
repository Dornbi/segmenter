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

* `--input-file <path>`: **Required**. Specifies the path to the input `Timeline.json` file.
* `--home-locations <spec1[;spec2;...]>`: **Required**. A semicolon-separated list defining home locations. Each `<spec>` can be:
    * `city,country[:radius_km]`: e.g., `"Zurich,Switzerland:15"` or `"Paris,France"`
    * `latitude,longitude[:radius_km]`: e.g., `"47.3769,8.5417:20"` or `"40.7128,-74.0060"`
    * If `:radius_km` is omitted, a default radius of **10 km** will be used for that location.
    * The program must resolve `city,country` specifications to latitude/longitude coordinates using a geocoding service.
* `--start-date <YYYY-MM-DD>`: **Optional**. Specifies the inclusive start date for processing. If omitted, processing starts from the earliest record in the file.
* `--end-date <YYYY-MM-DD>`: **Optional**. Specifies the inclusive end date for processing. If omitted, processing continues to the latest record in the file.
* `--date-filter <YYYY|YYYY-MM|YYYY-MM-DD>`: **Optional**. A single flag to set both start and end date implicitly:
    * `YYYY`: Sets start date to `YYYY-01-01` and end date to `YYYY-12-31`.
    * `YYYY-MM`: Sets start date to `YYYY-MM-01` and end date to the last day of `YYYY-MM`.
    * `YYYY-MM-DD`: Sets start date and end date to this specific day.
    * **Precedence:** If `--start-date` or `--end-date` are provided, they **override** any dates derived from `--date-filter`.
* `--output-dir <path>`: **Required**. Specifies the path to the directory where the output segment JSON files will be saved. The directory will be created if it doesn't exist.

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
* **Daily Location Check:** The program must process the timeline data day by day within the filtered date range. For each day:
    * Extract all geographic coordinates (`latitude, longitude`) recorded within that day. These can be found in various fields within `semanticSegments`, including `timelinePath[*].point`, `visit.placeLocation.latLng`, `activity.start.latLng`, `activity.end.latLng`, etc.
    * For each extracted point, calculate the Haversine distance to *each* specified home location's center.
    * A day is considered a "Home Day" if **all** recorded location points for that day fall **within** the specified radius of **at least one** of the home locations.
    * A day is considered an "Away Day" if **at least one** recorded location point falls **outside** the specified radii of **all** home locations.
    * Days with no identifiable location points should be treated consistently (e.g., ignored, or treated as "Home Days" - specify the chosen behavior. Default: Treat as "Home Day").
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
    * Save this JSON object to a file with the generated name inside the directory specified by `--output-dir`.
    * Ensure the output directory exists; create it if necessary. Handle potential file writing errors (e.g., permissions).

## 5. Technical Requirements & Considerations

* **Language:** Python 3.x
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

## 6. Open Questions / Future Considerations

* Confirm the precise handling strategy for days with no location data points (Treat as Home? Ignore?).
* Implement geocoding caching to improve performance and reduce reliance on external services for repeated runs with the same home locations.
* Add more detailed progress reporting, especially for large files.
* Consider adding unit tests for core logic (date filtering, distance calculation, segment identification).
* Option to define a minimum duration for a segment to be considered valid (e.g., ignore 1-day "away" periods).
