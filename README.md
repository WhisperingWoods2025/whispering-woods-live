# Whispering Woods

Whispering Woods is a prototype Streamlit dashboard for monitoring forest health using satellite-derived vegetation indices. The dashboard displays NDVI, NDWI, and EVI for multiple points within the Königssee forest area and supports date selection with a time slider.

## Files

- `app.py`: Streamlit app code for the dashboard.
- `sample_ndvi_data.csv`: Example dataset with coordinates, dates, NDVI, NDWI, and EVI values.
- `requirements.txt`: Python dependencies needed to run the app.

## Running the app locally

1. Install the dependencies:

```
pip install -r requirements.txt
```

2. Run the app using Streamlit:

```
streamlit run app.py
```

The dashboard will open in your web browser, showing vegetation indices and statistics for selected dates.
