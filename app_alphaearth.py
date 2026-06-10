"""
Streamlit application to visualize Google DeepMind's AlphaEarth embeddings for a chosen
year and area of interest (AOI). The app uses the Google Earth Engine (GEE)
Python API to fetch the annual satellite embedding dataset and displays three
embedding bands as an RGB image on a Folium map.

The embeddings represent 64-dimensional vectors summarising multi-sensor
observations over a calendar year. Each band ranges from -1 to 1 and does
not have a direct physical meaning but reveals spatial patterns across the
landscape. Bands `A01`, `A16` and `A09` are used to create a false-colour RGB
visualisation, following the public Earth Engine catalog example.

Key features:

* Authenticates to GEE using a service-account and JSON private key stored in
  Streamlit secrets (`EE_SERVICE_ACCOUNT`, `EE_PRIVATE_KEY`, and optionally
  `EE_PROJECT_ID`). An error is displayed if these secrets are missing or invalid.
* Enforces a no-cost runtime guard. If `EE_USAGE_MODE` is set to a commercial,
  paid, or billable mode, the app stops before Earth Engine initialisation.
* Provides a sidebar for selecting a year (2017-2024) and for optionally
  entering a GeoJSON polygon defining a custom AOI. If no AOI is supplied,
  the app falls back to a default bounding box around Koenigssee in Bavaria.
* Fetches embedding tiles from the `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`
  collection for the selected year and AOI, mosaics them, and displays the
  selected bands as an RGB layer on a Folium map. The AOI boundary is outlined
  on top of the map.
* Uses `streamlit-folium` to embed the Folium map in the Streamlit app.
"""

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

_COSTED_USAGE_MODES = {
    "billable",
    "commercial",
    "enterprise",
    "government_operational",
    "paid",
    "production_paid",
}


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


def init_ee() -> None:
    """Initialise Earth Engine using service-account credentials from Streamlit secrets."""

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


@st.cache_resource(show_spinner=False)
def _init_ee_cached() -> None:
    """Wrapper for caching Earth Engine initialisation."""
    init_ee()


def get_aoi(geojson_str: str) -> ee.Geometry:
    """Return the AOI geometry from a GeoJSON string or a default bounding box."""

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
            st.warning("Invalid GeoJSON provided. Falling back to default AOI.")

    # Default bounding box around Koenigssee (approximate lat/long).
    default_coords = [
        [12.95, 47.55],
        [12.95, 47.65],
        [13.05, 47.65],
        [13.05, 47.55],
        [12.95, 47.55],
    ]
    return ee.Geometry.Polygon([default_coords])


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


def add_ee_layer(m: folium.Map, image: ee.Image, vis_params: dict, name: str) -> None:
    """Add an Earth Engine image as a Folium tile layer."""
    map_id = image.getMapId(vis_params)
    folium.TileLayer(
        tiles=map_id["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name=name,
        overlay=True,
        control=True,
    ).add_to(m)


def add_aoi_boundary(m: folium.Map, aoi: ee.Geometry, color: str = "red") -> None:
    """Add AOI boundary to a Folium map as a non-filled outline."""
    folium.GeoJson(
        aoi.getInfo(),
        name="AOI boundary",
        style_function=lambda _: {"color": color, "weight": 2, "fillOpacity": 0},
    ).add_to(m)


def main() -> None:
    """Render the Streamlit user interface and map."""
    st.set_page_config(page_title="AlphaEarth Embeddings Explorer", layout="wide")
    st.title("AlphaEarth Embeddings Explorer")
    usage_mode = enforce_no_cost_guardrail()
    st.caption(
        f"No-cost mode: Earth Engine usage is treated as `{usage_mode}`; "
        "this app only reads public datasets and renders map layers."
    )

    _init_ee_cached()

    with st.sidebar:
        st.header("Controls")
        year = st.selectbox(
            "Select year", options=list(range(2017, 2025)), index=2024 - 2017
        )
        geojson_input: str = st.text_area(
            "Optional AOI GeoJSON polygon",
            "",
            height=120,
            help="Paste a GeoJSON polygon here to define a custom AOI.",
        )

    aoi = get_aoi(geojson_input)

    try:
        image, tile_count = get_embedding_image(year, aoi)
        centroid = aoi.centroid().coordinates().getInfo()
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not prepare the selected AOI/year.", exc)

    rgb_vis = {"bands": DEFAULT_RGB_BANDS, "min": -0.3, "max": 0.3}

    lat, lon = centroid[1], centroid[0]
    m = folium.Map(location=[lat, lon], zoom_start=11, tiles="OpenStreetMap")
    try:
        add_ee_layer(m, image, rgb_vis, f"{year} Embedding RGB")
        add_aoi_boundary(m, aoi)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not render the map layer.", exc)

    folium.LayerControl().add_to(m)

    st.subheader("Visualization")
    st.caption(f"Using {tile_count} AlphaEarth tile(s) for the selected AOI.")
    st.markdown(
        """
        The RGB image below uses embedding bands `A01`, `A16`, and `A09` to reveal
        spatial patterns across the selected area. Each band ranges from -1 to 1.
        """
    )
    st_folium(m, width=None, height=600)


if __name__ == "__main__":
    main()