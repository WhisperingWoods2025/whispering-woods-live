"""AlphaEarth Embedding Year Difference Explorer.

Streamlit app that compares AlphaEarth embedding bands between two years.

Allows selecting two years (2017-2024), an optional area of interest (AOI) via GeoJSON,
and three embedding bands to visualise. The app displays RGB maps for each selected
year and a difference map (band1 difference -> red, band2 difference -> green,
band3 difference -> blue). Differences are computed as Year2 minus Year1.

Bands are from 'A00' to 'A63'; each band ranges from -1 to 1 in the underlying images.
The difference image therefore ranges from -2 to 2, but values near zero indicate little change.

The app requires Google Earth Engine authentication via service account secrets
(`EE_SERVICE_ACCOUNT`, `EE_PRIVATE_KEY`, and optionally `EE_PROJECT_ID`) and stops
if `EE_USAGE_MODE` is set to a commercial, paid, or billable mode.
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

    # Default AOI: bounding box around Koenigssee
    default_coords = [
        [12.95, 47.55],
        [13.05, 47.55],
        [13.05, 47.62],
        [12.95, 47.62],
        [12.95, 47.55],
    ]
    return ee.Geometry.Polygon([default_coords])


def get_embedding_image(year: int) -> ee.Image:
    """Retrieve the first image for the given year from the satellite embedding collection."""
    collection = (
        ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
        .filter(ee.Filter.calendarRange(year, year, "year"))
    )
    image = collection.first()
    return image


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
    ).add_to(m)


def add_aoi_boundary(m: folium.Map, aoi: ee.Geometry, color: str = "yellow") -> None:
    """Add AOI boundary to a Folium map as a non-filled outline."""
    folium.GeoJson(
        aoi.getInfo(),
        name="AOI boundary",
        style_function=lambda _: {"color": color, "weight": 2, "fillOpacity": 0},
    ).add_to(m)


def build_map(center: list[float], zoom: int = 10) -> folium.Map:
    """Create a Folium map with consistent defaults."""
    return folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")


def main() -> None:
    """Render the Streamlit interface for exploring embedding differences."""
    st.set_page_config(page_title="AlphaEarth Embedding Difference Explorer", layout="wide")
    st.title("AlphaEarth Embedding Difference Explorer")
    usage_mode = enforce_no_cost_guardrail()
    st.caption(
        f"No-cost mode: Earth Engine usage is treated as `{usage_mode}`; "
        "this app only reads public datasets and renders map layers."
    )

    _init_ee_cached()

    with st.sidebar:
        st.header("Controls")
        year1 = st.selectbox("Year 1", options=list(range(2017, 2025)), index=0)
        year2 = st.selectbox("Year 2", options=list(range(2017, 2025)), index=7)
        if year2 < year1:
            st.warning("Year 2 should be greater than or equal to Year 1.")
        geojson_input = st.text_area(
            "Optional AOI GeoJSON polygon",
            "",
            height=120,
            help="Paste a GeoJSON polygon to define a custom AOI; leave blank for default.",
        )
        band_options = [f"A{str(i).zfill(2)}" for i in range(64)]
        selected_bands = st.multiselect(
            "Select 3 bands (RGB)", band_options, default=band_options[:3]
        )
        if len(selected_bands) != 3:
            st.warning("Please select exactly 3 bands.")

    if len(selected_bands) == 3:
        aoi = get_aoi(geojson_input)
        img1 = get_embedding_image(year1)
        img2 = get_embedding_image(year2)
        if not img1 or not img2:
            st.error("Could not retrieve embedding images for selected years.")
            return
        rgb_vis_year = {"bands": selected_bands, "min": -1, "max": 1}
        rgb_vis_diff = {"bands": selected_bands, "min": -2, "max": 2}
        centroid = aoi.centroid().coordinates().getInfo()
        center = [centroid[1], centroid[0]]

        m1 = build_map(center)
        add_ee_layer(m1, img1, rgb_vis_year, f"{year1} Embedding")
        add_aoi_boundary(m1, aoi)
        folium.LayerControl().add_to(m1)

        m2 = build_map(center)
        add_ee_layer(m2, img2, rgb_vis_year, f"{year2} Embedding")
        add_aoi_boundary(m2, aoi)
        folium.LayerControl().add_to(m2)

        diff_img = compute_difference(img1, img2, selected_bands)
        m_diff = build_map(center)
        add_ee_layer(m_diff, diff_img, rgb_vis_diff, f"Difference {year2}-{year1}")
        add_aoi_boundary(m_diff, aoi)
        folium.LayerControl().add_to(m_diff)

        st.subheader(f"Embedding for {year1}")
        st_folium(m1, width=None, height=350, key="map1")
        st.subheader(f"Embedding for {year2}")
        st_folium(m2, width=None, height=350, key="map2")
        st.subheader(f"Difference ({year2} - {year1})")
        st_folium(m_diff, width=None, height=350, key="map_diff")
        st.markdown(
            "The difference map uses the selected bands, with red representing band 1 difference, "
            "green band 2 difference and blue band 3 difference. Values closer to zero indicate little change."
        )


if __name__ == "__main__":
    main()
