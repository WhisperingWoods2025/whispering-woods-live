# Whispering Woods

Whispering Woods is a prototype Streamlit dashboard for monitoring forest health using satellite-derived vegetation indices. The dashboard displays NDVI, NDWI, and EVI for multiple points within the Königssee forest area and supports date selection with a time slider.

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
```

For local development, put the same values in `.streamlit/secrets.toml`. Do not commit real service-account keys to the repository.

The Cloud project must have the Earth Engine API enabled and be registered for Earth Engine use.
