import os
import json
import time
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

API_KEY = os.getenv("ORS_API_KEY")
API_URL = "https://api.heigit.org/openrouteservice/v2/directions/driving-car/json"
OUTPUT_FILE = "uae_routes_cleaned.json"

CITIES = {
    "Dubai": [55.2708, 25.2048],
    "Abu Dhabi": [54.3773, 24.4539],
    "Sharjah": [55.4033, 25.3463],
    "Ajman": [55.5136, 25.4052],
    "Ras Al Khaimah": [55.9432, 25.7895],
    "Fujairah": [56.3265, 25.1288],
    "Al Ain": [55.7447, 24.1917],
}


def fetch_route(origin, destination):
    payload = {
        "coordinates": [CITIES[origin], CITIES[destination]]
    }
    headers = {
        "Authorization": API_KEY,
        "Content-Type": "application/json",
    }

    for attempt in range(4):
        try:
            response = requests.post(
                API_URL,
                json=payload,
                headers=headers,
                timeout=60,
            )

            if response.status_code in (429, 500, 502, 503, 504):
                if attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue

            response.raise_for_status()
            data = response.json()
            summary = data["routes"][0]["summary"]

            distance_m = float(summary["distance"])
            duration_s = float(summary["duration"])

            if (
                not np.isfinite(distance_m)
                or not np.isfinite(duration_s)
                or distance_m <= 0
                or duration_s <= 0
            ):
                raise ValueError("Invalid distance or duration.")

            return distance_m, duration_s

        except (
            requests.RequestException,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as error:
            if attempt == 3:
                raise RuntimeError(
                    f"Failed route {origin} to {destination}: {error}"
                ) from error

            time.sleep(2 ** (attempt + 1))


def main():
    if not API_KEY:
        raise RuntimeError(
            "ORS_API_KEY is missing from GitHub repository secrets."
        )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    snapshot_date = retrieved_at[:10]
    records = []

    total_routes = len(CITIES) * (len(CITIES) - 1)
    route_number = 0

    # Fetch and validate the complete daily snapshot first.
    for origin in CITIES:
        for destination in CITIES:
            if origin == destination:
                continue

            route_number += 1
            print(
                f"Fetching route {route_number}/{total_routes}: "
                f"{origin} -> {destination}"
            )

            distance_m, duration_s = fetch_route(origin, destination)

            distance_km = distance_m / 1000
            duration_min = duration_s / 60
            speed_kmh = distance_km / (duration_s / 3600)

            records.append({
                "snapshot_id": f"{snapshot_date}_{origin}_to_{destination}",
                "snapshot_date": snapshot_date,
                "route_id": f"{origin}_to_{destination}",
                "origin": origin,
                "destination": destination,
                "distance_km": round(distance_km, 2),
                "duration_min": round(duration_min, 2),
                "estimated_speed_kmh": round(speed_kmh, 2),
                "data_source": "OpenRouteService",
                "data_type": "Route estimate; not live traffic",
                "retrieved_at_utc": retrieved_at,
                "api_status": "Success",
                "data_quality_flag": "Valid",
                "duplicate_route": False,
            })

            time.sleep(1)

    df = pd.DataFrame(records)

    if len(df) != total_routes:
        raise ValueError(
            f"Expected {total_routes} routes; received {len(df)}."
        )

    if df["route_id"].duplicated().any():
        raise ValueError("Duplicate routes detected in today's snapshot.")

    if not (
        np.isfinite(df["distance_km"]).all()
        and np.isfinite(df["duration_min"]).all()
        and np.isfinite(df["estimated_speed_kmh"]).all()
        and (df["distance_km"] > 0).all()
        and (df["duration_min"] > 0).all()
    ):
        raise ValueError("Daily snapshot validation failed.")

    # Load existing history, keeping older records.
    history = []

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
            history = json.load(file)

        if not isinstance(history, list):
            raise ValueError("Existing JSON must contain a list of records.")

    # Preserve older records and identify their snapshot dates.
    for record in history:
        if not record.get("snapshot_date"):
            old_timestamp = record.get("retrieved_at_utc", "")
            if len(old_timestamp) >= 10:
                record["snapshot_date"] = old_timestamp[:10]
            else:
                raise ValueError(
                    "An old record has no usable snapshot date."
                )

        if not record.get("snapshot_id"):
            record["snapshot_id"] = (
                f"{record['snapshot_date']}_{record['route_id']}"
            )

    # Replace today's snapshot if this workflow runs again today.
    # Keep every other date unchanged.
    history = [
        record for record in history
        if record.get("snapshot_date") != snapshot_date
    ]

    combined = history + records
    combined_df = pd.DataFrame(combined)

    if combined_df["snapshot_id"].duplicated().any():
        raise ValueError("Duplicate snapshot IDs detected in history.")

    combined.sort(
        key=lambda record: (
            record["snapshot_date"],
            record["route_id"],
        )
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(combined, file, indent=2, ensure_ascii=False)

    print("\nDaily route snapshot saved successfully.")
    print(f"Today's routes: {len(records)}")
    print(f"Historical records: {len(combined)}")
    print(f"Snapshot date (UTC): {snapshot_date}")
    print(f"Average route distance: {df['distance_km'].mean():.2f} km")
    print(f"Average estimated duration: {df['duration_min'].mean():.2f} min")
    print(f"Output file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
