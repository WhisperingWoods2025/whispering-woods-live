# Whispering Woods

Whispering Woods is a prototype Streamlit dashboard for exploring conservation-relevant forest information layers in a stakeholder-facing map interface. The main app combines public Google Earth Engine datasets around Berchtesgaden National Park, with a no-cost guardrail for non-commercial use.

## Files

- `app.py`: Earlier Streamlit dashboard for sample NDVI, NDWI, and EVI data.
- `app_alphaearth.py`: Main stakeholder map app for Whispering Woods forest intelligence layers.
- `app_alphaearth_diff.py`: Streamlit app for comparing AlphaEarth embedding bands between two years.
- `sample_ndvi_data.csv`: Example dataset with coordinates, dates, NDVI, NDWI, and EVI values.
- `requirements.txt`: Python dependencies needed to run the apps.

## Main stakeholder map

Run the main stakeholder app with:

```bash
streamlit run app_alphaearth.py
```

The default area of interest is Berchtesgaden National Park. The app first tries to use the WDPA protected-area polygon (`WDPAID 668`) from Earth Engine, and falls back to a local park-scale polygon if that query is unavailable.

The timeline runs from 2000 to 2026. Some layers have narrower availability and are shown only when the selected year supports them:

- AlphaEarth annual satellite embeddings: 2017-2024.
- Hansen tree-cover loss: cumulative loss from 2001-2025; 2026 uses the latest available 2025 loss year.
- ERA5-Land climate and soil fields: available from 1950 to near-real-time, so 2026 may be partial depending on the current month.

The map currently supports these real public Earth Engine layers:

- WDPA protected-area boundary for Berchtesgaden National Park.
- AlphaEarth annual satellite embeddings for landscape pattern exploration.
- Hansen Global Forest Change tree canopy and cumulative tree-cover loss.
- JRC Global Surface Water for water and recurring wetland context.
- ESA WorldCover for land-cover / habitat context.
- MODIS MCD64A1 burned-area history for the selected year.
- ERA5-Land 2 m air temperature and top-layer soil moisture model layers.

The app also includes prototype local station markers for stakeholder workflow design:

- Weather station readings: air temperature, humidity, and wind.
- Soil probe readings: soil moisture, soil temperature, pH, and soil organic carbon.

These station values are deterministic prototype readings, not live sensor feeds. They are intended to show where live local weather stations, soil probes, ranger observations, or field campaigns could plug into the stakeholder interface later.

Prototype-only future integrations are shown separately in the UI as planned layers, not as active evidence: inventory trees, species observations, trail impact reports, and ranger field notes.

## Running the sample NDVI dashboard locally

1. Install the dependencies:

```bash
pip install -r requirements.txt
```

2. Run the older sample dashboard using Streamlit:

```bash
streamlit run app.py
```

The sample dashboard opens in your browser and shows vegetation indices and statistics for selected dates.

## No-cost guardrail

This project is intended to avoid generating costs. The Earth Engine apps should be run only with an Earth Engine project registered for eligible non-commercial, research, conservation, or impact use.

To keep the project no-cost:

- Register the Google Cloud project for non-commercial Earth Engine access.
- Keep `EE_USAGE_MODE` set to `noncommercial`, `research`, `conservation`, or `impact`. If it is set to `commercial`, `paid`, `billable`, `enterprise`, `government_operational`, or `production_paid`, the Earth Engine apps stop before initializing Earth Engine.
- Do not switch the Earth Engine project to commercial/paid use unless cost generation is intentionally approved.
- Do not add batch exports to Google Cloud Storage, BigQuery, Vertex AI, paid Maps APIs, or other billable Google Cloud services.
- Keep the apps read-only. The current code reads public Earth Engine datasets and renders map layers; it does not export files, write Earth Engine assets, or create cloud resources.
- Monitor the Streamlit app after deployment and stop it if Google/Streamlit reports quota, billing, or paid-plan prompts.

## Earth Engine setup

The Earth Engine apps require a registered Google Cloud project plus service-account credentials. In Streamlit Cloud, add these secrets in the app settings:

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