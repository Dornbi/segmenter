# Google Timeline Segmenter

*Vibe-coded with Gemini 2.5 Pro (experimental)*

A Python tool to process Google Maps Timeline data (`Timeline.json`), filter out time spent near defined 'home' locations, and segment the remaining data into distinct trips (periods spent away from home). Each identified trip is saved as a separate JSON file, preserving the original `semanticSegments` format for the relevant time period.

This tool is useful for analyzing travel patterns, isolating specific journeys, or preparing timeline data for further processing or visualization by focusing on periods spent away from your usual locations.

You can look at the result:
https://timelineviewer.pages.dev/

## Features

* **Command-Line Interface:** Easy configuration via CLI arguments.
* **Timeline Parsing:** Reads and processes `Timeline.json` from Google Takeout.
* **Date Filtering:** Process data within specific date ranges (year, month, day, or start/end dates).
* **Home Location Filtering:** Define one or more "home" locations using coordinates or city/country names.
* **Radius Definition:** Specify a radius around home locations to define the "home zone". Uses Haversine distance for accurate calculation.
* **Geocoding:** Automatically converts `city,country` home specifications to latitude/longitude using Nominatim (requires internet connection for the first lookup).
* **Geocoding Cache:** Caches geocoding results in `geocache.json` to speed up subsequent runs and reduce reliance on external services.
* **Trip Segmentation:** Identifies contiguous blocks of days spent *outside* all defined home zone radii.
* **JSON Output:** Saves each identified trip ("segment") as a separate `Timeline.<start_date>.<end_date>.json` file containing the relevant `semanticSegments`.
* **Progress Reporting:** Uses `tqdm` to display progress during segment processing and file writing.

## Requirements

* Python 3.x (developed/tested with Python 3.8+)
* `pip` for installing dependencies

## Installation

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/your-username/your-repository-name.git](https://github.com/your-username/your-repository-name.git)
    cd your-repository-name
    ```
    (Replace `your-username/your-repository-name` with your actual repository details)

2.  **Install Dependencies:**
    It's recommended to use a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate # On Windows use `venv\Scripts\activate`
    ```
    Then install the required libraries:
    ```bash
    pip install -r requirements.txt
    ```
    Alternatively, install manually:
    ```bash
    pip install geopy python-dateutil tqdm
    ```

    *(Consider creating a `requirements.txt` file in your repository with the content below for easier installation)*
    ```
    geopy>=2.0
    python-dateutil>=2.8
    tqdm>=4.0
    ```

## Usage

The script is run from the command line:

```bash
python segmenter.py --input <path_to_timeline.json> --homeloc <home_specs> --outputdir <output_directory> [options]