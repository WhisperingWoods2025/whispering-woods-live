import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

@st.cache_data
def load_data():
    df = pd.read_csv("full_ndvi_weather.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df

df = load_data()

st.title("Whispering Woods Forest Health Dashboard (Static)")
st.markdown(
    "Markers are color-coded based on the NDVI index (green = healthy, orange = moderate, red = stressed). "
    "Wind direction is shown using arrow vectors; arrow length scales with wind speed. "
    "Use the slider to select a date starting from July 1."
)

min_date = df["date"].min().date()
max_date = df["date"].max().date()

selected_date = st.slider(
    "Select date",
    min_value=min_date,
    max_value=max_date,
    value=max_date,
    format="YYYY-MM-DD"
)

# Filter data for the selected date
filtered = df[df["date"] == pd.to_datetime(selected_date)]

if filtered.empty:
    st.write("No data available for selected date.")
else:
    # Determine colors based on NDVI values
    def ndvi_color(value):
        if value > 0.6:
            return (0.0, 0.8, 0.0)  # green
        elif value > 0.4:
            return (1.0, 0.65, 0.0)  # orange
        else:
            return (1.0, 0.0, 0.0)  # red

    colors = filtered["NDVI"].apply(ndvi_color).tolist()

    # Compute arrow vectors from wind speed and direction
    theta = np.radians(filtered["WindDirection"])
    u = filtered["WindSpeed"] * np.cos(theta)
    v = filtered["WindSpeed"] * np.sin(theta)

    fig, ax = plt.subplots()
    # Scatter points for NDVI
    ax.scatter(
        filtered["lon"],
        filtered["lat"],
        c=colors,
        s=100,
        edgecolors="black",
        linewidths=0.5,
        label="NDVI"
    )
    # Quiver for wind direction and speed
    ax.quiver(
        filtered["lon"],
        filtered["lat"],
        u,
        v,
        angles="xy",
        scale_units="xy",
        scale=10,
        color="blue",
        width=0.003
    )

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Forest Health and Wind Conditions on {selected_date}")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, linestyle="--", linewidth=0.5)

    st.pyplot(fig)

    # Display data table and summary statistics
    st.subheader("Data Table")
    st.dataframe(filtered)

    st.subheader("Summary Statistics")
    summary = filtered.describe(include="all")
    st.write(summary)
