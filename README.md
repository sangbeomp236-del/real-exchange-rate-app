# Real Exchange Rate App

A Streamlit application that uses monthly IMF data to calculate and visualize the real exchange rate (RER) between two countries or economies.

## Features

- Select Country 1 and Country 2 from ISO-3 countries/economies, including the Euro Area.
- Retrieve monthly IMF CPI and exchange-rate data from January 1976 where available.
- Calculate the nominal exchange rate in the required direction:
  
  **S(t) = units of Country 2 currency per one unit of Country 1 currency**

- Calculate the real exchange rate:

  **RER(t) = S(t) × P1(t) / P2(t)**

- Calculate the benchmark real exchange rate over the selected sample:

  **RER\* = average of RER(t) over valid months**

- Calculate the normalized real exchange-rate index:

  **Real Index(t) = 100 × RER(t) / RER\***

- Recalculate RER\* whenever the selected start or end month changes.
- Display:
  - Real exchange-rate index
  - Nominal exchange rate
  - Both series using separate y-axes
- Download all selected observations and calculations as a CSV file.
- Automatically verify that the average Real Index equals 100.
- Display one manual RER calculation for validation.

## Data Source

The application uses the IMF SDMX API:

`https://api.imf.org/external/sdmx/3.0`

Monthly CPI series use the IMF key:

`{ISO3}.CPI._T.IX.M`

Monthly exchange-rate series use:

`{ISO3}.XDC_USD.PA_RT.M`

The IMF Euro Area code is:

`G163`

IMF exchange-rate data are expressed as local-currency units per U.S. dollar.

Therefore, if:

- FX1 = Country 1 currency per USD
- FX2 = Country 2 currency per USD

then the required nominal exchange rate is:

**S(t) = FX2 / FX1**

For example, when the United Kingdom is Country 1 and the United States is Country 2, S(t) is expressed as **USD per GBP**.

## Data Availability

IMF data availability varies across countries and time periods. Some countries may have missing CPI or exchange-rate observations or shorter historical coverage.

The app keeps only months for which all required CPI and exchange-rate observations are available for both selected countries.

## Files

- `app.py` — Streamlit application
- `requirements.txt` — Python package requirements
- `README.md` — project documentation

## Python Version

The application is designed for **Python 3.12**.

## Requirements

The application uses:

- streamlit
- pandas
- numpy
- requests
- plotly
- pycountry

## Running the App

Install the required packages:

`pip install -r requirements.txt`

Then run:

`streamlit run app.py`

The application can also be deployed directly through Streamlit Community Cloud using this GitHub repository.
