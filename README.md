# Whispering Woods

Whispering Woods is a prototype Streamlit dashboard for exploring conservation-relevant forest information layers in a stakeholder-facing map interface. The active app focuses on Berchtesgaden National Park and combines public Google Earth Engine datasets, nearby DWD weather station observations, a derived 3D terrain view, an explainable forest-stress prediction surface, and clearly labelled prototype soil probes.

The project has an explicit no-cost guardrail for non-commercial thesis, research, conservation, and stakeholder demonstration use.

## Active app

- `app_alphaearth.py`: Main stakeholder map app for Whispering Woods forest intelligence layers.
- `requirements.txt`: Python dependencies needed to run the app.

Run the app with:

```bash
streamlit run app_alphaearth.py
```

The default area of interest is Berchtesgaden National Park. The app first tries to use the WDPA protected-area polygon (`WDPAID 668`) from Earth Engine, and falls back to a local park-scale polygon if that query is unavailable.

## Stakeholder interface

The app is designed as an interactive forest intelligence map:

- Workspace modes: Map, 3D View, and Predictions.
- Exploration lenses: Stakeholder overview, Forest change, Water and climate, and Habitat and risk.
- Timeline slider: 2000-2026.
- Projection controls: 2026-2040 scenario controls for the predictive stress surface.
- Interactive markers: DWD weather stations and prototype soil probes.
- Evidence board: insight cards, DWD annual weather trend, station table, prediction drivers, hotspots, and source notes.
- Map styles: satellite, light, and terrain.
- Custom AOI: optional GeoJSON polygon input for testing another area.

Some layers have narrower availability and are shown only when the selected year supports them:

- AlphaEarth annual satellite embeddings: 2017-2024.
- Hansen tree-cover loss: cumulative loss from 2001-2025; 2026 uses the latest available 2025 loss year.
- ERA5-Land climate and soil fields: available from 1950 to near-real-time, so 2026 may be partial depending on the current month.
- DWD daily weather station observations: shown for the selected year when the nearby station has records for that year.

AlphaEarth does not provide a native 3D scene. In this app, AlphaEarth remains a 2D annual embedding layer. The 3D View is derived by combining public terrain samples, the prediction surface, DWD stations, and prototype soil probes with `pydeck`.

## Data sources

The app currently supports these real public layers and feeds:

- WDPA protected-area boundary for Berchtesgaden National Park.
- AlphaEarth annual satellite embeddings for landscape pattern exploration.
- Hansen Global Forest Change tree canopy and cumulative tree-cover loss.
- JRC Global Surface Water for water and recurring wetland context.
- ESA WorldCover for land-cover / habitat context.
- MODIS MCD64A1 burned-area history for the selected year.
- ERA5-Land 2 m air temperature and top-layer soil moisture model layers.
- SRTM terrain samples for the derived 3D and prediction surfaces.
- DWD Climate Data Center daily climate station observations for nearby active stations.

External source links:

- DWD daily climate observations: `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/`
- DWD recent station files: `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/`
- DWD station metadata: `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/KL_Tageswerte_Beschreibung_Stationen.txt`
- AlphaEarth Satellite Embedding V1: `https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL`
- Google Earth Engine public datasets listed in `app_alphaearth.py`.

## Prediction caveat

The prediction surface is an explainable prototype score from 0-100. It combines terrain elevation, slope, canopy cover, historical tree-cover loss, recurring water, DWD climate trend, and a selected warming/drying scenario.

It is intended for stakeholder exploration and thesis prototyping, not operational hazard certification.

## Prototype-only sources

The app includes prototype soil probe markers for stakeholder workflow design:

- Soil moisture.
- Soil temperature.
- Soil pH.
- Soil organic carbon.

These values are deterministic prototype readings, not live sensor feeds. They show where live soil probes, ranger observations, or field campaigns could plug into the stakeholder interface later.

Prototype-only future integrations are shown separately in the UI as planned layers, not as active evidence: inventory trees, species observations, trail impact reports, and ranger field notes.

## No-cost guardrail

This project is intended to avoid generating costs. The Earth Engine app should be run only with an Earth Engine project registered for eligible non-commercial, research, conservation, or impact use.

To keep the project no-cost:

- Register the Google Cloud project for non-commercial Earth Engine access.
- Keep `EE_USAGE_MODE` set to `noncommercial`, `research`, `conservation`, or `impact`. If it is set to `commercial`, `paid`, `billable`, `enterprise`, `government_operational`, or `production_paid`, the app stops before initializing Earth Engine.
- Do not switch the Earth Engine project to commercial/paid use unless cost generation is intentionally approved.
- Do not add batch exports to Google Cloud Storage, BigQuery, Vertex AI, paid Maps APIs, or other billable Google Cloud services.
- Keep the app read-only. The current code reads public Earth Engine datasets, reads public DWD open-data files, renders map layers, samples a compact terrain grid, and calculates predictions inside Streamlit; it does not export files, write Earth Engine assets, train cloud models, or create cloud resources.
- Monitor the Streamlit app after deployment and stop it if Google/Streamlit reports quota, billing, or paid-plan prompts.

## Earth Engine setup

The app requires a registered Google Cloud project plus service-account credentials. In Streamlit Cloud, add these secrets in the app settings:

```toml
EE_SERVICE_ACCOUNT = "your-service-account@your-project.iam.gserviceaccount.com"
EE_PRIVATE_KEY = '''
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-service-account@your-project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com"
}
'''
# Optional when project_id is already present in EE_PRIVATE_KEY.
EE_PROJECT_ID = "your-project-id"
# Optional no-cost guard label. Defaults to noncommercial when omitted.
EE_USAGE_MODE = "noncommercial"
```

For local development, put the same values in `.streamlit/secrets.toml`. Do not commit real service-account keys to the repository.

The Cloud project must have the Earth Engine API enabled and be registered for Earth Engine use. The service account also needs project-level IAM access:

- `Service Usage Consumer` (`roles/serviceusage.serviceUsageConsumer`)
- `Earth Engine Resource Writer` (`roles/earthengine.writer`), shown as beta in some Google Cloud IAM screens

`Earth Engine Resource Viewer` (`roles/earthengine.viewer`) is enough for some read-only computations, but it does not include `earthengine.maps.create`, which the Folium/Streamlit map needs to request live Earth Engine map tiles.

`Earth Engine Resource Writer` is broader than pure viewing, so keep the app code read-only: do not add exports, asset writes, cloud storage writes, BigQuery writes, Vertex AI calls, or other billable/cloud-writing workflows. Granting the role does not by itself switch the project to paid/commercial Earth Engine use.

WDPA data has its own Protected Planet terms, including non-commercial-use restrictions. This prototype is intended for non-commercial thesis, research, conservation, and stakeholder demonstration use.
