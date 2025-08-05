import streamlit as st
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="Whispering Woods Live", layout="wide")

@st.cache_data
def load_data():
    return pd.read_csv("sample_ndvi_data.csv")

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
st.dataframe(filtered[['lat','lon','date','NDVI','NDWI','EVI']].reset_index(drop=True))

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

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=filtered,
        get_position='[lon, lat]',
        get_fill_color='color',
        get_radius=200,
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=filtered['lat'].mean(),
        longitude=filtered['lon'].mean(),
        zoom=12,
        pitch=0,
    )

    r = pdk.Deck(
        layers=[layer], 
        initial_view_state=view_state, 
        tooltip={"text": "Lat: {lat}\nLon: {lon}\nNDVI: {NDVI}\nNDWI: {NDWI}\nEVI: {EVI}"}
    )

    st.pydeck_chart(r)

    st.subheader("Summary Statistics")
    st.write(filtered[['NDVI', 'NDWI', 'EVI']].describe())
else:
    st.write("No data available for the selected date.")
