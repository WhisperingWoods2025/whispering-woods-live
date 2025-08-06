import streamlit as st
import pandas as pd
import pydeck as pdk
import math

st.set_page_config(page_title="Whispering Woods Live Wind Overlay", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv("full_ndvi_weather.csv")
    df['date'] = pd.to_datetime(df['date'])
    return df

df = load_data()

st.title("Whispering Woods Forest Health Dashboard with Wind Overlay")
st.markdown("""
This dashboard visualizes vegetation health indices (NDVI, NDWI, EVI) and weather variables for a small area around Königssee.
Use the date slider to explore daily readings from July onwards. Markers are color-coded based on the NDVI index (green = healthy, orange = moderate, red = stressed).
Wind direction and speed are shown as lines radiating from each location.
""")

# Date slider for filtering the data
selected_date = st.slider(
    "Select date",
    min_value=df['date'].min().date(),
    max_value=df['date'].max().date(),
    value=df['date'].min().date(),
    format="YYYY-MM-DD"
)

# Filter the data for the selected date
filtered = df[df['date'].dt.date == selected_date]

# Function to determine marker color based on NDVI values
def ndvi_color(n):
    if n > 0.6:
        return [0, 128, 0]  # green
    elif n > 0.4:
        return [255, 165, 0]  # orange
    else:
        return [255, 0, 0]  # red

if not filtered.empty:
    filtered = filtered.copy()
    filtered['color'] = filtered['NDVI'].apply(ndvi_color)
    # Compute wind vector end points based on wind speed and direction
    scale = 0.0005  # scaling factor for arrow length
    # Convert wind direction to radians
    filtered['theta'] = filtered['WindDirection'].apply(lambda d: math.radians(d))
    filtered['end_lon'] = filtered['lon'] + filtered['WindSpeed'] * scale * filtered['theta'].apply(lambda x: math.sin(x))
    filtered['end_lat'] = filtered['lat'] + filtered['WindSpeed'] * scale * filtered['theta'].apply(lambda x: math.cos(x))

    # Scatter plot layer for vegetation points
    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=filtered,
        get_position=['lon', 'lat'],
        get_fill_color='color',
        get_radius=200,
        pickable=True,
    )

    # Line layer for wind vectors
    wind_layer = pdk.Layer(
        "LineLayer",
        data=filtered,
        get_source_position=['lon', 'lat'],
        get_target_position=['end_lon', 'end_lat'],
        get_width=2,
        get_color=[0, 0, 255],
        pickable=False,
    )

    # Set the initial view state centered on the mean coordinates
    view_state = pdk.ViewState(
        latitude=filtered['lat'].mean(),
        longitude=filtered['lon'].mean(),
        zoom=12,
        pitch=0,
    )

    # Tooltip to display vegetation and weather information
    tooltip = {
        "text": (
            "Lat: {lat}\n"
            "Lon: {lon}\n"
            "NDVI: {NDVI}\n"
            "NDWI: {NDWI}\n"
            "EVI: {EVI}\n"
            "Temp: {Temperature} \u00b0C\n"
            "Rain: {Rainfall} mm\n"
            "Wind: {WindSpeed} m/s\n"
            "Dir: {WindDirection}\u00b0"
        )
    }

    r = pdk.Deck(
        layers=[scatter_layer, wind_layer],
        initial_view_state=view_state,
        tooltip=tooltip,
    )

    st.pydeck_chart(r)

    # Display data table
    st.subheader(f"Data for {selected_date}")
    st.dataframe(
        filtered[
            ['lat', 'lon', 'date', 'NDVI', 'NDWI', 'EVI', 'Temperature', 'Rainfall', 'WindSpeed', 'WindDirection']
        ].reset_index(drop=True)
    )

    # Summary statistics for vegetation indices
    st.subheader("Vegetation statistics")
    st.write(filtered[['NDVI', 'NDWI', 'EVI']].describe())

    # Summary statistics for weather variables
    st.subheader("Weather statistics")
    st.write(filtered[['Temperature', 'Rainfall', 'WindSpeed']].describe())
else:
    st.write("No data available for the selected date.")
