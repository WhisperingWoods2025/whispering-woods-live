"""AlphaEarth Embedding Year Difference Explorer.

Streamlit app that compares AlphaEarth embedding bands between two years.

Allows selecting two years (2017–2024), an optional area of interest (AOI) via GeoJSON,
and three embedding bands to visualise. The app displays RGB maps for each selected
year and a difference map (band1 difference -> red, band2 difference -> green,
band3 difference -> blue). Differences are computed as Year2 minus Year1.

Bands are from 'A00' to 'A63'; each band ranges from -1 to 1 in the underlying images
【749556096114857†L129-L147】. The difference image therefore ranges from -2 to 2, but values
near zero indicate little change.

The app requires Google Earth Engine authentication via service account secrets 
(`EE_SERVICE_ACCOUNT`, `EE_PRIVATE_KEY`).
"""

import streamlit as st
import geemap
import ee
from streamlit_folium import st_folium

# Cache Earth Engine initialisation
@st.cache_resource
def _init_ee_cached() -> None:
    """Initialise the Earth Engine API using service-account credentials from Streamlit secrets."""
    service_account = st.secrets.get("EE_SERVICE_ACCOUNT")
    private_key = st.secrets.get("EE_PRIVATE_KEY")
    if not service_account or not private_key:
        st.error("Earth Engine service-account credentials not found in Streamlit secrets.")
        raise ValueError("Missing Earth Engine credentials")
    credentials = ee.ServiceAccountCredentials(service_account, private_key)
    try:
        ee.Initialize(credentials)
    except Exception as e:
        st.error(f"Failed to initialise Earth Engine: {e}")
        raise

def get_aoi(geojson_str: str) -> ee.Geometry:
    """Return an AOI geometry from GeoJSON or a default bounding box if empty."""
    if geojson_str:
        try:
            feature = geemap.geojson_to_ee(geojson_str)
            geom = feature.geometry()
            return geom
        except Exception:
            st.warning("Invalid GeoJSON provided. Reverting to default AOI.")
    # Default AOI: bounding box around Königssee
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

def add_aoi_boundary(m: geemap.Map, aoi: ee.Geometry) -> None:
    """Add AOI boundary to a map as a non-filled outline."""
    outline = ee.Image().paint(aoi, 0, 2)
    m.add_layer(outline, {"palette": ["yellow"], "opacity": 1}, "AOI boundary")

def main() -> None:
    """Render the Streamlit interface for exploring embedding differences."""
    st.set_page_config(page_title="AlphaEarth Embedding Difference Explorer", layout="wide")
    st.title("AlphaEarth Embedding Difference Explorer")

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
        lat, lon = centroid[1], centroid[0]
        m1 = geemap.Map(center=[lat, lon], zoom=10)
        m1.add_layer(img1, rgb_vis_year, f"{year1} Embedding")
        add_aoi_boundary(m1, aoi)
        m1.add_layer_control()
        m2 = geemap.Map(center=[lat, lon], zoom=10)
        m2.add_layer(img2, rgb_vis_year, f"{year2} Embedding")
        add_aoi_boundary(m2, aoi)
        m2.add_layer_control()
        diff_img = compute_difference(img1, img2, selected_bands)
        m_diff = geemap.Map(center=[lat, lon], zoom=10)
        m_diff.add_layer(diff_img, rgb_vis_diff, f"Difference {year2}-{year1}")
        add_aoi_boundary(m_diff, aoi)
        m_diff.add_layer_control()
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
