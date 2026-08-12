"""Stakeholder-facing Whispering Woods forest intelligence dashboard."""

import calendar
import csv
import io
import json
import math
import re
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional

import folium
import pandas as pd
import pydeck as pdk
import streamlit as st
from branca.element import Element, MacroElement, Template

try:
    import ee  # type: ignore
except ImportError as exc:
    raise RuntimeError("The earthengine-api must be installed to run this app.") from exc

try:
    from streamlit_folium import st_folium  # type: ignore
except ImportError as exc:
    raise RuntimeError("The streamlit-folium package must be installed to run this app.") from exc


EMBEDDING_COLLECTION_ID = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
HANSEN_COLLECTION_ID = "UMD/hansen/global_forest_change_2025_v1_13"
SURFACE_WATER_COLLECTION_ID = "JRC/GSW1_4/GlobalSurfaceWater"
WORLDCOVER_COLLECTION_ID = "ESA/WorldCover/v200"
BURNED_AREA_COLLECTION_ID = "MODIS/061/MCD64A1"
ERA5_COLLECTION_ID = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
WDPA_COLLECTION_ID = "WCMC/WDPA/current/polygons"
DEM_IMAGE_ID = "USGS/SRTMGL1_003"
BERCHTESGADEN_WDPA_ID = 668

DWD_RECENT_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent"
DWD_HISTORICAL_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical"
DWD_HOURLY_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly"
DWD_HOURLY_PRODUCTS = {
    "precipitation": {"path": "precipitation/recent", "prefix": "RR", "value_fields": ("R1",)},
    "wind": {"path": "wind/recent", "prefix": "FF", "value_fields": ("F", "D")},
    "air_temperature": {"path": "air_temperature/recent", "prefix": "TU", "value_fields": ("TT_TU", "RF_TU")},
}

DEFAULT_RGB_BANDS = ["A01", "A16", "A09"]
AOI_COLOR = "#E3A72F"
ALPHAEARTH_YEARS = set(range(2017, 2025))
PREDICTION_STATION_ID = "00856"
COSTED_USAGE_MODES = {"billable", "commercial", "enterprise", "government_operational", "paid", "production_paid"}
FORECAST_CAVEAT = "Forecast is an explainable prototype model, not an operational risk decision."
FORECAST_HORIZON_YEARS = 10
DEFAULT_FORECAST_HORIZON_YEARS = 4
PREDICTION_DISABLED_LAYERS = {"precipitation", "wind_flow", "cloud_veil", "moisture_flow", "canopy_stress", "weather_sensors"}
PREDICTION_FORCED_LAYERS = {"prediction"}

SCENARIO_SETTINGS = {
    "Conservative": {"warming_per_year": 0.025, "drying_per_year": 0.15},
    "Moderate": {"warming_per_year": 0.045, "drying_per_year": 0.35},
    "Hot dry": {"warming_per_year": 0.075, "drying_per_year": 0.65},
}

DWD_STATIONS = [
    {"id": "19856", "name": "Schoenau am Koenigssee", "state": "Bayern", "lat": 47.6134, "lon": 12.9819, "elevation": 625, "distance_km": 7.4},
    {"id": "07424", "name": "Piding", "state": "Bayern", "lat": 47.7724, "lon": 12.9073, "elevation": 457, "distance_km": 24.9},
    {"id": "07105", "name": "Siegsdorf-Hoell", "state": "Bayern", "lat": 47.8350, "lon": 12.6548, "elevation": 719, "distance_km": 38.6},
    {"id": "02573", "name": "Waging am See-Schnoebling", "state": "Bayern", "lat": 47.9588, "lon": 12.7717, "elevation": 470, "distance_km": 47.4},
    {"id": "00856", "name": "Chieming", "state": "Bayern", "lat": 47.8843, "lon": 12.5404, "elevation": 551, "distance_km": 48.2},
]

SOIL_SENSOR_SITES = [
    {"name": "Koenigssee shoreline", "zone": "Lake edge", "lat": 47.592, "lon": 12.989, "elevation": 604, "seed": 1, "ph": 6.4, "carbon": 8.2},
    {"name": "Wimbachtal forest", "zone": "Mixed mountain forest", "lat": 47.569, "lon": 12.914, "elevation": 900, "seed": 3, "ph": 5.8, "carbon": 11.5},
    {"name": "Hintersee edge", "zone": "Wetland transition", "lat": 47.606, "lon": 12.849, "elevation": 790, "seed": 5, "ph": 6.1, "carbon": 9.8},
    {"name": "Funtensee basin", "zone": "High alpine basin", "lat": 47.493, "lon": 12.940, "elevation": 1600, "seed": 8, "ph": 5.5, "carbon": 6.9},
    {"name": "Watzmann slope", "zone": "Steep protection forest", "lat": 47.556, "lon": 12.923, "elevation": 1320, "seed": 11, "ph": 5.7, "carbon": 7.6},
]

LAYER_SECTIONS = [
    (
        "Weather canvas",
        [
            ("precipitation", "Precipitation field", "Soft rainfall cells shaped by the selected day or week."),
            ("wind_flow", "Wind streamlines", "Directional wind and rain-flow ribbons across the park."),
            ("cloud_veil", "Cloud and fog veil", "Translucent cloud/fog patches for stakeholder weather context."),
            ("moisture_flow", "Moisture flow", "Blue-green hydrology and soil-moisture ribbons."),
            ("canopy_stress", "Forest stress signal", "Prototype organic stress pattern driven by heat, dryness, and season."),
        ],
    ),
    (
        "Forest evidence",
        [
            ("alphaearth", "Landscape patterns", "AlphaEarth annual embedding RGB for visual pattern discovery."),
            ("prediction", "Predicted stress surface", "Explainable prototype vulnerability surface for the selected projection."),
            ("tree_cover", "Tree canopy", "Year-2000 tree canopy baseline."),
            ("tree_loss", "Tree-cover loss", "Cumulative forest loss to the selected year."),
            ("water", "Water and wetlands", "Recurring surface water and wetland context."),
            ("habitat", "Land-cover habitat", "ESA WorldCover classes for habitat context."),
            ("fire", "Burned-area history", "MODIS burned-area signal for the selected year."),
            ("air_temperature", "Air temperature model", "ERA5-Land annual mean 2 m air temperature."),
            ("soil_moisture", "Soil moisture model", "ERA5-Land annual mean top-layer soil moisture."),
        ],
    ),
    (
        "Observation points",
        [
            ("weather_sensors", "DWD station points", "Official nearby DWD daily climate observations."),
            ("soil_sensors", "Soil probe points", "Prototype local soil probes for workflow design."),
        ],
    ),
]
LAYER_META = [item for _, items in LAYER_SECTIONS for item in items]
WORKSPACE_MODES = ["Map", "3D View", "Predictions"]
WORKSPACE_QUERY_SLUGS = {"Map": "map", "3D View": "3d-view", "Predictions": "predictions"}
WORKSPACE_MODES_BY_SLUG = {slug: mode for mode, slug in WORKSPACE_QUERY_SLUGS.items()}

VIEW_PRESETS = {
    "Weather canvas": {
        "copy": "A living-map view with rain, cloud, wind, moisture, and forest-stress signals over the protected forest.",
        "layers": {
            "precipitation": True,
            "wind_flow": True,
            "cloud_veil": True,
            "moisture_flow": True,
            "canopy_stress": True,
            "alphaearth": False,
            "prediction": False,
            "tree_cover": False,
            "tree_loss": True,
            "water": True,
            "habitat": False,
            "fire": False,
            "air_temperature": False,
            "soil_moisture": True,
            "weather_sensors": False,
            "soil_sensors": False,
        },
    },
    "Forest health": {
        "copy": "Canopy, tree-cover loss, AlphaEarth, and the explainable stress surface for conservation decisions.",
        "layers": {
            "precipitation": False,
            "wind_flow": False,
            "cloud_veil": False,
            "moisture_flow": True,
            "canopy_stress": True,
            "alphaearth": True,
            "prediction": True,
            "tree_cover": True,
            "tree_loss": True,
            "water": True,
            "habitat": False,
            "fire": False,
            "air_temperature": False,
            "soil_moisture": False,
            "weather_sensors": False,
            "soil_sensors": False,
        },
    },
    "Water and climate": {
        "copy": "Hydrology, precipitation, wind direction, temperature, and soil moisture as one climate lens.",
        "layers": {
            "precipitation": True,
            "wind_flow": True,
            "cloud_veil": True,
            "moisture_flow": True,
            "canopy_stress": False,
            "alphaearth": False,
            "prediction": False,
            "tree_cover": False,
            "tree_loss": False,
            "water": True,
            "habitat": False,
            "fire": False,
            "air_temperature": True,
            "soil_moisture": True,
            "weather_sensors": False,
            "soil_sensors": False,
        },
    },
    "Habitat and risk": {
        "copy": "Habitat, fire history, historical loss, water buffers, and projected vulnerability hotspots.",
        "layers": {
            "precipitation": False,
            "wind_flow": True,
            "cloud_veil": False,
            "moisture_flow": True,
            "canopy_stress": True,
            "alphaearth": False,
            "prediction": True,
            "tree_cover": True,
            "tree_loss": True,
            "water": True,
            "habitat": True,
            "fire": True,
            "air_temperature": False,
            "soil_moisture": False,
            "weather_sensors": False,
            "soil_sensors": True,
        },
    },
}


def inject_theme_css() -> None:
    st.markdown(
        """
<style>
:root {
  --ww-bg: #f7f5ee;
  --ww-surface: rgba(255,255,255,.84);
  --ww-surface-strong: rgba(255,255,255,.96);
  --ww-ink: #122018;
  --ww-muted: #66746b;
  --ww-line: rgba(23, 42, 31, .12);
  --ww-green: #2f7d4f;
  --ww-blue: #3478a9;
  --ww-sky: #e7f2f7;
  --ww-gold: #e3a72f;
  --ww-coral: #ce6858;
}
[data-testid="stAppViewContainer"] {
  color: var(--ww-ink);
  background: linear-gradient(180deg, #fbfaf6 0%, #f5f2e8 48%, #eef4ef 100%);
}
[data-testid="stHeader"] {
  background: rgba(251,250,246,.82);
  border-bottom: 1px solid rgba(26,46,35,.08);
  backdrop-filter: blur(18px);
}
.block-container { max-width: 1900px; padding: 1rem 1.35rem 1.4rem; }
[data-testid="column"] { min-width: 0; }
.ww-topbar { display:flex; align-items:center; justify-content:space-between; min-height:56px; margin:.05rem 0 1rem; padding:.48rem .6rem .48rem .75rem; border:1px solid var(--ww-line); border-radius:8px; background:rgba(255,255,255,.76); box-shadow:0 18px 50px rgba(35,53,42,.08); backdrop-filter: blur(20px); }
.ww-brand { display:flex; align-items:center; gap:.68rem; color:var(--ww-ink); font-weight:790; font-size:1rem; }
.ww-mark { width:32px; height:32px; border-radius:8px; display:grid; place-items:center; color:#ffffff; background:#16251c; font-weight:850; box-shadow:inset 0 1px 0 rgba(255,255,255,.18); }
.ww-nav { display:flex; align-items:center; gap:.32rem; padding:.22rem; border:1px solid var(--ww-line); border-radius:8px; background:rgba(246,245,239,.72); }
.ww-nav a { padding:.44rem .7rem; border-radius:7px; color:var(--ww-muted); font-size:.84rem; font-weight:730; text-decoration:none; transition:background .16s ease, color .16s ease, box-shadow .16s ease; }
.ww-nav a:hover { color:var(--ww-ink); background:rgba(255,255,255,.72); }
.ww-nav .active { color:#ffffff; background:#17251c; box-shadow:0 8px 24px rgba(22,37,28,.18); }
.ww-hero { display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; margin:.1rem 0 .85rem; }
.ww-kicker, .ww-map-label, .ww-plan-label, .ww-section-label { color:var(--ww-green); font-size:.72rem; font-weight:800; text-transform:uppercase; letter-spacing:.06em; }
.ww-title { margin:.12rem 0 0; color:var(--ww-ink); font-size:2.55rem; line-height:1.01; font-weight:840; letter-spacing:0; }
.ww-hero-copy { color:var(--ww-muted); margin-top:.46rem; font-size:1rem; max-width:850px; line-height:1.45; }
.ww-status-row { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.42rem; }
.ww-status { color:#1d3325; border:1px solid rgba(47,125,79,.18); border-radius:8px; background:rgba(220,239,222,.66); padding:.43rem .64rem; font-size:.8rem; font-weight:770; }
.ww-status.gold { color:#523b08; border-color:rgba(227,167,47,.28); background:rgba(227,167,47,.18); }
.ww-panel { border:1px solid var(--ww-line); border-radius:8px; background:rgba(255,255,255,.80); box-shadow:0 18px 58px rgba(35,53,42,.09); padding:.85rem .85rem .72rem; position:sticky; top:72px; }
.ww-panel-title { color:var(--ww-ink); font-size:1.2rem; font-weight:840; margin:0 0 .18rem; }
.ww-panel-copy { color:var(--ww-muted); font-size:.86rem; line-height:1.42; margin:0 0 .7rem; }
.ww-control-band { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.72rem .78rem .45rem; margin-bottom:.62rem; background:rgba(247,245,238,.80); }
.ww-control-band.disabled { background:rgba(239,239,234,.62); border-color:rgba(26,46,35,.07); }
.ww-control-note { color:#7b877f; font-size:.76rem; line-height:1.34; margin:.16rem 0 .38rem; }
.ww-time-card { border:1px solid rgba(26,46,35,.10); border-radius:8px; background:rgba(255,255,255,.70); padding:.58rem .62rem .62rem; margin:.48rem 0 .56rem; }
.ww-time-card span { color:var(--ww-muted); display:block; font-size:.7rem; font-weight:780; text-transform:uppercase; letter-spacing:.04em; }
.ww-time-card strong { color:var(--ww-ink); display:block; font-size:.96rem; line-height:1.24; margin:.2rem 0 .5rem; }
.ww-time-rail { height:7px; border-radius:999px; background:rgba(26,46,35,.10); overflow:hidden; }
.ww-time-rail i { display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,#3478a9,#3ca7a6,#e3a72f); }
.ww-time-meta { display:flex; justify-content:space-between; gap:.5rem; margin-top:.4rem; color:#6a766d; font-size:.72rem; font-weight:720; }
.ww-time-meta em { font-style:normal; }
.ww-map-head { display:flex; align-items:center; justify-content:space-between; gap:.85rem; margin:.14rem 0 .5rem; }
.ww-map-title { color:var(--ww-ink); font-size:1.08rem; font-weight:800; }
.ww-legend { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.36rem; }
.ww-pill { display:inline-flex; align-items:center; gap:.34rem; padding:.3rem .48rem; border:1px solid var(--ww-line); border-radius:8px; background:rgba(255,255,255,.78); color:var(--ww-ink); font-size:.73rem; font-weight:760; }
.ww-dot { width:8px; height:8px; border-radius:99px; display:inline-block; }
.ww-signal-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.56rem; margin:.5rem 0 .9rem; }
.ww-signal { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.72rem .76rem; background:rgba(255,255,255,.78); box-shadow:0 12px 34px rgba(35,53,42,.07); min-height:100px; }
.ww-signal span { color:var(--ww-muted); font-size:.72rem; font-weight:760; display:block; }
.ww-signal strong { color:var(--ww-ink); display:block; font-size:1rem; margin-top:.22rem; line-height:1.22; }
.ww-bar { height:6px; margin-top:.55rem; border-radius:99px; background:rgba(26,46,35,.10); overflow:hidden; }
.ww-bar i { display:block; height:100%; border-radius:99px; }
.ww-kpi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.58rem; margin:.56rem 0 .9rem; }
.ww-kpi { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.72rem .78rem; background:rgba(255,255,255,.78); box-shadow:0 12px 34px rgba(35,53,42,.07); min-height:82px; }
.ww-kpi span { color:var(--ww-muted); font-size:.72rem; font-weight:760; display:block; }
.ww-kpi strong { color:var(--ww-ink); display:block; font-size:.98rem; margin-top:.24rem; line-height:1.22; }
.ww-forecast-caveat { border:1px solid rgba(206,104,88,.22); border-radius:8px; padding:.68rem .78rem; margin:.3rem 0 .72rem; background:rgba(206,104,88,.075); color:#6d352b; font-size:.88rem; line-height:1.38; }
.ww-forecast-caveat strong { display:block; color:#5c2c24; font-size:.72rem; font-weight:820; text-transform:uppercase; letter-spacing:.05em; margin-bottom:.16rem; }
.ww-insight-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.6rem; margin-top:.58rem; }
.ww-insight { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.78rem .82rem; background:rgba(255,255,255,.76); min-height:116px; }
.ww-insight span { display:block; color:var(--ww-green); font-size:.7rem; font-weight:800; text-transform:uppercase; letter-spacing:.05em; margin-bottom:.25rem; }
.ww-insight strong { display:block; color:var(--ww-ink); font-size:.98rem; margin-bottom:.34rem; }
.ww-insight p { color:#5f6d63; margin:0; font-size:.85rem; line-height:1.36; }
.ww-source-list { display:grid; gap:.48rem; margin-top:.7rem; }
.ww-source-item { color:#647267; border-top:1px solid rgba(26,46,35,.10); padding-top:.46rem; font-size:.8rem; line-height:1.35; }
.ww-source-item strong { color:var(--ww-ink); }
.ww-plan-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.42rem; margin-top:.42rem; }
.ww-plan-chip { color:#35513f; background:rgba(220,239,222,.54); border:1px dashed rgba(47,125,79,.24); border-radius:8px; padding:.46rem .5rem; font-size:.78rem; font-weight:730; }
.ww-selected { border:1px solid rgba(52,120,169,.28); border-radius:8px; padding:.56rem .7rem; background:rgba(52,120,169,.08); color:#204b6b; margin:.56rem 0 .75rem; font-size:.86rem; }
.ww-method { border:1px solid rgba(26,46,35,.10); border-radius:8px; padding:.86rem .95rem; background:rgba(255,255,255,.78); color:#526055; font-size:.88rem; line-height:1.44; }
.ww-project-brief { border:1px solid rgba(26,46,35,.12); border-radius:8px; background:linear-gradient(135deg, rgba(255,255,255,.88), rgba(240,247,239,.72)); box-shadow:0 18px 58px rgba(35,53,42,.10); padding:.86rem; margin:.2rem 0 .92rem; }
.ww-brief-top { display:flex; justify-content:space-between; align-items:flex-start; gap:.9rem; margin-bottom:.72rem; }
.ww-brief-kicker { color:var(--ww-green); font-size:.7rem; font-weight:820; text-transform:uppercase; letter-spacing:.06em; }
.ww-brief-title { color:var(--ww-ink); font-size:1.12rem; line-height:1.18; font-weight:830; margin:.12rem 0 .18rem; }
.ww-brief-copy { color:#5c6a61; font-size:.85rem; line-height:1.38; max-width:820px; }
.ww-brief-status { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.34rem; }
.ww-brief-chip { color:#234435; border:1px solid rgba(47,125,79,.18); border-radius:999px; background:rgba(220,239,222,.62); padding:.28rem .48rem; font-size:.7rem; font-weight:780; white-space:nowrap; }
.ww-brief-chip.warn { color:#63381c; border-color:rgba(227,167,47,.30); background:rgba(227,167,47,.16); }
.ww-brief-grid { display:grid; grid-template-columns:1.15fr .95fr; gap:.72rem; }
.ww-impact-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.5rem; }
.ww-impact-card { border:1px solid rgba(26,46,35,.09); border-radius:8px; background:rgba(255,255,255,.72); padding:.68rem .72rem; min-height:95px; }
.ww-impact-card span { display:block; color:#718076; font-size:.68rem; font-weight:800; letter-spacing:.04em; text-transform:uppercase; margin-bottom:.22rem; }
.ww-impact-card strong { display:block; color:var(--ww-ink); font-size:.98rem; line-height:1.18; margin-bottom:.28rem; }
.ww-impact-card p { color:#5d6b62; font-size:.8rem; line-height:1.32; margin:0; }
.ww-twin-card { position:relative; overflow:hidden; border:1px solid rgba(26,46,35,.09); border-radius:8px; background:rgba(18,32,24,.92); color:#eef6ef; min-height:100%; padding:.78rem .82rem; }
.ww-twin-card:before { content:""; position:absolute; inset:0; background:radial-gradient(circle at 24% 26%, rgba(90,171,111,.26), rgba(90,171,111,0) 34%), radial-gradient(circle at 82% 20%, rgba(52,120,169,.22), rgba(52,120,169,0) 34%); opacity:.9; }
.ww-twin-content { position:relative; z-index:1; }
.ww-tree-stand { position:relative; height:86px; margin:.38rem 0 .6rem; border-bottom:1px solid rgba(238,246,239,.22); }
.ww-tree-node { position:absolute; bottom:0; width:2px; height:var(--h); left:var(--x); background:linear-gradient(180deg, rgba(198,230,194,.94), rgba(71,130,84,.72)); border-radius:999px; }
.ww-tree-node:before { content:""; position:absolute; left:50%; top:-7px; width:var(--c); height:var(--c); transform:translateX(-50%); border-radius:999px; background:radial-gradient(circle, rgba(186,224,170,.95), rgba(68,150,102,.70)); box-shadow:0 0 18px rgba(108,194,133,.26); }
.ww-twin-card h3 { position:relative; z-index:1; margin:0 0 .25rem; font-size:.98rem; line-height:1.18; color:#ffffff; }
.ww-twin-card p { position:relative; z-index:1; margin:0; color:#c9d8cd; font-size:.78rem; line-height:1.35; }
.ww-twin-steps { position:relative; z-index:1; display:grid; gap:.34rem; margin-top:.62rem; }
.ww-twin-step { display:flex; justify-content:space-between; gap:.5rem; color:#dfece2; border-top:1px solid rgba(238,246,239,.13); padding-top:.34rem; font-size:.74rem; }
.ww-twin-step em { color:#95bca1; font-style:normal; font-weight:780; white-space:nowrap; }
.ww-brief-sources { display:flex; flex-wrap:wrap; gap:.34rem; margin-top:.68rem; }
.ww-source-chip { color:#506057; background:rgba(255,255,255,.58); border:1px solid rgba(26,46,35,.09); border-radius:999px; padding:.26rem .44rem; font-size:.68rem; font-weight:760; }
.ww-motion-proof { position:relative; overflow:hidden; border:1px solid rgba(43,95,92,.13); border-radius:8px; min-height:50px; margin:.18rem 0 .56rem; background:linear-gradient(135deg, rgba(247,251,248,.94), rgba(235,245,245,.70)); box-shadow:0 10px 30px rgba(35,53,42,.06); }
.ww-motion-proof:before { content:""; position:absolute; left:-24%; right:-24%; top:0; height:100%; background:radial-gradient(ellipse at 16% 38%, rgba(255,255,255,.76), rgba(197,217,219,.22) 34%, rgba(197,217,219,0) 58%), repeating-linear-gradient(104deg, rgba(44,116,139,0) 0 38px, rgba(44,116,139,.20) 38px 40px, rgba(255,255,255,.50) 40px 41px, rgba(44,116,139,0) 41px 82px); animation:ww-proof-sweep 7.8s linear infinite; opacity:.62; }
.ww-motion-proof:after { content:""; position:absolute; left:-18%; bottom:10px; width:42%; height:10px; border-radius:999px; background:linear-gradient(90deg, rgba(15,92,124,0), rgba(15,92,124,.42), rgba(255,255,255,.62), rgba(15,92,124,0)); filter:blur(.2px); animation:ww-proof-cloud 6.2s ease-in-out infinite; opacity:.54; }
.ww-motion-proof-content { position:relative; z-index:1; display:flex; align-items:center; justify-content:space-between; gap:.8rem; padding:.58rem .72rem; color:#183b36; }
.ww-motion-proof-content strong { display:block; font-size:.82rem; letter-spacing:.01em; }
.ww-motion-proof-content span { display:block; margin-top:.08rem; color:#5b746d; font-size:.72rem; font-weight:680; }
.ww-motion-proof-dot { width:8px; height:8px; border-radius:99px; background:#2f8c90; box-shadow:0 0 0 0 rgba(47,140,144,.34); animation:ww-proof-pulse 2.2s ease-out infinite; flex:0 0 auto; }
.ww-reduced-motion-note { display:none; position:relative; z-index:2; margin:-.1rem .72rem .54rem; color:#7a3f10; font-size:.72rem; font-weight:720; }
[data-testid="stIFrame"] { border:1px solid rgba(26,46,35,.14); border-radius:8px; overflow:hidden; box-shadow:0 22px 70px rgba(35,53,42,.16); }
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label, [data-testid="stSlider"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label { font-weight:720; color:var(--ww-ink)!important; opacity:1!important; }
[data-testid="stRadio"] label p, [data-testid="stRadio"] label span, [data-testid="stCheckbox"] label p, [data-testid="stCheckbox"] label span { color:var(--ww-ink)!important; opacity:1!important; }
[data-testid="stCheckbox"]:has(input:disabled) { opacity:.48; filter:saturate(.35); }
[data-testid="stCheckbox"]:has(input:disabled) label p, [data-testid="stCheckbox"]:has(input:disabled) label span { color:#7f8a82!important; }
[data-testid="stNumberInput"] input { border-radius:8px!important; background:#ffffff!important; color:var(--ww-ink)!important; font-weight:740!important; }
[data-testid="stButton"] button { border-radius:8px!important; font-weight:780!important; }
[data-testid="stAlert"], [data-testid="stDataFrame"] { border-radius:8px; overflow:hidden; }
.stTabs [data-baseweb="tab-list"] { gap:.35rem; }
.stTabs [data-baseweb="tab"] { border-radius:8px; padding:.35rem .62rem; background:rgba(255,255,255,.58); border:1px solid rgba(26,46,35,.08); }
@keyframes ww-proof-sweep { from { transform:translate3d(-12%,0,0); } to { transform:translate3d(12%,0,0); } }
@keyframes ww-proof-cloud { from { transform:translate3d(0,0,0) scaleX(.94); } to { transform:translate3d(182%,0,0) scaleX(1.08); } }
@keyframes ww-proof-pulse { 0% { box-shadow:0 0 0 0 rgba(47,140,144,.34); transform:scale(.92); } 100% { box-shadow:0 0 0 10px rgba(47,140,144,0); transform:scale(1.04); } }
@media (prefers-reduced-motion: reduce) { .ww-reduced-motion-note { display:block; } }
@media (max-width:1120px) { .block-container { padding:.8rem .65rem 1rem; } .ww-topbar,.ww-hero,.ww-map-head,.ww-brief-top { align-items:flex-start; flex-direction:column; } .ww-nav,.ww-status-row,.ww-legend,.ww-brief-status { justify-content:flex-start; } .ww-title { font-size:1.84rem; } .ww-signal-grid,.ww-kpi-grid,.ww-insight-grid,.ww-brief-grid,.ww-impact-grid { grid-template-columns:1fr; } .ww-panel { position:static; } }
</style>
        """,
        unsafe_allow_html=True,
    )


def _read_secret(name: str) -> Optional[str]:
    value = st.secrets.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalise_usage_mode(value: Optional[str]) -> str:
    if not value:
        return "noncommercial"
    return value.lower().replace(" ", "_").replace("-", "_")


def enforce_no_cost_guardrail() -> str:
    usage_mode = _normalise_usage_mode(_read_secret("EE_USAGE_MODE"))
    if usage_mode in COSTED_USAGE_MODES:
        st.error("No-cost guardrail active: this app is not configured for paid Earth Engine use.")
        st.caption("Use an Earth Engine project registered for eligible non-commercial, research, conservation, or impact work.")
        st.stop()
    return usage_mode


def get_earth_engine_error_help(error_text: str) -> str:
    if "earthengine.maps.create" in error_text:
        return "Live map rendering needs Earth Engine Resource Writer (`roles/earthengine.writer`) on this project."
    if "earthengine.computations.create" in error_text:
        return "The service account needs an Earth Engine project role such as Resource Viewer or Resource Writer."
    return "This is usually a project permission, Earth Engine registration, API enablement, or data availability issue."


def show_earth_engine_error(message: str, exc: Exception) -> None:
    error_text = str(exc)
    st.error(message)
    st.caption(get_earth_engine_error_help(error_text))
    st.code(error_text, language="text")
    st.stop()


def _build_service_account_key_data(service_account: str, private_key_secret: str, project_id: Optional[str]) -> tuple[str, Optional[str]]:
    raw_secret = private_key_secret.strip()
    try:
        key_info = json.loads(raw_secret)
    except json.JSONDecodeError:
        key_info = {
            "type": "service_account",
            "client_email": service_account,
            "private_key": raw_secret.replace("\\n", "\n"),
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
        st.warning("EE_SERVICE_ACCOUNT does not match the client_email in EE_PRIVATE_KEY.")
    return json.dumps(key_info), project_id or key_info.get("project_id")


def init_ee() -> None:
    service_account = _read_secret("EE_SERVICE_ACCOUNT")
    private_key_secret = _read_secret("EE_PRIVATE_KEY")
    project_id = _read_secret("EE_PROJECT_ID")
    if not service_account or not private_key_secret:
        st.error("Earth Engine credentials not found. Add EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY to Streamlit secrets.")
        st.stop()
    try:
        key_data, project_id = _build_service_account_key_data(service_account, private_key_secret, project_id)
        credentials = ee.ServiceAccountCredentials(service_account, key_data=key_data)
        ee.Initialize(credentials, project=project_id) if project_id else ee.Initialize(credentials)
    except Exception as exc:
        st.error("Failed to initialise Earth Engine with the configured service account.")
        st.caption("Confirm the Cloud project is registered for Earth Engine, the API is enabled, and the JSON key matches EE_SERVICE_ACCOUNT.")
        st.caption(str(exc))
        st.stop()


@st.cache_resource(show_spinner=False)
def _init_ee_cached() -> None:
    init_ee()


def get_fallback_berchtesgaden_aoi() -> ee.Geometry:
    return ee.Geometry.Polygon([[[12.815, 47.600], [12.865, 47.635], [12.965, 47.625], [13.070, 47.610], [13.125, 47.565], [13.115, 47.500], [13.050, 47.458], [12.955, 47.455], [12.875, 47.482], [12.820, 47.535], [12.815, 47.600]]])


def get_default_aoi() -> tuple[ee.Geometry, str]:
    try:
        park = ee.FeatureCollection(WDPA_COLLECTION_ID).filter(ee.Filter.eq("WDPAID", BERCHTESGADEN_WDPA_ID))
        if int(park.size().getInfo()) > 0:
            return park.geometry(), "Berchtesgaden National Park"
    except Exception:
        pass
    return get_fallback_berchtesgaden_aoi(), "Berchtesgaden National Park fallback boundary"


def get_aoi(geojson_str: str) -> tuple[ee.Geometry, str]:
    if geojson_str:
        try:
            geo = json.loads(geojson_str)
            geo_type = geo.get("type")
            if geo_type == "FeatureCollection":
                return ee.FeatureCollection(geo).geometry(), "Custom AOI"
            if geo_type == "Feature":
                return ee.Geometry(geo["geometry"]), "Custom AOI"
            return ee.Geometry(geo), "Custom AOI"
        except Exception:
            st.warning("Invalid GeoJSON provided. Falling back to Berchtesgaden National Park.")
    return get_default_aoi()


def get_aoi_view(aoi: ee.Geometry) -> tuple[list[float], list[list[float]]]:
    centroid = aoi.centroid().coordinates().getInfo()
    bounds_coords = aoi.bounds().coordinates().getInfo()[0]
    return [centroid[1], centroid[0]], [[lat, lon] for lon, lat in bounds_coords]


def get_alphaearth_image(year: int, aoi: ee.Geometry) -> tuple[ee.Image, int]:
    collection = ee.ImageCollection(EMBEDDING_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01").filterBounds(aoi)
    tile_count = int(collection.size().getInfo())
    if tile_count == 0:
        raise ValueError(f"No AlphaEarth embedding tiles were found for {year} in this AOI.")
    return collection.mosaic().clip(aoi), tile_count


def get_hansen_image() -> ee.Image:
    return ee.Image(HANSEN_COLLECTION_ID)


def get_tree_cover_layer(aoi: ee.Geometry) -> ee.Image:
    cover = get_hansen_image().select("treecover2000")
    return cover.updateMask(cover.gte(20)).clip(aoi)


def get_tree_loss_layer(year: int, aoi: ee.Geometry) -> ee.Image:
    if year <= 2000:
        return ee.Image(0).selfMask().clip(aoi)
    loss_year = get_hansen_image().select("lossyear")
    return loss_year.gt(0).And(loss_year.lte(min(year - 2000, 25))).selfMask().clip(aoi)


def get_surface_water_layer(aoi: ee.Geometry) -> ee.Image:
    occurrence = ee.Image(SURFACE_WATER_COLLECTION_ID).select("occurrence")
    return occurrence.updateMask(occurrence.gte(10)).clip(aoi)


def get_worldcover_layer(aoi: ee.Geometry) -> ee.Image:
    return ee.ImageCollection(WORLDCOVER_COLLECTION_ID).first().select("Map").clip(aoi)


def get_burned_area_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    collection = ee.ImageCollection(BURNED_AREA_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01").select("BurnDate")
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.max().selfMask().clip(aoi)


def get_era5_collection(year: int) -> ee.ImageCollection:
    return ee.ImageCollection(ERA5_COLLECTION_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01")


def get_air_temperature_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    collection = get_era5_collection(year)
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.select("temperature_2m").mean().subtract(273.15).clip(aoi)


def get_soil_moisture_layer(year: int, aoi: ee.Geometry) -> Optional[ee.Image]:
    collection = get_era5_collection(year)
    if int(collection.size().getInfo()) == 0:
        return None
    return collection.select("volumetric_soil_water_layer_1").mean().clip(aoi)


def dwd_float(row: dict[str, str], key: str) -> Optional[float]:
    raw_value = row.get(key, "").strip().replace(",", ".")
    if not raw_value:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return None if value <= -998 else value


def format_number(value: Optional[float], suffix: str, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{decimals}f}{suffix}"


def parse_dwd_date(raw_date: str) -> Optional[date]:
    try:
        return datetime.strptime(raw_date, "%Y%m%d").date()
    except ValueError:
        return None


def format_dwd_date(raw_date: str) -> str:
    parsed = parse_dwd_date(raw_date)
    return parsed.isoformat() if parsed else raw_date or "n/a"


def parse_dwd_hour(raw_date: str) -> Optional[datetime]:
    try:
        return datetime.strptime(raw_date, "%Y%m%d%H")
    except ValueError:
        return None


def format_dwd_hour(raw_date: str) -> str:
    parsed = parse_dwd_hour(raw_date)
    return parsed.strftime("%Y-%m-%d %H:00") if parsed else raw_date or "n/a"


def build_period_context(year: int, granularity: str, step_index: Optional[int]) -> dict:
    max_day = 366 if calendar.isleap(year) else 365
    if granularity == "Daily":
        day_index = min(max(1, int(step_index or 196)), max_day)
        target = date(year, 1, 1) + timedelta(days=day_index - 1)
        return {"granularity": granularity, "step": day_index, "target_date": target, "label": target.strftime("%b %d, %Y")}
    if granularity == "Weekly":
        week = min(max(1, int(step_index or 28)), 52)
        target = date(year, 1, 1) + timedelta(days=(week - 1) * 7 + 3)
        return {"granularity": granularity, "step": week, "target_date": target, "label": f"Week {week}, {year}"}
    return {"granularity": "Annual", "step": None, "target_date": date(year, 7, 1), "label": f"{year}"}


def add_years_safe(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_archive_url(station_id: str, archive_kind: str) -> str:
    if archive_kind == "recent":
        return f"{DWD_RECENT_BASE_URL}/tageswerte_KL_{station_id}_akt.zip"
    index_html = urllib.request.urlopen(f"{DWD_HISTORICAL_BASE_URL}/", timeout=12).read().decode("utf-8", errors="ignore")
    matches = sorted(set(re.findall(rf"tageswerte_KL_{re.escape(station_id)}_.*?_hist\.zip", index_html)))
    if not matches:
        raise ValueError(f"No DWD historical climate archive found for station {station_id}.")
    return f"{DWD_HISTORICAL_BASE_URL}/{matches[-1]}"


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_dwd_rows(station_id: str, archive_kind: str) -> list[dict[str, str]]:
    archive_url = get_dwd_archive_url(station_id, archive_kind)
    with urllib.request.urlopen(archive_url, timeout=18) as response:
        archive_data = response.read()
    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        product_names = [name for name in archive.namelist() if "produkt_klima_tag" in name and name.endswith(".txt")]
        if not product_names:
            raise ValueError(f"No DWD product file found in station archive {station_id}.")
        with archive.open(product_names[0]) as product_file:
            text = product_file.read().decode("latin1")
    rows = []
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        clean_row = {key.strip(): value.strip() for key, value in row.items() if key is not None and value is not None}
        if clean_row.get("MESS_DATUM"):
            rows.append(clean_row)
    return rows


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_dwd_hourly_rows(station_id: str, product_key: str) -> list[dict[str, str]]:
    product = DWD_HOURLY_PRODUCTS[product_key]
    archive_url = f"{DWD_HOURLY_BASE_URL}/{product['path']}/stundenwerte_{product['prefix']}_{station_id}_akt.zip"
    with urllib.request.urlopen(archive_url, timeout=18) as response:
        archive_data = response.read()
    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        product_names = [name for name in archive.namelist() if name.lower().split("/")[-1].startswith("produkt") and name.endswith(".txt")]
        if not product_names:
            raise ValueError(f"No DWD hourly product file found for {station_id} / {product_key}.")
        with archive.open(product_names[0]) as product_file:
            text = product_file.read().decode("latin1")
    rows = []
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        clean_row = {key.strip(): value.strip() for key, value in row.items() if key is not None and value is not None}
        if clean_row.get("MESS_DATUM"):
            rows.append(clean_row)
    return rows


def latest_hourly_row(rows: list[dict[str, str]], fields: tuple[str, ...]) -> Optional[dict[str, str]]:
    dated_rows = [(parsed, row) for row in rows if (parsed := parse_dwd_hour(row.get("MESS_DATUM", ""))) is not None]
    for _, row in sorted(dated_rows, key=lambda item: item[0], reverse=True):
        if any(dwd_float(row, field) is not None for field in fields):
            return row
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def get_dwd_live_reading(station_id: str) -> Optional[dict]:
    station = get_station(station_id)
    reading = {
        "station_id": station["id"],
        "name": station["name"],
        "state": station["state"],
        "lat": station["lat"],
        "lon": station["lon"],
        "elevation": station["elevation"],
        "distance_km": station["distance_km"],
        "period": "Live hourly DWD",
        "archive_kind": "live_hourly",
        "days": 1,
        "mean_temp": None,
        "max_temp": None,
        "min_temp": None,
        "precipitation": None,
        "humidity": None,
        "wind": None,
        "gust": None,
        "wind_direction": None,
        "live": True,
        "date": "latest hourly",
    }
    observation_times = []
    metric_count = 0

    try:
        temp_row = latest_hourly_row(fetch_dwd_hourly_rows(station_id, "air_temperature"), ("TT_TU", "RF_TU"))
    except Exception:
        temp_row = None
    if temp_row is not None:
        reading["mean_temp"] = dwd_float(temp_row, "TT_TU")
        reading["humidity"] = dwd_float(temp_row, "RF_TU")
        if parsed := parse_dwd_hour(temp_row.get("MESS_DATUM", "")):
            observation_times.append(parsed)
        metric_count += int(reading["mean_temp"] is not None or reading["humidity"] is not None)

    try:
        precip_row = latest_hourly_row(fetch_dwd_hourly_rows(station_id, "precipitation"), ("R1",))
    except Exception:
        precip_row = None
    if precip_row is not None:
        precip = dwd_float(precip_row, "R1")
        reading["precipitation"] = max(0.0, precip) if precip is not None else None
        if parsed := parse_dwd_hour(precip_row.get("MESS_DATUM", "")):
            observation_times.append(parsed)
        metric_count += int(reading["precipitation"] is not None)

    try:
        wind_row = latest_hourly_row(fetch_dwd_hourly_rows(station_id, "wind"), ("F", "D"))
    except Exception:
        wind_row = None
    if wind_row is not None:
        reading["wind"] = dwd_float(wind_row, "F")
        reading["wind_direction"] = dwd_float(wind_row, "D")
        reading["gust"] = round(float(reading["wind"]) * 1.8, 1) if reading["wind"] is not None else None
        if parsed := parse_dwd_hour(wind_row.get("MESS_DATUM", "")):
            observation_times.append(parsed)
        metric_count += int(reading["wind"] is not None or reading["wind_direction"] is not None)

    if metric_count == 0:
        return None
    if observation_times:
        reading["date"] = max(observation_times).strftime("%Y-%m-%d %H:00")
    return reading


def get_dwd_live_readings() -> tuple[list[dict], int]:
    readings = []
    unavailable = 0
    for station in DWD_STATIONS:
        reading = get_dwd_live_reading(station["id"])
        if reading is None:
            unavailable += 1
        else:
            readings.append(reading)
    readings.sort(key=lambda item: item["distance_km"])
    return readings, unavailable


def get_station(station_id: str) -> dict:
    return next((station for station in DWD_STATIONS if station["id"] == station_id), DWD_STATIONS[-1])


def select_dwd_rows_for_period(rows: list[dict[str, str]], year: int, granularity: str, step_index: Optional[int]) -> list[dict[str, str]]:
    period = build_period_context(year, granularity, step_index)
    selected = []
    for row in rows:
        parsed = parse_dwd_date(row.get("MESS_DATUM", ""))
        if not parsed or parsed.year != year:
            continue
        if granularity == "Annual":
            selected.append(row)
        elif granularity == "Weekly" and abs((parsed - period["target_date"]).days) <= 3:
            selected.append(row)
        elif granularity == "Daily" and parsed == period["target_date"]:
            selected.append(row)
    return selected


def summarise_dwd_rows(station: dict, rows: list[dict[str, str]], archive_kind: str, period: dict) -> Optional[dict]:
    if not rows:
        return None
    temps = [value for row in rows if (value := dwd_float(row, "TMK")) is not None]
    max_temps = [value for row in rows if (value := dwd_float(row, "TXK")) is not None]
    min_temps = [value for row in rows if (value := dwd_float(row, "TNK")) is not None]
    precipitation = [value for row in rows if (value := dwd_float(row, "RSK")) is not None]
    humidity = [value for row in rows if (value := dwd_float(row, "UPM")) is not None]
    wind = [value for row in rows if (value := dwd_float(row, "FM")) is not None]
    gust = [value for row in rows if (value := dwd_float(row, "FX")) is not None]
    dates = sorted(row.get("MESS_DATUM", "") for row in rows if row.get("MESS_DATUM"))
    return {
        "station_id": station["id"],
        "name": station["name"],
        "state": station["state"],
        "lat": station["lat"],
        "lon": station["lon"],
        "elevation": station["elevation"],
        "distance_km": station["distance_km"],
        "date": format_dwd_date(dates[-1]) if dates else period["label"],
        "period": period["label"],
        "archive_kind": archive_kind,
        "days": len(rows),
        "mean_temp": round(sum(temps) / len(temps), 1) if temps else None,
        "max_temp": max(max_temps) if max_temps else None,
        "min_temp": min(min_temps) if min_temps else None,
        "precipitation": round(sum(precipitation), 1) if precipitation else 0.0,
        "humidity": round(sum(humidity) / len(humidity), 0) if humidity else None,
        "wind": round(sum(wind) / len(wind), 1) if wind else None,
        "gust": max(gust) if gust else None,
    }


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_period_reading(station_id: str, year: int, granularity: str, step_index: Optional[int]) -> Optional[dict]:
    station = get_station(station_id)
    period = build_period_context(year, granularity, step_index)
    archive_order = ["recent", "historical"] if year >= 2025 else ["historical", "recent"]
    for archive_kind in archive_order:
        try:
            rows = fetch_dwd_rows(station_id, archive_kind)
        except Exception:
            continue
        selected_rows = select_dwd_rows_for_period(rows, year, granularity, step_index)
        reading = summarise_dwd_rows(station, selected_rows, archive_kind, period)
        if reading is not None:
            return reading
    return None


def get_dwd_readings_for_period(year: int, granularity: str, step_index: Optional[int]) -> tuple[list[dict], int]:
    readings = []
    unavailable = 0
    for station in DWD_STATIONS:
        reading = get_dwd_period_reading(station["id"], year, granularity, step_index)
        if reading is None:
            unavailable += 1
        else:
            readings.append(reading)
    readings.sort(key=lambda item: item["distance_km"])
    return readings, unavailable


@st.cache_data(ttl=21600, show_spinner=False)
def get_dwd_annual_series(station_id: str) -> list[dict]:
    rows_by_date: dict[str, dict[str, str]] = {}
    for archive_kind in ("historical", "recent"):
        try:
            rows = fetch_dwd_rows(station_id, archive_kind)
        except Exception:
            continue
        for row in rows:
            date_value = row.get("MESS_DATUM", "")
            if date_value:
                rows_by_date[date_value] = row

    buckets: dict[int, dict[str, list[float]]] = {}
    for date_value, row in rows_by_date.items():
        try:
            year = int(date_value[:4])
        except ValueError:
            continue
        if year < 2000 or year > 2026:
            continue
        temp = dwd_float(row, "TMK")
        precip = dwd_float(row, "RSK")
        humidity = dwd_float(row, "UPM")
        if temp is None and precip is None and humidity is None:
            continue
        bucket = buckets.setdefault(year, {"temp": [], "precip": [], "humidity": []})
        if temp is not None:
            bucket["temp"].append(temp)
        if precip is not None:
            bucket["precip"].append(precip)
        if humidity is not None:
            bucket["humidity"].append(humidity)

    series = []
    for year in sorted(buckets):
        bucket = buckets[year]
        if not bucket["temp"]:
            continue
        series.append({
            "Year": year,
            "Mean temp C": round(sum(bucket["temp"]) / len(bucket["temp"]), 1),
            "Precip mm": round(sum(bucket["precip"]), 1) if bucket["precip"] else None,
            "Mean humidity %": round(sum(bucket["humidity"]) / len(bucket["humidity"]), 0) if bucket["humidity"] else None,
            "Days": len(bucket["temp"]),
        })
    return series


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def average(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 1) if values else None


def precipitation_intensity(value: Optional[float], granularity: str, is_live: bool) -> float:
    if value is None:
        return 0.0
    precipitation = max(0.0, float(value))
    if precipitation <= 0.02:
        return 0.0
    if is_live:
        return clamp((precipitation / 8.0) ** 0.55, 0.04, 1.0)
    reference = {"Daily": 28.0, "Weekly": 95.0, "Annual": 1800.0}[granularity]
    return clamp((precipitation / reference) ** 0.65, 0.0, 1.0)


def circular_mean_degrees(values: list[float]) -> Optional[float]:
    if not values:
        return None
    sin_sum = sum(math.sin(math.radians(value)) for value in values)
    cos_sum = sum(math.cos(math.radians(value)) for value in values)
    if sin_sum == 0 and cos_sum == 0:
        return None
    return round(math.degrees(math.atan2(sin_sum, cos_sum)) % 360, 0)


def build_time_signal(year: int, granularity: str, step_index: Optional[int], readings: list[dict]) -> dict:
    period = build_period_context(year, granularity, step_index)
    is_live = any(item.get("live") for item in readings)
    day_of_year = period["target_date"].timetuple().tm_yday
    seasonal_wave = math.sin((day_of_year - 80) / 365 * math.tau)
    fallback_temp = 5.6 + 9.4 * seasonal_wave + (year - 2000) * 0.035
    fallback_precip = {"Daily": 2.4, "Weekly": 18.0, "Annual": 1350.0}[granularity] * (1.0 + 0.35 * math.sin((day_of_year + 25) / 365 * math.tau))
    fallback_humidity = 72 + 14 * math.sin((day_of_year + 90) / 365 * math.tau)
    fallback_wind = 2.8 + 0.8 * math.cos(day_of_year / 365 * math.tau)

    temps = [float(item["mean_temp"]) for item in readings if item.get("mean_temp") is not None]
    precip = [float(item["precipitation"]) for item in readings if item.get("precipitation") is not None]
    humidity = [float(item["humidity"]) for item in readings if item.get("humidity") is not None]
    wind = [float(item["wind"]) for item in readings if item.get("wind") is not None]
    gust = [float(item["gust"]) for item in readings if item.get("gust") is not None]
    wind_directions = [float(item["wind_direction"]) for item in readings if item.get("wind_direction") is not None]

    mean_temp = average(temps) if temps else round(fallback_temp, 1)
    if is_live:
        precipitation = round(max(precip), 1) if precip else 0.0
    else:
        precipitation = average(precip) if precip else round(fallback_precip, 1)
    mean_humidity = average(humidity) if humidity else round(fallback_humidity, 0)
    mean_wind = average(wind) if wind else round(fallback_wind, 1)
    max_gust = max(gust) if gust else round(mean_wind * 1.9, 1)

    precip_intensity = precipitation_intensity(precipitation, granularity, is_live)
    humidity_intensity = clamp(float(mean_humidity or 0) / 100, 0, 1)
    moisture = clamp(0.42 + humidity_intensity * 0.34 + precip_intensity * 0.26 - max(0, float(mean_temp or 0) - 18) * 0.012, 0, 1)
    cloud = clamp(0.22 + humidity_intensity * 0.44 + precip_intensity * 0.52, 0, 1)
    stress = clamp((float(mean_temp or 0) - 12) / 16 + (1 - moisture) * 0.52 + (year - 2000) * 0.006, 0, 1)
    wind_direction = circular_mean_degrees(wind_directions)
    if wind_direction is None:
        wind_direction = (205 + math.sin(day_of_year / 365 * math.tau) * 55 + float(mean_wind or 0) * 7) % 360
    return {
        "period_label": period["label"],
        "granularity": granularity,
        "mean_temp": mean_temp,
        "precipitation": precipitation,
        "humidity": mean_humidity,
        "wind": mean_wind,
        "gust": max_gust,
        "precip_intensity": precip_intensity,
        "moisture": moisture,
        "cloud": cloud,
        "stress": stress,
        "wind_direction": round(wind_direction, 0),
        "live": is_live,
        "source": "DWD live hourly observations" if is_live else ("DWD period readings" if readings else "seasonal fallback"),
    }


def estimate_soil_reading(site: dict, year: int, day_of_year: int = 196) -> dict[str, float]:
    phase = year - 2000
    seasonal = math.sin((day_of_year / 365 * math.tau) + site["seed"] * 0.35)
    elevation_km = site["elevation"] / 1000
    soil_temp = 7.8 + phase * 0.035 - elevation_km * 3.8 + seasonal * 1.25
    soil_moisture = 34 + elevation_km * 4.5 + seasonal * 6.0 + (site["seed"] % 4) * 1.2
    return {"soil_temp": round(soil_temp, 1), "soil_moisture": round(max(8, min(70, soil_moisture)), 1), "ph": round(site["ph"] + seasonal * 0.06, 2), "carbon": round(site["carbon"] + seasonal * 0.25, 1)}


def bounds_to_key(bounds: list[list[float]]) -> str:
    rounded_bounds = [[round(point[0], 5), round(point[1], 5)] for point in bounds]
    return json.dumps(rounded_bounds, sort_keys=True)


def risk_color(score: float) -> tuple[list[int], str, str]:
    if score >= 68:
        return [206, 104, 88, 210], "#ce6858", "High"
    if score >= 45:
        return [227, 167, 47, 192], "#e3a72f", "Watch"
    return [68, 150, 102, 176], "#449666", "Lower"


def build_fallback_environment_surface(bounds_key: str) -> list[dict]:
    bounds = json.loads(bounds_key)
    lats = [point[0] for point in bounds]
    lons = [point[1] for point in bounds]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    records = []
    for y_idx in range(13):
        lat = min_lat + (max_lat - min_lat) * (y_idx + 0.5) / 13
        for x_idx in range(15):
            lon = min_lon + (max_lon - min_lon) * (x_idx + 0.5) / 15
            ridge = math.sin((lon - min_lon) * 28) + math.cos((lat - min_lat) * 34)
            lake_distance = min(math.hypot(lat - 47.592, lon - 12.989), math.hypot(lat - 47.606, lon - 12.849))
            records.append({
                "lat": lat,
                "lon": lon,
                "elevation": 900 + ridge * 260 + (max_lat - lat) * 1300,
                "slope": 18 + abs(ridge) * 12,
                "tree_cover": clamp(68 + ridge * 12 - lake_distance * 180, 10, 95),
                "loss_year": 0,
                "water": clamp(85 - lake_distance * 1600, 0, 90),
                "source": "fallback",
            })
    return records


@st.cache_data(ttl=21600, show_spinner=False)
def sample_environment_surface(bounds_key: str, year: int) -> list[dict]:
    bounds = json.loads(bounds_key)
    lats = [point[0] for point in bounds]
    lons = [point[1] for point in bounds]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    features = []
    for y_idx in range(13):
        lat = min_lat + (max_lat - min_lat) * (y_idx + 0.5) / 13
        for x_idx in range(15):
            lon = min_lon + (max_lon - min_lon) * (x_idx + 0.5) / 15
            features.append(ee.Feature(ee.Geometry.Point([lon, lat]), {"lat": lat, "lon": lon}))

    points = ee.FeatureCollection(features)
    dem = ee.Image(DEM_IMAGE_ID).select("elevation").rename("elevation")
    slope = ee.Terrain.slope(dem).rename("slope")
    tree_cover = get_hansen_image().select("treecover2000").rename("tree_cover")
    loss_year = get_hansen_image().select("lossyear").rename("loss_year")
    water = ee.Image(SURFACE_WATER_COLLECTION_ID).select("occurrence").rename("water")
    image = dem.addBands(slope).addBands(tree_cover).addBands(loss_year).addBands(water)
    sampled = image.sampleRegions(collection=points, scale=120, geometries=False, tileScale=2).getInfo()
    records = []
    for feature in sampled.get("features", []):
        props = feature.get("properties", {})
        if "elevation" not in props:
            continue
        records.append({
            "lat": float(props.get("lat")),
            "lon": float(props.get("lon")),
            "elevation": float(props.get("elevation", 0)),
            "slope": float(props.get("slope", 0)),
            "tree_cover": float(props.get("tree_cover", 0)),
            "loss_year": float(props.get("loss_year", 0)),
            "water": float(props.get("water", 0)),
            "source": "earth_engine",
        })
    if not records:
        raise ValueError("No environmental samples returned for the selected area.")
    return records


def get_climate_signal(year: int, projection_year: int, scenario_name: str) -> dict:
    scenario = SCENARIO_SETTINGS[scenario_name]
    station = get_station(PREDICTION_STATION_ID)
    rows = get_dwd_annual_series(PREDICTION_STATION_ID)
    if not rows:
        projection_gap = max(0, projection_year - max(year, 2026))
        return {"station": station["name"], "base_temp": None, "recent_temp": None, "temp_delta": 0.0, "projected_temp_delta": round(projection_gap * scenario["warming_per_year"], 2), "precip_delta_pct": 0.0, "projected_precip_delta_pct": round(-projection_gap * scenario["drying_per_year"], 1), "source_note": "DWD trend unavailable; projection uses scenario settings only."}

    df = pd.DataFrame(rows)
    base = df[(df["Year"] >= 2000) & (df["Year"] <= 2009)]
    max_available_year = int(df["Year"].max())
    analysis_year = min(max(year, 2000), max_available_year)
    recent = df[(df["Year"] >= max(2000, analysis_year - 4)) & (df["Year"] <= analysis_year)]
    if base.empty:
        base = df.head(min(5, len(df)))
    if recent.empty:
        recent = df.tail(min(5, len(df)))

    base_temp = float(base["Mean temp C"].mean())
    recent_temp = float(recent["Mean temp C"].mean())
    base_precip = float(base["Precip mm"].dropna().mean()) if not base["Precip mm"].dropna().empty else 0.0
    recent_precip = float(recent["Precip mm"].dropna().mean()) if not recent["Precip mm"].dropna().empty else base_precip
    precip_delta_pct = ((recent_precip - base_precip) / base_precip * 100) if base_precip else 0.0
    projection_gap = max(0, projection_year - max(analysis_year, 2026))
    projected_temp_delta = (recent_temp - base_temp) + projection_gap * scenario["warming_per_year"]
    projected_precip_delta_pct = precip_delta_pct - projection_gap * scenario["drying_per_year"]
    return {
        "station": station["name"],
        "base_temp": round(base_temp, 1),
        "recent_temp": round(recent_temp, 1),
        "temp_delta": round(recent_temp - base_temp, 2),
        "projected_temp_delta": round(projected_temp_delta, 2),
        "precip_delta_pct": round(precip_delta_pct, 1),
        "projected_precip_delta_pct": round(projected_precip_delta_pct, 1),
        "source_note": f"Climate signal uses DWD annual summaries from {station['name']}.",
    }


def score_prediction_row(row: dict, year: int, projection_year: int, climate_signal: dict) -> dict:
    elevation = float(row.get("elevation") or 0)
    slope = float(row.get("slope") or 0)
    tree_cover = float(row.get("tree_cover") or 0)
    loss_year = float(row.get("loss_year") or 0)
    water = float(row.get("water") or 0)
    observed_loss_year = 2000 + int(loss_year) if loss_year > 0 else None
    loss_active = bool(observed_loss_year and observed_loss_year <= min(year, 2025))
    recent_loss = bool(observed_loss_year and min(year, 2025) - observed_loss_year <= 5)

    warming = clamp(float(climate_signal["projected_temp_delta"]) / 2.5, 0, 1) * 22
    dryness = clamp(-float(climate_signal["projected_precip_delta_pct"]) / 20, 0, 1) * 15
    low_canopy = clamp((58 - tree_cover) / 58, 0, 1) * 22
    loss_history = (24 if loss_active else 0) + (7 if recent_loss else 0)
    steep_terrain = clamp((slope - 14) / 35, 0, 1) * 13
    lower_elevation = clamp((1220 - elevation) / 900, 0, 1) * 8
    water_buffer = clamp(water / 80, 0, 1) * 12
    projection_pressure = clamp((projection_year - year) / 14, 0, 1) * 5
    score = clamp(18 + warming + dryness + low_canopy + loss_history + steep_terrain + lower_elevation + projection_pressure - water_buffer, 1, 99)
    color, color_hex, label = risk_color(score)

    drivers = {"warming": warming, "dryness": dryness, "low canopy": low_canopy, "loss history": loss_history, "steep terrain": steep_terrain, "lower elevation": lower_elevation}
    dominant = sorted(drivers.items(), key=lambda item: item[1], reverse=True)[:2]
    reason = ", ".join(name for name, value in dominant if value > 2) or "balanced conditions"
    if water_buffer > 7:
        reason = f"{reason}; recurring water lowers stress"

    return {
        "lat": round(float(row["lat"]), 6),
        "lon": round(float(row["lon"]), 6),
        "elevation": round(elevation, 0),
        "slope": round(slope, 1),
        "tree_cover": round(tree_cover, 1),
        "loss_year": int(loss_year) if loss_year else 0,
        "water": round(water, 1),
        "risk_score": round(score, 1),
        "risk_label": label,
        "color": color,
        "color_hex": color_hex,
        "height_risk": round(score * 28, 1),
        "height_terrain": round(max(80, elevation * 0.55), 1),
        "reason": reason,
        "warming": round(warming, 1),
        "dryness": round(dryness, 1),
        "low_canopy": round(low_canopy, 1),
        "loss_history": round(loss_history, 1),
        "steep_terrain": round(steep_terrain, 1),
        "water_buffer": round(water_buffer, 1),
        "source": row.get("source", "earth_engine"),
    }


def build_prediction_surface(bounds: list[list[float]], year: int, projection_year: int, scenario_name: str) -> tuple[pd.DataFrame, dict, Optional[str]]:
    bounds_key = bounds_to_key(bounds)
    climate_signal = get_climate_signal(year, projection_year, scenario_name)
    note = None
    try:
        environment_rows = sample_environment_surface(bounds_key, min(year, 2025))
    except Exception as exc:
        environment_rows = build_fallback_environment_surface(bounds_key)
        note = f"Prediction terrain is using a fallback surface because the public DEM sample was unavailable: {exc}"
    records = [score_prediction_row(row, year, projection_year, climate_signal) for row in environment_rows]
    return pd.DataFrame(records), climate_signal, note


def add_ee_layer(m: folium.Map, image: ee.Image, vis_params: dict, name: str, opacity: float = 0.85) -> None:
    map_id = image.getMapId(vis_params)
    folium.TileLayer(tiles=map_id["tile_fetcher"].url_format, attr="Google Earth Engine", name=name, overlay=True, control=True, opacity=opacity).add_to(m)


def add_aoi_boundary(m: folium.Map, aoi: ee.Geometry, area_name: str) -> None:
    folium.GeoJson(aoi.getInfo(), name=area_name, style_function=lambda _: {"color": AOI_COLOR, "weight": 2.8, "fillOpacity": 0, "opacity": 0.95}).add_to(m)


def build_map(center: list[float], bounds: list[list[float]], basemap: str) -> folium.Map:
    m = folium.Map(location=center, zoom_start=12, tiles=None, control_scale=True)
    if basemap == "Satellite":
        folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri, Maxar, Earthstar Geographics, and the GIS User Community", name="Satellite", control=False).add_to(m)
    elif basemap == "Terrain":
        folium.TileLayer("OpenTopoMap", name="Terrain", control=False).add_to(m)
    else:
        folium.TileLayer("CartoDB positron", name="Light map", control=False).add_to(m)
    m.fit_bounds(bounds, padding=(24, 24))
    return m


def get_bounds_stats(bounds: list[list[float]]) -> dict:
    lats = [point[0] for point in bounds]
    lons = [point[1] for point in bounds]
    return {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lon": min(lons),
        "max_lon": max(lons),
        "lat_span": max(max(lats) - min(lats), 0.02),
        "lon_span": max(max(lons) - min(lons), 0.02),
    }


def blob_points(center_lat: float, center_lon: float, radius_lat: float, radius_lon: float, seed: float, count: int = 38) -> list[list[float]]:
    points = []
    for idx in range(count):
        angle = math.tau * idx / count
        wobble = 1 + 0.18 * math.sin(angle * 3 + seed) + 0.08 * math.cos(angle * 5 - seed * 0.7)
        points.append([center_lat + math.sin(angle) * radius_lat * wobble, center_lon + math.cos(angle) * radius_lon * wobble])
    return points


def flowline_points(start_lat: float, start_lon: float, angle_deg: float, lat_span: float, lon_span: float, seed: float, segments: int = 34) -> list[list[float]]:
    angle = math.radians(angle_deg)
    dx = math.sin(angle) * lon_span * 0.82
    dy = math.cos(angle) * lat_span * 0.82
    normal_x = math.cos(angle) * lon_span * 0.035
    normal_y = -math.sin(angle) * lat_span * 0.035
    points = []
    for idx in range(segments):
        t = idx / (segments - 1)
        wave = math.sin(t * math.tau * 1.65 + seed) * (0.45 + 0.18 * math.sin(seed))
        points.append([start_lat + dy * (t - 0.5) + normal_y * wave, start_lon + dx * (t - 0.5) + normal_x * wave])
    return points


def screen_motion_vector(angle_deg: float, distance_px: float) -> tuple[float, float]:
    angle = math.radians(angle_deg)
    return math.sin(angle) * distance_px, -math.cos(angle) * distance_px


def add_weather_motion_overlay(m: folium.Map, bounds: list[list[float]], layers: dict[str, bool], signal: dict) -> None:
    active_motion = any(layers.get(key) for key in ("cloud_veil", "precipitation", "wind_flow"))
    if not active_motion:
        return

    stats = get_bounds_stats(bounds)
    min_lat, min_lon = stats["min_lat"], stats["min_lon"]
    lat_span, lon_span = stats["lat_span"], stats["lon_span"]
    seed = (int(signal["wind_direction"]) + int(float(signal["precipitation"] or 0) * 10)) / 57.0
    wind = clamp(float(signal["wind"] or 0) / 9, 0, 1)
    cloud_dx, cloud_dy = screen_motion_vector(float(signal["wind_direction"]), 90 + wind * 120)
    css_angle = 90 - float(signal["wind_direction"])

    payload = {
        "clouds": [],
        "wind": [],
        "rain": [],
        "stage": {
            "cloud": bool(layers.get("cloud_veil")),
            "wind": bool(layers.get("wind_flow")),
            "rain": bool(layers.get("precipitation") and signal["precip_intensity"] > 0.01),
            "angle": round(css_angle, 1),
            "wind_strength": round(wind, 2),
            "precip_intensity": round(signal["precip_intensity"], 2),
            "seed": round(seed, 3),
        },
    }
    if layers.get("cloud_veil"):
        for idx in range(6):
            payload["clouds"].append({
                "lat": min_lat + lat_span * (0.14 + ((idx * 0.17 + seed * 0.07) % 0.72)),
                "lon": min_lon + lon_span * (0.12 + ((idx * 0.21 + seed * 0.05) % 0.76)),
                "size": round(126 + idx % 3 * 36 + signal["cloud"] * 50),
                "opacity": round(0.16 + signal["cloud"] * 0.20, 2),
                "dx": round(cloud_dx * (0.75 + idx * 0.08), 1),
                "dy": round(cloud_dy * (0.75 + idx * 0.08), 1),
                "delay": round(idx * -4.2, 1),
                "duration": round(18.0 - wind * 2.8 + idx * 0.8, 1),
            })
    style = """
<style>
.ww-motion-layer { position:absolute; inset:0; pointer-events:none; z-index:1000; overflow:hidden; isolation:isolate; }
.ww-motion-layer * { pointer-events:none; }
.ww-motion-stage { position:absolute; inset:0; overflow:hidden; mix-blend-mode:normal; }
.ww-motion-badge { position:absolute; right:12px; top:12px; z-index:3; display:flex; align-items:center; gap:6px; padding:6px 8px; border-radius:999px; background:rgba(248,252,250,.78); color:#244846; border:1px solid rgba(42,83,72,.16); box-shadow:0 8px 24px rgba(35,53,42,.12); backdrop-filter:blur(10px); font:760 10px/1.1 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; letter-spacing:.04em; animation:ww-motion-badge-pulse 2.8s ease-in-out infinite alternate; }
.ww-motion-badge i { width:6px; height:6px; border-radius:99px; background:#2f9ca2; box-shadow:0 0 0 0 rgba(47,156,162,.34); animation:ww-motion-dot 2.2s ease-out infinite; }
.ww-motion-cloud-shelf { position:absolute; left:-22%; top:3%; width:144%; height:43%; opacity:.22; filter:blur(1.6px); background:radial-gradient(ellipse at 18% 44%, rgba(255,255,255,.44), rgba(211,225,226,.18) 28%, rgba(211,225,226,0) 52%), radial-gradient(ellipse at 52% 36%, rgba(255,255,255,.38), rgba(192,214,218,.18) 32%, rgba(192,214,218,0) 58%), radial-gradient(ellipse at 82% 54%, rgba(255,255,255,.40), rgba(202,219,221,.16) 32%, rgba(202,219,221,0) 60%); animation:ww-viewport-cloud 26s ease-in-out infinite alternate; }
.ww-wind-streamfield { position:absolute; inset:-6%; width:112%; height:112%; opacity:var(--wind-alpha); transform:rotate(var(--angle)); transform-origin:center; filter:drop-shadow(0 0 2px rgba(255,255,255,.28)); mix-blend-mode:screen; }
.ww-wind-streamfield path { fill:none; stroke:rgba(226,248,255,.56); stroke-width:.56; stroke-linecap:round; stroke-dasharray:10 18; stroke-dashoffset:0; vector-effect:non-scaling-stroke; animation:ww-streamline-drift var(--speed) linear infinite; animation-delay:var(--delay); }
.ww-wind-streamfield path:nth-child(3n) { stroke:rgba(190,234,248,.42); stroke-width:.46; stroke-dasharray:7 19; }
.ww-wind-streamfield path:nth-child(4n) { stroke:rgba(255,255,255,.48); stroke-width:.38; stroke-dasharray:5 17; }
.ww-wind-streamfield path:nth-child(7n) { opacity:.62; }
.ww-precip-radar { position:absolute; inset:-18%; opacity:var(--rain-alpha); filter:blur(10px) saturate(1.25); mix-blend-mode:multiply; background:radial-gradient(ellipse at 66% 58%, rgba(35,100,255,.58) 0 18%, rgba(35,100,255,.28) 28%, rgba(35,100,255,0) 48%), radial-gradient(ellipse at 42% 72%, rgba(107,96,245,.44) 0 15%, rgba(107,96,245,.22) 26%, rgba(107,96,245,0) 47%), radial-gradient(ellipse at 80% 72%, rgba(183,82,216,.36) 0 12%, rgba(183,82,216,.18) 24%, rgba(183,82,216,0) 42%), radial-gradient(ellipse at 32% 48%, rgba(91,180,255,.32) 0 14%, rgba(91,180,255,.12) 28%, rgba(91,180,255,0) 45%); animation:ww-radar-drift 18s ease-in-out infinite alternate; }
.ww-precip-radar:before { content:""; position:absolute; inset:-4%; opacity:.72; background:radial-gradient(ellipse at 58% 46%, rgba(255,255,255,.88) 0 5%, rgba(255,255,255,.30) 9%, rgba(255,255,255,0) 18%), radial-gradient(ellipse at 46% 62%, rgba(255,255,255,.60) 0 4%, rgba(255,255,255,0) 14%), radial-gradient(ellipse at 72% 70%, rgba(255,255,255,.46) 0 4%, rgba(255,255,255,0) 13%); animation:ww-radar-holes 11s ease-in-out infinite alternate; }
.ww-precip-radar:after { content:""; position:absolute; inset:0; opacity:.52; background:radial-gradient(ellipse at 68% 58%, rgba(31,91,235,.42) 0 12%, rgba(31,91,235,0) 30%), radial-gradient(ellipse at 78% 68%, rgba(177,73,205,.34) 0 10%, rgba(177,73,205,0) 26%); animation:ww-radar-pulse 8.5s ease-in-out infinite alternate; }
.ww-motion-cloud { position:absolute; border-radius:999px; border:1px solid rgba(107,133,138,.07); background:radial-gradient(circle at 35% 42%, rgba(255,255,255,.68), rgba(209,224,224,.36) 47%, rgba(154,181,187,.13) 68%, rgba(154,181,187,0) 80%); filter:blur(1px); box-shadow:0 10px 32px rgba(52,120,169,.08); animation:ww-cloud-drift var(--duration) ease-in-out infinite alternate; animation-delay:var(--delay); opacity:var(--opacity); }
@keyframes ww-cloud-drift {
  from { transform:translate(-50%,-50%) translate(0,0) scale(.96); }
  to { transform:translate(-50%,-50%) translate(var(--dx),var(--dy)) scale(1.10); }
}
@keyframes ww-wind-sweep {
  from { transform:translate(-50%,-50%) rotate(var(--angle)) translateX(calc(var(--travel) * -1)); opacity:.04; }
  18% { opacity:var(--opacity); }
  74% { opacity:var(--opacity); }
  to { transform:translate(-50%,-50%) rotate(var(--angle)) translateX(var(--travel)); opacity:.06; }
}
@keyframes ww-wind-flow {
  from { transform:translateX(-18px); opacity:.04; }
  42% { opacity:.92; }
  to { transform:translateX(24px); opacity:0; }
}
@keyframes ww-rain-cell {
  from { transform:translate(-50%,-50%) rotate(var(--angle)) translateX(-10px); }
  to { transform:translate(-50%,-50%) rotate(var(--angle)) translateX(10px); }
}
@keyframes ww-rain-run {
  from { transform:translateY(-22px); opacity:0; }
  28% { opacity:.82; }
  to { transform:translateY(50px); opacity:0; }
}
@keyframes ww-viewport-cloud {
  from { transform:translate3d(-4%, -1%, 0) scale(1); }
  to { transform:translate3d(7%, 3%, 0) scale(1.035); }
}
@keyframes ww-viewport-wind {
  from { transform:rotate(var(--angle)) translateX(-24%); }
  to { transform:rotate(var(--angle)) translateX(24%); }
}
@keyframes ww-viewport-rain {
  from { background-position:0 0; }
  to { background-position:52px 72px; }
}
@keyframes ww-streamline-drift {
  from { stroke-dashoffset:36; opacity:.16; }
  28% { opacity:.92; }
  76% { opacity:.72; }
  to { stroke-dashoffset:-34; opacity:.16; }
}
@keyframes ww-radar-drift {
  from { transform:translate3d(-3%,1%,0) scale(1); }
  to { transform:translate3d(4%,-2%,0) scale(1.035); }
}
@keyframes ww-radar-holes {
  from { transform:translate3d(-2%,1%,0) scale(.98); opacity:.62; }
  to { transform:translate3d(3%,-1%,0) scale(1.04); opacity:.80; }
}
@keyframes ww-radar-pulse {
  from { transform:scale(.98); opacity:.34; }
  to { transform:scale(1.04); opacity:.64; }
}
@keyframes ww-motion-badge-pulse {
  from { transform:translateY(0); opacity:.72; }
  to { transform:translateY(1px); opacity:.94; }
}
@keyframes ww-motion-dot {
  from { box-shadow:0 0 0 0 rgba(47,156,162,.34); transform:scale(.88); }
  to { box-shadow:0 0 0 9px rgba(47,156,162,0); transform:scale(1.04); }
}
</style>
"""
    motion = MacroElement()
    motion._name = "WeatherMotionOverlay"
    motion.payload = json.dumps(payload)
    motion._template = Template("""
{% macro script(this, kwargs) %}
(function() {
  const map = {{ this._parent.get_name() }};
  const payload = {{ this.payload | safe }};
  const container = map.getContainer();
  const existing = container.querySelector(".ww-motion-layer");
  if (existing) existing.remove();
  const layer = L.DomUtil.create("div", "ww-motion-layer", container);
  const nodes = [];
  const stage = L.DomUtil.create("div", "ww-motion-stage", layer);
  stage.style.setProperty("--angle", payload.stage.angle + "deg");
  stage.style.setProperty("--wind-alpha", (0.38 + payload.stage.wind_strength * 0.20).toFixed(2));
  stage.style.setProperty("--rain-alpha", (payload.stage.precip_intensity * 0.62).toFixed(2));
  const badge = L.DomUtil.create("div", "ww-motion-badge", layer);
  badge.innerHTML = "<i></i><span>weather flow</span>";
  function addWindStreamfield() {
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "ww-wind-streamfield");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.style.setProperty("--angle", payload.stage.angle + "deg");
    const count = Math.round(44 + payload.stage.wind_strength * 24);
    for (let idx = 0; idx < count; idx += 1) {
      const col = idx % 8;
      const row = Math.floor(idx / 8);
      const x = -14 + col * 16 + ((idx * 13 + payload.stage.seed * 11) % 7);
      const y = -4 + row * 12 + ((idx * 17 + payload.stage.seed * 9) % 8);
      const sweep = 24 + (idx % 5) * 5 + payload.stage.wind_strength * 9;
      const bend = ((idx % 6) - 2.5) * 1.8 + Math.sin(idx + payload.stage.seed) * 4.5;
      const d = [
        "M", x.toFixed(2), y.toFixed(2),
        "C", (x + sweep * .28).toFixed(2), (y - bend).toFixed(2),
        (x + sweep * .66).toFixed(2), (y + bend * .55).toFixed(2),
        (x + sweep).toFixed(2), (y + bend * .18).toFixed(2)
      ].join(" ");
      const path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", d);
      path.style.setProperty("--speed", (9.4 - payload.stage.wind_strength * 2.1 + (idx % 7) * .38).toFixed(2) + "s");
      path.style.setProperty("--delay", (-idx * .16).toFixed(2) + "s");
      svg.appendChild(path);
    }
    const curls = [[20,22,8], [74,24,6], [34,72,7], [82,78,9]];
    curls.forEach(function(item, idx) {
      const cx = item[0], cy = item[1], r = item[2];
      const path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", [
        "M", (cx - r).toFixed(2), cy.toFixed(2),
        "C", (cx - r * .3).toFixed(2), (cy - r * 1.2).toFixed(2),
        (cx + r * 1.2).toFixed(2), (cy - r * .8).toFixed(2),
        (cx + r * .8).toFixed(2), cy.toFixed(2),
        "C", (cx + r * .4).toFixed(2), (cy + r * .8).toFixed(2),
        (cx - r * .6).toFixed(2), (cy + r * .45).toFixed(2),
        (cx - r * .2).toFixed(2), (cy - r * .08).toFixed(2)
      ].join(" "));
      path.style.setProperty("--speed", (11.5 + idx * .7).toFixed(2) + "s");
      path.style.setProperty("--delay", (-idx * 1.25).toFixed(2) + "s");
      svg.appendChild(path);
    });
    stage.appendChild(svg);
  }
  if (payload.stage.cloud) {
    L.DomUtil.create("div", "ww-motion-cloud-shelf", stage);
  }
  if (payload.stage.rain) {
    L.DomUtil.create("div", "ww-precip-radar", stage);
  }
  if (payload.stage.wind) {
    addWindStreamfield();
  }
  function register(el, item) {
    layer.appendChild(el);
    nodes.push({el: el, lat: item.lat, lon: item.lon});
  }
  function setBase(el, item) {
    el.style.setProperty("--opacity", item.opacity);
    el.style.setProperty("--delay", item.delay + "s");
    el.style.setProperty("--duration", item.duration + "s");
  }
  payload.clouds.forEach(function(item) {
    const el = document.createElement("div");
    el.className = "ww-motion-cloud";
    setBase(el, item);
    el.style.width = item.size + "px";
    el.style.height = Math.round(item.size * .56) + "px";
    el.style.setProperty("--dx", item.dx + "px");
    el.style.setProperty("--dy", item.dy + "px");
    register(el, item);
  });
  function renderMotion() {
    nodes.forEach(function(node) {
      const point = map.latLngToContainerPoint([node.lat, node.lon]);
      node.el.style.left = point.x + "px";
      node.el.style.top = point.y + "px";
    });
  }
  map.on("zoom viewreset move", renderMotion);
  requestAnimationFrame(renderMotion);
})();
{% endmacro %}
""")
    root = m.get_root()
    root.header.add_child(Element(style))
    m.add_child(motion)


def add_weather_canvas_overlays(m: folium.Map, bounds: list[list[float]], layers: dict[str, bool], signal: dict) -> None:
    stats = get_bounds_stats(bounds)
    min_lat, max_lat, min_lon, max_lon = stats["min_lat"], stats["max_lat"], stats["min_lon"], stats["max_lon"]
    lat_span, lon_span = stats["lat_span"], stats["lon_span"]
    seed = (int(signal["wind_direction"]) + int(float(signal["precipitation"] or 0) * 10)) / 57.0

    if layers.get("cloud_veil"):
        group = folium.FeatureGroup(name="Cloud and fog veil", show=True)
        cloud_opacity = 0.07 + signal["cloud"] * 0.12
        for idx in range(6):
            center_lat = min_lat + lat_span * (0.12 + ((idx * 0.19 + seed * 0.07) % 0.76))
            center_lon = min_lon + lon_span * (0.10 + ((idx * 0.23 + seed * 0.05) % 0.78))
            points = blob_points(center_lat, center_lon, lat_span * (0.11 + idx % 3 * 0.018), lon_span * (0.13 + idx % 2 * 0.026), seed + idx)
            folium.Polygon(points, color="#f4f7f2", weight=1, opacity=cloud_opacity * 0.45, fill=True, fill_color="#f4f7f2", fill_opacity=cloud_opacity, tooltip="Cloud / fog veil").add_to(group)
        group.add_to(m)

    if layers.get("precipitation") and signal["precip_intensity"] > 0.01:
        group = folium.FeatureGroup(name="Precipitation field", show=True)
        rain_opacity = clamp(signal["precip_intensity"] * 0.22, 0.0, 0.24)
        radar_colors = ("#4b8cff", "#6977f2", "#a06fe0")
        for idx in range(7):
            center_lat = min_lat + lat_span * (0.09 + ((idx * 0.17 + seed * 0.11) % 0.82))
            center_lon = min_lon + lon_span * (0.08 + ((idx * 0.29 + seed * 0.09) % 0.82))
            points = blob_points(center_lat, center_lon, lat_span * (0.075 + signal["precip_intensity"] * 0.055), lon_span * (0.09 + signal["precip_intensity"] * 0.06), seed + idx * 1.7)
            cell_opacity = rain_opacity * (1.0 - (idx % 4) * 0.14)
            folium.Polygon(points, color=radar_colors[idx % len(radar_colors)], weight=0, opacity=0, fill=True, fill_color=radar_colors[idx % len(radar_colors)], fill_opacity=cell_opacity, tooltip=f"Precipitation: {format_number(signal['precipitation'], ' mm')}").add_to(group)
        for idx in range(6):
            start_lat = min_lat + lat_span * (0.06 + idx * 0.11)
            start_lon = min_lon + lon_span * (0.08 + ((idx * 0.13 + seed) % 0.78))
            folium.PolyLine(flowline_points(start_lat, start_lon, signal["wind_direction"] + 18, lat_span * 0.34, lon_span * 0.34, seed + idx), color="#9ed6f1", weight=0.55, opacity=signal["precip_intensity"] * 0.12, dash_array="2 18", tooltip="Rain direction").add_to(group)
        group.add_to(m)

    if layers.get("wind_flow"):
        group = folium.FeatureGroup(name="Wind streamlines", show=True)
        wind_opacity = 0.10 + clamp(float(signal["wind"] or 0) / 9, 0, 1) * 0.16
        for idx in range(14):
            start_lat = min_lat + lat_span * (0.05 + idx * 0.068)
            start_lon = min_lon + lon_span * (0.02 + ((idx * 0.19 + seed * 0.3) % 0.96))
            folium.PolyLine(flowline_points(start_lat, start_lon, signal["wind_direction"], lat_span * 0.62, lon_span * 0.62, seed + idx * 0.8), color="#edfaff", weight=1.1, opacity=wind_opacity, dash_array="5 18", tooltip=f"Wind {format_number(signal['wind'], ' m/s')} from {signal['wind_direction']:.0f} deg").add_to(group)
            folium.PolyLine(flowline_points(start_lat, start_lon, signal["wind_direction"], lat_span * 0.62, lon_span * 0.62, seed + idx * 0.8), color="#58aeca", weight=0.45, opacity=wind_opacity * 0.55, dash_array="5 18").add_to(group)
        group.add_to(m)

    if layers.get("moisture_flow"):
        group = folium.FeatureGroup(name="Moisture flow", show=True)
        moisture_opacity = 0.035 + signal["moisture"] * 0.13
        for idx in range(10):
            start_lat = min_lat + lat_span * (0.16 + ((idx * 0.085 + seed * 0.05) % 0.68))
            start_lon = min_lon + lon_span * (0.06 + idx * 0.085)
            points = flowline_points(start_lat, start_lon, 24 + idx * 3, lat_span * 0.52, lon_span * 0.46, seed + idx)
            folium.PolyLine(points, color="#a4e0dc", weight=1.35, opacity=moisture_opacity, dash_array="4 19", tooltip="Moisture flow").add_to(group)
            folium.PolyLine(points, color="#2f8f91", weight=0.35, opacity=moisture_opacity * 0.72, dash_array="4 19").add_to(group)
        for lake_lat, lake_lon in ((47.592, 12.989), (47.606, 12.849)):
            points = blob_points(lake_lat, lake_lon, lat_span * 0.085, lon_span * 0.07, seed)
            folium.Polygon(points, color="#7ed5d0", weight=0, opacity=0, fill=True, fill_color="#7ed5d0", fill_opacity=moisture_opacity * 1.25, tooltip="Water-buffer moisture zone").add_to(group)
        group.add_to(m)

    if layers.get("canopy_stress"):
        group = folium.FeatureGroup(name="Forest stress signal", show=True)
        stress_opacity = 0.07 + signal["stress"] * 0.22
        for idx in range(5):
            center_lat = min_lat + lat_span * (0.20 + ((idx * 0.16 + seed * 0.13) % 0.60))
            center_lon = min_lon + lon_span * (0.18 + ((idx * 0.22 + seed * 0.10) % 0.64))
            color = "#ce6858" if signal["stress"] > 0.55 else "#e3a72f"
            points = blob_points(center_lat, center_lon, lat_span * (0.075 + idx * 0.008), lon_span * (0.10 + idx * 0.01), seed + idx * 2.1)
            folium.Polygon(points, color=color, weight=1, opacity=stress_opacity, fill=True, fill_color=color, fill_opacity=stress_opacity, tooltip="Prototype forest stress signal").add_to(group)
        group.add_to(m)

    add_weather_motion_overlay(m, bounds, layers, signal)


def add_prediction_surface_overlay(m: folium.Map, prediction_df: pd.DataFrame) -> None:
    if prediction_df.empty:
        return
    group = folium.FeatureGroup(name="Predicted stress surface", show=True)
    for _, row in prediction_df.iterrows():
        opacity = 0.08 + clamp(float(row["risk_score"]) / 100, 0, 1) * 0.20
        radius = 300 + float(row["risk_score"]) * 6.5
        popup_html = f"""
        <div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; min-width: 230px;'>
          <strong>{row['risk_label']} stress | {row['risk_score']}/100</strong><br>
          <span>{row['reason']}</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Elevation / slope</td><td>{row['elevation']:.0f} m / {row['slope']:.1f}</td></tr>
            <tr><td>Tree cover</td><td>{row['tree_cover']:.1f}%</td></tr>
            <tr><td>Water occurrence</td><td>{row['water']:.1f}%</td></tr>
          </table>
        </div>
        """
        folium.Circle(location=[row["lat"], row["lon"]], radius=radius, color=row["color_hex"], weight=0.8, opacity=opacity, fill=True, fill_color=row["color_hex"], fill_opacity=opacity, tooltip=f"Predicted stress: {row['risk_score']}/100", popup=folium.Popup(popup_html, max_width=320)).add_to(group)
    group.add_to(m)


def add_dwd_weather_markers(m: folium.Map, readings: list[dict], unavailable: int, layers: dict[str, bool]) -> list[str]:
    if not layers.get("weather_sensors"):
        return []
    if not readings:
        return ["No DWD weather station records were available for the selected period."]
    notes = [f"DWD has no selected-period records for {unavailable} nearby station(s)."] if unavailable else []
    group = folium.FeatureGroup(name="DWD station points", show=True)
    for reading in readings:
        observation_label = reading.get("date", reading.get("period", "n/a"))
        sample_label = "latest hourly record" if reading.get("live") else f"{reading['days']} observed day(s)"
        wind_direction = reading.get("wind_direction")
        wind_label = format_number(reading["wind"], " m/s")
        if wind_direction is not None:
            wind_label = f"{wind_label} / {wind_direction:.0f} deg"
        popup_html = f"""
        <div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; min-width: 260px;'>
          <strong>{reading['name']}</strong><br>
          <span>DWD {reading['station_id']} | {reading['elevation']} m | {reading['distance_km']} km from park center</span><br>
          <span>{reading['period']} | {observation_label} | {sample_label}</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Mean temp</td><td>{format_number(reading['mean_temp'], ' C')}</td></tr>
            <tr><td>Precipitation</td><td>{format_number(reading['precipitation'], ' mm')}</td></tr>
            <tr><td>Humidity</td><td>{format_number(reading['humidity'], '%', 0)}</td></tr>
            <tr><td>Wind</td><td>{wind_label}</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(location=[reading["lat"], reading["lon"]], radius=5.5, color="#ffffff", weight=1.5, fill=True, fill_color="#3478a9", fill_opacity=0.82, tooltip=f"DWD weather: {reading['name']}", popup=folium.Popup(popup_html, max_width=340)).add_to(group)
    group.add_to(m)
    return notes


def add_soil_sensor_markers(m: folium.Map, year: int, period: dict, layers: dict[str, bool]) -> None:
    if not layers.get("soil_sensors"):
        return
    group = folium.FeatureGroup(name="Prototype soil probe points", show=True)
    day_of_year = period["target_date"].timetuple().tm_yday
    for site in SOIL_SENSOR_SITES:
        reading = estimate_soil_reading(site, year, day_of_year)
        popup_html = f"""
        <div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; min-width: 230px;'>
          <strong>{site['name']}</strong><br>
          <span>{site['zone']} | prototype soil probe</span>
          <table style='margin-top: 8px; width: 100%; font-size: 12px;'>
            <tr><td>Soil moisture</td><td>{reading['soil_moisture']}%</td></tr>
            <tr><td>Soil temp</td><td>{reading['soil_temp']} C</td></tr>
            <tr><td>pH / SOC</td><td>{reading['ph']} / {reading['carbon']}%</td></tr>
          </table>
        </div>
        """
        folium.CircleMarker(location=[site["lat"], site["lon"]], radius=5.5, color="#ffffff", weight=1.5, fill=True, fill_color="#e3a72f", fill_opacity=0.82, tooltip=f"Prototype soil probe: {site['name']}", popup=folium.Popup(popup_html, max_width=300)).add_to(group)
    group.add_to(m)


def add_selected_layers(m: folium.Map, year: int, period: dict, signal: dict, aoi: ee.Geometry, bounds: list[list[float]], layers: dict[str, bool], readings: list[dict], unavailable: int) -> tuple[int, list[str]]:
    alphaearth_tile_count = 0
    notes = []
    if layers.get("alphaearth"):
        if year in ALPHAEARTH_YEARS:
            alphaearth, alphaearth_tile_count = get_alphaearth_image(year, aoi)
            add_ee_layer(m, alphaearth, {"bands": DEFAULT_RGB_BANDS, "min": -0.3, "max": 0.3}, "Landscape patterns", opacity=0.62)
        else:
            notes.append("AlphaEarth is available for 2017-2024, so it is hidden for this year.")
    if layers.get("tree_cover"):
        add_ee_layer(m, get_tree_cover_layer(aoi), {"min": 20, "max": 95, "palette": ["#d5e8bd", "#2c8c4a", "#0e4f2e"]}, "Tree canopy", opacity=0.42)
    if layers.get("tree_loss"):
        if year > 2025:
            notes.append("Tree-cover loss uses Hansen data through 2025 for 2026 views.")
        add_ee_layer(m, get_tree_loss_layer(year, aoi), {"min": 1, "max": 1, "palette": ["#ce6858"]}, "Tree-cover loss", opacity=0.70)
    if layers.get("water"):
        add_ee_layer(m, get_surface_water_layer(aoi), {"min": 10, "max": 100, "palette": ["#bde7ff", "#3478a9", "#075985"]}, "Water and wetlands", opacity=0.58)
    if layers.get("habitat"):
        add_ee_layer(m, get_worldcover_layer(aoi), {"min": 10, "max": 100, "palette": ["#006400", "#ffbb22", "#ffff4c", "#f096ff", "#fa0000", "#b4b4b4", "#f0f0f0", "#0064c8", "#0096a0", "#00cf75", "#fae6a0"]}, "Land-cover habitat", opacity=0.36)
    if layers.get("fire"):
        burned_area = get_burned_area_layer(year, aoi)
        if burned_area is None:
            notes.append("Burned-area history is not available for the selected year yet.")
        else:
            add_ee_layer(m, burned_area, {"min": 1, "max": 366, "palette": ["#ffdd8a", "#e3a72f", "#ce6858"]}, "Burned-area history", opacity=0.72)
    if layers.get("air_temperature"):
        air_temperature = get_air_temperature_layer(year, aoi)
        if air_temperature is None:
            notes.append("ERA5-Land air temperature is not available for the selected year yet.")
        else:
            add_ee_layer(m, air_temperature, {"min": -5, "max": 14, "palette": ["#244cbd", "#e8f5ff", "#ffb14e", "#ce6858"]}, "Air temperature model", opacity=0.42)
    if layers.get("soil_moisture"):
        soil_moisture = get_soil_moisture_layer(year, aoi)
        if soil_moisture is None:
            notes.append("ERA5-Land soil moisture is not available for the selected year yet.")
        else:
            add_ee_layer(m, soil_moisture, {"min": 0.18, "max": 0.55, "palette": ["#8c510a", "#f6e8c3", "#80cdc1", "#01665e"]}, "Soil moisture model", opacity=0.48)

    add_weather_canvas_overlays(m, bounds, layers, signal)
    notes.extend(add_dwd_weather_markers(m, readings, unavailable, layers))
    add_soil_sensor_markers(m, year, period, layers)
    return alphaearth_tile_count, notes


def build_weather_table(readings: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Station": r["name"], "Source": r["period"], "Observed": r.get("date", "n/a"), "Days": r["days"], "Distance km": r["distance_km"], "Mean temp C": r["mean_temp"], "Precip mm": r["precipitation"], "Humidity %": r["humidity"], "Wind m/s": r["wind"], "Wind deg": r.get("wind_direction"), "Gust m/s": r["gust"]}
        for r in readings
    ])


def build_sensor_frame(year: int, period: dict, readings: list[dict]) -> pd.DataFrame:
    rows = []
    for reading in readings:
        rows.append({"name": reading["name"], "kind": "DWD weather", "lat": reading["lat"], "lon": reading["lon"], "elevation": reading["elevation"], "color": [52, 120, 169, 220], "radius": 170, "tooltip": f"{format_number(reading['mean_temp'], ' C')} | {format_number(reading['precipitation'], ' mm')} precip"})
    day_of_year = period["target_date"].timetuple().tm_yday
    for site in SOIL_SENSOR_SITES:
        reading = estimate_soil_reading(site, year, day_of_year)
        rows.append({"name": site["name"], "kind": "Prototype soil probe", "lat": site["lat"], "lon": site["lon"], "elevation": site["elevation"], "color": [227, 167, 47, 230], "radius": 145, "tooltip": f"{reading['soil_moisture']}% moisture | pH {reading['ph']}"})
    return pd.DataFrame(rows)


def apply_view_preset(view_mode: str, app_mode: str) -> None:
    preset_key = f"{app_mode}:{view_mode}"
    if st.session_state.get("active_view_preset") == preset_key:
        return
    st.session_state["active_view_preset"] = preset_key
    preset_layers = VIEW_PRESETS[view_mode]["layers"]
    for layer_id, _, _ in LAYER_META:
        st.session_state[f"layer_{layer_id}"] = preset_layers.get(layer_id, False)


def apply_prediction_layer_scope(app_mode: str) -> None:
    if app_mode != "Predictions":
        return
    for layer_id in PREDICTION_DISABLED_LAYERS:
        st.session_state[f"layer_{layer_id}"] = False
    for layer_id in PREDICTION_FORCED_LAYERS:
        st.session_state[f"layer_{layer_id}"] = True


def is_prediction_scoped_layer(app_mode: str, layer_id: str) -> bool:
    return app_mode == "Predictions" and layer_id in (PREDICTION_DISABLED_LAYERS | PREDICTION_FORCED_LAYERS)


def get_query_value(name: str) -> Optional[str]:
    value = st.query_params.get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value else None


def sync_workspace_mode_from_query() -> None:
    workspace_slug = get_query_value("workspace")
    query_mode = WORKSPACE_MODES_BY_SLUG.get(workspace_slug or "")
    if query_mode and st.session_state.get("workspace_query_slug") != workspace_slug:
        st.session_state["workspace_mode"] = query_mode
        st.session_state["workspace_query_slug"] = workspace_slug
    elif "workspace_mode" not in st.session_state:
        st.session_state["workspace_mode"] = "Map"


def sync_workspace_query(app_mode: str) -> None:
    workspace_slug = WORKSPACE_QUERY_SLUGS[app_mode]
    if get_query_value("workspace") != workspace_slug:
        st.query_params["workspace"] = workspace_slug
    st.session_state["workspace_query_slug"] = workspace_slug


def get_period_step_key(granularity: str) -> str:
    return "timeline_day" if granularity == "Daily" else "timeline_week"


def get_period_step_bounds(year: int, granularity: str) -> tuple[int, int]:
    if granularity == "Daily":
        return 1, 366 if calendar.isleap(year) else 365
    if granularity == "Weekly":
        return 1, 52
    return 1, 1


def get_default_period_step(year: int, granularity: str) -> int:
    if granularity == "Daily":
        return min(196, get_period_step_bounds(year, granularity)[1])
    if granularity == "Weekly":
        return 28
    return 1


def clamp_session_step(key: str, year: int, granularity: str) -> None:
    min_step, max_step = get_period_step_bounds(year, granularity)
    current = int(st.session_state.get(key, get_default_period_step(year, granularity)))
    st.session_state[key] = min(max(current, min_step), max_step)


def advance_period_step(key: str, year: int, granularity: str, delta: int) -> None:
    clamp_session_step(key, year, granularity)
    min_step, max_step = get_period_step_bounds(year, granularity)
    st.session_state[key] = min(max(int(st.session_state[key]) + delta, min_step), max_step)


def render_timeline_status(year: int, granularity: str, step_index: Optional[int]) -> None:
    period = build_period_context(year, granularity, step_index)
    if granularity == "Annual":
        progress = ((year - 2000) / 26) * 100
        left_label, right_label = "2000", "2026"
    else:
        min_step, max_step = get_period_step_bounds(year, granularity)
        progress = ((int(step_index or min_step) - min_step) / max(max_step - min_step, 1)) * 100
        left_label, right_label = str(min_step), str(max_step)
    st.markdown(f"""
<div class="ww-time-card">
  <span>Selected time</span>
  <strong>{period['label']}</strong>
  <div class="ww-time-rail"><i style="width:{progress:.1f}%;"></i></div>
  <div class="ww-time-meta"><em>{left_label}</em><em>{granularity}</em><em>{right_label}</em></div>
</div>
    """, unsafe_allow_html=True)


def render_forecast_horizon_status(today: date, horizon_years: int) -> None:
    target = add_years_safe(today, horizon_years)
    progress = (horizon_years / FORECAST_HORIZON_YEARS) * 100
    horizon_label = "Today" if horizon_years == 0 else f"+{horizon_years} year(s)"
    st.markdown(f"""
<div class="ww-time-card">
  <span>Forecast horizon</span>
  <strong>{horizon_label}</strong>
  <div class="ww-time-rail"><i style="width:{progress:.1f}%;"></i></div>
  <div class="ww-time-meta"><em>{today.strftime('%b %d, %Y')}</em><em>Prototype forecast</em><em>{target.strftime('%b %d, %Y')}</em></div>
</div>
    """, unsafe_allow_html=True)


def render_topbar(app_mode: str) -> None:
    def nav_class(label: str) -> str:
        return "active" if label == app_mode else ""

    nav_items = "".join(
        f'<a class="{nav_class(label)}" href="?workspace={WORKSPACE_QUERY_SLUGS[label]}" target="_self">{label}</a>'
        for label in WORKSPACE_MODES
    )
    st.markdown(f"""
<div class="ww-topbar">
  <div class="ww-brand"><div class="ww-mark">W</div><span>Whispering Woods</span></div>
  <div class="ww-nav">{nav_items}</div>
</div>
    """, unsafe_allow_html=True)


def render_header(usage_mode: str, enabled_count: int, area_name: str, view_mode: str, app_mode: str, period_label: str, projection_year: int) -> None:
    titles = {"Map": "Forest weather canvas", "3D View": "Terrain, stress, and observation points", "Predictions": "Forest vulnerability forecast"}
    lens_copy = VIEW_PRESETS[view_mode]["copy"]
    if app_mode == "Predictions":
        lens_copy = FORECAST_CAVEAT
    timeline_status = f"Today -> {projection_year}" if app_mode == "Predictions" else (f"Projection {projection_year}" if app_mode == "3D View" else period_label)
    mode_status = "Prototype forecast" if app_mode == "Predictions" else "Earth Engine live"
    st.markdown(f"""
<div class="ww-hero">
  <div>
    <div class="ww-kicker">{area_name}</div>
    <div class="ww-title">{titles[app_mode]}</div>
    <div class="ww-hero-copy">{lens_copy}</div>
  </div>
  <div class="ww-status-row">
    <div class="ww-status">{mode_status}</div>
    <div class="ww-status gold">{usage_mode}</div>
    <div class="ww-status">{timeline_status}</div>
    <div class="ww-status">{enabled_count} layers</div>
  </div>
</div>
    """, unsafe_allow_html=True)


def render_layer_panel() -> tuple:
    st.markdown("<div class='ww-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='ww-panel-title'>Explore</div>", unsafe_allow_html=True)
    st.markdown("<div class='ww-panel-copy'>Shape the forest canvas by time, lens, and evidence layer.</div>", unsafe_allow_html=True)

    sync_workspace_mode_from_query()
    st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Workspace</div>", unsafe_allow_html=True)
    app_mode = st.radio("Workspace", WORKSPACE_MODES, horizontal=True, label_visibility="collapsed", key="workspace_mode")
    sync_workspace_query(app_mode)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Lens</div>", unsafe_allow_html=True)
    view_mode = st.selectbox("Exploration lens", list(VIEW_PRESETS.keys()), index=0, label_visibility="collapsed")
    apply_view_preset(view_mode, app_mode)
    apply_prediction_layer_scope(app_mode)
    st.caption(VIEW_PRESETS[view_mode]["copy"])
    st.markdown("</div>", unsafe_allow_html=True)

    today = date.today()
    step_index: Optional[int] = None
    if app_mode == "Predictions":
        st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Forecast horizon</div>", unsafe_allow_html=True)
        year = today.year
        granularity = "Daily"
        step_index = today.timetuple().tm_yday
        weather_source = "Live DWD hourly"
        default_horizon = min(max(int(st.session_state.get("forecast_horizon_years", DEFAULT_FORECAST_HORIZON_YEARS)), 0), FORECAST_HORIZON_YEARS)
        horizon_years = int(st.slider("Years from today", min_value=0, max_value=FORECAST_HORIZON_YEARS, value=default_horizon, step=1, key="forecast_horizon_years"))
        projection_year = today.year + horizon_years
        render_forecast_horizon_status(today, horizon_years)
    else:
        st.markdown("<div class='ww-control-band'><div class='ww-section-label'>Timeline</div>", unsafe_allow_html=True)
        year = int(st.number_input("Year", min_value=2000, max_value=2026, value=int(st.session_state.get("timeline_year", 2024)), step=1, key="timeline_year"))
        granularity = st.radio("Time step", ["Weekly", "Daily", "Annual"], index=0, horizontal=True, key="timeline_granularity")
        weather_source = st.radio("Weather source", ["Live DWD hourly", "Selected timeline"], index=0, horizontal=True, key="weather_source", help="Live reads recent public hourly DWD files. Selected timeline uses daily DWD climate records for the chosen day, week, or year.")
        if granularity != "Annual":
            step_key = get_period_step_key(granularity)
            clamp_session_step(step_key, year, granularity)
            previous_col, step_col, next_col = st.columns([0.22, 0.56, 0.22])
            with previous_col:
                if st.button("Prev", key=f"{step_key}_prev", use_container_width=True):
                    advance_period_step(step_key, year, granularity, -1)
            with next_col:
                if st.button("Next", key=f"{step_key}_next", use_container_width=True):
                    advance_period_step(step_key, year, granularity, 1)
            min_step, max_step = get_period_step_bounds(year, granularity)
            with step_col:
                step_index = int(st.number_input("Week" if granularity == "Weekly" else "Day of year", min_value=min_step, max_value=max_step, step=1, key=step_key))
        render_timeline_status(year, granularity, step_index)
        projection_year = int(st.number_input("Projection year", min_value=2026, max_value=2040, value=int(st.session_state.get("projection_year", 2030)), step=1, key="projection_year"))
    risk_scenario = st.selectbox("Climate scenario", list(SCENARIO_SETTINGS.keys()), index=1)
    basemap = st.selectbox("Map style", ["Light", "Satellite", "Terrain"], index=0)
    height_mode = "Risk score"
    if app_mode == "3D View":
        height_mode = st.radio("3D height", ["Risk score", "Terrain"], index=0, horizontal=True)
    st.markdown("</div>", unsafe_allow_html=True)

    for section_label, section_layers in LAYER_SECTIONS:
        section_disabled = app_mode == "Predictions" and section_label == "Weather canvas"
        section_class = "ww-control-band disabled" if section_disabled else "ww-control-band"
        st.markdown(f"<div class='{section_class}'><div class='ww-section-label'>{section_label}</div>", unsafe_allow_html=True)
        if section_disabled:
            st.markdown("<div class='ww-control-note'>Weather motion is paused in Forecast. The model uses DWD climate trend internally instead of live rain, wind, or cloud animation switches.</div>", unsafe_allow_html=True)
        elif app_mode == "Predictions" and section_label == "Forest evidence":
            st.markdown("<div class='ww-control-note'>The predicted stress surface is locked on; other evidence layers remain optional context.</div>", unsafe_allow_html=True)
        for layer_id, label, help_text in section_layers:
            disabled = is_prediction_scoped_layer(app_mode, layer_id)
            st.checkbox(label, key=f"layer_{layer_id}", help=help_text, disabled=disabled)
        st.markdown("</div>", unsafe_allow_html=True)

    layers = {layer_id: bool(st.session_state.get(f"layer_{layer_id}", False)) for layer_id, _, _ in LAYER_META}
    with st.expander("Custom AOI", expanded=False):
        geojson_input: str = st.text_area("GeoJSON polygon", "", height=120, help="Leave blank to use Berchtesgaden National Park.")
    st.markdown("</div>", unsafe_allow_html=True)
    return app_mode, year, projection_year, risk_scenario, height_mode, basemap, geojson_input, layers, view_mode, granularity, step_index, weather_source


def render_sources_panel() -> None:
    st.markdown("""
<div class="ww-source-list">
  <div class="ww-source-item"><strong>Boundary</strong><br>WDPA Berchtesgaden National Park, with local fallback.</div>
  <div class="ww-source-item"><strong>Earth observation</strong><br>AlphaEarth, Hansen, JRC water, ESA WorldCover, MODIS, ERA5-Land, and SRTM.</div>
  <div class="ww-source-item"><strong>Weather motion</strong><br>DWD live hourly observations by default, with selected-period daily records for timeline comparison. Rain, cloud, wind, and moisture patterns are rendered in-app.</div>
  <div class="ww-source-item"><strong>Prototype observations</strong><br>Soil probes are deterministic placeholders until a real sensor feed is supplied.</div>
</div>
    """, unsafe_allow_html=True)


def render_planned_layers() -> None:
    st.markdown("""
<div class="ww-plan-label">Planned integrations</div>
<div class="ww-plan-grid"><div class="ww-plan-chip">Inventory trees</div><div class="ww-plan-chip">Species observations</div><div class="ww-plan-chip">Trail impact reports</div><div class="ww-plan-chip">Ranger field notes</div></div>
    """, unsafe_allow_html=True)


def render_environment_strip(signal: dict) -> None:
    precip_width = round(signal["precip_intensity"] * 100)
    moisture_width = round(signal["moisture"] * 100)
    cloud_width = round(signal["cloud"] * 100)
    stress_width = round(signal["stress"] * 100)
    wind_width = round(clamp(float(signal["wind"] or 0) / 9, 0, 1) * 100)
    st.markdown(f"""
<div class="ww-signal-grid">
  <div class="ww-signal"><span>Precipitation</span><strong>{format_number(signal['precipitation'], ' mm')}</strong><div class="ww-bar"><i style="width:{precip_width}%;background:#3478a9;"></i></div></div>
  <div class="ww-signal"><span>Wind</span><strong>{format_number(signal['wind'], ' m/s')} | {signal['wind_direction']:.0f} deg</strong><div class="ww-bar"><i style="width:{wind_width}%;background:#8eb8c7;"></i></div></div>
  <div class="ww-signal"><span>Moisture</span><strong>{moisture_width}% signal</strong><div class="ww-bar"><i style="width:{moisture_width}%;background:#3ca7a6;"></i></div></div>
  <div class="ww-signal"><span>Cloud/fog</span><strong>{cloud_width}% veil</strong><div class="ww-bar"><i style="width:{cloud_width}%;background:#b7c8cc;"></i></div></div>
  <div class="ww-signal"><span>Forest stress signal</span><strong>{stress_width}% prototype</strong><div class="ww-bar"><i style="width:{stress_width}%;background:#ce6858;"></i></div></div>
</div>
    """, unsafe_allow_html=True)


def render_weather_motion_proof(layers: dict[str, bool], signal: dict) -> None:
    if not any(layers.get(key) for key in ("cloud_veil", "precipitation", "wind_flow")):
        return
    active_parts = []
    if layers.get("wind_flow"):
        active_parts.append(f"wind {format_number(signal['wind'], ' m/s')} / {signal['wind_direction']:.0f} deg")
    if layers.get("precipitation"):
        active_parts.append(f"rain {format_number(signal['precipitation'], ' mm')}")
    if layers.get("cloud_veil"):
        active_parts.append(f"cloud {round(signal['cloud'] * 100)}%")
    st.markdown(f"""
<div class="ww-motion-proof">
  <div class="ww-motion-proof-content">
    <div>
      <strong>Weather flow layer</strong>
      <span>{' | '.join(active_parts)}</span>
    </div>
    <div class="ww-motion-proof-dot"></div>
  </div>
  <div class="ww-reduced-motion-note">Your browser or OS reports reduced motion. If the strip is static, animation may be suppressed locally.</div>
</div>
    """, unsafe_allow_html=True)


def render_observation_summary(period: dict, view_mode: str, layers: dict[str, bool], signal: dict, readings: list[dict], unavailable: int, app_mode: str, projection_year: int) -> None:
    if readings:
        nearest = readings[0]
        weather_label = f"{format_number(nearest['mean_temp'], ' C')} | {format_number(nearest['precipitation'], ' mm')}"
        station_label = f"{len(readings)} station(s), {unavailable} gap(s)"
    else:
        weather_label = f"Seasonal fallback for {period['label']}"
        station_label = "DWD period records unavailable"
    time_label = "Forecast horizon" if app_mode == "Predictions" else "Time view"
    time_value = f"Today -> {projection_year}" if app_mode == "Predictions" else period["label"]
    st.markdown(f"""
<div class="ww-kpi-grid">
  <div class="ww-kpi"><span>{time_label}</span><strong>{time_value}</strong></div>
  <div class="ww-kpi"><span>Nearest weather</span><strong>{weather_label}</strong></div>
  <div class="ww-kpi"><span>Coverage</span><strong>{station_label}</strong></div>
  <div class="ww-kpi"><span>Lens</span><strong>{view_mode}</strong></div>
</div>
    """, unsafe_allow_html=True)
    active_labels = [label for layer_id, label, _ in LAYER_META if layers.get(layer_id)]
    if active_labels:
        st.caption("Active evidence: " + ", ".join(active_labels) + f". Weather canvas signal source: {signal['source']}.")


def build_project_action(prediction_df: Optional[pd.DataFrame], signal: dict, app_mode: str) -> tuple[str, str, str, str]:
    if prediction_df is not None and not prediction_df.empty:
        mean_score = round(float(prediction_df["risk_score"].mean()), 1)
        high_share = round(float((prediction_df["risk_score"] >= 68).mean() * 100), 0)
        top = prediction_df.nlargest(1, "risk_score").iloc[0]
        if mean_score >= 64 or high_share >= 22:
            action = "Prioritize field review"
            detail = f"{high_share:.0f}% of sampled cells are high-stress in this prototype surface. Start with {top['reason']}."
            tone = "warn"
        elif mean_score >= 46 or high_share >= 8:
            action = "Keep under watch"
            detail = f"Mean prototype stress is {mean_score}/100. Compare canopy, water buffers, and recent weather before selecting field routes."
            tone = "warn"
        else:
            action = "Maintain observation"
            detail = f"Mean prototype stress is {mean_score}/100. Use this as a baseline for future change detection."
            tone = "ok"
        return action, detail, f"{mean_score}/100", tone

    stress_pct = round(signal["stress"] * 100)
    if stress_pct >= 58:
        return "Open forecast view", "The live context signal is elevated. Use Predictions to see whether terrain, canopy, water, and climate trend point to the same areas.", f"{stress_pct}% signal", "warn"
    if app_mode == "Predictions":
        return "Prototype forecast", FORECAST_CAVEAT, f"{stress_pct}% signal", "warn"
    return "Explore evidence layers", "Turn on canopy, water, tree-cover loss, and habitat layers to move from ambience into decision context.", f"{stress_pct}% signal", "ok"


def render_project_impact_brief(area_name: str, app_mode: str, period: dict, signal: dict, readings: list[dict], layers: dict[str, bool], projection_year: int, prediction_df: Optional[pd.DataFrame] = None, climate_signal: Optional[dict] = None) -> None:
    action, action_detail, stress_value, action_tone = build_project_action(prediction_df, signal, app_mode)
    moisture_pct = round(signal["moisture"] * 100)
    source = signal.get("source", "selected evidence")
    nearest = readings[0]["name"] if readings else "seasonal fallback"
    climate_copy = "DWD annual climate trend" if climate_signal else source
    target_label = f"Today to {projection_year}" if app_mode == "Predictions" else period["label"]
    forecast_badge = "Prototype forecast" if prediction_df is not None and not prediction_df.empty else "Evidence canvas"
    chips = [
        "WDPA boundary",
        "DWD weather/climate",
        "Earth Engine public layers",
        "Prototype stress model" if prediction_df is not None and not prediction_df.empty else "Layer exploration",
        "Tree twin path",
    ]
    chip_markup = "".join(f"<span class='ww-source-chip'>{chip}</span>" for chip in chips)
    tree_nodes = "".join(
        f"<i class='ww-tree-node' style='--x:{8 + idx * 7}%;--h:{34 + (idx % 5) * 9}px;--c:{12 + (idx % 4) * 4}px;'></i>"
        for idx in range(12)
    )
    action_class = "ww-brief-chip warn" if action_tone == "warn" else "ww-brief-chip"
    st.markdown(f"""
<div class="ww-project-brief">
  <div class="ww-brief-top">
    <div>
      <div class="ww-brief-kicker">Impact brief</div>
      <div class="ww-brief-title">{area_name}</div>
      <div class="ww-brief-copy">A conservation-oriented digital twin view for reading forest condition, monitoring priorities, and the next evidence needed at tree level.</div>
    </div>
    <div class="ww-brief-status">
      <span class="ww-brief-chip">{forecast_badge}</span>
      <span class="{action_class}">{action}</span>
      <span class="ww-brief-chip warn">Field validation needed</span>
    </div>
  </div>
  <div class="ww-brief-grid">
    <div>
      <div class="ww-impact-grid">
        <div class="ww-impact-card"><span>Decision window</span><strong>{target_label}</strong><p>Use the selected time or forecast horizon to frame what should be inspected next, not as an operational decision by itself.</p></div>
        <div class="ww-impact-card"><span>Forest stress</span><strong>{stress_value}</strong><p>{action_detail}</p></div>
        <div class="ww-impact-card"><span>Water and moisture</span><strong>{moisture_pct}% context</strong><p>Moisture and recurring water help explain where stress may be buffered or where dry slopes need closer attention.</p></div>
        <div class="ww-impact-card"><span>Evidence confidence</span><strong>Real + prototype</strong><p>{climate_copy}; nearest station context: {nearest}. Individual-tree data is still planned.</p></div>
      </div>
      <div class="ww-brief-sources">{chip_markup}</div>
    </div>
    <div class="ww-twin-card">
      <div class="ww-twin-content">
        <div class="ww-brief-kicker">Tree digital twin</div>
        <h3>From stand-level evidence to individual-tree memory</h3>
        <p>The current app reads the forest as layers. The next product step is a tree register that can later anchor scans, health notes, and Gaussian splat visual assets.</p>
        <div class="ww-tree-stand">{tree_nodes}</div>
        <div class="ww-twin-steps">
          <div class="ww-twin-step"><span>Canopy, water, terrain, climate</span><em>live now</em></div>
          <div class="ww-twin-step"><span>Species, height, crown condition, field notes</span><em>next</em></div>
          <div class="ww-twin-step"><span>LiDAR/photogrammetry and Gaussian splat scenes</span><em>later</em></div>
          <div class="ww-twin-step"><span>Forecast feedback from observed tree health</span><em>validate</em></div>
        </div>
      </div>
    </div>
  </div>
</div>
    """, unsafe_allow_html=True)


def render_prediction_summary(prediction_df: pd.DataFrame, climate_signal: dict, projection_year: int, scenario_name: str) -> None:
    if prediction_df.empty:
        return
    mean_score = round(float(prediction_df["risk_score"].mean()), 1)
    high_share = round(float((prediction_df["risk_score"] >= 68).mean() * 100), 0)
    top = prediction_df.nlargest(1, "risk_score").iloc[0]
    temp_delta = climate_signal.get("projected_temp_delta", 0)
    precip_delta = climate_signal.get("projected_precip_delta_pct", 0)
    st.markdown(f"""
<div class="ww-forecast-caveat"><strong>Prototype forecast</strong>{FORECAST_CAVEAT}</div>
<div class="ww-kpi-grid">
  <div class="ww-kpi"><span>Mean stress</span><strong>{mean_score}/100</strong></div>
  <div class="ww-kpi"><span>High-stress share</span><strong>{high_share:.0f}%</strong></div>
  <div class="ww-kpi"><span>Climate signal</span><strong>{temp_delta:+.1f} C | {precip_delta:+.0f}% precip</strong></div>
  <div class="ww-kpi"><span>Top hotspot</span><strong>{top['risk_score']:.1f}/100 | {top['risk_label']}</strong></div>
</div>
    """, unsafe_allow_html=True)
    st.caption(f"Projection: {projection_year}, scenario: {scenario_name}. {climate_signal.get('source_note', '')}")


def get_enabled_labels(layers: dict[str, bool]) -> list[tuple[str, str]]:
    label_specs = [
        ("precipitation", "Precipitation", "#3478a9"),
        ("wind_flow", "Wind", "#8eb8c7"),
        ("cloud_veil", "Cloud/fog", "#b7c8cc"),
        ("moisture_flow", "Moisture", "#3ca7a6"),
        ("canopy_stress", "Forest stress", "#ce6858"),
        ("alphaearth", "Landscape", "#449666"),
        ("prediction", "Predicted stress", "#ce6858"),
        ("tree_cover", "Tree canopy", "#2c8c4a"),
        ("tree_loss", "Forest loss", "#ce6858"),
        ("water", "Water", "#3478a9"),
        ("habitat", "Habitat", "#a7bd52"),
        ("fire", "Burned area", "#e3a72f"),
        ("air_temperature", "Air temp", "#ce6858"),
        ("soil_moisture", "Soil moisture", "#45a6b7"),
        ("weather_sensors", "DWD points", "#3478a9"),
        ("soil_sensors", "Soil points", "#e3a72f"),
    ]
    labels = [(label, color) for layer_id, label, color in label_specs if layers.get(layer_id)]
    return labels or [("Park boundary", AOI_COLOR)]


def render_map_heading(period_label: str, enabled_labels: list[tuple[str, str]], area_name: str, title: str = "Forest evidence layers") -> None:
    legend_markup = "".join(f"<span class='ww-pill'><span class='ww-dot' style='background:{color}'></span>{label}</span>" for label, color in enabled_labels)
    st.markdown(f"""
<div class="ww-map-head"><div><div class="ww-map-label">{area_name}</div><div class="ww-map-title">{title}, {period_label}</div></div><div class="ww-legend">{legend_markup}</div></div>
    """, unsafe_allow_html=True)


def build_insight_items(view_mode: str, year: int, period: dict, layers: dict[str, bool], signal: dict, notes: list[str]) -> list[tuple[str, str, str]]:
    items = [("Lens", view_mode, VIEW_PRESETS[view_mode]["copy"])]
    if any(layers.get(key) for key in ("precipitation", "wind_flow", "cloud_veil", "moisture_flow")):
        items.append(("Weather canvas", signal["source"], "Weather overlays are rendered in-app from DWD station evidence when available, with a labelled seasonal fallback."))
    if layers.get("alphaearth"):
        items.append(("Landscape", "AlphaEarth active" if year in ALPHAEARTH_YEARS else "AlphaEarth hidden", "Annual embeddings currently cover 2017-2024." if year not in ALPHAEARTH_YEARS else "Embedding colors reveal landscape pattern differences inside the park."))
    if layers.get("prediction"):
        items.append(("Forecast", "Prototype model", FORECAST_CAVEAT))
    if layers.get("tree_loss"):
        items.append(("Forest change", "Cumulative loss", "The red layer marks Hansen tree-cover loss up to the selected year."))
    if layers.get("canopy_stress"):
        items.append(("Forest stress signal", f"{round(signal['stress'] * 100)}% prototype", "The stress signal is a visual prototype, not a field-validated hazard layer."))
    for note in notes[:2]:
        items.append(("Data note", "Coverage", note))
    return items[:6]


def render_map_selection(map_state: Optional[dict]) -> None:
    if not isinstance(map_state, dict):
        return
    clicked = map_state.get("last_object_clicked_tooltip") or map_state.get("last_object_clicked_popup")
    if clicked:
        st.markdown(f"<div class='ww-selected'><strong>Selected on map:</strong> {clicked}</div>", unsafe_allow_html=True)
        return
    last_clicked = map_state.get("last_clicked")
    if isinstance(last_clicked, dict) and "lat" in last_clicked and "lng" in last_clicked:
        st.markdown(f"<div class='ww-selected'><strong>Map point:</strong> {last_clicked['lat']:.5f}, {last_clicked['lng']:.5f}</div>", unsafe_allow_html=True)


def render_prediction_evidence(prediction_df: pd.DataFrame, climate_signal: dict, scenario_name: str, projection_year: int) -> None:
    if prediction_df.empty:
        return
    drivers_tab, hotspots_tab, method_tab = st.tabs(["Drivers", "Hotspots", "Model note"])
    with drivers_tab:
        driver_df = pd.DataFrame([
            {"Driver": "Warming", "Contribution": prediction_df["warming"].mean()},
            {"Driver": "Dryness", "Contribution": prediction_df["dryness"].mean()},
            {"Driver": "Low canopy", "Contribution": prediction_df["low_canopy"].mean()},
            {"Driver": "Loss history", "Contribution": prediction_df["loss_history"].mean()},
            {"Driver": "Steep terrain", "Contribution": prediction_df["steep_terrain"].mean()},
            {"Driver": "Water buffer", "Contribution": -prediction_df["water_buffer"].mean()},
        ])
        st.bar_chart(driver_df.set_index("Driver"), height=280)
    with hotspots_tab:
        hotspots = prediction_df.nlargest(12, "risk_score")[["risk_score", "risk_label", "reason", "elevation", "slope", "tree_cover", "water", "lat", "lon"]]
        st.dataframe(hotspots, use_container_width=True, hide_index=True)
    with method_tab:
        st.markdown(f"""
<div class="ww-method">
<strong>Projection {projection_year} | {scenario_name}</strong><br>
{FORECAST_CAVEAT} It combines public terrain, slope, tree canopy, tree-cover loss, recurring water, and the DWD annual climate signal from {climate_signal.get('station', 'the selected station')}. It is designed for stakeholder exploration, not operational use.
</div>
        """, unsafe_allow_html=True)


def render_evidence_board(year: int, period: dict, view_mode: str, layers: dict[str, bool], signal: dict, readings: list[dict], unavailable: int, notes: list[str], prediction_df: Optional[pd.DataFrame] = None, climate_signal: Optional[dict] = None, scenario_name: str = "Moderate", projection_year: int = 2030) -> None:
    insights_tab, weather_tab, station_tab, sources_tab = st.tabs(["Insights", "Weather timeline", "Stations", "Sources"])
    with insights_tab:
        markup = "".join(f"<div class='ww-insight'><span>{e}</span><strong>{t}</strong><p>{b}</p></div>" for e, t, b in build_insight_items(view_mode, year, period, layers, signal, notes))
        st.markdown(f"<div class='ww-insight-grid'>{markup}</div>", unsafe_allow_html=True)
    with weather_tab:
        st.caption(f"Selected period: {period['label']}. Signal source: {signal['source']}.")
        default_index = next((idx for idx, station in enumerate(DWD_STATIONS) if station["id"] == PREDICTION_STATION_ID), 0)
        station = st.selectbox("Weather trend station", DWD_STATIONS, index=default_index, format_func=lambda item: f"{item['name']} ({item['distance_km']} km)")
        series = get_dwd_annual_series(station["id"])
        if not series:
            st.info("No annual DWD trend records are available for this station in the 2000-2026 window.")
        else:
            df = pd.DataFrame(series)
            selected = df[df["Year"] == year]
            if selected.empty:
                st.caption(f"No annual summary is available for {station['name']} in {year}.")
            else:
                row = selected.iloc[0]
                st.caption(f"{station['name']} in {year}: {row['Mean temp C']} C mean temp, {row['Precip mm']} mm precipitation, {int(row['Days'])} observed day(s).")
            temp_col, precip_col = st.columns(2)
            chart_df = df.set_index("Year")
            with temp_col:
                st.line_chart(chart_df[["Mean temp C"]], height=240)
            with precip_col:
                st.bar_chart(chart_df[["Precip mm"]], height=240)
    with station_tab:
        weather_df = build_weather_table(readings)
        if weather_df.empty:
            st.info(f"No configured DWD station has a record for {period['label']}. {unavailable} station(s) unavailable.")
        else:
            st.dataframe(weather_df, use_container_width=True, hide_index=True)
    with sources_tab:
        render_sources_panel()
        render_planned_layers()
    if prediction_df is not None and climate_signal is not None and not prediction_df.empty:
        render_prediction_evidence(prediction_df, climate_signal, scenario_name, projection_year)


def build_3d_deck(prediction_df: pd.DataFrame, sensor_df: pd.DataFrame, center: list[float], height_mode: str) -> pdk.Deck:
    terrain_df = prediction_df.copy()
    terrain_df["height"] = terrain_df["height_terrain"] if height_mode == "Terrain" else terrain_df["height_risk"]
    terrain_df["deck_tooltip"] = terrain_df.apply(lambda row: f"{row['risk_label']} stress: {row['risk_score']}/100<br>{row['reason']}<br>Elevation {row['elevation']:.0f} m", axis=1)
    layers = [pdk.Layer("ColumnLayer", data=terrain_df, get_position="[lon, lat]", get_elevation="height", get_fill_color="color", radius=120, coverage=0.82, pickable=True, auto_highlight=True)]
    if not sensor_df.empty:
        layers.append(pdk.Layer("ScatterplotLayer", data=sensor_df, get_position="[lon, lat]", get_radius="radius", get_fill_color="color", get_line_color=[255, 255, 255, 230], line_width_min_pixels=1, pickable=True, auto_highlight=True))
    view_state = pdk.ViewState(latitude=center[0], longitude=center[1], zoom=10.7, pitch=58, bearing=-28)
    return pdk.Deck(map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json", initial_view_state=view_state, layers=layers, tooltip={"html": "<b>{name}{risk_label}</b><br>{tooltip}{deck_tooltip}", "style": {"backgroundColor": "#122018", "color": "#ffffff"}})


def render_3d_view(prediction_df: pd.DataFrame, sensor_df: pd.DataFrame, center: list[float], height_mode: str) -> None:
    if prediction_df.empty:
        st.info("No 3D terrain samples are available for this area.")
        return
    st.pydeck_chart(build_3d_deck(prediction_df, sensor_df, center, height_mode), use_container_width=True)


def render_map_mode(year: int, period: dict, projection_year: int, scenario_name: str, basemap: str, layers: dict[str, bool], view_mode: str, signal: dict, readings: list[dict], unavailable: int, aoi: ee.Geometry, area_name: str, center: list[float], bounds: list[list[float]]) -> None:
    prediction_df: Optional[pd.DataFrame] = None
    climate_signal: Optional[dict] = None
    try:
        m = build_map(center, bounds, basemap)
        alphaearth_tile_count, notes = add_selected_layers(m, year, period, signal, aoi, bounds, layers, readings, unavailable)
        if layers.get("prediction"):
            prediction_df, climate_signal, prediction_note = build_prediction_surface(bounds, year, projection_year, scenario_name)
            add_prediction_surface_overlay(m, prediction_df)
            if prediction_note:
                notes.append(prediction_note)
        add_aoi_boundary(m, aoi, area_name)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not render the selected forest layers.", exc)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    render_weather_motion_proof(layers, signal)
    render_map_heading(period["label"], get_enabled_labels(layers), area_name, title="Environmental layer canvas")
    map_state = st_folium(m, width=None, height=780)
    render_map_selection(map_state)
    render_project_impact_brief(area_name, app_mode="Map", period=period, signal=signal, readings=readings, layers=layers, projection_year=projection_year, prediction_df=prediction_df, climate_signal=climate_signal)
    captions = [f"Weather-canvas overlays are rendered in-app from {signal['source']}; animated wind, cloud, moisture, and rain cues are visual guides, not operational radar. Annual Earth Engine layers stay source-native and read-only."]
    if layers.get("alphaearth") and alphaearth_tile_count:
        captions.append(f"AlphaEarth is scoped to {alphaearth_tile_count} tile(s) for the selected AOI.")
    captions.extend(notes)
    st.caption(" ".join(captions))
    render_evidence_board(year, period, view_mode, layers, signal, readings, unavailable, notes, prediction_df, climate_signal, scenario_name, projection_year)


def render_predictions_mode(year: int, period: dict, projection_year: int, scenario_name: str, basemap: str, layers: dict[str, bool], signal: dict, readings: list[dict], unavailable: int, aoi: ee.Geometry, area_name: str, center: list[float], bounds: list[list[float]]) -> None:
    prediction_df, climate_signal, prediction_note = build_prediction_surface(bounds, year, projection_year, scenario_name)
    render_prediction_summary(prediction_df, climate_signal, projection_year, scenario_name)
    render_project_impact_brief(area_name, app_mode="Predictions", period=period, signal=signal, readings=readings, layers=layers, projection_year=projection_year, prediction_df=prediction_df, climate_signal=climate_signal)
    forecast_label = f"Today -> {projection_year}"
    map_layers = dict(layers)
    map_layers["prediction"] = False
    try:
        m = build_map(center, bounds, basemap)
        _, notes = add_selected_layers(m, year, period, signal, aoi, bounds, map_layers, readings, unavailable)
        add_prediction_surface_overlay(m, prediction_df)
        add_aoi_boundary(m, aoi, area_name)
        if prediction_note:
            notes.append(prediction_note)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not render the prediction map.", exc)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    render_map_heading(forecast_label, [("Predicted stress", "#ce6858"), ("Moisture", "#3ca7a6"), ("Wind", "#8eb8c7")], area_name, title="Forecast surface")
    map_state = st_folium(m, width=None, height=660)
    render_map_selection(map_state)
    st.caption(" ".join(notes) if notes else "Prediction is calculated in-app from public read-only layers and local DWD observations.")
    render_prediction_evidence(prediction_df, climate_signal, scenario_name, projection_year)


def render_3d_mode(year: int, period: dict, projection_year: int, scenario_name: str, height_mode: str, bounds: list[list[float]], center: list[float], signal: dict, readings: list[dict]) -> None:
    prediction_df, climate_signal, prediction_note = build_prediction_surface(bounds, year, projection_year, scenario_name)
    sensor_df = build_sensor_frame(year, period, readings)
    render_prediction_summary(prediction_df, climate_signal, projection_year, scenario_name)
    render_project_impact_brief("Berchtesgaden National Park", app_mode="3D View", period=period, signal=signal, readings=readings, layers={"prediction": True}, projection_year=projection_year, prediction_df=prediction_df, climate_signal=climate_signal)
    render_map_heading(f"{period['label']} -> {projection_year}", [("Risk columns", "#ce6858"), ("Terrain", "#449666"), ("Stations", "#3478a9"), ("Soil probes", "#e3a72f")], "Berchtesgaden National Park", title="3D forest view")
    render_3d_view(prediction_df, sensor_df, center, height_mode)
    if prediction_note:
        st.caption(prediction_note)
    render_prediction_evidence(prediction_df, climate_signal, scenario_name, projection_year)


def main() -> None:
    st.set_page_config(page_title="Whispering Woods", layout="wide", initial_sidebar_state="collapsed")
    inject_theme_css()
    usage_mode = enforce_no_cost_guardrail()
    _init_ee_cached()

    control_col, main_col = st.columns([0.95, 3.35], gap="large")
    with control_col:
        app_mode, year, projection_year, scenario_name, height_mode, basemap, geojson_input, layers, view_mode, granularity, step_index, weather_source = render_layer_panel()
        render_sources_panel()
        render_planned_layers()

    period = build_period_context(year, granularity, step_index)
    try:
        if weather_source == "Live DWD hourly":
            readings, unavailable = get_dwd_live_readings()
        else:
            readings, unavailable = get_dwd_readings_for_period(year, granularity, step_index)
    except Exception:
        readings, unavailable = [], len(DWD_STATIONS)
    signal = build_time_signal(year, granularity, step_index, readings)

    aoi, area_name = get_aoi(geojson_input)
    try:
        center, bounds = get_aoi_view(aoi)
    except Exception as exc:
        show_earth_engine_error("Earth Engine could not locate the selected area.", exc)

    enabled_count = sum(1 for enabled in layers.values() if enabled)
    with main_col:
        render_topbar(app_mode)
        render_header(usage_mode, enabled_count, area_name, view_mode, app_mode, period["label"], projection_year)
        render_environment_strip(signal)
        render_observation_summary(period, view_mode, layers, signal, readings, unavailable, app_mode, projection_year)
        if app_mode == "Map":
            render_map_mode(year, period, projection_year, scenario_name, basemap, layers, view_mode, signal, readings, unavailable, aoi, area_name, center, bounds)
        elif app_mode == "Predictions":
            render_predictions_mode(year, period, projection_year, scenario_name, basemap, layers, signal, readings, unavailable, aoi, area_name, center, bounds)
        else:
            render_3d_mode(year, period, projection_year, scenario_name, height_mode, bounds, center, signal, readings)


if __name__ == "__main__":
    main()
