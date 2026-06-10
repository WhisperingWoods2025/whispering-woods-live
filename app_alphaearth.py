"""Stakeholder-facing Whispering Woods forest layer explorer."""

import json
import math
from typing import Optional

import folium
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

DEFAULT_RGB_BANDS = ["A01", "A16", "A09"]
AOI_COLOR = "#F1C75B"
AVAILABLE_YEARS = list(range(2000, 2027))
ALPHAEARTH_YEARS = set(range(2017, 2025))

SENSOR_SITES = [
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
  --ww-nav: #07100b;
  --ww-panel: #f0e4b8;
  --ww-panel-text: #203427;
  --ww-text: #f3f6ef;
  --ww-muted: #9fb29f;
  --ww-green: #a8d7a8;
  --ww-gold: #f1c75b;
}

[data-testid="stAppViewContainer"] { background: var(--ww-bg); color: var(--ww-text); }
[data-testid="stHeader"] { background: rgba(7, 17, 12, 0.92); border-bottom: 1px solid rgba(168, 215, 168, 0.12); }
[data-testid="stSidebar"] { background: #07110c; }
.block-container { max-width: 1760px; padding: 1.1rem 1.6rem 1.2rem; }

.ww-topbar {
  display: flex; align-items: center; justify-content: space-between; min-height: 48px;
  margin: -0.2rem 0 1.1rem; padding: 0.45rem 0.85rem; background: #07100b;
  border: 1px solid rgba(168, 215, 168, 0.16); border-radius: 8px;
}
.ww-brand { display: flex; align-items: center; gap: 0.6rem; color: var(--ww-text); font-weight: 780; font-size: 1.02rem; }
.ww-mark { width: 26px; height: 26px; border-radius: 6px; display: grid; place-items: center; color: #07110c; background: var(--ww-green); font-weight: 900; }
.ww-nav { display: flex; align-items: center; gap: 0.45rem; color: var(--ww-muted); font-size: 0.9rem; font-weight: 690; }
.ww-nav span { padding: 0.36rem 0.64rem; border-radius: 6px; }
.ww-nav .active { color: #07110c; background: var(--ww-green); }

.ww-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; margin-bottom: 0.8rem; }
.ww-kicker, .ww-map-label, .ww-plan-label, .ww-section-label { color: var(--ww-muted); font-size: 0.76rem; font-weight: 740; }
.ww-title { margin: 0.05rem 0 0; color: var(--ww-text); font-size: 2.2rem; line-height: 1.04; font-weight: 820; }
.ww-status-row { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.45rem; }
.ww-status { color: #dcead9; border: 1px solid rgba(168, 215, 168, 0.22); border-radius: 6px; background: rgba(168, 215, 168, 0.08); padding: 0.38rem 0.58rem; font-size: 0.82rem; font-weight: 720; }
.ww-status.gold { color: #fff1bb; border-color: rgba(241, 199, 91, 0.35); background: rgba(241, 199, 91, 0.1); }

.ww-map-head { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; margin: 0 0 0.48rem; }
.ww-map-title { color: var(--ww-text); font-size: 1.04rem; font-weight: 780; }
.ww-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.42rem; }
.ww-pill { display: inline-flex; align-items: center; gap: 0.32rem; padding: 0.24rem 0.42rem; border: 1px solid rgba(168, 215, 168, 0.17); border-radius: 6px; background: rgba(168, 215, 168, 0.08); color: #dcead9; font-size: 0.76rem; font-weight: 720; }
.ww-dot { width: 8px; height: 8px; border-radius: 99px; display: inline-block; }

.ww-panel-title { color: var(--ww-panel); font-size: 1.35rem; font-weight: 820; margin: 0 0 0.25rem; }
.ww-panel-copy { color: var(--ww-muted); font-size: 0.9rem; line-height: 1.42; margin: 0 0 0.8rem; }
.ww-control-band { border: 1px solid rgba(168, 215, 168, 0.18); border-radius: 8px; padding: 0.75rem 0.85rem 0.45rem; margin-bottom: 0.75rem; background: rgba(16, 33, 24, 0.72); }
.ww-source-list { display: grid; gap: 0.5rem; margin-top: 0.85rem; }
.ww-source-item { color: rgba(243, 246, 239, 0.78); border-top: 1px solid rgba(168, 215, 168, 0.14); padding-top: 0.48rem; font-size: 0.82rem; line-height: 1.34; }
.ww-source-item strong { color: var(--ww-text); }
.ww-plan-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.45rem; margin-top: 0.4rem; }
.ww-plan-chip { color: rgba(243, 246, 239, 0.88); background: rgba(168, 215, 168, 0.08); border: 1px dashed rgba(168, 215, 168, 0.2); border-radius: 6px; padding: 0.45rem 0.55rem; font-size: 0.8rem; font-weight: 680; }

.ww-sensor-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.55rem; margin: 0.6rem 0 0.8rem; }
.ww-sensor-card { border: 1px solid rgba(168, 215, 168, 0.14); border-radius: 8px; padding: 0.65rem 0.75rem; background: rgba(16, 33, 24, 0.72); }
.ww-sensor-card strong { color: var(--ww-text); display: block; font-size: 0.95rem; }
.ww-sensor-card span { color: var(--ww-muted); font-size: 0.78rem; font-weight: 700; }

[data-testid="stIFrame"] { border: 1px solid rgba(168, 215, 168, 0.22); border-radius: 8px; overflow: hidden; box-shadow: 0 20px 54px rgba(0, 0, 0, 0.34); }
[data-testid="stCheckbox"] label, [data-testid="stSlider"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label { font-weight: 680; color: var(--ww-text) !important; }
[data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] div { border-color: rgba(168, 215, 168, 0.22) !important; }
[data-testid="stAlert"] { border-radius: 8px; }

@media (max-width: 1050px) {
  .block-container { padding: 0.9rem 0.8rem 1.1rem; }
  .ww-topbar, .ww-hero, .ww-map-head { align-items: flex-start; flex-direction: column; }
  .ww-nav, .ww-status-row, .ww-legend { justify-content: flex-start; }
  .ww-title { font-size: 1.85rem; }
  .ww-sensor-grid { grid-template-columns: 1fr; }
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


def estimate_sensor_reading(site: dict, year: int) -> dict[str, float]:
    """Generate deterministic prototype local sensor values for the selected year."""
    phase = year - 2000
    seasonal = math.sin((phase + site["seed"]) / 3.2)
    elevation_km = site["elevation"] / 1000
    air_temp = 7.8 + phase * 0.045 - elevation_km * 4.1 + seasonal * 0.7
    soil_temp = air_temp + 1.2 - elevation_km * 0.5
    soil_moisture = 34 + elevation_km * 4.5 + seasonal * 4.0 + (site["seed"] % 4) * 1.2
    humidity = 76 + seasonal * 5.5 + (site["seed"] % 3) * 2.0
    wind = 5.0 + elevation_km * 3.4 + abs(seasonal) * 1.7
    return {
        "air_temp": round(air_temp, 1),
        "soil_temp": round(soil_temp, 1),
        "soil_moisture": round(max(8, min(70, soil_moisture)), 1),
        "humidity": round(max(35, min(98, humidity)), 0),
        "wind": round(wind, 1),
        "ph": round(site["ph"] + seasonal * 0.06, 2),
        "carbon": round(site["carbon"] + seasonal * 0.25, 1),
    }


def add_sensor_markers(m: folium.Map, year: int, layers: dict[str, bool]) -> None:
    """Add prototype local weather and soil probe readings as map markers."""
    if not layers["weather_sensors"] and not layers["soil_sensors"]:
        return

    group = folium.FeatureGroup(name="Local sensor prototype", show=True)
    for site in SENSOR_SITES:
        reading = estimate_sensor_reading(site, year)
        rows = ""
        if layers["weather_sensors"]:
            rows += (
                f"<tr><td>Air temp</td><td>{reading['air_temp']} C</td></tr>"
                f"<tr><td>Humidity</td><td>{reading['humidity']}%</td></tr>"
                f"<tr><td>Wind</td><td>{reading['wind']} m/s</td></tr>"
            )
        if layers["soil_sensors"]:
            rows += (
                f"<tr><td>Soil moisture</td><td>{reading['soil_moisture']}%</td></tr>"
                f"<tr><td>Soil temp</td><td>{reading['soil_temp']} C</td></tr>"
                f"<tr><td>pH / SOC</td><td>{reading['ph']} / {reading['carbon']}%</td></tr>"
            )
        popup_html = f"""
        <div style='font-family: sans-serif; min-width: 230px;'>
          <strong>{site['name']}</strong><br>
          <span>{site['zone']} | {site['elevation']} m | prototype sensor</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>{rows}</table>
        </div>
        """
        color = "#a8d7a8" if layers["weather_sensors"] and layers["soil_sensors"] else "#4ea8de"
        if layers["soil_sensors"] and not layers["weather_sensors"]:
            color = "#f1c75b"
        folium.CircleMarker(
            location=[site["lat"], site["lon"]],
            radius=7,
            color="#07110c",
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.94,
            tooltip=f"{site['name']} sensor prototype",
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


def render_header(usage_mode: str, year: int, enabled_count: int, area_name: str) -> None:
    """Render the top application heading."""
    st.markdown(
        f"""
<div class="ww-hero">
  <div>
    <div class="ww-kicker">Stakeholder view | {area_name}</div>
    <div class="ww-title">Forest Intelligence Map</div>
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


def render_layer_panel() -> tuple[int, str, str, dict[str, bool]]:
    """Render stakeholder controls and return selections."""
    st.markdown("<div class='ww-panel-title'>Layers</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='ww-panel-copy'>Choose the evidence layers to show across Berchtesgaden National Park.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='ww-control-band'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-section-label'>TIME</div>", unsafe_allow_html=True)
    year = st.slider("Analysis year", min_value=2000, max_value=2026, value=2024)
    basemap = st.selectbox("Map style", ["Satellite", "Light", "Terrain"], index=0)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-section-label'>REAL DATA LAYERS</div>", unsafe_allow_html=True)
    layers = {
        "alphaearth": st.checkbox("Landscape patterns", value=True),
        "tree_cover": st.checkbox("Tree canopy", value=False),
        "tree_loss": st.checkbox("Tree-cover loss", value=True),
        "water": st.checkbox("Water and wetlands", value=True),
        "habitat": st.checkbox("Land-cover habitat", value=False),
        "fire": st.checkbox("Burned area history", value=False),
        "air_temperature": st.checkbox("Air temperature model", value=False),
        "soil_moisture": st.checkbox("Soil moisture model", value=False),
    }
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-section-label'>LOCAL SENSOR PROTOTYPE</div>", unsafe_allow_html=True)
    layers["weather_sensors"] = st.checkbox("Weather station readings", value=True)
    layers["soil_sensors"] = st.checkbox("Soil probe readings", value=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Custom AOI", expanded=False):
        geojson_input: str = st.text_area("GeoJSON polygon", "", height=124, help="Leave blank to use Berchtesgaden National Park.")
    return year, basemap, geojson_input, layers


def render_sources_panel() -> None:
    """Render concise source notes for stakeholder transparency."""
    st.markdown(
        """
<div class="ww-source-list">
  <div class="ww-source-item"><strong>Protected area boundary</strong><br>WDPA boundary for Berchtesgaden National Park, with local fallback.</div>
  <div class="ww-source-item"><strong>Earth observation layers</strong><br>AlphaEarth, Hansen forest change, JRC water, ESA WorldCover, MODIS burned area.</div>
  <div class="ww-source-item"><strong>Climate and soil context</strong><br>ERA5-Land monthly model fields for air temperature and top-layer soil moisture.</div>
  <div class="ww-source-item"><strong>Local sensors</strong><br>Prototype station values for stakeholder workflow design, ready to replace with live feeds.</div>
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


def render_sensor_summary(year: int) -> None:
    """Show compact prototype sensor averages."""
    readings = [estimate_sensor_reading(site, year) for site in SENSOR_SITES]
    avg_air = round(sum(r["air_temp"] for r in readings) / len(readings), 1)
    avg_soil = round(sum(r["soil_moisture"] for r in readings) / len(readings), 1)
    avg_ph = round(sum(r["ph"] for r in readings) / len(readings), 2)
    st.markdown(
        f"""
<div class="ww-sensor-grid">
  <div class="ww-sensor-card"><span>Prototype weather</span><strong>{avg_air} C avg air temp</strong></div>
  <div class="ww-sensor-card"><span>Prototype soil</span><strong>{avg_soil}% avg moisture</strong></div>
  <div class="ww-sensor-card"><span>Prototype chemistry</span><strong>pH {avg_ph} mean</strong></div>
</div>
        """,
        unsafe_allow_html=True,
    )


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
    if layers["weather_sensors"] or layers["soil_sensors"]:
        labels.append(("Sensors", "#f1c75b"))
    return labels or [("Park boundary", AOI_COLOR)]


def add_selected_layers(m: folium.Map, year: int, aoi: ee.Geometry, layers: dict[str, bool]) -> tuple[int, list[str]]:
    """Add selected Earth Engine and prototype sensor layers."""
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

    add_sensor_markers(m, year, layers)
    return alphaearth_tile_count, notes


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
        year, basemap, geojson_input, layers = render_layer_panel()
        render_sources_panel()
        render_planned_layers()

    enabled_count = sum(1 for enabled in layers.values() if enabled)
    aoi, area_name = get_aoi(geojson_input)

    with left:
        render_header(usage_mode, year, enabled_count, area_name)
        render_sensor_summary(year)

        try:
            center, bounds = get_aoi_view(aoi)
            m = build_map(center, bounds, basemap)
            alphaearth_tile_count, notes = add_selected_layers(m, year, aoi, layers)
            add_aoi_boundary(m, aoi, area_name)
        except Exception as exc:
            show_earth_engine_error("Earth Engine could not render the selected forest layers.", exc)

        folium.LayerControl(position="topright", collapsed=True).add_to(m)
        render_map_heading(year, get_enabled_labels(layers), area_name)
        st_folium(m, width=None, height=760)

        captions = ["Visible map layers are public Earth Engine datasets plus clearly labelled prototype sensor readings."]
        if layers["alphaearth"] and alphaearth_tile_count:
            captions.append(f"AlphaEarth is scoped to {alphaearth_tile_count} tile(s) for the selected AOI.")
        captions.extend(notes)
        st.caption(" ".join(captions))


if __name__ == "__main__":
    main()