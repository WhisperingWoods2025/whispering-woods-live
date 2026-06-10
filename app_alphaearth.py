"""Stakeholder-facing Whispering Woods forest intelligence dashboard."""

import csv
import io
import json
import math
import re
import urllib.request
import zipfile
from typing import Optional

import folium
import pandas as pd
import streamlit as st

try:
    import ee  # type: ignore
except ImportError as exc:
    raise RuntimeError("The earthengine-api must be installed to run this app.") from exc

try:
    from streamlit_folium import st_folium  # type: ignore
except ImportError as exc:
    raise RuntimeError(
        "The streamlit-folium package must be installed to run this app. See requirements.txt."
    ) from exc


EMBEDDING_COLLECTION_ID = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
HANSEN_COLLECTION_ID = "UMD/hansen/global_forest_change_2025_v1_13"
SURFACE_WATER_COLLECTION_ID = "JRC/GSW1_4/GlobalSurfaceWater"
WORLDCOVER_COLLECTION_ID = "ESA/WorldCover/v200"
BURNED_AREA_COLLECTION_ID = "MODIS/061/MCD64A1"
ERA5_COLLECTION_ID = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
WDPA_COLLECTION_ID = "WCMC/WDPA/current/polygons"
BERCHTESGADEN_WDPA_ID = 668

DWD_RECENT_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent"
DWD_HISTORICAL_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical"

DEFAULT_RGB_BANDS = ["A01", "A16", "A09"]
AOI_COLOR = "#F1C75B"
ALPHAEARTH_YEARS = set(range(2017, 2025))

DWD_STATIONS = [
    {
        "id": "19856",
        "name": "Schoenau am Koenigssee",
        "state": "Bayern",
        "lat": 47.6134,
        "lon": 12.9819,
        "elevation": 625,
        "distance_km": 7.4,
    },
    {
        "id": "07424",
        "name": "Piding",
        "state": "Bayern",
        "lat": 47.7724,
        "lon": 12.9073,
        "elevation": 457,
        "distance_km": 24.9,
    },
    {
        "id": "07105",
        "name": "Siegsdorf-Hoell",
        "state": "Bayern",
        "lat": 47.8350,
        "lon": 12.6548,
        "elevation": 719,
        "distance_km": 38.6,
    },
    {
        "id": "02573",
        "name": "Waging am See-Schnoebling",
        "state": "Bayern",
        "lat": 47.9588,
        "lon": 12.7717,
        "elevation": 470,
        "distance_km": 47.4,
    },
    {
        "id": "00856",
        "name": "Chieming",
        "state": "Bayern",
        "lat": 47.8843,
        "lon": 12.5404,
        "elevation": 551,
        "distance_km": 48.2,
    },
]

SOIL_SENSOR_SITES = [
    {
        "name": "Koenigssee shoreline",
        "zone": "Lake edge",
        "lat": 47.592,
        "lon": 12.989,
        "elevation": 604,
        "seed": 1,
        "ph": 6.4,
        "carbon": 8.2,
    },
    {
        "name": "Wimbachtal forest",
        "zone": "Mixed mountain forest",
        "lat": 47.569,
        "lon": 12.914,
        "elevation": 900,
        "seed": 3,
        "ph": 5.8,
        "carbon": 11.5,
    },
    {
        "name": "Hintersee edge",
        "zone": "Wetland transition",
        "lat": 47.606,
        "lon": 12.849,
        "elevation": 790,
        "seed": 5,
        "ph": 6.1,
        "carbon": 9.8,
    },
    {
        "name": "Funtensee basin",
        "zone": "High alpine basin",
        "lat": 47.493,
        "lon": 12.940,
        "elevation": 1600,
        "seed": 8,
        "ph": 5.5,
        "carbon": 6.9,
    },
    {
        "name": "Watzmann slope",
        "zone": "Steep protection forest",
        "lat": 47.556,
        "lon": 12.923,
        "elevation": 1320,
        "seed": 11,
        "ph": 5.7,
        "carbon": 7.6,
    },
]

LAYER_META = [
    ("alphaearth", "Landscape patterns", "AlphaEarth embedding RGB for visual pattern discovery."),
    ("tree_cover", "Tree canopy", "Year-2000 tree canopy baseline."),
    ("tree_loss", "Tree-cover loss", "Cumulative forest loss to the selected year."),
    ("water", "Water and wetlands", "Recurring surface water and wetland context."),
    ("habitat", "Land-cover habitat", "ESA WorldCover classes for habitat context."),
    ("fire", "Burned area history", "MODIS burned-area signal for the selected year."),
    ("air_temperature", "Air temperature model", "ERA5-Land annual mean 2 m air temperature."),
    ("soil_moisture", "Soil moisture model", "ERA5-Land annual mean top-layer soil moisture."),
    ("weather_sensors", "DWD weather stations", "Official nearby DWD daily climate observations."),
    ("soil_sensors", "Soil probe prototype", "Prototype local soil probes for workflow design."),
]

VIEW_PRESETS = {
    "Stakeholder overview": {
        "copy": "Balanced forest, water, observation, and landscape evidence for a first walkthrough.",
        "layers": {
            "alphaearth": True,
            "tree_cover": False,
            "tree_loss": True,
            "water": True,
            "habitat": False,
            "fire": False,
            "air_temperature": False,
            "soil_moisture": False,
            "weather_sensors": True,
            "soil_sensors": True,
        },
    },
    "Forest change": {
        "copy": "Prioritizes canopy, tree-cover loss, and landscape pattern change.",
        "layers": {
            "alphaearth": True,
            "tree_cover": True,
            "tree_loss": True,
            "water": False,
            "habitat": False,
            "fire": False,
            "air_temperature": False,
            "soil_moisture": False,
            "weather_sensors": False,
            "soil_sensors": False,
        },
    },
    "Water and climate": {
        "copy": "Shows water, temperature, soil moisture, and local weather context together.",
        "layers": {
            "alphaearth": False,
            "tree_cover": False,
            "tree_loss": False,
            "water": True,
            "habitat": False,
            "fire": False,
            "air_temperature": True,
            "soil_moisture": True,
            "weather_sensors": True,
            "soil_sensors": True,
        },
    },
    "Habitat and risk": {
        "copy": "Combines habitat, water, fire history, and field-observation placeholders.",
        "layers": {
            "alphaearth": False,
            "tree_cover": True,
            "tree_loss": True,
            "water": True,
            "habitat": True,
            "fire": True,
            "air_temperature": False,
            "soil_moisture": False,
            "weather_sensors": True,
            "soil_sensors": True,
        },
    },
]

_COSTED_USAGE_MODES = {
    "billable",
    "commercial",
    "enterprise",
    "government_operational",
    "paid",
    "production_paid",
}


def inject_theme_css() -> None:
    """Apply the stakeholder-facing Whispering Woods visual system."""
    st.markdown(
        """
<style>
:root {
  --ww-bg: #07110c;
  --ww-ink: #f3f6ef;
  --ww-muted: #a7b9a7;
  --ww-soft: rgba(168, 215, 168, 0.1);
  --ww-line: rgba(168, 215, 168, 0.18);
  --ww-green: #a8d7a8;
  --ww-gold: #f1c75b;
  --ww-blue: #4ea8de;
  --ww-red: #d9624b;
}

[data-testid="stAppViewContainer"] { background: var(--ww-bg); color: var(--ww-ink); }
[data-testid="stHeader"] { background: rgba(7, 17, 12, 0.94); border-bottom: 1px solid var(--ww-line); }
[data-testid="stSidebar"] { background: #07110c; }
.block-container { max-width: 1780px; padding: 1.05rem 1.55rem 1.3rem; }

.ww-topbar {
  display: flex; align-items: center; justify-content: space-between; min-height: 48px;
  margin: -0.2rem 0 1.0rem; padding: 0.45rem 0.85rem; background: #07100b;
  border: 1px solid rgba(168, 215, 168, 0.16); border-radius: 8px;
}
.ww-brand { display: flex; align-items: center; gap: 0.6rem; color: var(--ww-ink); font-weight: 780; font-size: 1.02rem; }
.ww-mark { width: 26px; height: 26px; border-radius: 6px; display: grid; place-items: center; color: #07110c; background: var(--ww-green); font-weight: 900; }
.ww-nav { display: flex; align-items: center; gap: 0.45rem; color: var(--ww-muted); font-size: 0.9rem; font-weight: 690; }
.ww-nav span { padding: 0.36rem 0.64rem; border-radius: 6px; }
.ww-nav .active { color: #07110c; background: var(--ww-green); }

.ww-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; margin-bottom: 0.75rem; }
.ww-kicker, .ww-map-label, .ww-plan-label, .ww-section-label { color: var(--ww-muted); font-size: 0.76rem; font-weight: 740; }
.ww-title { margin: 0.05rem 0 0; color: var(--ww-ink); font-size: 2.1rem; line-height: 1.04; font-weight: 820; letter-spacing: 0; }
.ww-hero-copy { color: var(--ww-muted); margin-top: 0.35rem; font-size: 0.95rem; max-width: 780px; }
.ww-status-row { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.45rem; }
.ww-status { color: #dcead9; border: 1px solid rgba(168, 215, 168, 0.22); border-radius: 6px; background: rgba(168, 215, 168, 0.08); padding: 0.38rem 0.58rem; font-size: 0.82rem; font-weight: 720; }
.ww-status.gold { color: #fff1bb; border-color: rgba(241, 199, 91, 0.35); background: rgba(241, 199, 91, 0.1); }

.ww-map-head { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; margin: 0 0 0.48rem; }
.ww-map-title { color: var(--ww-ink); font-size: 1.04rem; font-weight: 780; }
.ww-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.42rem; }
.ww-pill { display: inline-flex; align-items: center; gap: 0.32rem; padding: 0.24rem 0.42rem; border: 1px solid rgba(168, 215, 168, 0.17); border-radius: 6px; background: rgba(168, 215, 168, 0.08); color: #dcead9; font-size: 0.76rem; font-weight: 720; }
.ww-dot { width: 8px; height: 8px; border-radius: 99px; display: inline-block; }

.ww-panel-title { color: #f0e4b8; font-size: 1.28rem; font-weight: 820; margin: 0 0 0.25rem; }
.ww-panel-copy { color: var(--ww-muted); font-size: 0.9rem; line-height: 1.42; margin: 0 0 0.8rem; }
.ww-control-band { border: 1px solid var(--ww-line); border-radius: 8px; padding: 0.75rem 0.85rem 0.45rem; margin-bottom: 0.75rem; background: rgba(16, 33, 24, 0.72); }
.ww-source-list { display: grid; gap: 0.5rem; margin-top: 0.85rem; }
.ww-source-item { color: rgba(243, 246, 239, 0.78); border-top: 1px solid rgba(168, 215, 168, 0.14); padding-top: 0.48rem; font-size: 0.82rem; line-height: 1.34; }
.ww-source-item strong { color: var(--ww-ink); }
.ww-plan-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.45rem; margin-top: 0.4rem; }
.ww-plan-chip { color: rgba(243, 246, 239, 0.88); background: rgba(168, 215, 168, 0.08); border: 1px dashed rgba(168, 215, 168, 0.2); border-radius: 6px; padding: 0.45rem 0.55rem; font-size: 0.8rem; font-weight: 680; }

.ww-kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.55rem; margin: 0.55rem 0 0.85rem; }
.ww-kpi { border: 1px solid rgba(168, 215, 168, 0.14); border-radius: 8px; padding: 0.64rem 0.74rem; background: rgba(16, 33, 24, 0.72); min-height: 72px; }
.ww-kpi span { color: var(--ww-muted); font-size: 0.75rem; font-weight: 720; display: block; }
.ww-kpi strong { color: var(--ww-ink); display: block; font-size: 0.94rem; margin-top: 0.22rem; line-height: 1.2; }

.ww-insight-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.6rem; margin-top: 0.55rem; }
.ww-insight { border: 1px solid rgba(168, 215, 168, 0.14); border-radius: 8px; padding: 0.72rem 0.82rem; background: rgba(16, 33, 24, 0.65); min-height: 112px; }
.ww-insight span { display: block; color: var(--ww-muted); font-size: 0.74rem; font-weight: 740; margin-bottom: 0.22rem; }
.ww-insight strong { display: block; color: var(--ww-ink); font-size: 0.95rem; margin-bottom: 0.32rem; }
.ww-insight p { color: rgba(243, 246, 239, 0.78); margin: 0; font-size: 0.86rem; line-height: 1.35; }
.ww-selected { border: 1px solid rgba(78, 168, 222, 0.35); border-radius: 8px; padding: 0.55rem 0.7rem; background: rgba(78, 168, 222, 0.1); color: #d9efff; margin: 0.55rem 0 0.75rem; font-size: 0.86rem; }

[data-testid="stIFrame"] { border: 1px solid rgba(168, 215, 168, 0.22); border-radius: 8px; overflow: hidden; box-shadow: 0 20px 54px rgba(0, 0, 0, 0.34); }
[data-testid="stCheckbox"] label, [data-testid="stSlider"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label, [data-testid="stRadio"] label { font-weight: 680; color: var(--ww-ink) !important; }
[data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] div { border-color: rgba(168, 215, 168, 0.22) !important; }
[data-testid="stAlert"] { border-radius: 8px; }

@media (max-width: 1120px) {
  .block-container { padding: 0.9rem 0.8rem 1.1rem; }
  .ww-topbar, .ww-hero, .ww-map-head { align-items: flex-start; flex-direction: column; }
  .ww-nav, .ww-status-row, .ww-legend { justify-content: flex-start; }
  .ww-title { font-size: 1.8rem; }
  .ww-kpi-grid, .ww-insight-grid { grid-template-columns: 1fr; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _read_secret(name: str) -> Optional[str]:
    """Read a string secret, returning None when it is missing or blank."""
    value = st.secrets.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalise_usage_mode(value: Optional[str]) -> str:
    """Normalize the optional Earth Engine usage mode secret."""
    if not value:
        return "noncommercial"
    return value.lower().replace(" ", "_").replace("-", "_")


def enforce_no_cost_guardrail() -> str:
    """Stop the app if secrets explicitly mark the Earth Engine project as paid."""
    usage_mode = _normalise_usage_mode(_read_secret("EE_USAGE_MODE"))
    if usage_mode in _COSTED_USAGE_MODES:
        st.error("No-cost guardrail active: this app is not configured for paid Earth Engine use.")
        st.caption(
            "Use an Earth Engine project registered for eligible non-commercial, research, "
            "conservation, or impact work. The app stopped before initializing Earth Engine."
        )
        st.stop()
    return usage_mode


def get_earth_engine_error_help(error_text: str) -> str:
    """Return a practical setup hint for common Earth Engine IAM errors."""
    if "earthengine.maps.create" in error_text:
        return (
            "The service account can reach Earth Engine, but live map rendering needs "
            "Earth Engine Resource Writer (`roles/earthengine.writer`) on this project."
        )
    if "earthengine.computations.create" in error_text:
        return (
            "The service account needs an Earth Engine project role. Add Earth Engine Resource "
            "Viewer or Earth Engine Resource Writer on this project."
        )
    return "This is usually a project permission, Earth Engine registration, API enablement, or data availability issue."


def show_earth_engine_error(message: str, exc: Exception) -> None:
    """Display Earth Engine failures without triggering Streamlit's redacted traceback."""
    error_text = str(exc)
    st.error(message)
    st.caption(get_earth_engine_error_help(error_text))
    st.code(error_text, language="text")
    st.stop()


def _build_service_account_key_data(
    service_account: str, private_key_secret: str, project_id: Optional[str]
) -> tuple[str, Optional[str]]:
    """Return JSON key data suitable for ee.ServiceAccountCredentials."""
    raw_secret = private_key_secret.strip()
    try:
        key_info = json.loads(raw_secret)
    except json.JSONDecodeError:
        private_key = raw_secret.replace("\\n", "\n")
        key_info = {
            "type": "service_account",
            "client_email": service_account,
            "private_key": private_key,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        if project_id:
            key_info["project_id"] = project_id
    else:
        if not isinstance(key_info, dict):
            raise ValueError("EE_PRIVATE_KEY must contain a JSON service-account key object.")
        key_info.setdefault("client_email", service_account)
        if isinstance(key_info.get("private_key"), str):
            key_info["private_key"] = key_info["private_key"].replace("\\n", "\n")
        if project_id:
            key_info.setdefault("project_id", project_id)

    key_email = key_info.get("client_email")
    if key_email and key_email != service_account:
        st.warning(
            "EE_SERVICE_ACCOUNT does not match the client_email in EE_PRIVATE_KEY. "
            "Use the service-account email from the JSON key."
        )

    project_id = project_id or key_info.get("project_id")
    return json.dumps(key_info), project_id


def init_ee() -> None:
    """Initialise Earth Engine using service-account credentials from Streamlit secrets."""
    service_account = _read_secret("EE_SERVICE_ACCOUNT")
    private_key_secret = _read_secret("EE_PRIVATE_KEY")
    project_id = _read_secret("EE_PROJECT_ID")

    if not service_account or not private_key_secret:
        st.error("Earth Engine credentials not found. Add EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY to Streamlit secrets.")
        st.stop()

    try:
        key_data, project_id = _build_service_account_key_data(service_account, private_key_secret, project_id)
        credentials = ee.ServiceAccountCredentials(service_account, key_data=key_data)
        if project_id:
            ee.Initialize(credentials, project=project_id)
        else:
            ee.Initialize(credentials)
    except Exception as exc:
        st.error("Failed to initialise Earth Engine with the configured service account.")
        st.caption("Confirm the Cloud project is registered for Earth Engine, the API is enabled, and the service-account JSON key matches EE_SERVICE_ACCOUNT.")
        st.caption(str(exc))
        st.stop()


@st.cache_resource(show_spinner=False)
def _init_ee_cached() -> None:
    """Wrapper for caching Earth Engine initialisation."""
    init_ee()


def get_fallback_berchtesgaden_aoi() -> ee.Geometry:
    """Fallback park-scale polygon if WDPA is temporarily unavailable."""
    return ee.Geometry.Polygon(
        [[
            [12.815, 47.600],
            [12.865, 47.635],
            [12.965, 47.625],
            [13.070, 47.610],
            [13.125, 47.565],
            [13.115, 47.500],
            [13.050, 47.458],
            [12.955, 47.455],
            [12.875, 47.482],
            [12.820, 47.535],
            [12.815, 47.600],
        ]]
    )


def get_default_aoi() -> tuple[ee.Geometry, str]:
    """Return Berchtesgaden National Park from WDPA, with a local fallback."""
    try:
        park = ee.FeatureCollection(WDPA_COLLECTION_ID).filter(
            ee.Filter.eq("WDPAID", BERCHTESGADEN_WDPA_ID)
        )
        if int(park.size().getInfo()) > 0:
            return park.geometry(), "Berchtesgaden National Park"
    except Exception:
        pass
    return get_fallback_berchtesgaden_aoi(), "Berchtesgaden National Park fallback boundary"


def get_aoi(geojson_str: str) -> tuple[ee.Geometry, str]:
    """Return a custom AOI geometry or the Berchtesgaden National Park boundary."""
    if geojson_str:
        try:
            geo = json.loads(geojson_str)
            geo_type = geo.get("type")
            if geo_type == "FeatureCollection":
                return ee.FeatureCollection(geo).geometry(), "Custom AOI"
            if geo_type == "Feature":
                return ee.Geometry(geo["geometry"]), "Custom AOI"
            return ee.Geometry(geo), "Custom AOI"
        except Exception:
            st.warning("Invalid GeoJSON provided. Falling back to Berchtesgaden National Park.")
    return get_default_aoi()


def get_aoi_view(aoi: ee.Geometry) -> tuple[list[float], list[list[float]]]:
    """Return center and Leaflet bounds for the selected AOI."""
    centroid = aoi.centroid().coordinates().getInfo()
    bounds_coords = aoi.bounds().coordinates().getInfo()[0]
    return [centroid[1], centroid[0]], [[lat, lon] for lon, lat in bounds_coords]


def get_alphaearth_image(year: int, aoi: ee.Geometry) -> tuple[ee.Image, int]:
    """Retrieve and mosaic AlphaEarth embedding tiles for the given year and AOI."""
    collection = (
        ee.ImageCollection(EMBEDDING_COLLECTION_ID)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .filterBounds(aoi)
    )
    tile_count = int(collection.size().getInfo())
    if tile_count == 0:
        raise ValueError(f"No AlphaEarth embedding tiles were found for {year} in this AOI.")
    return collection.mosaic().clip(aoi), tile_count


def get_hansen_image() -> ee.Image:
    """Return the current Hansen Global Forest Change image."""
    return ee.Image(HANSEN_COLLECTION_ID)


def get_tree_cover_layer(aoi: ee.Geometry) -> ee.Image:
    """Return year-2000 canopy cover from Hansen."""
    cover = get_hansen_image().select("treecover2000")
    return cover.updateMask(cover.gte(20)).clip(aoi)


def get_tree_loss_layer(year: int, aoi: ee.Geometry) -> ee.Image:
    """Return cumulative tree-cover loss up to the selected year."""
    if year <= 2000:
        return ee.Image(0).selfMask().clip(aoi)
    loss_year = get_hansen_image().select("lossyear")
    max_loss_year = min(year - 2000, 25)
    return loss_year.gt(0).And(loss_year.lte(max_loss_year)).selfMask().clip(aoi)


def get_surface_water_layer(aoi: ee.Geometry) -> ee.Image:
    """Return recurring surface water from JRC Global Surface Water."""
    occurrence = ee.Image(SURFACE_WATER_COLLECTION_ID).select("occurrence")
    return occurrence.updateMask(occurrence.gte(10)).clip(aoi)


def get_worldcover_layer(aoi: ee.Geometry) -> ee.Image:
    """Return ESA WorldCover land-cover classes."""
    return ee.ImageCollection(WORLDCOVER_COLLECTION_ID).first().select("Map").clip(aoi)


def get_burned_area_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    """Return MODIS burned-area observations for the selected year, if available."""
    collection = (
        ee.ImageCollection(BURNED_AREA_COLLECTION_ID)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .select("BurnDate")
    )
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.max().selfMask().clip(aoi)


def get_era5_collection(year: int) -> ee.ImageCollection:
    """Return ERA5-Land monthly data for the selected year."""
    return ee.ImageCollection(ERA5_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01")


def get_air_temperature_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    """Return mean 2 m air temperature in Celsius for the selected year."""
    collection = get_era5_collection(year)
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.select("temperature_2m").mean().subtract(273.15).clip(aoi)


def get_soil_moisture_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    """Return mean top-layer volumetric soil moisture for the selected year."""
    collection = get_era5_collection(year)
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.select("volumetric_soil_water_layer_1").mean().clip(aoi)


def dwd_float(row: dict[str, str], key: str) -> Optional[float]:
    """Parse DWD numeric values and convert missing flags to None."""
    raw_value = row.get(key, "").strip().replace(",", ".")
    if not raw_value:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    if value <= -998:
        return None
    return value


def format_number(value: Optional[float], suffix: str, decimals: int = 1) -> str:
    """Format nullable numeric values for popup tables."""
    if value is None:
        return "n/a"
    return f"{value:.{decimals}f}{suffix}"


def format_dwd_date(raw_date: str) -> str:
    """Format YYYYMMDD DWD dates for readable labels."""
    if len(raw_date) != 8:
        return raw_date or "n/a"
    return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_archive_url(station_id: str, archive_kind: str) -> str:
    """Return the DWD zip URL for a recent or historical daily climate archive."""
    if archive_kind == "recent":
        return f"{DWD_RECENT_BASE_URL}/tageswerte_KL_{station_id}_akt.zip"

    index_html = urllib.request.urlopen(f"{DWD_HISTORICAL_BASE_URL}/", timeout=12).read().decode(
        "utf-8", errors="ignore"
    )
    pattern = rf"tageswerte_KL_{re.escape(station_id)}_.*?_hist\.zip"
    matches = sorted(set(re.findall(pattern, index_html)))
    if not matches:
        raise ValueError(f"No DWD historical climate archive found for station {station_id}.")
    return f"{DWD_HISTORICAL_BASE_URL}/{matches[-1]}"


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_dwd_rows(station_id: str, archive_kind: str) -> list[dict[str, str]]:
    """Download and parse DWD daily climate rows for one station archive."""
    archive_url = get_dwd_archive_url(station_id, archive_kind)
    with urllib.request.urlopen(archive_url, timeout=18) as response:
        archive_data = response.read()

    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        product_names = [
            name
            for name in archive.namelist()
            if "produkt_klima_tag" in name and name.endswith(".txt")
        ]
        if not product_names:
            raise ValueError(f"No DWD product file found in station archive {station_id}.")
        with archive.open(product_names[0]) as product_file:
            text = product_file.read().decode("latin1")

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = []
    for row in reader:
        clean_row = {
            key.strip(): value.strip()
            for key, value in row.items()
            if key is not None and value is not None
        }
        if clean_row.get("MESS_DATUM"):
            rows.append(clean_row)
    return rows


def get_dwd_daily_reading(station: dict, year: int) -> Optional[dict]:
    """Return the latest available daily DWD reading for the selected year."""
    archive_order = ["recent", "historical"] if year >= 2025 else ["historical", "recent"]
    for archive_kind in archive_order:
        try:
            rows = fetch_dwd_rows(station["id"], archive_kind)
        except Exception:
            continue
        candidates = [
            row
            for row in rows
            if row.get("MESS_DATUM", "").startswith(str(year)) and dwd_float(row, "TMK") is not None
        ]
        if not candidates:
            continue
        row = candidates[-1]
        return {
            "station_id": station["id"],
            "name": station["name"],
            "state": station["state"],
            "lat": station["lat"],
            "lon": station["lon"],
            "elevation": station["elevation"],
            "distance_km": station["distance_km"],
            "date": format_dwd_date(row.get("MESS_DATUM", "")),
            "archive_kind": archive_kind,
            "mean_temp": dwd_float(row, "TMK"),
            "max_temp": dwd_float(row, "TXK"),
            "min_temp": dwd_float(row, "TNK"),
            "humidity": dwd_float(row, "UPM"),
            "wind": dwd_float(row, "FM"),
            "gust": dwd_float(row, "FX"),
            "precipitation": dwd_float(row, "RSK"),
            "sunshine": dwd_float(row, "SDK"),
        }
    return None


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_readings_for_year(year: int) -> tuple[list[dict], int]:
    """Return available DWD station readings and unavailable count for the selected year."""
    readings = []
    unavailable = 0
    for station in DWD_STATIONS:
        reading = get_dwd_daily_reading(station, year)
        if reading:
            readings.append(reading)
        else:
            unavailable += 1
    return readings, unavailable


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_annual_series(station_id: str, start_year: int = 2000, end_year: int = 2026) -> list[dict]:
    """Return annual DWD temperature and precipitation summary rows for one station."""
    rows_by_date = {}
    for archive_kind in ["historical", "recent"]:
        try:
            rows = fetch_dwd_rows(station_id, archive_kind)
        except Exception:
            continue
        for row in rows:
            date = row.get("MESS_DATUM", "")
            if len(date) == 8:
                rows_by_date[date] = row

    buckets: dict[int, dict[str, list[float]]] = {}
    for date, row in rows_by_date.items():
        try:
            year = int(date[:4])
        except ValueError:
            continue
        if year < start_year or year > end_year:
            continue
        bucket = buckets.setdefault(year, {"temp": [], "precip": [], "humidity": []})
        temp = dwd_float(row, "TMK")
        precip = dwd_float(row, "RSK")
        humidity = dwd_float(row, "UPM")
        if temp is not None:
            bucket["temp"].append(temp)
        if precip is not None:
            bucket["precip"].append(precip)
        if humidity is not None:
            bucket["humidity"].append(humidity)

    series = []
    for year in sorted(buckets):
        bucket = buckets[year]
        if not bucket["temp"]:
            continue
        series.append(
            {
                "Year": year,
                "Mean temp C": round(sum(bucket["temp"]) / len(bucket["temp"]), 1),
                "Precip mm": round(sum(bucket["precip"]), 1) if bucket["precip"] else None,
                "Mean humidity %": round(sum(bucket["humidity"]) / len(bucket["humidity"]), 0)
                if bucket["humidity"]
                else None,
                "Days": len(bucket["temp"]),
            }
        )
    return series


def estimate_soil_reading(site: dict, year: int) -> dict[str, float]:
    """Generate deterministic prototype soil probe values for the selected year."""
    phase = year - 2000
    seasonal = math.sin((phase + site["seed"]) / 3.2)
    elevation_km = site["elevation"] / 1000
    soil_temp = 7.8 + phase * 0.035 - elevation_km * 3.8 + seasonal * 0.55
    soil_moisture = 34 + elevation_km * 4.5 + seasonal * 4.0 + (site["seed"] % 4) * 1.2
    return {
        "soil_temp": round(soil_temp, 1),
        "soil_moisture": round(max(8, min(70, soil_moisture)), 1),
        "ph": round(site["ph"] + seasonal * 0.06, 2),
        "carbon": round(site["carbon"] + seasonal * 0.25, 1),
    }


def add_dwd_weather_markers(m: folium.Map, year: int, layers: dict[str, bool]) -> list[str]:
    """Add real DWD daily climate station markers for the selected year."""
    if not layers["weather_sensors"]:
        return []

    notes = []
    try:
        readings, unavailable = get_dwd_readings_for_year(year)
    except Exception as exc:
        return [f"DWD weather station data could not be loaded: {exc}"]

    if not readings:
        return [f"No DWD daily weather station records were available for the selected year {year}."]
    if unavailable:
        notes.append(f"DWD has no selected-year daily records for {unavailable} nearby station(s).")

    group = folium.FeatureGroup(name="DWD daily weather stations", show=True)
    for reading in readings:
        source_label = "recent daily feed" if reading["archive_kind"] == "recent" else "historical daily archive"
        popup_html = f"""
        <div style='font-family: sans-serif; min-width: 260px;'>
          <strong>{reading['name']}</strong><br>
          <span>DWD station {reading['station_id']} | {reading['elevation']} m | {reading['distance_km']} km from park center</span><br>
          <span>{reading['date']} | {source_label}</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Mean temp</td><td>{format_number(reading['mean_temp'], ' C')}</td></tr>
            <tr><td>Min / max temp</td><td>{format_number(reading['min_temp'], ' C')} / {format_number(reading['max_temp'], ' C')}</td></tr>
            <tr><td>Precipitation</td><td>{format_number(reading['precipitation'], ' mm')}</td></tr>
            <tr><td>Humidity</td><td>{format_number(reading['humidity'], '%', 0)}</td></tr>
            <tr><td>Mean wind</td><td>{format_number(reading['wind'], ' m/s')}</td></tr>
            <tr><td>Max gust</td><td>{format_number(reading['gust'], ' m/s')}</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(
            location=[reading["lat"], reading["lon"]],
            radius=7,
            color="#07110c",
            weight=2,
            fill=True,
            fill_color="#4ea8de",
            fill_opacity=0.94,
            tooltip=f"DWD weather: {reading['name']}",
            popup=folium.Popup(popup_html, max_width=340),
        ).add_to(group)
    group.add_to(m)
    return notes


def add_soil_sensor_markers(m: folium.Map, year: int, layers: dict[str, bool]) -> None:
    """Add clearly labelled prototype soil probe readings as map markers."""
    if not layers["soil_sensors"]:
        return

    group = folium.FeatureGroup(name="Prototype soil probes", show=True)
    for site in SOIL_SENSOR_SITES:
        reading = estimate_soil_reading(site, year)
        popup_html = f"""
        <div style='font-family: sans-serif; min-width: 230px;'>
          <strong>{site['name']}</strong><br>
          <span>{site['zone']} | {site['elevation']} m | prototype soil probe</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Soil moisture</td><td>{reading['soil_moisture']}%</td></tr>
            <tr><td>Soil temp</td><td>{reading['soil_temp']} C</td></tr>
            <tr><td>pH / SOC</td><td>{reading['ph']} / {reading['carbon']}%</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(
            location=[site["lat"], site["lon"]],
            radius=7,
            color="#07110c",
            weight=2,
            fill=True,
            fill_color="#f1c75b",
            fill_opacity=0.94,
            tooltip=f"Prototype soil probe: {site['name']}",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(group)
    group.add_to(m)


def add_ee_layer(m: folium.Map, image: ee.Image, vis_params: dict, name: str, opacity: float = 0.85) -> None:
    """Add an Earth Engine image as a Folium tile layer."""
    map_id = image.getMapId(vis_params)
    folium.TileLayer(
        tiles=map_id["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name=name,
        overlay=True,
        control=True,
        opacity=opacity,
    ).add_to(m)


def add_aoi_boundary(m: folium.Map, aoi: ee.Geometry, area_name: str, color: str = AOI_COLOR) -> None:
    """Add AOI boundary to a Folium map as a non-filled outline."""
    folium.GeoJson(
        aoi.getInfo(),
        name=area_name,
        style_function=lambda _: {
            "color": color,
            "weight": 2.7,
            "fillOpacity": 0,
            "opacity": 0.98,
        },
    ).add_to(m)


def build_map(center: list[float], bounds: list[list[float]], basemap: str) -> folium.Map:
    """Create the map surface and focus it on the AOI."""
    m = folium.Map(location=center, zoom_start=12, tiles=None, control_scale=True)
    if basemap == "Satellite":
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
            name="Satellite",
            control=False,
        ).add_to(m)
    elif basemap == "Terrain":
        folium.TileLayer("OpenTopoMap", name="Terrain", control=False).add_to(m)
    else:
        folium.TileLayer("CartoDB positron", name="Light map", control=False).add_to(m)
    m.fit_bounds(bounds, padding=(24, 24))
    return m


def render_topbar() -> None:
    """Render app navigation."""
    st.markdown(
        """
<div class="ww-topbar">
  <div class="ww-brand"><div class="ww-mark">W</div><span>Whispering Woods</span></div>
  <div class="ww-nav"><span class="active">Forest Map</span><span>Species Monitoring</span><span>3D View</span></div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_header(usage_mode: str, year: int, enabled_count: int, area_name: str, view_mode: str) -> None:
    """Render the top application heading."""
    lens_copy = VIEW_PRESETS[view_mode]["copy"]
    st.markdown(
        f"""
<div class="ww-hero">
  <div>
    <div class="ww-kicker">Stakeholder view | {area_name}</div>
    <div class="ww-title">Forest Intelligence Map</div>
    <div class="ww-hero-copy">{lens_copy}</div>
  </div>
  <div class="ww-status-row">
    <div class="ww-status">Earth Engine live</div>
    <div class="ww-status gold">{usage_mode}</div>
    <div class="ww-status">{year}</div>
    <div class="ww-status">{enabled_count} layers</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def apply_view_preset(view_mode: str) -> None:
    """Reset layer checkbox state when the exploration lens changes."""
    if st.session_state.get("active_view_preset") == view_mode:
        return
    st.session_state["active_view_preset"] = view_mode
    preset_layers = VIEW_PRESETS[view_mode]["layers"]
    for layer_id, _, _ in LAYER_META:
        st.session_state[f"layer_{layer_id}"] = preset_layers.get(layer_id, False)


def render_layer_panel() -> tuple[int, str, str, dict[str, bool], str]:
    """Render stakeholder controls and return selections."""
    st.markdown("<div class='ww-panel-title'>Explore</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='ww-panel-copy'>Pick a lens, then refine the active evidence layers.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='ww-control-band'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-section-label'>LENS</div>", unsafe_allow_html=True)
    view_mode = st.selectbox("Exploration lens", list(VIEW_PRESETS.keys()), index=0)
    apply_view_preset(view_mode)
    st.caption(VIEW_PRESETS[view_mode]["copy"])
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-section-label'>TIME AND MAP</div>", unsafe_allow_html=True)
    year = st.slider("Analysis year", min_value=2000, max_value=2026, value=2024)
    basemap = st.selectbox("Map style", ["Satellite", "Light", "Terrain"], index=0)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-section-label'>VISIBLE EVIDENCE</div>", unsafe_allow_html=True)
    layers = {}
    for layer_id, label, help_text in LAYER_META:
        layers[layer_id] = st.checkbox(label, key=f"layer_{layer_id}", help=help_text)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Custom AOI", expanded=False):
        geojson_input: str = st.text_area(
            "GeoJSON polygon",
            "",
            height=124,
            help="Leave blank to use Berchtesgaden National Park.",
        )
    return year, basemap, geojson_input, layers, view_mode


def render_sources_panel() -> None:
    """Render concise source notes for stakeholder transparency."""
    st.markdown(
        """
<div class="ww-source-list">
  <div class="ww-source-item"><strong>Protected area boundary</strong><br>WDPA boundary for Berchtesgaden National Park, with local fallback.</div>
  <div class="ww-source-item"><strong>Earth observation layers</strong><br>AlphaEarth, Hansen forest change, JRC water, ESA WorldCover, MODIS burned area.</div>
  <div class="ww-source-item"><strong>Climate and soil context</strong><br>ERA5-Land monthly model fields for air temperature and top-layer soil moisture.</div>
  <div class="ww-source-item"><strong>Local observations</strong><br>DWD daily climate station records plus clearly labelled prototype soil probes.</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_planned_layers() -> None:
    """Show planned data categories without pretending they are active data."""
    st.markdown(
        """
<div class="ww-plan-label">Planned integrations</div>
<div class="ww-plan-grid">
  <div class="ww-plan-chip">Inventory trees</div>
  <div class="ww-plan-chip">Species observations</div>
  <div class="ww-plan-chip">Trail impact reports</div>
  <div class="ww-plan-chip">Ranger field notes</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_observation_summary(year: int, view_mode: str, layers: dict[str, bool]) -> None:
    """Show compact real DWD and prototype soil summaries."""
    try:
        dwd_readings, unavailable = get_dwd_readings_for_year(year)
    except Exception:
        dwd_readings = []
        unavailable = len(DWD_STATIONS)

    soil_readings = [estimate_soil_reading(site, year) for site in SOIL_SENSOR_SITES]
    avg_soil = round(sum(r["soil_moisture"] for r in soil_readings) / len(soil_readings), 1)
    avg_ph = round(sum(r["ph"] for r in soil_readings) / len(soil_readings), 2)
    active_labels = [label for layer_id, label, _ in LAYER_META if layers.get(layer_id)]

    if dwd_readings:
        nearest = dwd_readings[0]
        weather_label = f"{format_number(nearest['mean_temp'], ' C')} at {nearest['name']}"
        station_label = f"{len(dwd_readings)} station(s), {unavailable} gap(s)"
    else:
        weather_label = f"No DWD station record for {year}"
        station_label = "Station layer waiting for records"

    st.markdown(
        f"""
<div class="ww-kpi-grid">
  <div class="ww-kpi"><span>Exploration lens</span><strong>{view_mode}</strong></div>
  <div class="ww-kpi"><span>Real DWD weather</span><strong>{weather_label}</strong></div>
  <div class="ww-kpi"><span>Station coverage</span><strong>{station_label}</strong></div>
  <div class="ww-kpi"><span>Prototype soil</span><strong>{avg_soil}% moisture | pH {avg_ph}</strong></div>
</div>
        """,
        unsafe_allow_html=True,
    )
    if active_labels:
        st.caption("Active evidence: " + ", ".join(active_labels))


def render_map_heading(year: int, enabled_labels: list[tuple[str, str]], area_name: str) -> None:
    """Render the map section heading and active layer legend."""
    legend_markup = "".join(
        f"<span class='ww-pill'><span class='ww-dot' style='background:{color}'></span>{label}</span>"
        for label, color in enabled_labels
    )
    st.markdown(
        f"""
<div class="ww-map-head">
  <div>
    <div class="ww-map-label">{area_name}</div>
    <div class="ww-map-title">Forest evidence layers, {year}</div>
  </div>
  <div class="ww-legend">{legend_markup}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def get_enabled_labels(layers: dict[str, bool]) -> list[tuple[str, str]]:
    """Return labels for the visible map legend."""
    labels = []
    if layers["alphaearth"]:
        labels.append(("Landscape", "#55d68a"))
    if layers["tree_cover"]:
        labels.append(("Tree canopy", "#2c8c4a"))
    if layers["tree_loss"]:
        labels.append(("Forest loss", "#d9624b"))
    if layers["water"]:
        labels.append(("Water", "#4ea8de"))
    if layers["habitat"]:
        labels.append(("Habitat", "#b8d86b"))
    if layers["fire"]:
        labels.append(("Burned area", "#ff9f1c"))
    if layers["air_temperature"]:
        labels.append(("Air temp", "#ff6b4a"))
    if layers["soil_moisture"]:
        labels.append(("Soil moisture", "#45b7d1"))
    if layers["weather_sensors"]:
        labels.append(("DWD weather", "#4ea8de"))
    if layers["soil_sensors"]:
        labels.append(("Soil probes", "#f1c75b"))
    return labels or [("Park boundary", AOI_COLOR)]


def add_selected_layers(m: folium.Map, year: int, aoi: ee.Geometry, layers: dict[str, bool]) -> tuple[int, list[str]]:
    """Add selected Earth Engine, DWD, and prototype soil layers."""
    alphaearth_tile_count = 0
    notes = []

    if layers["alphaearth"]:
        if year in ALPHAEARTH_YEARS:
            alphaearth, alphaearth_tile_count = get_alphaearth_image(year, aoi)
            add_ee_layer(
                m,
                alphaearth,
                {"bands": DEFAULT_RGB_BANDS, "min": -0.3, "max": 0.3},
                "Landscape patterns",
                opacity=0.78,
            )
        else:
            notes.append("AlphaEarth is available for 2017-2024, so it is hidden for this year.")

    if layers["tree_cover"]:
        add_ee_layer(
            m,
            get_tree_cover_layer(aoi),
            {"min": 20, "max": 95, "palette": ["#d5e8bd", "#2c8c4a", "#0e4f2e"]},
            "Tree canopy",
            opacity=0.5,
        )
    if layers["tree_loss"]:
        if year > 2025:
            notes.append("Tree-cover loss uses Hansen data through 2025 for 2026 views.")
        add_ee_layer(
            m,
            get_tree_loss_layer(year, aoi),
            {"min": 1, "max": 1, "palette": ["#d9624b"]},
            "Tree-cover loss",
            opacity=0.88,
        )
    if layers["water"]:
        add_ee_layer(
            m,
            get_surface_water_layer(aoi),
            {"min": 10, "max": 100, "palette": ["#bde7ff", "#4ea8de", "#075985"]},
            "Water and wetlands",
            opacity=0.72,
        )
    if layers["habitat"]:
        add_ee_layer(
            m,
            get_worldcover_layer(aoi),
            {
                "min": 10,
                "max": 100,
                "palette": [
                    "#006400",
                    "#ffbb22",
                    "#ffff4c",
                    "#f096ff",
                    "#fa0000",
                    "#b4b4b4",
                    "#f0f0f0",
                    "#0064c8",
                    "#0096a0",
                    "#00cf75",
                    "#fae6a0",
                ],
            },
            "Land-cover habitat",
            opacity=0.42,
        )
    if layers["fire"]:
        burned_area = get_burned_area_layer(year, aoi)
        if burned_area is None:
            notes.append("Burned-area history is not available for the selected year yet.")
        else:
            add_ee_layer(
                m,
                burned_area,
                {"min": 1, "max": 366, "palette": ["#ffdd8a", "#ff9f1c", "#bd1f36"]},
                "Burned area history",
                opacity=0.86,
            )
    if layers["air_temperature"]:
        air_temperature = get_air_temperature_layer(year, aoi)
        if air_temperature is None:
            notes.append("ERA5-Land air temperature is not available for the selected year yet.")
        else:
            add_ee_layer(
                m,
                air_temperature,
                {"min": -5, "max": 14, "palette": ["#244cbd", "#e8f5ff", "#ffb14e", "#bd1f36"]},
                "Air temperature model",
                opacity=0.48,
            )
    if layers["soil_moisture"]:
        soil_moisture = get_soil_moisture_layer(year, aoi)
        if soil_moisture is None:
            notes.append("ERA5-Land soil moisture is not available for the selected year yet.")
        else:
            add_ee_layer(
                m,
                soil_moisture,
                {"min": 0.18, "max": 0.55, "palette": ["#8c510a", "#f6e8c3", "#80cdc1", "#01665e"]},
                "Soil moisture model",
                opacity=0.56,
            )

    notes.extend(add_dwd_weather_markers(m, year, layers))
    add_soil_sensor_markers(m, year, layers)
    return alphaearth_tile_count, notes


def build_weather_table(year: int) -> pd.DataFrame:
    """Build a station table for the selected analysis year."""
    readings, _ = get_dwd_readings_for_year(year)
    rows = []
    for reading in readings:
        rows.append(
            {
                "Station": reading["name"],
                "Date": reading["date"],
                "Distance km": reading["distance_km"],
                "Elevation m": reading["elevation"],
                "Mean temp C": reading["mean_temp"],
                "Precip mm": reading["precipitation"],
                "Humidity %": reading["humidity"],
                "Wind m/s": reading["wind"],
            }
        )
    return pd.DataFrame(rows)


def build_insight_items(view_mode: str, year: int, layers: dict[str, bool], notes: list[str]) -> list[tuple[str, str, str]]:
    """Create compact stakeholder insight cards from the current selections."""
    items = [
        (
            "Lens",
            view_mode,
            VIEW_PRESETS[view_mode]["copy"],
        )
    ]
    if layers.get("alphaearth"):
        if year in ALPHAEARTH_YEARS:
            items.append(("Landscape", "AlphaEarth active", "Embedding colors help reveal spatial pattern differences inside the park."))
        else:
            items.append(("Landscape", "AlphaEarth hidden", "AlphaEarth annual embeddings currently cover 2017-2024."))
    if layers.get("tree_loss"):
        items.append(("Forest change", "Cumulative loss", "The red layer marks Hansen tree-cover loss up to the selected year."))
    if layers.get("water") or layers.get("soil_moisture"):
        items.append(("Hydrology", "Water context", "Water and soil moisture layers help explain wetland edges and stress signals."))
    if layers.get("weather_sensors"):
        items.append(("Observations", "DWD stations", "Blue markers use official DWD daily climate records where records exist for the selected year."))
    for note in notes[:2]:
        items.append(("Data note", "Coverage", note))
    return items[:6]


def render_map_selection(map_state: Optional[dict]) -> None:
    """Show simple feedback for the latest clicked map object."""
    if not isinstance(map_state, dict):
        return
    clicked = map_state.get("last_object_clicked_tooltip") or map_state.get("last_object_clicked_popup")
    if clicked:
        st.markdown(
            f"<div class='ww-selected'><strong>Selected on map:</strong> {clicked}</div>",
            unsafe_allow_html=True,
        )


def render_evidence_board(year: int, view_mode: str, layers: dict[str, bool], notes: list[str]) -> None:
    """Render interactive evidence panels below the map."""
    insights_tab, weather_tab, station_tab, sources_tab = st.tabs(
        ["Insights", "Weather trend", "Station table", "Sources"]
    )

    with insights_tab:
        items = build_insight_items(view_mode, year, layers, notes)
        markup = "".join(
            f"""
<div class="ww-insight">
  <span>{eyebrow}</span>
  <strong>{title}</strong>
  <p>{body}</p>
</div>
            """
            for eyebrow, title, body in items
        )
        st.markdown(f"<div class='ww-insight-grid'>{markup}</div>", unsafe_allow_html=True)

    with weather_tab:
        default_index = next((idx for idx, station in enumerate(DWD_STATIONS) if station["id"] == "00856"), 0)
        station = st.selectbox(
            "Weather trend station",
            DWD_STATIONS,
            index=default_index,
            format_func=lambda item: f"{item['name']} ({item['distance_km']} km)",
        )
        series = get_dwd_annual_series(station["id"])
        if not series:
            st.info("No annual DWD trend records are available for this station in the 2000-2026 window.")
        else:
            df = pd.DataFrame(series)
            selected = df[df["Year"] == year]
            if selected.empty:
                st.caption(f"No annual summary is available for {station['name']} in {year}.")
            else:
                row = selected.iloc[0]
                st.caption(
                    f"{station['name']} in {year}: {row['Mean temp C']} C mean temp, "
                    f"{row['Precip mm']} mm precipitation, {int(row['Days'])} observed day(s)."
                )
            temp_col, precip_col = st.columns(2)
            chart_df = df.set_index("Year")
            with temp_col:
                st.line_chart(chart_df[["Mean temp C"]], height=240)
            with precip_col:
                st.bar_chart(chart_df[["Precip mm"]], height=240)

    with station_tab:
        weather_df = build_weather_table(year)
        if weather_df.empty:
            st.info(f"No configured DWD station has a daily climate record for {year}.")
        else:
            st.dataframe(weather_df, use_container_width=True, hide_index=True)

    with sources_tab:
        render_sources_panel()
        render_planned_layers()


def main() -> None:
    """Render the Streamlit user interface and map."""
    st.set_page_config(
        page_title="Whispering Woods Forest Map",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme_css()

    usage_mode = enforce_no_cost_guardrail()
    _init_ee_cached()

    render_topbar()
    left, right = st.columns([3.35, 1.0], gap="large")

    with right:
        year, basemap, geojson_input, layers, view_mode = render_layer_panel()
        render_sources_panel()
        render_planned_layers()

    enabled_count = sum(1 for enabled in layers.values() if enabled)
    aoi, area_name = get_aoi(geojson_input)

    with left:
        render_header(usage_mode, year, enabled_count, area_name, view_mode)
        render_observation_summary(year, view_mode, layers)

        try:
            center, bounds = get_aoi_view(aoi)
            m = build_map(center, bounds, basemap)
            alphaearth_tile_count, notes = add_selected_layers(m, year, aoi, layers)
            add_aoi_boundary(m, aoi, area_name)
        except Exception as exc:
            show_earth_engine_error("Earth Engine could not render the selected forest layers.", exc)

        folium.LayerControl(position="topright", collapsed=True).add_to(m)
        render_map_heading(year, get_enabled_labels(layers), area_name)
        map_state = st_folium(m, width=None, height=760)
        render_map_selection(map_state)

        captions = [
            "Visible map layers are public Earth Engine datasets, DWD daily climate observations, "
            "and clearly labelled prototype soil probes."
        ]
        if layers["alphaearth"] and alphaearth_tile_count:
            captions.append(f"AlphaEarth is scoped to {alphaearth_tile_count} tile(s) for the selected AOI.")
        captions.extend(notes)
        st.caption(" ".join(captions))
        render_evidence_board(year, view_mode, layers, notes)


if __name__ == "__main__":
    main()