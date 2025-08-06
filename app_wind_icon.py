import streamlit as st
import pandas as pd
import pydeck as pdk
import math

st.set_page_config(page_title="Whispering Woods Live Wind Icon Overlay", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv("full_ndvi_weather.csv")
    df['date'] = pd.to_datetime(df['date'])
    return df

df = load_data()

st.title("Whispering Woods Forest Health Dashboard with Wind Icons")
st.markdown("""
This dashboard visualizes vegetation health indices (NDVI, NDWI, EVI) and weather variables for a small area around Königssee.
Use the date slider to explore daily readings from July onwards. Markers are color-coded based on the NDVI index (green = healthy, orange = moderate, red = stressed).
Wind direction and speed are shown as arrows rotated according to wind direction; arrow size scales with wind speed.
""")

# Date slider
selected_date = st.slider(
    "Select date",
    min_value=df['date'].min().date(),
    max_value=df['date'].max().date(),
    value=df['date'].max().date(),
    format="YYYY-MM-DD"
)
filtered = df[df['date'].dt.date == selected_date]

# NDVI color function
def ndvi_color(n):
    if n > 0.6:
        return [0, 128, 0]
    elif n > 0.4:
        return [255, 165, 0]
    else:
        return [255, 0, 0]

if not filtered.empty:
    filtered = filtered.copy()
    filtered['color'] = filtered['NDVI'].apply(ndvi_color)
    filtered['icon_data'] = 'arrow'

    # define icon atlas and mapping
    ICON_URL = "https://raw.githubusercontent.com/visgl/deck.gl-data/master/website/icon-atlas.png"
    ICON_MAPPING = {
        "arrow": {"x": 0, "y": 0, "width": 128, "height": 128, "mask": True}
    }

    # scatter layer
    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=filtered,
        get_position=['lon', 'lat'],
        get_fill_color='color',
        get_radius=200,
        pickable=True
    )

    # icon layer for wind
    icon_layer = pdk.Layer(
        "IconLayer",
        data=filtered,
        get_icon='icon_data',
        get_size='WindSpeed',
        size_scale=200,
        get_angle='WindDirection',
        get_position=['lon', 'lat'],
        get_color=[0, 0, 255],
        icon_atlas=ICON_URL,
        icon_mapping=ICON_MAPPING,
        pickable=True
    )

    # view state
    view_state = pdk.ViewState(
        latitude=filtered['lat'].mean(),
        longitude=filtered['lon'].mean(),
        zoom=12,
        pitch=0
    )

    tooltip = {
        "text": "Lat: {lat}\\nLon: {lon}\\nNDVI: {NDVI}\\nNDWI: {NDWI}\\nEVI: {EVI}\\nTemp: {Temperature}\\u00b0C\\nRain: {Rainfall} mm\\nWind: {WindSpeed} m/s\\nDir: {WindDirection}\\u00b0"
    }

    r = pdk.Deck(
        layers=[scatter_layer, icon_layer],
        initial_view_state=view_state,
        tooltip=tooltip
    )
    st.pydeck_chart(r)

    # Show data table
    st.subheader(f"Data for {selected_date}")
    st.dataframe(
        filtered[
            ['lat', 'lon', 'date', 'NDVI', 'NDWI', 'EVI', 'Temperature', 'Rainfall', 'WindSpeed', 'WindDirection']
        ].reset_index(drop=True)
    )

    st.subheader("Vegetation statistics")
    st.write(filtered[['NDVI', 'NDWI', 'EVI']].describe())

    st.subheader("Weather statistics")
    st.write(filtered[['Temperature', 'Rainfall', 'WindSpeed']].describe())
else:
    st.write("No data available for the selected date.")
