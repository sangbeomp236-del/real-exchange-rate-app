import io
from datetime import date

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ---------------------------------------------------------
# Page setup
# ---------------------------------------------------------
st.set_page_config(
    page_title="Real Exchange Rate App",
    page_icon="🌍",
    layout="wide",
)

st.title("🌍 Real Exchange Rate App")
st.write(
    """
    This app uses monthly IMF data to calculate the real exchange rate (RER)
    between two countries.
    
    **Definition:**  
    S(t) = units of Country 2 currency per one unit of Country 1 currency  
    
    RER(t) = S(t) × P1(t) / P2(t)
    """
)


# ---------------------------------------------------------
# Country list
# ISO-3 codes used by IMF
# ---------------------------------------------------------
COUNTRIES = {
    "Argentina": "ARG",
    "Australia": "AUS",
    "Austria": "AUT",
    "Belgium": "BEL",
    "Brazil": "BRA",
    "Canada": "CAN",
    "Chile": "CHL",
    "China": "CHN",
    "Colombia": "COL",
    "Croatia": "HRV",
    "Czech Republic": "CZE",
    "Denmark": "DNK",
    "Egypt": "EGY",
    "Euro Area": "G163",
    "Finland": "FIN",
    "France": "FRA",
    "Germany": "DEU",
    "Greece": "GRC",
    "Hong Kong SAR": "HKG",
    "Hungary": "HUN",
    "Iceland": "ISL",
    "India": "IND",
    "Indonesia": "IDN",
    "Ireland": "IRL",
    "Israel": "ISR",
    "Italy": "ITA",
    "Japan": "JPN",
    "Korea": "KOR",
    "Malaysia": "MYS",
    "Mexico": "MEX",
    "Netherlands": "NLD",
    "New Zealand": "NZL",
    "Norway": "NOR",
    "Pakistan": "PAK",
    "Peru": "PER",
    "Philippines": "PHL",
    "Poland": "POL",
    "Portugal": "PRT",
    "Romania": "ROU",
    "Saudi Arabia": "SAU",
    "Singapore": "SGP",
    "South Africa": "ZAF",
    "Spain": "ESP",
    "Sweden": "SWE",
    "Switzerland": "CHE",
    "Thailand": "THA",
    "Türkiye": "TUR",
    "United Kingdom": "GBR",
    "United States": "USA",
}


# ---------------------------------------------------------
# IMF API functions
# ---------------------------------------------------------
HEADERS = {
    "Accept": "text/csv",
    "User-Agent": "real-exchange-rate-streamlit-app/1.0",
}


def parse_imf_csv(response_text):
    """
    Parse IMF SDMX CSV output.
    Returns a DataFrame with Date and Value.
    """
    df = pd.read_csv(io.StringIO(response_text), low_memory=False)

    if df.empty:
        return pd.DataFrame(columns=["Date", "Value"])

    # IMF normally uses TIME_PERIOD and OBS_VALUE
    time_col = None
    value_col = None

    for col in df.columns:
        if col.upper() == "TIME_PERIOD":
            time_col = col
        if col.upper() == "OBS_VALUE":
            value_col = col

    if time_col is None or value_col is None:
        raise ValueError(
            f"Could not identify TIME_PERIOD or OBS_VALUE. "
            f"Returned columns: {list(df.columns)}"
        )

    result = df[[time_col, value_col]].copy()
    result.columns = ["Date", "Value"]

    # IMF monthly dates can appear as 2024-M01
    result["Date"] = (
        result["Date"]
        .astype(str)
        .str.replace("-M", "-", regex=False)
    )

    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Value"] = pd.to_numeric(result["Value"], errors="coerce")

    result = (
        result
        .dropna(subset=["Date", "Value"])
        .drop_duplicates(subset=["Date"])
        .sort_values("Date")
    )

    return result


@st.cache_data(ttl=3600)
def fetch_imf_series(dataflow, key, start="1976-01"):
    """
    Try IMF SDMX 3.0 first.
    If the public 3.0 endpoint is unavailable, fall back to IMF SDMX 2.1.
    """

    # Current SDMX 3.0 endpoint
    url_3 = (
        f"https://api.imf.org/external/sdmx/3.0/data/"
        f"dataflow/IMF.STA/{dataflow}/~/{key}"
        f"?c[TIME_PERIOD]=ge:{start}"
    )

    try:
        r = requests.get(
            url_3,
            headers=HEADERS,
            timeout=30,
        )

        if r.status_code == 200 and len(r.text) > 100:
            result = parse_imf_csv(r.text)

            if not result.empty:
                return result

    except Exception:
        pass

    # Fallback to IMF SDMX 2.1
    url_2 = (
        f"https://api.imf.org/external/sdmx/2.1/data/"
        f"IMF.STA,{dataflow}/{key}"
        f"?startPeriod={start}"
    )

    r = requests.get(
        url_2,
        headers={
            "Accept": "application/vnd.sdmx.data+csv;version=1.0.0",
            "User-Agent": "real-exchange-rate-streamlit-app/1.0",
        },
        timeout=30,
    )

    r.raise_for_status()

    result = parse_imf_csv(r.text)

    if result.empty:
        raise ValueError(
            f"No IMF observations were returned for {key}."
        )

    return result


@st.cache_data(ttl=3600)
def get_cpi(country_code):
    """
    Monthly headline CPI index.
    IMF key:
    COUNTRY.CPI._T.IX.M
    """
    key = f"{country_code}.CPI._T.IX.M"
    df = fetch_imf_series("CPI", key)
    df = df.rename(columns={"Value": "CPI"})
    return df


@st.cache_data(ttl=3600)
def get_fx(country_code):
    """
    Monthly exchange rate:
    units of local currency per USD.
    IMF key:
    COUNTRY.XDC_USD.PA_RT.M
    """

    # USD per USD = 1 by definition
    if country_code == "USA":
        dates = pd.date_range(
            start="1976-01-01",
            end=pd.Timestamp.today(),
            freq="MS",
        )

        return pd.DataFrame(
            {
                "Date": dates,
                "FX_per_USD": 1.0,
            }
        )

    key = f"{country_code}.XDC_USD.PA_RT.M"
    df = fetch_imf_series("ER", key)
    df = df.rename(columns={"Value": "FX_per_USD"})
    return df


# ---------------------------------------------------------
# Sidebar inputs
# ---------------------------------------------------------
st.sidebar.header("Settings")

country_names = list(COUNTRIES.keys())

default_c1 = country_names.index("United Kingdom")
default_c2 = country_names.index("United States")

country1_name = st.sidebar.selectbox(
    "Country 1",
    country_names,
    index=default_c1,
)

country2_name = st.sidebar.selectbox(
    "Country 2",
    country_names,
    index=default_c2,
)

country1 = COUNTRIES[country1_name]
country2 = COUNTRIES[country2_name]

chart_type = st.sidebar.radio(
    "Chart",
    ["Real", "Nominal", "Both"],
    index=2,
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Data source: IMF SDMX API. "
    "Monthly CPI and period-average exchange rates."
)


# ---------------------------------------------------------
# Load data
# ---------------------------------------------------------
if country1 == country2:
    st.error("Please select two different countries.")
    st.stop()


with st.spinner("Downloading IMF data..."):
    try:
        cpi1 = get_cpi(country1)
        cpi2 = get_cpi(country2)

        fx1 = get_fx(country1)
        fx2 = get_fx(country2)

    except Exception as e:
        st.error(
            "The IMF data could not be downloaded. "
            "The selected country may have limited coverage, "
            "or the IMF API may be temporarily unavailable."
        )

        st.code(str(e))
        st.stop()


# ---------------------------------------------------------
# Merge data
# ---------------------------------------------------------
cpi1 = cpi1.rename(columns={"CPI": "P1"})
cpi2 = cpi2.rename(columns={"CPI": "P2"})

fx1 = fx1.rename(columns={"FX_per_USD": "FX1_per_USD"})
fx2 = fx2.rename(columns={"FX_per_USD": "FX2_per_USD"})

data = (
    cpi1
    .merge(cpi2, on="Date", how="inner")
    .merge(fx1, on="Date", how="inner")
    .merge(fx2, on="Date", how="inner")
)

data = data.sort_values("Date").dropna()

if data.empty:
    st.error(
        "There are no overlapping CPI and exchange-rate observations "
        "for the selected countries."
    )
    st.stop()


# ---------------------------------------------------------
# Economic calculations
# ---------------------------------------------------------
#
# IMF FX data:
# FX1 = Country 1 currency per USD
# FX2 = Country 2 currency per USD
#
# Required:
# S = Country 2 currency per Country 1 currency
#
# Therefore:
# S = FX2 / FX1
#
# Example:
# UK Country 1, US Country 2:
# FX1 = GBP/USD
# FX2 = USD/USD = 1
#
# S = 1 / (GBP/USD) = USD/GBP
#

data["S"] = data["FX2_per_USD"] / data["FX1_per_USD"]

# RER = S × P1 / P2
data["RER"] = data["S"] * data["P1"] / data["P2"]


# ---------------------------------------------------------
# Date selector
# ---------------------------------------------------------
min_date = data["Date"].min().date()
max_date = data["Date"].max().date()

st.sidebar.markdown("### Sample period")

start_date = st.sidebar.date_input(
    "Start month",
    value=min_date,
    min_value=min_date,
    max_value=max_date,
)

end_date = st.sidebar.date_input(
    "End month",
    value=max_date,
    min_value=min_date,
    max_value=max_date,
)

if start_date > end_date:
    st.error("Start date must be before end date.")
    st.stop()


sample = data[
    (data["Date"].dt.date >= start_date)
    & (data["Date"].dt.date <= end_date)
].copy()

if sample.empty:
    st.error("No valid observations exist in the selected period.")
    st.stop()


# ---------------------------------------------------------
# Recalculate RER* whenever selected dates change
# ---------------------------------------------------------
rer_star = sample["RER"].mean()

sample["Real_Index"] = 100 * sample["RER"] / rer_star


# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------
st.subheader(
    f"{country1_name} vs. {country2_name}"
)

st.write(
    f"""
    **Nominal exchange rate S:**  
    {country2_name} currency per one unit of {country1_name} currency.
    """
)

col1, col2, col3 = st.columns(3)

col1.metric(
    "RER* (sample average)",
    f"{rer_star:.4f}",
)

col2.metric(
    "Average Real Index",
    f"{sample['Real_Index'].mean():.2f}",
)

col3.metric(
    "Valid monthly observations",
    f"{len(sample):,}",
)


# ---------------------------------------------------------
# Charts
# ---------------------------------------------------------
if chart_type == "Real":

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["Real_Index"],
            mode="lines",
            name="Real Index",
        )
    )

    fig.add_hline(
        y=100,
        line_dash="dash",
        annotation_text="Sample average = 100",
    )

    fig.update_layout(
        title="Real Exchange Rate Index",
        xaxis_title="Date",
        yaxis_title="Real Index",
        hovermode="x unified",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )


elif chart_type == "Nominal":

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["S"],
            mode="lines",
            name="Nominal S",
        )
    )

    fig.update_layout(
        title="Nominal Exchange Rate",
        xaxis_title="Date",
        yaxis_title=(
            f"{country2_name} currency "
            f"per {country1_name} currency"
        ),
        hovermode="x unified",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )


else:

    fig = make_subplots(
        specs=[[{"secondary_y": True}]]
    )

    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["Real_Index"],
            mode="lines",
            name="Real Index",
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["S"],
            mode="lines",
            name="Nominal S",
        ),
        secondary_y=True,
    )

    fig.add_hline(
        y=100,
        line_dash="dash",
        secondary_y=False,
    )

    fig.update_layout(
        title="Real and Nominal Exchange Rates",
        xaxis_title="Date",
        hovermode="x unified",
    )

    fig.update_yaxes(
        title_text="Real Index",
        secondary_y=False,
    )

    fig.update_yaxes(
        title_text=(
            f"Nominal S: {country2_name} currency "
            f"per {country1_name} currency"
        ),
        secondary_y=True,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )


# ---------------------------------------------------------
# Data table
# ---------------------------------------------------------
st.subheader("Data")

output = sample[
    [
        "Date",
        "P1",
        "P2",
        "FX1_per_USD",
        "FX2_per_USD",
        "S",
        "RER",
        "Real_Index",
    ]
].copy()

output.columns = [
    "Date",
    f"CPI_{country1}",
    f"CPI_{country2}",
    f"{country1}_currency_per_USD",
    f"{country2}_currency_per_USD",
    "Nominal_S",
    "RER",
    "Real_Index",
]

output["Date"] = output["Date"].dt.strftime("%Y-%m")

st.dataframe(
    output,
    use_container_width=True,
)


# ---------------------------------------------------------
# CSV download
# ---------------------------------------------------------
csv = output.to_csv(
    index=False
).encode("utf-8")

st.download_button(
    label="⬇️ Download CSV",
    data=csv,
    file_name=(
        f"rer_{country1}_{country2}_"
        f"{start_date}_{end_date}.csv"
    ),
    mime="text/csv",
)


# ---------------------------------------------------------
# Manual verification section
# ---------------------------------------------------------
st.subheader("Manual RER Verification")

last_row = sample.iloc[-1]

st.write(
    f"""
    For **{last_row['Date'].strftime('%Y-%m')}**:

    - P1 = {last_row['P1']:.4f}
    - P2 = {last_row['P2']:.4f}
    - S = {last_row['S']:.6f}

    **RER = S × P1 / P2**

    = {last_row['S']:.6f} × {last_row['P1']:.4f} / {last_row['P2']:.4f}

    = **{last_row['RER']:.6f}**
    """
)

st.caption(
    "Real Index is normalized so that its average equals 100 "
    "over the selected sample period."
)
