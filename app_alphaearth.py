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
import pydeck as pdk
import streamlit as st

try:
    import ee  # type: ignore
except ImportError as exc:
    raise RuntimeError("The earthengine-api must be installed to run this app.") from exc

try:
    from streamlit_folium import st_folium  # type: ignore
except ImportError as exc:
    raise RuntimeError("The streamlit-folium package must be installed to run this app.") from exc


EMBEDDING_COLLECTION_ID = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
HANSEN_COLLECTION_ID = "UMD/hansen/global_forest_change_2025_v1_13"
SURFACE_WATER_COLLECTION_ID = "JRC/GSW1_4/GlobalSurfaceWater"
WORLDCOVER_COLLECTION_ID = "ESA/WorldCover/v200"
BURNED_AREA_COLLECTION_ID = "MODIS/061/MCD64A1"
ERA5_COLLECTION_ID = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
WDPA_COLLECTION_ID = "WCMC/WDPA/current/polygons"
DEM_IMAGE_ID = "USGS/SRTMGL1_003"
BERCHTESGADEN_WDPA_ID = 668

DWD_RECENT_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent"
DWD_HISTORICAL_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical"

DEFAULT_RGB_BANDS = ["A01", "A16", "A09"]
AOI_COLOR = "#F0B84A"
ALPHAEARTH_YEARS = set(range(2017, 2025))
PREDICTION_STATION_ID = "00856"
COSTED_USAGE_MODES = {"billable", "commercial", "enterprise", "government_operational", "paid", "production_paid"}

SCENARIO_SETTINGS = {
    "Conservative": {"warming_per_year": 0.025, "drying_per_year": 0.15},
    "Moderate": {"warming_per_year": 0.045, "drying_per_year": 0.35},
    "Hot dry": {"warming_per_year": 0.075, "drying_per_year": 0.65},
}

DWD_STATIONS = [
    {"id": "19856", "name": "Schoenau am Koenigssee", "state": "Bayern", "lat": 47.6134, "lon": 12.9819, "elevation": 625, "distance_km": 7.4},
    {"id": "07424", "name": "Piding", "state": "Bayern", "lat": 47.7724, "lon": 12.9073, "elevation": 457, "distance_km": 24.9},
    {"id": "07105", "name": "Siegsdorf-Hoell", "state": "Bayern", "lat": 47.8350, "lon": 12.6548, "elevation": 719, "distance_km": 38.6},
    {"id": "02573", "name": "Waging am See-Schnoebling", "state": "Bayern", "lat": 47.9588, "lon": 12.7717, "elevation": 470, "distance_km": 47.4},
    {"id": "00856", "name": "Chieming", "state": "Bayern", "lat": 47.8843, "lon": 12.5404, "elevation": 551, "distance_km": 48.2},
]

SOIL_SENSOR_SITES = [
    {"name": "Koenigssee shoreline", "zone": "Lake edge", "lat": 47.592, "lon": 12.989, "elevation": 604, "seed": 1, "ph": 6.4, "carbon": 8.2},
    {"name": "Wimbachtal forest", "zone": "Mixed mountain forest", "lat": 47.569, "lon": 12.914, "elevation": 900, "seed": 3, "ph": 5.8, "carbon": 11.5},
    {"name": "Hintersee edge", "zone": "Wetland transition", "lat": 47.606, "lon": 12.849, "elevation": 790, "seed": 5, "ph": 6.1, "carbon": 9.8},
    {"name": "Funtensee basin", "zone": "High alpine basin", "lat": 47.493, "lon": 12.940, "elevation": 1600, "seed": 8, "ph": 5.5, "carbon": 6.9},
    {"name": "Watzmann slope", "zone": "Steep protection forest", "lat": 47.556, "lon": 12.923, "elevation": 1320, "seed": 11, "ph": 5.7, "carbon": 7.6},
]

LAYER_META = [
    ("alphaearth", "Landscape patterns", "AlphaEarth embedding RGB for visual pattern discovery."),
    ("prediction", "Predicted forest stress", "Explainable forest vulnerability score for the selected projection."),
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
        "copy": "A balanced first walkthrough: forest change, water, local observations, and landscape patterns.",
        "layers": {"alphaearth": True, "prediction": False, "tree_cover": False, "tree_loss": True, "water": True, "habitat": False, "fire": False, "air_temperature": False, "soil_moisture": False, "weather_sensors": True, "soil_sensors": True},
    },
    "Forest change": {
        "copy": "Canopy, tree-cover loss, and AlphaEarth landscape patterns for year-to-year discussion.",
        "layers": {"alphaearth": True, "prediction": False, "tree_cover": True, "tree_loss": True, "water": False, "habitat": False, "fire": False, "air_temperature": False, "soil_moisture": False, "weather_sensors": False, "soil_sensors": False},
    },
    "Water and climate": {
        "copy": "Water, air temperature, soil moisture, and nearby DWD weather station context.",
        "layers": {"alphaearth": False, "prediction": False, "tree_cover": False, "tree_loss": False, "water": True, "habitat": False, "fire": False, "air_temperature": True, "soil_moisture": True, "weather_sensors": True, "soil_sensors": True},
    },
    "Habitat and risk": {
        "copy": "Habitat, fire history, tree loss, field placeholders, and the prototype stress score.",
        "layers": {"alphaearth": False, "prediction": True, "tree_cover": True, "tree_loss": True, "water": True, "habitat": True, "fire": True, "air_temperature": False, "soil_moisture": False, "weather_sensors": True, "soil_sensors": True},
    },
}


def inject_theme_css() -> None:
    st.markdown(
        """
<style>
:root {
  --ww-bg: #f6f5ef;
  --ww-surface: rgba(255,255,255,.82);
  --ww-surface-strong: rgba(255,255,255,.94);
  --ww-ink: #16251c;
  --ww-muted: #65756a;
  --ww-soft: #e7eadf;
  --ww-line: rgba(26, 46, 35, .12);
  --ww-green: #2f7d4f;
  --ww-mint: #d9f0df;
  --ww-gold: #f0b84a;
  --ww-blue: #3478a9;
  --ww-coral: #cf624e;
}
[data-testid="stAppViewContainer"] {
  color: var(--ww-ink);
  background:
    radial-gradient(circle at 18% 8%, rgba(217,240,223,.72), transparent 32%),
    linear-gradient(180deg, #fbfaf6 0%, #f3f1e8 48%, #eef3ed 100%);
}
[data-testid="stHeader"] {
  background: rgba(251,250,246,.78);
  border-bottom: 1px solid rgba(26,46,35,.08);
  backdrop-filter: blur(18px);
}
.block-container { max-width: 1840px; padding: 1.05rem 1.5rem 1.4rem; }
[data-testid="column"] { min-width: 0; }
.ww-shell { border:1px solid var(--ww-line); border-radius:8px; background:var(--ww-surface); box-shadow:0 24px 80px rgba(35,53,42,.10); backdrop-filter: blur(16px); }
.ww-topbar { display:flex; align-items:center; justify-content:space-between; min-height:58px; margin:.05rem 0 1rem; padding:.52rem .68rem .52rem .82rem; border:1px solid var(--ww-line); border-radius:8px; background:rgba(255,255,255,.74); box-shadow:0 14px 48px rgba(44,73,55,.08); backdrop-filter: blur(20px); }
.ww-brand { display:flex; align-items:center; gap:.68rem; color:var(--ww-ink); font-weight:780; font-size:1rem; }
.ww-mark { width:32px; height:32px; border-radius:8px; display:grid; place-items:center; color:#ffffff; background:linear-gradient(145deg,#28593d,#57a774); font-weight:850; box-shadow:inset 0 1px 0 rgba(255,255,255,.22); }
.ww-nav { display:flex; align-items:center; gap:.32rem; padding:.22rem; border:1px solid var(--ww-line); border-radius:8px; background:rgba(246,245,239,.72); }
.ww-nav span { padding:.44rem .7rem; border-radius:7px; color:var(--ww-muted); font-size:.84rem; font-weight:720; }
.ww-nav .active { color:#ffffff; background:#17251c; box-shadow:0 8px 24px rgba(22,37,28,.18); }
.ww-hero { display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; margin:.1rem 0 .85rem; }
.ww-kicker, .ww-map-label, .ww-plan-label, .ww-section-label { color:var(--ww-green); font-size:.72rem; font-weight:790; text-transform:uppercase; letter-spacing:.06em; }
.ww-title { margin:.12rem 0 0; color:var(--ww-ink); font-size:2.42rem; line-height:1.02; font-weight:830; letter-spacing:0; }
.ww-hero-copy { color:var(--ww-muted); margin-top:.46rem; font-size:1rem; max-width:820px; line-height:1.45; }
.ww-status-row { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.42rem; }
.ww-status { color:#1d3325; border:1px solid rgba(47,125,79,.18); border-radius:8px; background:rgba(217,240,223,.62); padding:.43rem .64rem; font-size:.8rem; font-weight:760; }
.ww-status.gold { color:#533b08; border-color:rgba(240,184,74,.28); background:rgba(240,184,74,.18); }
.ww-map-head { display:flex; align-items:center; justify-content:space-between; gap:.85rem; margin:.14rem 0 .5rem; }
.ww-map-title { color:var(--ww-ink); font-size:1.06rem; font-weight:790; }
.ww-legend { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.36rem; }
.ww-pill { display:inline-flex; align-items:center; gap:.34rem; padding:.3rem .48rem; border:1px solid var(--ww-line); border-radius:8px; background:rgba(255,255,255,.78); color:var(--ww-ink); font-size:.73rem; font-weight:760; }
.ww-dot { width:8px; height:8px; border-radius:99px; display:inline-block; }
.ww-panel { border:1px solid var(--ww-line); border-radius:8px; background:rgba(255,255,255,.78); box-shadow:0 18px 58px rgba(35,53,42,.09); padding:.85rem .85rem .72rem; position:sticky; top:72px; }
.ww-panel-title { color:var(--ww-ink); font-size:1.22rem; font-weight:830; margin:0 0 .18rem; }
.ww-panel-copy { color:var(--ww-muted); font-size:.86rem; line-height:1.42; margin:0 0 .7rem; }
.ww-control-band { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.72rem .78rem .42rem; margin-bottom:.62rem; background:rgba(246,245,239,.78); }
.ww-source-list { display:grid; gap:.48rem; margin-top:.7rem; }
.ww-source-item { color:#647267; border-top:1px solid rgba(26,46,35,.10); padding-top:.46rem; font-size:.8rem; line-height:1.35; }
.ww-source-item strong { color:var(--ww-ink); }
.ww-plan-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.42rem; margin-top:.42rem; }
.ww-plan-chip { color:#35513f; background:rgba(217,240,223,.54); border:1px dashed rgba(47,125,79,.24); border-radius:8px; padding:.46rem .5rem; font-size:.78rem; font-weight:730; }
.ww-kpi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.58rem; margin:.56rem 0 .9rem; }
.ww-kpi { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.72rem .78rem; background:rgba(255,255,255,.78); box-shadow:0 12px 34px rgba(35,53,42,.07); min-height:82px; }
.ww-kpi span { color:var(--ww-muted); font-size:.72rem; font-weight:760; display:block; }
.ww-kpi strong { color:var(--ww-ink); display:block; font-size:.98rem; margin-top:.24rem; line-height:1.22; }
.ww-insight-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.6rem; margin-top:.58rem; }
.ww-insight { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.78rem .82rem; background:rgba(255,255,255,.76); min-height:116px; }
.ww-insight span { display:block; color:var(--ww-green); font-size:.7rem; font-weight:800; text-transform:uppercase; letter-spacing:.05em; margin-bottom:.25rem; }
.ww-insight strong { display:block; color:var(--ww-ink); font-size:.98rem; margin-bottom:.34rem; }
.ww-insight p { color:#5f6d63; margin:0; font-size:.85rem; line-height:1.36; }
.ww-selected { border:1px solid rgba(52,120,169,.28); border-radius:8px; padding:.56rem .7rem; background:rgba(52,120,169,.08); color:#204b6b; margin:.56rem 0 .75rem; font-size:.86rem; }
.ww-method { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.86rem .95rem; background:rgba(255,255,255,.78); color:#526055; font-size:.88rem; line-height:1.44; }
[data-testid="stIFrame"] { border:1px solid rgba(26,46,35,.14); border-radius:8px; overflow:hidden; box-shadow:0 22px 70px rgba(35,53,42,.16); }
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color:var(--ww-ink); }
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label, [data-testid="stSlider"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label { font-weight:720; color:var(--ww-ink)!important; }
[data-testid="stAlert"] { border-radius:8px; }
[data-testid="stDataFrame"] { border-radius:8px; overflow:hidden; }
.stTabs [data-baseweb="tab-list"] { gap:.35rem; }
.stTabs [data-baseweb="tab"] { border-radius:8px; padding:.35rem .62rem; background:rgba(255,255,255,.58); border:1px solid rgba(26,46,35,.08); }
@media (max-width:1120px) { .block-container { padding:.8rem .65rem 1rem; } .ww-topbar,.ww-hero,.ww-map-head { align-items:flex-start; flex-direction:column; } .ww-nav,.ww-status-row,.ww-legend { justify-content:flex-start; } .ww-title { font-size:1.84rem; } .ww-kpi-grid,.ww-insight-grid { grid-template-columns:1fr; } .ww-panel { position:static; } }
</style>
        """,
        unsafe_allow_html=True,
    )


def _read_secret(name: str) -> Optional[str]:
    value = st.secrets.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalise_usage_mode(value: Optional[str]) -> str:
    if not value:
        return "noncommercial"
    return value.lower().replace(" ", "_").replace("-", "_")


def enforce_no_cost_guardrail() -> str:
    usage_mode = _normalise_usage_mode(_read_secret("EE_USAGE_MODE"))
    if usage_mode in COSTED_USAGE_MODES:
        st.error("No-cost guardrail active: this app is not configured for paid Earth Engine use.")
        st.caption("Use an Earth Engine project registered for eligible non-commercial, research, conservation, or impact work.")
        st.stop()
    return usage_mode


def get_earth_engine_error_help(error_text: str) -> str:
    if "earthengine.maps.create" in error_text:
        return "Live map rendering needs Earth Engine Resource Writer (`roles/earthengine.writer`) on this project."
    if "earthengine.computations.create" in error_text:
        return "The service account needs an Earth Engine project role such as Resource Viewer or Resource Writer."
    return "This is usually a project permission, Earth Engine registration, API enablement, or data availability issue."


def show_earth_engine_error(message: str, exc: Exception) -> None:
    error_text = str(exc)
    st.error(message)
    st.caption(get_earth_engine_error_help(error_text))
    st.code(error_text, language="text")
    st.stop()


def _build_service_account_key_data(service_account: str, private_key_secret: str, project_id: Optional[str]) -> tuple[str, Optional[str]]:
    raw_secret = private_key_secret.strip()
    try:
        key_info = json.loads(raw_secret)
    except json.JSONDecodeError:
        key_info = {
            "type": "service_account",
            "client_email": service_account,
            "private_key": raw_secret.replace("\\n", "\n"),
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
        st.warning("EE_SERVICE_ACCOUNT does not match the client_email in EE_PRIVATE_KEY.")
    return json.dumps(key_info), project_id or key_info.get("project_id")


def init_ee() -> None:
    service_account = _read_secret("EE_SERVICE_ACCOUNT")
    private_key_secret = _read_secret("EE_PRIVATE_KEY")
    project_id = _read_secret("EE_PROJECT_ID")
    if not service_account or not private_key_secret:
        st.error("Earth Engine credentials not found. Add EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY to Streamlit secrets.")
        st.stop()
    try:
        key_data, project_id = _build_service_account_key_data(service_account, private_key_secret, project_id)
        credentials = ee.ServiceAccountCredentials(service_account, key_data=key_data)
        ee.Initialize(credentials, project=project_id) if project_id else ee.Initialize(credentials)
    except Exception as exc:
        st.error("Failed to initialise Earth Engine with the configured service account.")
        st.caption("Confirm the Cloud project is registered for Earth Engine, the API is enabled, and the JSON key matches EE_SERVICE_ACCOUNT.")
        st.caption(str(exc))
        st.stop()


@st.cache_resource(show_spinner=False)
def _init_ee_cached() -> None:
    init_ee()


def get_fallback_berchtesgaden_aoi() -> ee.Geometry:
    return ee.Geometry.Polygon([[[12.815, 47.600], [12.865, 47.635], [12.965, 47.625], [13.070, 47.610], [13.125, 47.565], [13.115, 47.500], [13.050, 47.458], [12.955, 47.455], [12.875, 47.482], [12.820, 47.535], [12.815, 47.600]]])


def get_default_aoi() -> tuple[ee.Geometry, str]:
    try:
        park = ee.FeatureCollection(WDPA_COLLECTION_ID).filter(ee.Filter.eq("WDPAID", BERCHTESGADEN_WDPA_ID))
        if int(park.size().getInfo()) > 0:
            return park.geometry(), "Berchtesgaden National Park"
    except Exception:
        pass
    return get_fallback_berchtesgaden_aoi(), "Berchtesgaden National Park fallback boundary"


def get_aoi(geojson_str: str) -> tuple[ee.Geometry, str]:
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
    centroid = aoi.centroid().coordinates().getInfo()
    bounds_coords = aoi.bounds().coordinates().getInfo()[0]
    return [centroid[1], centroid[0]], [[lat, lon] for lon, lat in bounds_coords]


def get_alphaearth_image(year: int, aoi: ee.Geometry) -> tuple[ee.Image, int]:
    collection = ee.ImageCollection(EMBEDDING_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01").filterBounds(aoi)
    tile_count = int(collection.size().getInfo())
    if tile_count == 0:
        raise ValueError(f"No AlphaEarth embedding tiles were found for {year} in this AOI.")
    return collection.mosaic().clip(aoi), tile_count


def get_hansen_image() -> ee.Image:
    return ee.Image(HANSEN_COLLECTION_ID)


def get_tree_cover_layer(aoi: ee.Geometry) -> ee.Image:
    cover = get_hansen_image().select("treecover2000")
    return cover.updateMask(cover.gte(20)).clip(aoi)


def get_tree_loss_layer(year: int, aoi: ee.Geometry) -> ee.Image:
    if year <= 2000:
        return ee.Image(0).selfMask().clip(aoi)
    loss_year = get_hansen_image().select("lossyear")
    return loss_year.gt(0).And(loss_year.lte(min(year - 2000, 25))).selfMask().clip(aoi)


def get_surface_water_layer(aoi: ee.Geometry) -> ee.Image:
    occurrence = ee.Image(SURFACE_WATER_COLLECTION_ID).select("occurrence")
    return occurrence.updateMask(occurrence.gte(10)).clip(aoi)


def get_worldcover_layer(aoi: ee.Geometry) -> ee.Image:
    return ee.ImageCollection(WORLDCOVER_COLLECTION_ID).first().select("Map").clip(aoi)


def get_burned_area_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    collection = ee.ImageCollection(BURNED_AREA_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01").select("BurnDate")
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.max().selfMask().clip(aoi)


def get_era5_collection(year: int) -> ee.ImageCollection:
    return ee.ImageCollection(ERA5_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01")


def get_air_temperature_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    collection = get_era5_collection(year)
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.select("temperature_2m").mean().subtract(273.15).clip(aoi)


def get_soil_moisture_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    collection = get_era5_collection(year)
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.select("volumetric_soil_water_layer_1").mean().clip(aoi)


def dwd_float(row: dict[str, str], key: str) -> Optional[float]:
    raw_value = row.get(key, "").strip().replace(",", ".")
    if not raw_value:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return None if value <= -998 else value


def format_number(value: Optional[float], suffix: str, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{decimals}f}{suffix}"


def format_dwd_date(raw_date: str) -> str:
    if len(raw_date) != 8:
        return raw_date or "n/a"
    return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_archive_url(station_id: str, archive_kind: str) -> str:
    if archive_kind == "recent":
        return f"{DWD_RECENT_BASE_URL}/tageswerte_KL_{station_id}_akt.zip"
    index_html = urllib.request.urlopen(f"{DWD_HISTORICAL_BASE_URL}/", timeout=12).read().decode("utf-8", errors="ignore")
    matches = sorted(set(re.findall(rf"tageswerte_KL_{re.escape(station_id)}_.*?_hist\.zip", index_html)))
    if not matches:
        raise ValueError(f"No DWD historical climate archive found for station {station_id}.")
    return f"{DWD_HISTORICAL_BASE_URL}/{matches[-1]}"


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_dwd_rows(station_id: str, archive_kind: str) -> list[dict[str, str]]:
    archive_url = get_dwd_archive_url(station_id, archive_kind)
    with urllib.request.urlopen(archive_url, timeout=18) as response:
        archive_data = response.read()
    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        product_names = [name for name in archive.namelist() if "produkt_klima_tag" in name and name.endswith(".txt")]
        if not product_names:
            raise ValueError(f"No DWD product file found in station archive {station_id}.")
        with archive.open(product_names[0]) as product_file:
            text = product_file.read().decode("latin1")
    rows = []
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        clean_row = {key.strip(): value.strip() for key, value in row.items() if key is not None and value is not None}
        if clean_row.get("MESS_DATUM"):
            rows.append(clean_row)
    return rows


def get_dwd_daily_reading(station: dict, year: int) -> Optional[dict]:
    archive_order = ["recent", "historical"] if year >= 2025 else ["historical", "recent"]
    for archive_kind in archive_order:
        try:
            rows = fetch_dwd_rows(station["id"], archive_kind)
        except Exception:
            continue
        candidates = [row for row in rows if row.get("MESS_DATUM", "").startswith(str(year))]
        if not candidates:
            continue
        row = max(candidates, key=lambda item: item.get("MESS_DATUM", ""))
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
            "precipitation": dwd_float(row, "RSK"),
            "humidity": dwd_float(row, "UPM"),
            "wind": dwd_float(row, "FM"),
            "gust": dwd_float(row, "FX"),
        }
    return None


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_readings_for_year(year: int) -> tuple[list[dict], int]:
    readings = []
    unavailable = 0
    for station in DWD_STATIONS:
        reading = get_dwd_daily_reading(station, year)
        if reading is None:
            unavailable += 1
        else:
            readings.append(reading)
    readings.sort(key=lambda item: item["distance_km"])
    return readings, unavailable


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_annual_series(station_id: str) -> list[dict]:
    rows_by_date: dict[str, dict[str, str]] = {}
    for archive_kind in ("historical", "recent"):
        try:
            rows = fetch_dwd_rows(station_id, archive_kind)
        except Exception:
            continue
        for row in rows:
            date_value = row.get("MESS_DATUM", "")
            if date_value:
                rows_by_date[date_value] = row

    buckets: dict[int, dict[str, list[float]]] = {}
    for date_value, row in rows_by_date.items():
        try:
            year = int(date_value[:4])
        except ValueError:
            continue
        if year < 2000 or year > 2026:
            continue
        temp = dwd_float(row, "TMK")
        precip = dwd_float(row, "RSK")
        humidity = dwd_float(row, "UPM")
        if temp is None and precip is None and humidity is None:
            continue
        bucket = buckets.setdefault(year, {"temp": [], "precip": [], "humidity": []})
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
        series.append({
            "Year": year,
            "Mean temp C": round(sum(bucket["temp"]) / len(bucket["temp"]), 1),
            "Precip mm": round(sum(bucket["precip"]), 1) if bucket["precip"] else None,
            "Mean humidity %": round(sum(bucket["humidity"]) / len(bucket["humidity"]), 0) if bucket["humidity"] else None,
            "Days": len(bucket["temp"]),
        })
    return series


def estimate_soil_reading(site: dict, year: int) -> dict[str, float]:
    phase = year - 2000
    seasonal = math.sin((phase + site["seed"]) / 3.2)
    elevation_km = site["elevation"] / 1000
    soil_temp = 7.8 + phase * 0.035 - elevation_km * 3.8 + seasonal * 0.55
    soil_moisture = 34 + elevation_km * 4.5 + seasonal * 4.0 + (site["seed"] % 4) * 1.2
    return {"soil_temp": round(soil_temp, 1), "soil_moisture": round(max(8, min(70, soil_moisture)), 1), "ph": round(site["ph"] + seasonal * 0.06, 2), "carbon": round(site["carbon"] + seasonal * 0.25, 1)}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def risk_color(score: float) -> tuple[list[int], str, str]:
    if score >= 68:
        return [207, 98, 78, 208], "#cf624e", "High"
    if score >= 45:
        return [240, 184, 74, 192], "#f0b84a", "Watch"
    return [68, 166, 104, 176], "#44a668", "Lower"


def bounds_to_key(bounds: list[list[float]]) -> str:
    rounded_bounds = [[round(point[0], 5), round(point[1], 5)] for point in bounds]
    return json.dumps(rounded_bounds, sort_keys=True)


def build_fallback_environment_surface(bounds_key: str) -> list[dict]:
    bounds = json.loads(bounds_key)
    lats = [point[0] for point in bounds]
    lons = [point[1] for point in bounds]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    records = []
    for y_idx in range(13):
        lat = min_lat + (max_lat - min_lat) * (y_idx + 0.5) / 13
        for x_idx in range(15):
            lon = min_lon + (max_lon - min_lon) * (x_idx + 0.5) / 15
            ridge = math.sin((lon - min_lon) * 28) + math.cos((lat - min_lat) * 34)
            lake_distance = min(math.hypot(lat - 47.592, lon - 12.989), math.hypot(lat - 47.606, lon - 12.849))
            records.append({
                "lat": lat,
                "lon": lon,
                "elevation": 900 + ridge * 260 + (max_lat - lat) * 1300,
                "slope": 18 + abs(ridge) * 12,
                "tree_cover": clamp(68 + ridge * 12 - lake_distance * 180, 10, 95),
                "loss_year": 0,
                "water": clamp(85 - lake_distance * 1600, 0, 90),
                "source": "fallback",
            })
    return records


@st.cache_data(ttl=21600, show_spinner=False)
def sample_environment_surface(bounds_key: str, year: int) -> list[dict]:
    bounds = json.loads(bounds_key)
    lats = [point[0] for point in bounds]
    lons = [point[1] for point in bounds]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    features = []
    for y_idx in range(13):
        lat = min_lat + (max_lat - min_lat) * (y_idx + 0.5) / 13
        for x_idx in range(15):
            lon = min_lon + (max_lon - min_lon) * (x_idx + 0.5) / 15
            features.append(ee.Feature(ee.Geometry.Point([lon, lat]), {"lat": lat, "lon": lon}))

    points = ee.FeatureCollection(features)
    dem = ee.Image(DEM_IMAGE_ID).select("elevation").rename("elevation")
    slope = ee.Terrain.slope(dem).rename("slope")
    tree_cover = get_hansen_image().select("treecover2000").rename("tree_cover")
    loss_year = get_hansen_image().select("lossyear").rename("loss_year")
    water = ee.Image(SURFACE_WATER_COLLECTION_ID).select("occurrence").rename("water")
    image = dem.addBands(slope).addBands(tree_cover).addBands(loss_year).addBands(water)
    sampled = image.sampleRegions(collection=points, scale=120, geometries=False, tileScale=2).getInfo()
    records = []
    for feature in sampled.get("features", []):
        props = feature.get("properties", {})
        if "elevation" not in props:
            continue
        records.append({
            "lat": float(props.get("lat")),
            "lon": float(props.get("lon")),
            "elevation": float(props.get("elevation", 0)),
            "slope": float(props.get("slope", 0)),
            "tree_cover": float(props.get("tree_cover", 0)),
            "loss_year": float(props.get("loss_year", 0)),
            "water": float(props.get("water", 0)),
            "source": "earth_engine",
        })
    if not records:
        raise ValueError("No environmental samples returned for the selected area.")
    return records


def get_climate_signal(year: int, projection_year: int, scenario_name: str) -> dict:
    scenario = SCENARIO_SETTINGS[scenario_name]
    station = next((item for item in DWD_STATIONS if item["id"] == PREDICTION_STATION_ID), DWD_STATIONS[-1])
    rows = get_dwd_annual_series(PREDICTION_STATION_ID)
    if not rows:
        projection_gap = max(0, projection_year - max(year, 2026))
        return {"station": station["name"], "base_temp": None, "recent_temp": None, "temp_delta": 0.0, "projected_temp_delta": round(projection_gap * scenario["warming_per_year"], 2), "precip_delta_pct": 0.0, "projected_precip_delta_pct": round(-projection_gap * scenario["drying_per_year"], 1), "source_note": "DWD trend unavailable; projection uses scenario settings only."}

    df = pd.DataFrame(rows)
    base = df[(df["Year"] >= 2000) & (df["Year"] <= 2009)]
    max_available_year = int(df["Year"].max())
    analysis_year = min(max(year, 2000), max_available_year)
    recent = df[(df["Year"] >= max(2000, analysis_year - 4)) & (df["Year"] <= analysis_year)]
    if base.empty:
        base = df.head(min(5, len(df)))
    if recent.empty:
        recent = df.tail(min(5, len(df)))

    base_temp = float(base["Mean temp C"].mean())
    recent_temp = float(recent["Mean temp C"].mean())
    base_precip = float(base["Precip mm"].dropna().mean()) if not base["Precip mm"].dropna().empty else 0.0
    recent_precip = float(recent["Precip mm"].dropna().mean()) if not recent["Precip mm"].dropna().empty else base_precip
    precip_delta_pct = ((recent_precip - base_precip) / base_precip * 100) if base_precip else 0.0
    projection_gap = max(0, projection_year - max(analysis_year, 2026))
    projected_temp_delta = (recent_temp - base_temp) + projection_gap * scenario["warming_per_year"]
    projected_precip_delta_pct = precip_delta_pct - projection_gap * scenario["drying_per_year"]
    return {
        "station": station["name"],
        "base_temp": round(base_temp, 1),
        "recent_temp": round(recent_temp, 1),
        "temp_delta": round(recent_temp - base_temp, 2),
        "projected_temp_delta": round(projected_temp_delta, 2),
        "precip_delta_pct": round(precip_delta_pct, 1),
        "projected_precip_delta_pct": round(projected_precip_delta_pct, 1),
        "source_note": f"Climate signal uses DWD annual summaries from {station['name']}.",
    }


def score_prediction_row(row: dict, year: int, projection_year: int, climate_signal: dict) -> dict:
    elevation = float(row.get("elevation") or 0)
    slope = float(row.get("slope") or 0)
    tree_cover = float(row.get("tree_cover") or 0)
    loss_year = float(row.get("loss_year") or 0)
    water = float(row.get("water") or 0)
    observed_loss_year = 2000 + int(loss_year) if loss_year > 0 else None
    loss_active = bool(observed_loss_year and observed_loss_year <= min(year, 2025))
    recent_loss = bool(observed_loss_year and min(year, 2025) - observed_loss_year <= 5)

    warming = clamp(float(climate_signal["projected_temp_delta"]) / 2.5, 0, 1) * 22
    dryness = clamp(-float(climate_signal["projected_precip_delta_pct"]) / 20, 0, 1) * 15
    low_canopy = clamp((58 - tree_cover) / 58, 0, 1) * 22
    loss_history = (24 if loss_active else 0) + (7 if recent_loss else 0)
    steep_terrain = clamp((slope - 14) / 35, 0, 1) * 13
    lower_elevation = clamp((1220 - elevation) / 900, 0, 1) * 8
    water_buffer = clamp(water / 80, 0, 1) * 12
    projection_pressure = clamp((projection_year - year) / 14, 0, 1) * 5
    score = clamp(18 + warming + dryness + low_canopy + loss_history + steep_terrain + lower_elevation + projection_pressure - water_buffer, 1, 99)
    color, color_hex, label = risk_color(score)

    drivers = {"warming": warming, "dryness": dryness, "low canopy": low_canopy, "loss history": loss_history, "steep terrain": steep_terrain, "lower elevation": lower_elevation}
    dominant = sorted(drivers.items(), key=lambda item: item[1], reverse=True)[:2]
    reason = ", ".join(name for name, value in dominant if value > 2) or "balanced conditions"
    if water_buffer > 7:
        reason = f"{reason}; recurring water lowers stress"

    return {
        "lat": round(float(row["lat"]), 6),
        "lon": round(float(row["lon"]), 6),
        "elevation": round(elevation, 0),
        "slope": round(slope, 1),
        "tree_cover": round(tree_cover, 1),
        "loss_year": int(loss_year) if loss_year else 0,
        "water": round(water, 1),
        "risk_score": round(score, 1),
        "risk_label": label,
        "color": color,
        "color_hex": color_hex,
        "height_risk": round(score * 28, 1),
        "height_terrain": round(max(80, elevation * 0.55), 1),
        "reason": reason,
        "warming": round(warming, 1),
        "dryness": round(dryness, 1),
        "low_canopy": round(low_canopy, 1),
        "loss_history": round(loss_history, 1),
        "steep_terrain": round(steep_terrain, 1),
        "water_buffer": round(water_buffer, 1),
        "source": row.get("source", "earth_engine"),
    }


def build_prediction_surface(bounds: list[list[float]], year: int, projection_year: int, scenario_name: str) -> tuple[pd.DataFrame, dict, Optional[str]]:
    bounds_key = bounds_to_key(bounds)
    climate_signal = get_climate_signal(year, projection_year, scenario_name)
    note = None
    try:
        environment_rows = sample_environment_surface(bounds_key, min(year, 2025))
    except Exception as exc:
        environment_rows = build_fallback_environment_surface(bounds_key)
        note = f"Prediction terrain is using a fallback surface because the public DEM sample was unavailable: {exc}"
    records = [score_prediction_row(row, year, projection_year, climate_signal) for row in environment_rows]
    return pd.DataFrame(records), climate_signal, note


def add_ee_layer(m: folium.Map, image: ee.Image, vis_params: dict, name: str, opacity: float = 0.85) -> None:
    map_id = image.getMapId(vis_params)
    folium.TileLayer(tiles=map_id["tile_fetcher"].url_format, attr="Google Earth Engine", name=name, overlay=True, control=True, opacity=opacity).add_to(m)


def add_aoi_boundary(m: folium.Map, aoi: ee.Geometry, area_name: str) -> None:
    folium.GeoJson(aoi.getInfo(), name=area_name, style_function=lambda _: {"color": AOI_COLOR, "weight": 2.8, "fillOpacity": 0, "opacity": 0.95}).add_to(m)


def build_map(center: list[float], bounds: list[list[float]], basemap: str) -> folium.Map:
    m = folium.Map(location=center, zoom_start=12, tiles=None, control_scale=True)
    if basemap == "Satellite":
        folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri, Maxar, Earthstar Geographics, and the GIS User Community", name="Satellite", control=False).add_to(m)
    elif basemap == "Terrain":
        folium.TileLayer("OpenTopoMap", name="Terrain", control=False).add_to(m)
    else:
        folium.TileLayer("CartoDB positron", name="Light map", control=False).add_to(m)
    m.fit_bounds(bounds, padding=(24, 24))
    return m


def add_prediction_surface_markers(m: folium.Map, prediction_df: pd.DataFrame) -> None:
    if prediction_df.empty:
        return
    group = folium.FeatureGroup(name="Predicted forest stress", show=True)
    for _, row in prediction_df.iterrows():
        popup_html = f"""
        <div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; min-width: 230px;'>
          <strong>{row['risk_label']} stress | {row['risk_score']}/100</strong><br>
          <span>{row['reason']}</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Elevation / slope</td><td>{row['elevation']:.0f} m / {row['slope']:.1f}</td></tr>
            <tr><td>Tree cover</td><td>{row['tree_cover']:.1f}%</td></tr>
            <tr><td>Water occurrence</td><td>{row['water']:.1f}%</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(location=[row["lat"], row["lon"]], radius=5.5, color="#ffffff", weight=1.2, fill=True, fill_color=row["color_hex"], fill_opacity=0.74, tooltip=f"Predicted stress: {row['risk_score']}/100", popup=folium.Popup(popup_html, max_width=320)).add_to(group)
    group.add_to(m)


def add_dwd_weather_markers(m: folium.Map, year: int, layers: dict[str, bool]) -> list[str]:
    if not layers["weather_sensors"]:
        return []
    try:
        readings, unavailable = get_dwd_readings_for_year(year)
    except Exception as exc:
        return [f"DWD weather station data could not be loaded: {exc}"]
    if not readings:
        return [f"No DWD daily weather station records were available for {year}."]
    notes = [f"DWD has no selected-year daily records for {unavailable} nearby station(s)."] if unavailable else []
    group = folium.FeatureGroup(name="DWD daily weather stations", show=True)
    for reading in readings:
        popup_html = f"""
        <div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; min-width: 260px;'>
          <strong>{reading['name']}</strong><br>
          <span>DWD {reading['station_id']} | {reading['elevation']} m | {reading['distance_km']} km from park center</span><br>
          <span>{reading['date']} | {reading['archive_kind']} archive</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Mean temp</td><td>{format_number(reading['mean_temp'], ' C')}</td></tr>
            <tr><td>Precipitation</td><td>{format_number(reading['precipitation'], ' mm')}</td></tr>
            <tr><td>Humidity</td><td>{format_number(reading['humidity'], '%', 0)}</td></tr>
            <tr><td>Wind</td><td>{format_number(reading['wind'], ' m/s')}</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(location=[reading["lat"], reading["lon"]], radius=7, color="#ffffff", weight=2, fill=True, fill_color="#3478a9", fill_opacity=0.94, tooltip=f"DWD weather: {reading['name']}", popup=folium.Popup(popup_html, max_width=340)).add_to(group)
    group.add_to(m)
    return notes


def add_soil_sensor_markers(m: folium.Map, year: int, layers: dict[str, bool]) -> None:
    if not layers["soil_sensors"]:
        return
    group = folium.FeatureGroup(name="Prototype soil probes", show=True)
    for site in SOIL_SENSOR_SITES:
        reading = estimate_soil_reading(site, year)
        popup_html = f"""
        <div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; min-width: 230px;'>
          <strong>{site['name']}</strong><br>
          <span>{site['zone']} | prototype soil probe</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Soil moisture</td><td>{reading['soil_moisture']}%</td></tr>
            <tr><td>Soil temp</td><td>{reading['soil_temp']} C</td></tr>
            <tr><td>pH / SOC</td><td>{reading['ph']} / {reading['carbon']}%</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(location=[site["lat"], site["lon"]], radius=7, color="#ffffff", weight=2, fill=True, fill_color="#f0b84a", fill_opacity=0.94, tooltip=f"Prototype soil probe: {site['name']}", popup=folium.Popup(popup_html, max_width=300)).add_to(group)
    group.add_to(m)


def add_selected_layers(m: folium.Map, year: int, aoi: ee.Geometry, layers: dict[str, bool]) -> tuple[int, list[str]]:
    alphaearth_tile_count = 0
    notes = []
    if layers["alphaearth"]:
        if year in ALPHAEARTH_YEARS:
            alphaearth, alphaearth_tile_count = get_alphaearth_image(year, aoi)
            add_ee_layer(m, alphaearth, {"bands": DEFAULT_RGB_BANDS, "min": -0.3, "max": 0.3}, "Landscape patterns", opacity=0.72)
        else:
            notes.append("AlphaEarth is available for 2017-2024, so it is hidden for this year.")
    if layers["tree_cover"]:
        add_ee_layer(m, get_tree_cover_layer(aoi), {"min": 20, "max": 95, "palette": ["#d5e8bd", "#2c8c4a", "#0e4f2e"]}, "Tree canopy", opacity=0.48)
    if layers["tree_loss"]:
        if year > 2025:
            notes.append("Tree-cover loss uses Hansen data through 2025 for 2026 views.")
        add_ee_layer(m, get_tree_loss_layer(year, aoi), {"min": 1, "max": 1, "palette": ["#cf624e"]}, "Tree-cover loss", opacity=0.86)
    if layers["water"]:
        add_ee_layer(m, get_surface_water_layer(aoi), {"min": 10, "max": 100, "palette": ["#bde7ff", "#3478a9", "#075985"]}, "Water and wetlands", opacity=0.70)
    if layers["habitat"]:
        add_ee_layer(m, get_worldcover_layer(aoi), {"min": 10, "max": 100, "palette": ["#006400", "#ffbb22", "#ffff4c", "#f096ff", "#fa0000", "#b4b4b4", "#f0f0f0", "#0064c8", "#0096a0", "#00cf75", "#fae6a0"]}, "Land-cover habitat", opacity=0.40)
    if layers["fire"]:
        burned_area = get_burned_area_layer(year, aoi)
        if burned_area is None:
            notes.append("Burned-area history is not available for the selected year yet.")
        else:
            add_ee_layer(m, burned_area, {"min": 1, "max": 366, "palette": ["#ffdd8a", "#f0b84a", "#cf624e"]}, "Burned area history", opacity=0.84)
    if layers["air_temperature"]:
        air_temperature = get_air_temperature_layer(year, aoi)
        if air_temperature is None:
            notes.append("ERA5-Land air temperature is not available for the selected year yet.")
        else:
            add_ee_layer(m, air_temperature, {"min": -5, "max": 14, "palette": ["#244cbd", "#e8f5ff", "#ffb14e", "#cf624e"]}, "Air temperature model", opacity=0.46)
    if layers["soil_moisture"]:
        soil_moisture = get_soil_moisture_layer(year, aoi)
        if soil_moisture is None:
            notes.append("ERA5-Land soil moisture is not available for the selected year yet.")
        else:
            add_ee_layer(m, soil_moisture, {"min": 0.18, "max": 0.55, "palette": ["#8c510a", "#f6e8c3", "#80cdc1", "#01665e"]}, "Soil moisture model", opacity=0.54)
    notes.extend(add_dwd_weather_markers(m, year, layers))
    add_soil_sensor_markers(m, year, layers)
    return alphaearth_tile_count, notes


def build_weather_table(year: int) -> pd.DataFrame:
    readings, _ = get_dwd_readings_for_year(year)
    return pd.DataFrame([
        {"Station": r["name"], "Date": r["date"], "Distance km": r["distance_km"], "Elevation m": r["elevation"], "Mean temp C": r["mean_temp"], "Precip mm": r["precipitation"], "Humidity %": r["humidity"], "Wind m/s": r["wind"]}
        for r in readings
    ])


def build_sensor_frame(year: int) -> pd.DataFrame:
    rows = []
    try:
        readings, _ = get_dwd_readings_for_year(year)
    except Exception:
        readings = []
    for reading in readings:
        rows.append({"name": reading["name"], "kind": "DWD weather", "lat": reading["lat"], "lon": reading["lon"], "elevation": reading["elevation"], "color": [52, 120, 169, 220], "radius": 170, "tooltip": f"{format_number(reading['mean_temp'], ' C')} | {format_number(reading['precipitation'], ' mm')} precip"})
    for site in SOIL_SENSOR_SITES:
        reading = estimate_soil_reading(site, year)
        rows.append({"name": site["name"], "kind": "Prototype soil probe", "lat": site["lat"], "lon": site["lon"], "elevation": site["elevation"], "color": [240, 184, 74, 230], "radius": 145, "tooltip": f"{reading['soil_moisture']}% moisture | pH {reading['ph']}"})
    return pd.DataFrame(rows)


def apply_view_preset(view_mode: str) -> None:
    if st.session_state.get("active_view_preset") == view_mode:
        return
    st.session_state["active_view_preset"] = view_mode
    preset_layers = VIEW_PRESETS[view_mode]["layers"]
    for layer_id, _, _ in LAYER_META:
        st.session_state[f"layer_{layer_id}"] = preset_layers.get(layer_id, False)


def render_topbar(app_mode: str) -> None:
    def nav_class(label: str) -> str:
        return "active" if label == app_mode else ""

    st.markdown(f"""
<div class="ww-topbar">
  <div class="ww-brand"><div class="ww-mark">W</div><span>Whispering Woods</span></div>
  <div class="ww-nav"><span class="{nav_class('Map')}">Map</span><span class="{nav_class('3D View')}">3D View</span><span class="{nav_class('Predictions')}">Predictions</span></div>
</div>
    """, unsafe_allow_html=True)


def render_header(usage_mode: str, year: int, enabled_count: int, area_name: str, view_mode: str, app_mode: str, projection_year: int) -> None:
    titles = {"Map": "Berchtesgaden forest intelligence", "3D View": "Terrain, stress, and observation points", "Predictions": "Forest vulnerability forecast"}
    lens_copy = VIEW_PRESETS[view_mode]["copy"]
    projection_status = f"Projection {projection_year}" if app_mode in {"3D View", "Predictions"} else f"{year}"
    st.markdown(f"""
<div class="ww-hero">
  <div>
    <div class="ww-kicker">{area_name}</div>
    <div class="ww-title">{titles[app_mode]}</div>
    <div class="ww-hero-copy">{lens_copy}</div>
  </div>
  <div class="ww-status-row">
    <div class="ww-status">Earth Engine live</div>
    <div class="ww-status gold">{usage_mode}</div>
    <div class="ww-status">{projection_status}</div>
    <div class="ww-status">{enabled_count} layers</div>
  </div>
</div>
    """, unsafe_allow_html=True)


def render_layer_panel() -> tuple[str, int, int, str, str, str, str, dict[str, bool], str]:
    st.markdown("<div class='ww-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-panel-title'>Explore</div>", unsafe_allow_html=True)
    st.markdown("<div class='ww-panel-copy'>Choose a view and tune the evidence layers.</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Workspace</div>", unsafe_allow_html=True)
    app_mode = st.radio("Workspace", ["Map", "3D View", "Predictions"], index=0, horizontal=True, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Lens</div>", unsafe_allow_html=True)
    view_mode = st.selectbox("Exploration lens", list(VIEW_PRESETS.keys()), index=0, label_visibility="collapsed")
    apply_view_preset(view_mode)
    st.caption(VIEW_PRESETS[view_mode]["copy"])
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Time and scenario</div>", unsafe_allow_html=True)
    year = st.slider("Analysis year", min_value=2000, max_value=2026, value=2024)
    projection_year = st.slider("Projection year", min_value=2026, max_value=2040, value=2030)
    risk_scenario = st.selectbox("Climate scenario", list(SCENARIO_SETTINGS.keys()), index=1)
    basemap = st.selectbox("Map style", ["Satellite", "Light", "Terrain"], index=0)
    height_mode = "Risk score"
    if app_mode == "3D View":
        height_mode = st.radio("3D height", ["Risk score", "Terrain"], index=0, horizontal=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Evidence layers</div>", unsafe_allow_html=True)
    layers = {}
    for layer_id, label, help_text in LAYER_META:
        layers[layer_id] = st.checkbox(label, key=f"layer_{layer_id}", help=help_text)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Custom AOI", expanded=False):
        geojson_input: str = st.text_area("GeoJSON polygon", "", height=120, help="Leave blank to use Berchtesgaden National Park.")
    st.markdown("</div>", unsafe_allow_html=True)
    return app_mode, year, projection_year, risk_scenario, height_mode, basemap, geojson_input, layers, view_mode


def render_sources_panel() -> None:
    st.markdown("""
<div class="ww-source-list">
  <div class="ww-source-item"><strong>Boundary</strong><br>WDPA Berchtesgaden National Park, with local fallback.</div>
  <div class="ww-source-item"><strong>Earth observation</strong><br>AlphaEarth, Hansen, JRC water, ESA WorldCover, MODIS, ERA5-Land, and SRTM.</div>
  <div class="ww-source-item"><strong>Local observations</strong><br>DWD daily climate station records and labelled prototype soil probes.</div>
</div>
    """, unsafe_allow_html=True)


def render_planned_layers() -> None:
    st.markdown("""
<div class="ww-plan-label">Planned integrations</div>
<div class="ww-plan-grid"><div class="ww-plan-chip">Inventory trees</div><div class="ww-plan-chip">Species observations</div><div class="ww-plan-chip">Trail impact reports</div><div class="ww-plan-chip">Ranger field notes</div></div>
    """, unsafe_allow_html=True)


def render_observation_summary(year: int, view_mode: str, layers: dict[str, bool]) -> None:
    try:
        dwd_readings, unavailable = get_dwd_readings_for_year(year)
    except Exception:
        dwd_readings = []
        unavailable = len(DWD_STATIONS)
    soil_readings = [estimate_soil_reading(site, year) for site in SOIL_SENSOR_SITES]
    avg_soil = round(sum(r["soil_moisture"] for r in soil_readings) / len(soil_readings), 1)
    avg_ph = round(sum(r["ph"] for r in soil_readings) / len(soil_readings), 2)
    if dwd_readings:
        nearest = dwd_readings[0]
        weather_label = f"{format_number(nearest['mean_temp'], ' C')} at {nearest['name']}"
        station_label = f"{len(dwd_readings)} station(s), {unavailable} gap(s)"
    else:
        weather_label = f"No DWD station record for {year}"
        station_label = "Station layer waiting for records"
    st.markdown(f"""
<div class="ww-kpi-grid">
  <div class="ww-kpi"><span>Lens</span><strong>{view_mode}</strong></div>
  <div class="ww-kpi"><span>Weather</span><strong>{weather_label}</strong></div>
  <div class="ww-kpi"><span>Coverage</span><strong>{station_label}</strong></div>
  <div class="ww-kpi"><span>Prototype soil</span><strong>{avg_soil}% moisture | pH {avg_ph}</strong></div>
</div>
    """, unsafe_allow_html=True)
    active_labels = [label for layer_id, label, _ in LAYER_META if layers.get(layer_id)]
    if active_labels:
        st.caption("Active evidence: " + ", ".join(active_labels))


def render_prediction_summary(prediction_df: pd.DataFrame, climate_signal: dict, projection_year: int, scenario_name: str) -> None:
    if prediction_df.empty:
        return
    mean_score = round(float(prediction_df["risk_score"].mean()), 1)
    high_share = round(float((prediction_df["risk_score"] >= 68).mean() * 100), 0)
    top = prediction_df.nlargest(1, "risk_score").iloc[0]
    temp_delta = climate_signal.get("projected_temp_delta", 0)
    precip_delta = climate_signal.get("projected_precip_delta_pct", 0)
    st.markdown(f"""
<div class="ww-kpi-grid">
  <div class="ww-kpi"><span>Mean stress</span><strong>{mean_score}/100</strong></div>
  <div class="ww-kpi"><span>High-stress share</span><strong>{high_share:.0f}%</strong></div>
  <div class="ww-kpi"><span>Climate signal</span><strong>{temp_delta:+.1f} C | {precip_delta:+.0f}% precip</strong></div>
  <div class="ww-kpi"><span>Top hotspot</span><strong>{top['risk_score']:.1f}/100 | {top['risk_label']}</strong></div>
</div>
    """, unsafe_allow_html=True)
    st.caption(f"Projection: {projection_year}, scenario: {scenario_name}. {climate_signal.get('source_note', '')}")


def get_enabled_labels(layers: dict[str, bool]) -> list[tuple[str, str]]:
    label_specs = [("alphaearth", "Landscape", "#44a668"), ("prediction", "Predicted stress", "#cf624e"), ("tree_cover", "Tree canopy", "#2c8c4a"), ("tree_loss", "Forest loss", "#cf624e"), ("water", "Water", "#3478a9"), ("habitat", "Habitat", "#a7bd52"), ("fire", "Burned area", "#f0b84a"), ("air_temperature", "Air temp", "#cf624e"), ("soil_moisture", "Soil moisture", "#45a6b7"), ("weather_sensors", "DWD weather", "#3478a9"), ("soil_sensors", "Soil probes", "#f0b84a")]
    labels = [(label, color) for layer_id, label, color in label_specs if layers.get(layer_id)]
    return labels or [("Park boundary", AOI_COLOR)]


def render_map_heading(year: int, enabled_labels: list[tuple[str, str]], area_name: str, title: str = "Forest evidence layers") -> None:
    legend_markup = "".join(f"<span class='ww-pill'><span class='ww-dot' style='background:{color}'></span>{label}</span>" for label, color in enabled_labels)
    st.markdown(f"""
<div class="ww-map-head"><div><div class="ww-map-label">{area_name}</div><div class="ww-map-title">{title}, {year}</div></div><div class="ww-legend">{legend_markup}</div></div>
    """, unsafe_allow_html=True)


def build_insight_items(view_mode: str, year: int, layers: dict[str, bool], notes: list[str]) -> list[tuple[str, str, str]]:
    items = [("Lens", view_mode, VIEW_PRESETS[view_mode]["copy"])]
    if layers.get("alphaearth"):
        items.append(("Landscape", "AlphaEarth active" if year in ALPHAEARTH_YEARS else "AlphaEarth hidden", "Annual embeddings currently cover 2017-2024." if year not in ALPHAEARTH_YEARS else "Embedding colors reveal landscape pattern differences inside the park."))
    if layers.get("prediction"):
        items.append(("Forecast", "Stress surface active", "The prototype score combines terrain, canopy, loss, water, and DWD climate trend signals."))
    if layers.get("tree_loss"):
        items.append(("Forest change", "Cumulative loss", "The red layer marks Hansen tree-cover loss up to the selected year."))
    if layers.get("water") or layers.get("soil_moisture"):
        items.append(("Hydrology", "Water context", "Water and soil moisture layers help explain wetland edges and stress signals."))
    if layers.get("weather_sensors"):
        items.append(("Observations", "DWD stations", "Blue markers use official DWD daily climate records when available."))
    for note in notes[:2]:
        items.append(("Data note", "Coverage", note))
    return items[:6]


def render_map_selection(map_state: Optional[dict]) -> None:
    if not isinstance(map_state, dict):
        return
    clicked = map_state.get("last_object_clicked_tooltip") or map_state.get("last_object_clicked_popup")
    if clicked:
        st.markdown(f"<div class='ww-selected'><strong>Selected on map:</strong> {clicked}</div>", unsafe_allow_html=True)
        return
    last_clicked = map_state.get("last_clicked")
    if isinstance(last_clicked, dict) and "lat" in last_clicked and "lng" in last_clicked:
        st.markdown(f"<div class='ww-selected'><strong>Map point:</strong> {last_clicked['lat']:.5f}, {last_clicked['lng']:.5f}</div>", unsafe_allow_html=True)


def render_prediction_evidence(prediction_df: pd.DataFrame, climate_signal: dict, scenario_name: str, projection_year: int) -> None:
    if prediction_df.empty:
        return
    drivers_tab, hotspots_tab, method_tab = st.tabs(["Drivers", "Hotspots", "Model note"])
    with drivers_tab:
        driver_df = pd.DataFrame([
            {"Driver": "Warming", "Contribution": prediction_df["warming"].mean()},
            {"Driver": "Dryness", "Contribution": prediction_df["dryness"].mean()},
            {"Driver": "Low canopy", "Contribution": prediction_df["low_canopy"].mean()},
            {"Driver": "Loss history", "Contribution": prediction_df["loss_history"].mean()},
            {"Driver": "Steep terrain", "Contribution": prediction_df["steep_terrain"].mean()},
            {"Driver": "Water buffer", "Contribution": -prediction_df["water_buffer"].mean()},
        ])
        st.bar_chart(driver_df.set_index("Driver"), height=280)
    with hotspots_tab:
        hotspots = prediction_df.nlargest(12, "risk_score")[["risk_score", "risk_label", "reason", "elevation", "slope", "tree_cover", "water", "lat", "lon"]]
        st.dataframe(hotspots, use_container_width=True, hide_index=True)
    with method_tab:
        st.markdown(f"""
<div class="ww-method">
<strong>Projection {projection_year} | {scenario_name}</strong><br>
This is an explainable prototype index from 0-100. It combines public terrain, slope, tree canopy, tree-cover loss, recurring water, and the DWD annual climate signal from {climate_signal.get('station', 'the selected station')}. It is designed for stakeholder exploration, not operational hazard certification.
</div>
        """, unsafe_allow_html=True)


def render_evidence_board(year: int, view_mode: str, layers: dict[str, bool], notes: list[str], prediction_df: Optional[pd.DataFrame] = None, climate_signal: Optional[dict] = None, scenario_name: str = "Moderate", projection_year: int = 2030) -> None:
    insights_tab, weather_tab, station_tab, sources_tab = st.tabs(["Insights", "Weather", "Stations", "Sources"])
    with insights_tab:
        markup = "".join(f"<div class='ww-insight'><span>{e}</span><strong>{t}</strong><p>{b}</p></div>" for e, t, b in build_insight_items(view_mode, year, layers, notes))
        st.markdown(f"<div class='ww-insight-grid'>{markup}</div>", unsafe_allow_html=True)
    with weather_tab:
        default_index = next((idx for idx, station in enumerate(DWD_STATIONS) if station["id"] == "00856"), 0)
        station = st.selectbox("Weather trend station", DWD_STATIONS, index=default_index, format_func=lambda item: f"{item['name']} ({item['distance_km']} km)")
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
                st.caption(f"{station['name']} in {year}: {row['Mean temp C']} C mean temp, {row['Precip mm']} mm precipitation, {int(row['Days'])} observed day(s).")
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
    if prediction_df is not None and climate_signal is not None and not prediction_df.empty:
        render_prediction_evidence(prediction_df, climate_signal, scenario_name, projection_year)


def build_3d_deck(prediction_df: pd.DataFrame, sensor_df: pd.DataFrame, center: list[float], height_mode: str) -> pdk.Deck:
    terrain_df = prediction_df.copy()
    terrain_df["height"] = terrain_df["height_terrain"] if height_mode == "Terrain" else terrain_df["height_risk"]
    terrain_df["deck_tooltip"] = terrain_df.apply(lambda row: f"{row['risk_label']} stress: {row['risk_score']}/100<br>{row['reason']}<br>Elevation {row['elevation']:.0f} m", axis=1)
    layers = [pdk.Layer("ColumnLayer", data=terrain_df, get_position="[lon, lat]", get_elevation="height", get_fill_color="color", radius=120, coverage=0.82, pickable=True, auto_highlight=True)]
    if not sensor_df.empty:
        layers.append(pdk.Layer("ScatterplotLayer", data=sensor_df, get_position="[lon, lat]", get_radius="radius", get_fill_color="color", get_line_color=[255, 255, 255, 230], line_width_min_pixels=1, pickable=True, auto_highlight=True))
    view_state = pdk.ViewState(latitude=center[0], longitude=center[1], zoom=10.7, pitch=58, bearing=-28)
    return pdk.Deck(map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json", initial_view_state=view_state, layers=layers, tooltip={"html": "<b>{name}{risk_label}</b><br>{tooltip}{deck_tooltip}", "style": {"backgroundColor": "#16251c", "color": "#ffffff"}})


def render_3d_view(prediction_df: pd.DataFrame, sensor_df: pd.DataFrame, center: list[float], height_mode: str) -> None:
    if prediction_df.empty:
        st.info("No 3D terrain samples are available for this area.")
        return
    st.pydeck_chart(build_3d_deck(prediction_df, sensor_df, center, height_mode), use_container_width=True)


def render_map_mode(year: int, projection_year: int, scenario_name: str, basemap: str, layers: dict[str, bool], view_mode: str, aoi: ee.Geometry, area_name: str, center: list[float], bounds: list[list[float]]) -> None:
    prediction_df: Optional[pd.DataFrame] = None
    climate_signal: Optional[dict] = None
    try:
        m = build_map(center, bounds, basemap)
        alphaearth_tile_count, notes = add_selected_layers(m, year, aoi, layers)
        if layers.get("prediction"):
            prediction_df, climate_signal, prediction_note = build_prediction_surface(bounds, year, projection_year, scenario_name)
            add_prediction_surface_markers(m, prediction_df)
            if prediction_note:
                notes.append(prediction_note)
        add_aoi_boundary(m, aoi, area_name)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not render the selected forest layers.", exc)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    render_map_heading(year, get_enabled_labels(layers), area_name)
    map_state = st_folium(m, width=None, height=760)
    render_map_selection(map_state)
    captions = ["Visible layers are public Earth Engine datasets, DWD daily climate observations, and clearly labelled prototype soil probes."]
    if layers["alphaearth"] and alphaearth_tile_count:
        captions.append(f"AlphaEarth is scoped to {alphaearth_tile_count} tile(s) for the selected AOI.")
    captions.extend(notes)
    st.caption(" ".join(captions))
    render_evidence_board(year, view_mode, layers, notes, prediction_df, climate_signal, scenario_name, projection_year)


def render_predictions_mode(year: int, projection_year: int, scenario_name: str, basemap: str, layers: dict[str, bool], aoi: ee.Geometry, area_name: str, center: list[float], bounds: list[list[float]]) -> None:
    prediction_df, climate_signal, prediction_note = build_prediction_surface(bounds, year, projection_year, scenario_name)
    render_prediction_summary(prediction_df, climate_signal, projection_year, scenario_name)
    map_layers = dict(layers)
    map_layers["prediction"] = False
    try:
        m = build_map(center, bounds, basemap)
        _, notes = add_selected_layers(m, year, aoi, map_layers)
        add_prediction_surface_markers(m, prediction_df)
        add_aoi_boundary(m, aoi, area_name)
        if prediction_note:
            notes.append(prediction_note)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not render the prediction map.", exc)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    render_map_heading(projection_year, [("Predicted stress", "#cf624e"), ("DWD weather", "#3478a9"), ("Soil probes", "#f0b84a")], area_name, title="Forecast surface")
    map_state = st_folium(m, width=None, height=650)
    render_map_selection(map_state)
    st.caption(" ".join(notes) if notes else "Prediction is calculated in-app from public read-only layers and local DWD observations.")
    render_prediction_evidence(prediction_df, climate_signal, scenario_name, projection_year)


def render_3d_mode(year: int, projection_year: int, scenario_name: str, height_mode: str, bounds: list[list[float]], center: list[float]) -> None:
    prediction_df, climate_signal, prediction_note = build_prediction_surface(bounds, year, projection_year, scenario_name)
    sensor_df = build_sensor_frame(year)
    render_prediction_summary(prediction_df, climate_signal, projection_year, scenario_name)
    render_map_heading(projection_year, [("Risk columns", "#cf624e"), ("Terrain", "#44a668"), ("Stations", "#3478a9"), ("Soil probes", "#f0b84a")], "Berchtesgaden National Park", title="3D forest view")
    render_3d_view(prediction_df, sensor_df, center, height_mode)
    if prediction_note:
        st.caption(prediction_note)
    render_prediction_evidence(prediction_df, climate_signal, scenario_name, projection_year)


def main() -> None:
    st.set_page_config(page_title="Whispering Woods", layout="wide", initial_sidebar_state="collapsed")
    inject_theme_css()
    usage_mode = enforce_no_cost_guardrail()
    _init_ee_cached()

    control_col, main_col = st.columns([0.95, 3.25], gap="large")
    with control_col:
        app_mode, year, projection_year, scenario_name, height_mode, basemap, geojson_input, layers, view_mode = render_layer_panel()
        render_sources_panel()
        render_planned_layers()

    aoi, area_name = get_aoi(geojson_input)
    try:
        center, bounds = get_aoi_view(aoi)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not locate the selected area.", exc)

    enabled_count = sum(1 for enabled in layers.values() if enabled)
    with main_col:
        render_topbar(app_mode)
        render_header(usage_mode, year, enabled_count, area_name, view_mode, app_mode, projection_year)
        render_observation_summary(year, view_mode, layers)
        if app_mode == "Map":
            render_map_mode(year, projection_year, scenario_name, basemap, layers, view_mode, aoi, area_name, center, bounds)
        elif app_mode == "Predictions":
            render_predictions_mode(year, projection_year, scenario_name, basemap, layers, aoi, area_name, center, bounds)
        else:
            render_3d_mode(year, projection_year, scenario_name, height_mode, bounds, center)


if __name__ == "__main__":
    main()
