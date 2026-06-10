# Whispering Woods

Whispering Woods is a prototype Streamlit dashboard for monitoring forest health using satellite-derived vegetation indices. The dashboard displays NDVI, NDWI, and EVI for multiple points within the Koenigssee forest area and supports date selection with a time slider.

## Files

- `app.py`: Streamlit app code for the dashboard.
- `app_alphaearth.py`: Streamlit app for viewing AlphaEarth annual embedding RGB layers from Google Earth Engine.
- `app_alphaearth_diff.py`: Streamlit app for comparing AlphaEarth embedding bands between two years.
- `sample_ndvi_data.csv`: Example dataset with coordinates, dates, NDVI, NDWI, and EVI values.
- `requirements.txt`: Python dependencies needed to run the app.

## Running the app locally

1. Install the dependencies:

```bash
pip install -r requirements.txt
```

2. Run the main dashboard using Streamlit:

```bash
streamlit run app.py
```

The dashboard will open in your web browser, showing vegetation indices and statistics for selected dates.

## No-cost guardrail

This project is intended to avoid generating costs. The AlphaEarth apps should be run only with an Earth Engine project registered for eligible non-commercial, research, conservation, or impact use.

To keep the project no-cost:

- Register the Google Cloud project for non-commercial Earth Engine access.
- Keep `EE_USAGE_MODE` set to `noncommercial`, `research`, `conservation`, or `impact`. If it is set to `commercial`, `paid`, `billable`, `enterprise`, `government_operational`, or `production_paid`, the AlphaEarth apps stop before initializing Earth Engine.
- Do not switch the Earth Engine project to commercial/paid use unless cost generation is intentionally approved.
- Do not add batch exports to Google Cloud Storage, BigQuery, Vertex AI, paid Maps APIs, or other billable Google Cloud services.
- Keep the AlphaEarth apps read-only. The current code reads public Earth Engine datasets and renders map layers; it does not export files, write Earth Engine assets, or create cloud resources.
- Monitor the Streamlit app after deployment and stop it if Google/Streamlit reports quota, billing, or paid-plan prompts.

## Earth Engine setup for AlphaEarth apps

The AlphaEarth apps use Google Earth Engine and require a registered Google Cloud project plus service-account credentials. In Streamlit Cloud, add these secrets in the app settings:

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