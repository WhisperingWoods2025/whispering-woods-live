import streamlit as st
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="Whispering Woods Forest Health Dashboard with Wind Arrows", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv("full_ndvi_weather.csv")
    df['date'] = pd.to_datetime(df['date'])
    return df

df = load_data()

st.title("Whispering Woods Forest Health Dashboard with Wind Arrows")
st.markdown("""
This dashboard visualizes vegetation health indices (NDVI, NDWI, EVI) and weather variables for a small area around Königssee.
Use the date slider to explore daily readings from July onwards. Markers are color-coded based on the NDVI index (green = healthy, orange = moderate, red = stressed).
Wind direction is shown using arrow symbols that point in the approximate wind direction; arrow size scales with wind speed.
""")

selected_date = st.slider(
    "Select date",
    min_value=df['date'].min().date(),
    max_value=df['date'].max().date(),
    value=df['date'].max().date(),
    format="YYYY-MM-DD"
)
filtered = df[df['date'].dt.date == selected_date]

def ndvi_color(n):
    if n > 0.6:
        return [0, 128, 0]
    elif n > 0.4:
        return [255, 165, 0]
    else:
        return [255, 0, 0]

# Map wind direction degrees to an arrow character
def arrow_from_direction(deg):
    dirs = ['\u2191', '\u2197', '\u2192', '\u2198', '\u2193', '\u2199', '\u2190', '\u2196']
    try:
        idx = int((deg % 360) / 45.0 + 0.5) % 8
        return dirs[idx]
    except:
        return ''

if not filtered.empty:
    filtered = filtered.copy()
    filtered['color'] = filtered['NDVI'].apply(ndvi_color)
    filtered['arrow_char'] = filtered['WindDirection'].apply(arrow_from_direction)
    # Set text size proportional to wind speed (e.g., 10 + wind speed * 2)
    filtered['text_size'] = filtered['WindSpeed'] * 2 + 10

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=filtered,
        get_position=["lon", "lat"],
        get_fill_color="color",
        get_radius=200,
        pickable=True
    )

    text_layer = pdk.Layer(
        "TextLayer",
        data=filtered,
        get_position=["lon", "lat"],
        get_text="arrow_char",
        get_size="text_size",
        get_color=[0, 0, 255],
        billboard=True,
        pickable=True
    )

    view_state = pdk.ViewState(
        latitude=filtered['lat'].mean(),
        longitude=filtered['lon'].mean(),
        zoom=12,
        pitch=0
    )

    tooltip = {
        "text": "Lat: {lat}\nLon: {lon}\nNDVI: {NDVI}\nNDWI: {NDWI}\nEVI: {EVI}\nTemp: {Temperature}\u00b0C\nRain: {Rainfall} mm\nWind: {WindSpeed} m/s\nDir: {WindDirection}\u00b0"
    }

    r = pdk.Deck(
        layers=[scatter_layer, text_layer],
        initial_view_state=view_state,
        tooltip=tooltip
    )
    st.pydeck_chart(r)

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
