# PRD: Google Timeline Segmenter

**Version:** 1.0
**Date:** 2025-05-01
**Author:** Gemini AI

## 1. Introduction

This document outlines the requirements for a Python program designed to process Google Maps Timeline data (`Timeline.json`). The program's primary function is to read a potentially large Timeline JSON file, identify periods where the user was away from defined "home" locations, and export these periods ("segments" or "trips") as separate, smaller JSON files preserving the original data structure. This allows users to isolate and analyze specific trips or periods of travel from their extensive location history.

## 2. Goals

* Parse a Google `Timeline.json` file containing location history data.
* Filter timeline data based on user-specified date ranges.
* Identify days spent entirely within a defined radius of one or more "home" locations.
* Group consecutive days spent outside of all "home" location radii into distinct segments (trips).
* Export each identified segment into a separate JSON file, maintaining the original Google Timeline format (`{"timelineObjects": [...]}`).
* Provide a clear command-line interface (CLI) for user interaction and parameter input.
* Handle potentially large input files (e.g., 60MB+) efficiently.

## 3. Non-Goals

* Visualizing timeline data (e.g., plotting on a map).
* Performing advanced data analysis (e.g., calculating distances, speeds, duration summaries).
* Modifying the original input `Timeline.json` file.
* Providing a Graphical User Interface (GUI).
* Supporting location history formats other than Google's `Timeline.json`.
* Real-time processing or monitoring.
* Merging or combining segments after creation.

## 4. User Stories

* **As a user**, I want to specify the path to my `Timeline.json` file so the program can process my location history.
* **As a user**, I want to define one or more "home" locations (by city/country or coordinates) and an optional radius for each, so the program can distinguish between time spent at home and time spent away.
* **As a user**, I want to optionally specify a start date and/or an end date (or a specific period like a year or month) for processing, so I can focus the analysis on relevant timeframes.
* **As a user**, I want to specify an output directory where the program will save the generated trip files.
* **As a user**, I want the program to automatically group consecutive "away" days into segments and save each segment as a separate JSON file named with its start and end date.
* **As a user**, I want clear feedback if I provide invalid parameters or if the program encounters errors (e.g., file not found, invalid date format, geocoding failure).

## 5. Functional Requirements

### 5.1. Input Processing

* **FR1.1:** The program MUST accept the path to a single `Timeline.json` file as a required command-line argument.
* **FR1.2:** The program MUST parse the JSON structure, specifically targeting the `timelineObjects` array. It should handle objects like `placeVisit` and `activitySegment` which contain location and time information.
    * Relevant fields within `timelineObjects` include:
        * `placeVisit`: `location.latitudeE7`, `location.longitudeE7`, `duration.startTimestampMs`, `duration.endTimestampMs`.
        * `activitySegment`: `startLocation.latitudeE7`, `startLocation.longitudeE7`, `endLocation.latitudeE7`, `endLocation.longitudeE7`, `duration.startTimestampMs`, `duration.endTimestampMs`. (Note: `activitySegment` may also contain `waypointPath` or `simplifiedRawPath` with more points).
* **FR1.3:** The program SHOULD handle potentially large files efficiently, possibly by using a streaming JSON parser or iterating through objects without loading the entire file into memory at once.
* **FR1.4:** Timestamps (e.g., `startTimestampMs`, `endTimestampMs`) are in milliseconds since the Unix epoch (UTC). The program MUST correctly convert these for date-based comparisons. Latitude/Longitude are stored as integers (degrees * $10^7$). The program MUST convert these to standard decimal degrees for distance calculations.

### 5.2. Date Filtering

* **FR2.1:** The program MUST accept optional `--start-date` and `--end-date` arguments in `YYYY-MM-DD` format.
* **FR2.2:** The program MUST accept an optional `--period` argument which can take `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` format. This flag serves as a shorthand for setting both the start and end date of the processing window:
    * `--period YYYY`: Sets start date to `YYYY-01-01` and end date to `YYYY-12-31`.
    * `--period YYYY-MM`: Sets start date to `YYYY-MM-01` and end date to the last day of `YYYY-MM`.
    * `--period YYYY-MM-DD`: Sets start date to `YYYY-MM-DD` and end date to `YYYY-MM-DD`.
* **FR2.3:** If both `--period` and specific `--start-date`/`--end-date` flags are provided, the specific flags (`--start-date`, `--end-date`) MUST take precedence over `--period`.
* **FR2.4:** The program MUST ignore all `timelineObjects` whose relevant timestamp (e.g., `startTimestampMs`) falls entirely *before* the effective start date (considering UTC conversion and the start of the day).
* **FR2.5:** The program MUST ignore all `timelineObjects` whose relevant timestamp (e.g., `startTimestampMs`) falls entirely *after* the effective end date (considering UTC conversion and the end of the day).
* **FR2.6:** If no date filters are provided, the program MUST process all data within the `Timeline.json` file.

### 5.3. Home Location Definition

* **FR3.1:** The program MUST accept one or more "home" locations via the `--home` flag (can be specified multiple times).
* **FR3.2:** Each `--home` flag value MUST support two formats:
    * `City,Country[:RadiusKm]` (e.g., `"Zurich,Switzerland:15"`, `"Paris,France"`)
    * `Latitude,Longitude[:RadiusKm]` (e.g., `"47.3769,8.5417:15"`, `"48.8566,2.3522"`)
* **FR3.3:** If the `City,Country` format is used, the program MUST use a geocoding service/library (e.g., `geopy` with Nominatim or another provider) to resolve the city/country name to latitude/longitude coordinates. The program should handle potential geocoding failures gracefully (e.g., print a warning and skip that home location, or exit with an error).
* **FR3.4:** If the optional `:RadiusKm` suffix is omitted for a home location, the program MUST use a default radius of 10 kilometers.
* **FR3.5:** The program MUST be able to store multiple home locations, each with its specific coordinates and radius.

### 5.4. Location Processing and Segment Identification

* **FR4.1:** The program MUST iterate through the filtered `timelineObjects` chronologically, grouping them by calendar day (based on UTC timestamps, considering day boundaries).
* **FR4.2:** For each day, the program MUST examine the location data of *all* `timelineObjects` occurring on that day.
* **FR4.3:** A day is considered "at home" if **ALL** recorded location points (from `placeVisit.location`, `activitySegment.startLocation`, `activitySegment.endLocation`, and potentially intermediate points if used) on that day fall within the specified radius of **at least one** of the defined home locations.
* **FR4.4:** A day is considered "away" if **ANY** recorded location point on that day falls outside the radii of **ALL** defined home locations.
* **FR4.5:** Distance calculation between recorded points and home location centers MUST use the Haversine formula (or an equivalent spherical distance calculation) to account for the Earth's curvature.
* **FR4.6:** The program MUST identify contiguous sequences of "away" days. Each such sequence constitutes a single "segment" or "trip".
* **FR4.7:** A segment starts on the first "away" day and ends on the last consecutive "away" day. Single "away" days constitute a segment of length one day.

### 5.5. Output Generation

* **FR5.1:** The program MUST accept a required `--output-dir` argument specifying the directory where segment files will be saved.
* **FR5.2:** The program MUST ensure the output directory exists. If it does not exist, it MUST attempt to create it. If creation fails, it MUST report an error and exit.
* **FR5.3:** For each identified segment (sequence of "away" days):
    * Determine the start date (`YYYY-MM-DD`) of the segment (the first day in the sequence).
    * Determine the end date (`YYYY-MM-DD`) of the segment (the last day in the sequence).
    * Collect all `timelineObjects` whose timestamps fall within the start and end dates (inclusive) of the segment.
    * Construct the output JSON content in the format: `{"timelineObjects": [list_of_collected_timelineObjects]}`.
    * Construct the output filename using the pattern: `Timeline.<segment_start_date>.<segment_end_date>.json` (e.g., `Timeline.2023-07-10.2023-07-24.json`).
    * Write the constructed JSON data to the generated filename within the specified output directory.

## 6. Non-Functional Requirements

* **NFR1. Performance:** The program should process a ~60MB JSON file in a reasonable timeframe (e.g., under a few minutes) on typical desktop hardware. Memory usage should be managed, avoiding loading the entire dataset if possible.
* **NFR2. Usability:**
    * The CLI should be clear and follow standard conventions (`argparse`).
    * Error messages should be informative (e.g., file not found, invalid date format, invalid home location format, geocoding failure, output directory not writable).
    * Optional: Provide progress indication (e.g., processing date X, found segment Y).
* **NFR3. Reliability:** The program must correctly identify home/away days based on the rules, accurately group segments, and generate valid JSON output files. Distance calculations must be accurate. Date/time handling must be correct, especially regarding timezones (assume UTC input) and day boundaries.
* **NFR4. Maintainability:** Code should be well-structured, commented, and follow Python best practices (PEP 8). Dependencies should be clearly listed.

## 7. Command-Line Interface (CLI) Design

The program will be executed from the command line using flags:

```bash
python timeline_segmenter.py \
    --input <path/to/Timeline.json> \
    --output-dir <path/to/output/directory> \
    --home "City1,Country1[:RadiusKm]" \
    [--home "Lat2,Lon2[:RadiusKm]"] \
    [...] \
    [--start-date YYYY-MM-DD] \
    [--end-date YYYY-MM-DD] \
    [--period YYYY|YYYY-MM|YYYY-MM-DD]