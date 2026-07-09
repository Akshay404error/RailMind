"""
RailMind - Data Loader (v2)
Loads the 4 raw dataset files into pandas DataFrames.

Confirmed shapes (from actual run):
  stations.json  -> GeoJSON FeatureCollection, Point features (some geometry=None)
  trains.json    -> GeoJSON FeatureCollection, LineString features (route per train)
  schedules.json -> flat list of stop records (train_name, station_code, arrival, departure, day, ...)
  etrain_delays.csv -> flat CSV
"""

import json
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

STATIONS_PATH = DATA_DIR / "stations.json"
TRAINS_PATH = DATA_DIR / "trains.json"
SCHEDULES_PATH = DATA_DIR / "schedules.json"
DELAYS_PATH = DATA_DIR / "etrain_delays.csv"


def _load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _feature_collection_to_df(raw: dict) -> pd.DataFrame:
    """
    Flattens a GeoJSON FeatureCollection into a DataFrame.
    Handles Point features (-> latitude/longitude) and LineString
    features (-> route_coordinates list), and tolerates geometry=None.
    """
    features = raw.get("features") or []
    records = []

    for feature in features:
        if not isinstance(feature, dict):
            continue

        props = feature.get("properties") or {}
        record = dict(props)

        geom = feature.get("geometry")  # may legitimately be None
        if geom:
            gtype = geom.get("type")
            coords = geom.get("coordinates")

            if gtype == "Point" and coords:
                record["longitude"] = coords[0]
                record["latitude"] = coords[1]
            elif gtype == "LineString" and coords:
                record["route_coordinates"] = coords
                record["num_route_points"] = len(coords)
            else:
                record["geometry_type"] = gtype
        else:
            record["geometry_type"] = None

        records.append(record)

    return pd.DataFrame(records)


def load_stations() -> pd.DataFrame:
    """Loads stations.json -> one row per station (Point geometry)."""
    raw = _load_json(STATIONS_PATH)
    if not (isinstance(raw, dict) and "features" in raw):
        raise ValueError("stations.json is not a FeatureCollection — inspect manually.")

    df = _feature_collection_to_df(raw)

    n_missing_geom = df["latitude"].isna().sum() if "latitude" in df.columns else len(df)
    if n_missing_geom:
        print(f"  note: {n_missing_geom} stations have no coordinates (geometry was null)")

    return df


def load_trains() -> pd.DataFrame:
    """
    Loads trains.json -> one row per train ROUTE (LineString geometry).
    This is route-level info: endpoints, timings, classes available.
    NOT per-station schedule detail (that's schedules.json).
    """
    raw = _load_json(TRAINS_PATH)
    if not (isinstance(raw, dict) and "features" in raw):
        raise ValueError("trains.json is not a FeatureCollection — inspect manually.")

    df = _feature_collection_to_df(raw)

    # Standardize the train number column name if present
    if "number" in df.columns:
        df = df.rename(columns={"number": "train_number"})

    return df


def load_schedules() -> pd.DataFrame:
    """Loads schedules.json -> flat list of (train, station, arrival, departure, day)."""
    raw = _load_json(SCHEDULES_PATH)
    if isinstance(raw, list):
        df = pd.DataFrame(raw)
    elif isinstance(raw, dict):
        records = []
        for train_number, stops in raw.items():
            if isinstance(stops, list):
                for stop in stops:
                    stop = dict(stop)
                    stop["train_number"] = train_number
                    records.append(stop)
        df = pd.DataFrame(records)
    else:
        raise ValueError("Unrecognized schedules.json structure — inspect manually.")

    # train_number types can be mixed (int/str) across files — normalize to str
    if "train_number" in df.columns:
        df["train_number"] = df["train_number"].astype(str)

    return df


def load_delays() -> pd.DataFrame:
    """Loads etrain_delays.csv."""
    if not DELAYS_PATH.exists():
        raise FileNotFoundError(f"File not found: {DELAYS_PATH}")
    df = pd.read_csv(DELAYS_PATH)
    if "train_number" in df.columns:
        df["train_number"] = df["train_number"].astype(str)
    return df


def load_all():
    datasets = {}
    for name, loader_fn in [
        ("stations", load_stations),
        ("trains", load_trains),
        ("schedules", load_schedules),
        ("delays", load_delays),
    ]:
        try:
            df = loader_fn()
            datasets[name] = df
            print(f"[OK] {name}: {df.shape[0]} rows, {df.shape[1]} columns")
            print(f"     columns: {list(df.columns)}")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
    return datasets


if __name__ == "__main__":
    data = load_all()
    for name, df in data.items():
        print(f"\n--- {name} preview ---")
        print(df.head(3))