"""Streamlit app that compares AlphaEarth embedding bands between two years."""

import json
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
DEFAULT_RGB_BANDS = ["A01", "A16", "A09"]
AOI_COLOR = "#D7A84E"
DIFF_COLOR = "#B96F4C"

_COSTED_USAGE_MODES = {
    "billable",
    "commercial",
    "enterprise",
    "government_operational",
    "paid",
    "production_paid",
}


def inject_theme_css() -> None:
    """Apply a compact visual system on top of Streamlit defaults."""
    st.markdown(
        """
<style>
:root {
  --ww-bg: #0c1410;
  --ww-panel: #121d17;
  --ww-panel-2: #17241d;
  --ww-line: #284033;
  --ww-text: #eef4ed;
  --ww-muted: #9faf9f;
  --ww-accent: #8ebf75;
  --ww-gold: #d7a84e;
  --ww-copper: #b96f4c;
}

[data-testid="stAppViewContainer"] {
  background: var(--ww-bg);
  color: var(--ww-text);
}

[data-testid="stHeader"] {
  background: rgba(12, 20, 16, 0.92);
  border-bottom: 1px solid rgba(142, 191, 117, 0.12);
}

.block-container {
  max-width: 1540px;
  padding: 2.25rem 2.5rem 2rem;
}

[data-testid="stSidebar"] {
  background: #101914;
  border-right: 1px solid var(--ww-line);
}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
  gap: 0.85rem;
}

[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p {
  color: var(--ww-text);
}

[data-testid="stSidebar"] label {
  font-size: 0.9rem;
  font-weight: 650;
}

[data-testid="stSelectbox"] div,
[data-testid="stMultiSelect"] div,
[data-testid="stTextArea"] textarea {
  border-color: rgba(142, 191, 117, 0.18) !important;
}

[data-testid="stTextArea"] textarea {
  min-height: 132px;
}

.ww-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1.5rem;
  margin-bottom: 1.35rem;
}

.ww-kicker,
.ww-side-kicker,
.ww-metric-label,
.ww-map-label {
  color: var(--ww-muted);
  font-size: 0.78rem;
  font-weight: 700;
}

.ww-title {
  margin: 0.1rem 0 0;
  color: var(--ww-text);
  font-size: 2.55rem;
  line-height: 1.05;
  font-weight: 760;
}

.ww-status-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
}

.ww-status {
  border: 1px solid rgba(142, 191, 117, 0.22);
  border-radius: 6px;
  color: #dfead9;
  background: rgba(142, 191, 117, 0.08);
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.42rem 0.62rem;
}

.ww-status.gold {
  border-color: rgba(215, 168, 78, 0.36);
  background: rgba(215, 168, 78, 0.12);
}

.ww-side-title {
  color: var(--ww-text);
  font-size: 1.35rem;
  font-weight: 760;
  margin: 0.3rem 0 0.1rem;
}

.ww-side-note {
  color: var(--ww-muted);
  font-size: 0.82rem;
  line-height: 1.45;
  border-left: 2px solid var(--ww-gold);
  padding: 0.1rem 0 0.1rem 0.7rem;
}

.ww-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0.75rem 0 1rem;
}

.ww-metric {
  background: linear-gradient(180deg, rgba(23, 36, 29, 0.96), rgba(18, 29, 23, 0.96));
  border: 1px solid rgba(142, 191, 117, 0.14);
  border-radius: 8px;
  padding: 0.85rem 0.9rem;
}

.ww-metric strong {
  display: block;
  color: var(--ww-text);
  font-size: 1.1rem;
  line-height: 1.2;
  margin-top: 0.25rem;
}

.ww-map-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 1.15rem 0 0.6rem;
}

.ww-map-title {
  color: var(--ww-text);
  font-size: 1.12rem;
  font-weight: 760;
}

.ww-band-list {
  color: var(--ww-muted);
  font-size: 0.88rem;
}

.ww-band-list code {
  color: #bfe5ad;
  background: rgba(142, 191, 117, 0.12);
  border: 1px solid rgba(142, 191, 117, 0.15);
  border-radius: 5px;
  padding: 0.12rem 0.32rem;
}

[data-testid="stIFrame"] {
  border: 1px solid rgba(142, 191, 117, 0.2);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28);
}

[data-testid="stAlert"] {
  border-radius: 8px;
}

@media (max-width: 900px) {
  .block-container {
    padding: 1.25rem 1rem 1.5rem;
  }

  .ww-header,
  .ww-map-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .ww-status-row {
    justify-content: flex-start;
  }

  .ww-title {
    font-size: 2rem;
  }

  .ww-metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
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
            "Earth Engine Resource Writer (`roles/earthengine.writer`) on this project. "
            "Keep Service Usage Consumer too. This role enables map tile creation; this app "
            "still does not export files, write Earth Engine assets, or create cloud resources."
        )
    if "earthengine.computations.create" in error_text:
        return (
            "The service account needs an Earth Engine project role. Add Earth Engine Resource "
            "Viewer (`roles/earthengine.viewer`) or Earth Engine Resource Writer "
            "(`roles/earthengine.writer`) on this project, and keep Service Usage Consumer."
        )
    return (
        "This is usually a project permission, Earth Engine registration, API enablement, "
        "or dataset/AOI availability issue. The app stopped before rendering the map."
    )


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


@st.cache_resource(show_spinner=False)
def _init_ee_cached() -> None:
    """Initialise the Earth Engine API using service-account credentials from Streamlit secrets."""
    service_account = _read_secret("EE_SERVICE_ACCOUNT")
    private_key_secret = _read_secret("EE_PRIVATE_KEY")
    project_id = _read_secret("EE_PROJECT_ID")

    if not service_account or not private_key_secret:
        st.error(
            "Earth Engine credentials not found. Add EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY "
            "to Streamlit secrets."
        )
        st.caption(
            "EE_PRIVATE_KEY should be the full JSON key file contents. EE_PROJECT_ID is optional "
            "when the JSON key includes project_id."
        )
        st.stop()

    try:
        key_data, project_id = _build_service_account_key_data(
            service_account, private_key_secret, project_id
        )
        credentials = ee.ServiceAccountCredentials(service_account, key_data=key_data)
        if project_id:
            ee.Initialize(credentials, project=project_id)
        else:
            ee.Initialize(credentials)
    except Exception as exc:
        st.error("Failed to initialise Earth Engine with the configured service account.")
        st.caption(
            "Confirm the Cloud project is registered for Earth Engine, the API is enabled, "
            "and the service-account JSON key matches EE_SERVICE_ACCOUNT."
        )
        st.caption(str(exc))
        st.stop()


def get_aoi(geojson_str: str) -> ee.Geometry:
    """Return an AOI geometry from GeoJSON or a default bounding box if empty."""
    if geojson_str:
        try:
            geo = json.loads(geojson_str)
            geo_type = geo.get("type")
            if geo_type == "FeatureCollection":
                return ee.FeatureCollection(geo).geometry()
            if geo_type == "Feature":
                return ee.Geometry(geo["geometry"])
            return ee.Geometry(geo)
        except Exception:
            st.warning("Invalid GeoJSON provided. Reverting to default AOI.")

    default_coords = [
        [12.95, 47.55],
        [13.05, 47.55],
        [13.05, 47.62],
        [12.95, 47.62],
        [12.95, 47.55],
    ]
    return ee.Geometry.Polygon([default_coords])


def get_aoi_view(aoi: ee.Geometry) -> tuple[list[float], list[list[float]]]:
    """Return center and Leaflet bounds for the selected AOI."""
    centroid = aoi.centroid().coordinates().getInfo()
    bounds_coords = aoi.bounds().coordinates().getInfo()[0]
    return [centroid[1], centroid[0]], [[lat, lon] for lon, lat in bounds_coords]


def get_embedding_image(year: int, aoi: ee.Geometry) -> tuple[ee.Image, int]:
    """Retrieve and mosaic embedding tiles for the given year and AOI."""
    collection = (
        ee.ImageCollection(EMBEDDING_COLLECTION_ID)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .filterBounds(aoi)
    )
    tile_count = int(collection.size().getInfo())
    if tile_count == 0:
        raise ValueError(f"No AlphaEarth embedding tiles were found for {year} in this AOI.")
    return collection.mosaic().clip(aoi), tile_count


def compute_difference(image1: ee.Image, image2: ee.Image, bands: list[str]) -> ee.Image:
    """Compute difference image (image2 - image1) for the selected bands."""
    band_diffs = []
    for band in bands:
        diff = image2.select(band).subtract(image1.select(band))
        band_diffs.append(diff.rename(band))
    return ee.Image.cat(band_diffs)


def add_ee_layer(m: folium.Map, image: ee.Image, vis_params: dict, name: str) -> None:
    """Add an Earth Engine image as a Folium tile layer."""
    map_id = image.getMapId(vis_params)
    folium.TileLayer(
        tiles=map_id["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name=name,
        overlay=True,
        control=True,
        opacity=0.88,
    ).add_to(m)


def add_aoi_boundary(m: folium.Map, aoi: ee.Geometry, color: str = AOI_COLOR) -> None:
    """Add AOI boundary to a Folium map as a non-filled outline."""
    folium.GeoJson(
        aoi.getInfo(),
        name="AOI boundary",
        style_function=lambda _: {
            "color": color,
            "weight": 2.5,
            "fillOpacity": 0,
            "opacity": 0.95,
        },
    ).add_to(m)


def build_map(center: list[float], bounds: list[list[float]]) -> folium.Map:
    """Create the map surface and focus it on the AOI."""
    m = folium.Map(location=center, zoom_start=11, tiles=None, control_scale=True)
    folium.TileLayer("CartoDB positron", name="Base map", control=False).add_to(m)
    m.fit_bounds(bounds, padding=(24, 24))
    return m


def render_sidebar() -> tuple[int, int, str, list[str]]:
    """Render controls and return selected inputs."""
    with st.sidebar:
        st.markdown(
            """
<div class="ww-side-kicker">Whispering Woods</div>
<div class="ww-side-title">Change Explorer</div>
            """,
            unsafe_allow_html=True,
        )
        year1 = st.selectbox("Baseline year", options=list(range(2017, 2025)), index=0)
        year2 = st.selectbox("Comparison year", options=list(range(2017, 2025)), index=7)
        band_options = [f"A{str(i).zfill(2)}" for i in range(64)]
        selected_bands = st.multiselect("RGB bands", band_options, default=DEFAULT_RGB_BANDS)
        geojson_input = st.text_area(
            "AOI GeoJSON",
            "",
            height=132,
            help="Paste a GeoJSON polygon to replace the default AOI.",
        )
        st.markdown(
            "<div class='ww-side-note'>Default AOI: Koenigssee, Bavaria.</div>",
            unsafe_allow_html=True,
        )
    return year1, year2, geojson_input, selected_bands


def render_header(usage_mode: str, year1: int, year2: int) -> None:
    """Render the top application heading."""
    st.markdown(
        f"""
<div class="ww-header">
  <div>
    <div class="ww-kicker">Whispering Woods</div>
    <div class="ww-title">AlphaEarth Change</div>
  </div>
  <div class="ww-status-row">
    <div class="ww-status">Earth Engine live</div>
    <div class="ww-status gold">{usage_mode}</div>
    <div class="ww-status">{year1} to {year2}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_grid(
    year1: int,
    year2: int,
    tile_count1: int,
    tile_count2: int,
    selected_bands: list[str],
    usage_mode: str,
) -> None:
    """Render compact context metrics."""
    bands = " / ".join(selected_bands)
    st.markdown(
        f"""
<div class="ww-metric-grid">
  <div class="ww-metric"><div class="ww-metric-label">Window</div><strong>{year1} to {year2}</strong></div>
  <div class="ww-metric"><div class="ww-metric-label">AOI Tiles</div><strong>{tile_count1} / {tile_count2}</strong></div>
  <div class="ww-metric"><div class="ww-metric-label">RGB Bands</div><strong>{bands}</strong></div>
  <div class="ww-metric"><div class="ww-metric-label">Usage Mode</div><strong>{usage_mode}</strong></div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_map_heading(label: str, title: str, bands: list[str]) -> None:
    """Render a map section heading."""
    band_markup = " ".join(f"<code>{band}</code>" for band in bands)
    st.markdown(
        f"""
<div class="ww-map-head">
  <div>
    <div class="ww-map-label">{label}</div>
    <div class="ww-map-title">{title}</div>
  </div>
  <div class="ww-band-list">{band_markup}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Render the Streamlit interface for exploring embedding differences."""
    st.set_page_config(page_title="Whispering Woods AlphaEarth Change", layout="wide")
    inject_theme_css()

    usage_mode = enforce_no_cost_guardrail()
    _init_ee_cached()
    year1, year2, geojson_input, selected_bands = render_sidebar()
    render_header(usage_mode, year1, year2)

    if year2 < year1:
        st.warning("Comparison year is earlier than the baseline year.")
    if len(selected_bands) != 3:
        st.warning("Select exactly 3 RGB bands.")
        st.stop()

    aoi = get_aoi(geojson_input)
    try:
        img1, tile_count1 = get_embedding_image(year1, aoi)
        img2, tile_count2 = get_embedding_image(year2, aoi)
        center, bounds = get_aoi_view(aoi)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not prepare the selected AOI/years.", exc)

    render_metric_grid(year1, year2, tile_count1, tile_count2, selected_bands, usage_mode)

    rgb_vis_year = {"bands": selected_bands, "min": -0.3, "max": 0.3}
    rgb_vis_diff = {"bands": selected_bands, "min": -0.2, "max": 0.2}

    try:
        m1 = build_map(center, bounds)
        add_ee_layer(m1, img1, rgb_vis_year, f"{year1} embedding")
        add_aoi_boundary(m1, aoi)
        folium.LayerControl(position="topright", collapsed=True).add_to(m1)

        m2 = build_map(center, bounds)
        add_ee_layer(m2, img2, rgb_vis_year, f"{year2} embedding")
        add_aoi_boundary(m2, aoi)
        folium.LayerControl(position="topright", collapsed=True).add_to(m2)

        diff_img = compute_difference(img1, img2, selected_bands)
        m_diff = build_map(center, bounds)
        add_ee_layer(m_diff, diff_img, rgb_vis_diff, f"Difference {year2}-{year1}")
        add_aoi_boundary(m_diff, aoi, DIFF_COLOR)
        folium.LayerControl(position="topright", collapsed=True).add_to(m_diff)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not render one of the map layers.", exc)

    left, right = st.columns(2, gap="large")
    with left:
        render_map_heading("Baseline", f"Embedding, {year1}", selected_bands)
        st_folium(m1, width=None, height=430, key="map1")
    with right:
        render_map_heading("Comparison", f"Embedding, {year2}", selected_bands)
        st_folium(m2, width=None, height=430, key="map2")

    render_map_heading("Delta", f"Change, {year2} minus {year1}", selected_bands)
    st_folium(m_diff, width=None, height=560, key="map_diff")


if __name__ == "__main__":
    main()