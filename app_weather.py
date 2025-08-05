import streamlit as st
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="Whispering Woods Live", layout="wide")

@st.cache_data
def load_data():
    """Load the vegetation and weather dataset.

    The application expects a CSV with columns:
      lat, lon, date, NDVI, NDWI, EVI, Temperature, Rainfall, WindSpeed

    Returns a pandas DataFrame with parsed dates.
    """
    return pd.read_csv("sample_ndvi_weather.csv")

# Load the data and parse dates
df = load_data()
df['date'] = pd.to_datetime(df['date'])

st.title("Whispering Woods Forest Health Dashboard")
st.markdown(
    "This dashboard visualizes vegetation health indicators (NDVI, NDWI, EVI) "
    "for a small area around Königssee. Use the date selector to view readings "
    "for a specific day. Color-coded markers indicate vegetation stress (red), moderate (orange) "
    "or healthy (green) conditions based on the NDVI index."
)

# Date selector for filtering the data
selected_date = st.slider(
    "Select date", 
    min_value=df['date'].min().date(), 
    max_value=df['date'].max().date(),
    value=df['date'].min().date(),
    format="YYYY-MM-DD"
)

# Filter the data for the selected date
filtered = df[df['date'].dt.date == selected_date]

st.subheader(f"Data for {selected_date}")
st.dataframe(
    filtered[
        ['lat','lon','date','NDVI','NDWI','EVI','Temperature','Rainfall','WindSpeed']
    ].reset_index(drop=True)
)

# Function to determine marker color based on NDVI values
def ndvi_color(n):
    if n > 0.6:
        return [0, 128, 0]  # green
    elif n > 0.4:
        return [255, 165, 0]  # orange
    else:
        return [255, 0, 0]  # red

if not filtered.empty:
    # Compute a color for each marker based on NDVI
    filtered = filtered.copy()
    filtered['color'] = filtered['NDVI'].apply(ndvi_color)

    # Define a layer for the scatter plot with weather and vegetation info in tooltip
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=filtered,
        get_position='[lon, lat]',
        get_fill_color='color',
        get_radius=200,
        pickable=True,
    )

    # Center the map on the filtered points
    view_state = pdk.ViewState(
        latitude=filtered['lat'].mean(),
        longitude=filtered['lon'].mean(),
        zoom=12,
        pitch=0,
    )

    # Tooltip with vegetation and weather information
    tooltip = {
        "text": (
            "Lat: {lat}\n" 
            "Lon: {lon}\n" 
            "NDVI: {NDVI}\n"
            "NDWI: {NDWI}\n"
            "EVI: {EVI}\n"
            "Temp: {Temperature} °C\n"
            "Rain: {Rainfall} mm\n"
            "Wind: {WindSpeed} m/s"
        )
    }

    r = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip=tooltip,
    )

    st.pydeck_chart(r)

    # Summary statistics for vegetation indices
    st.subheader("Vegetation Statistics")
    st.write(filtered[['NDVI', 'NDWI', 'EVI']].describe())

    # Summary statistics for weather variables
    st.subheader("Weather Statistics")
    st.write(filtered[['Temperature','Rainfall','WindSpeed']].describe())
else:
    st.write("No data available for the selected date.")
