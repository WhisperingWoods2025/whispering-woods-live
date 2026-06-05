"""
Streamlit application to visualize Google DeepMind's AlphaEarth embeddings for a chosen
year and area of interest (AOI).  The app uses the Google Earth Engine (GEE)
Python API to fetch the annual satellite embedding dataset and displays the first
three embedding bands (`A00`, `A01` and `A02`) as an RGB image on a Folium map.

The embeddings represent 64-dimensional vectors summarising multi-sensor
observations over a calendar year.  Each band ranges from -1 to 1 and does
not have a direct physical meaning but reveals spatial patterns across the
landscape.  Bands `A00`, `A01` and `A02` are used to
create a false-colour RGB visualisation by mapping them to red, green and blue
channels respectively.

Key features:

* Authenticates to GEE using a service-account and JSON private key stored in
  Streamlit secrets (`EE_SERVICE_ACCOUNT`, `EE_PRIVATE_KEY`, and optionally
  `EE_PROJECT_ID`).  An error is displayed if these secrets are missing or invalid.
* Provides a sidebar for selecting a year (2017-2024) and for optionally
  entering a GeoJSON polygon defining a custom AOI.  If no AOI is supplied,
  the app falls back to a default bounding box around Königssee in Bavaria.
* Fetches the appropriate embedding image from the `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`
  collection for the selected year and displays the first three bands as an
  RGB layer on a Folium map.  The AOI boundary is outlined on top of the map.
* Uses `streamlit-folium` to embed the Folium map in the Streamlit app.
"""

import json
from typing import Optional

import streamlit as st

try:
    import ee  # type: ignore
except ImportError as exc:
    raise RuntimeError("The earthengine-api must be installed to run this app.") from exc

try:
    import geemap.foliumap as geemap  # type: ignore
except ImportError as exc:
    raise RuntimeError(
        "The geemap package must be installed to run this app.  See requirements.txt."
    ) from exc

try:
    from streamlit_folium import st_folium  # type: ignore
except ImportError as exc:
    raise RuntimeError(
        "The streamlit-folium package must be installed to run this app.  See requirements.txt."
    ) from exc


def _read_secret(name: str) -> Optional[str]:
    """Read a string secret, returning None when it is missing or blank."""
    value = st.secrets.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


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
    """Return the AOI geometry from a GeoJSON string or a default bounding box.

    Parameters
    ----------
    geojson_str: str
        A JSON string containing a GeoJSON polygon.  If empty or invalid the
        default bounding box around Königssee (Germany) is used.

    Returns
    -------
    ee.Geometry
        A geometry representing the AOI.
    """

    if geojson_str:
        try:
            geo = json.loads(geojson_str)
            # Expecting a Polygon geometry
            return ee.Geometry(geo)
        except Exception:
            st.warning("Invalid GeoJSON provided. Falling back to default AOI.")

    # Default bounding box around Königssee (approximate lat/long).
    # Coordinates order: [lng, lat]
    default_coords = [
        [12.95, 47.55],
        [12.95, 47.65],
        [13.05, 47.65],
        [13.05, 47.55],
        [12.95, 47.55],
    ]
    return ee.Geometry.Polygon([default_coords])


def get_embedding_image(year: int) -> ee.Image:
    """Retrieve the first image for the given year from the embedding collection.

    The Satellite Embedding V1 collection contains annual images from 2017-2024
    where the start and end times correspond to the calendar year.  This
    function filters the collection by year and returns the first image.
    """

    collection = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL").filter(
        ee.Filter.calendarRange(year, year, "year")
    )
    image = collection.first()
    return image


def add_aoi_boundary(m: geemap.Map, aoi: ee.Geometry) -> None:
    """Add AOI boundary to a map as a non-filled outline."""
    outline = ee.Image().paint(aoi, 0, 2)  # value 0 (black), width 2 pixels
    m.add_layer(outline, {"palette": ["red"], "opacity": 1}, "AOI")


def main() -> None:
    """Render the Streamlit user interface and map."""
    st.set_page_config(page_title="AlphaEarth Embeddings Explorer", layout="wide")
    st.title("AlphaEarth Embeddings Explorer")

    # Initialise Earth Engine
    _init_ee_cached()

    # Sidebar controls
    with st.sidebar:
        st.header("Controls")
        year = st.selectbox(
            "Select year", options=list(range(2017, 2025)), index=2024 - 2017
        )
        geojson_input: str = st.text_area(
            "Optional AOI GeoJSON polygon", "", height=120, help="Paste a GeoJSON polygon here to define a custom AOI."
        )

    # Retrieve AOI
    aoi = get_aoi(geojson_input)

    # Retrieve embedding image for selected year
    image = get_embedding_image(year)
    if not image:
        st.error(f"No embedding available for {year}.")
        return

    # Visualisation parameters: map A00->R, A01->G, A02->B.  Data range is [-1,1].
    rgb_vis = {"bands": ["A00", "A01", "A02"], "min": -1, "max": 1}

    # Create map centered on the AOI
    centroid = aoi.centroid().coordinates().getInfo()
    lat, lon = centroid[1], centroid[0]
    m = geemap.Map(center=[lat, lon], zoom=11)
    m.add_layer(image, rgb_vis, f"{year} Embedding RGB")
    add_aoi_boundary(m, aoi)
    m.add_layer_control()

    st.subheader("Visualization")
    st.markdown(
        """
        The RGB image below uses the first three embedding bands (`A00`, `A01`, `A02`) to reveal
        spatial patterns across the selected area.  Each band ranges from -1 to 1.
        """
    )
    # Display the map
    st_folium(m, width=None, height=600)


if __name__ == "__main__":
    main()
