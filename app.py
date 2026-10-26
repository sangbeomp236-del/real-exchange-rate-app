import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pycountry
import requests
import streamlit as st
from plotly.subplots import make_subplots


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Real Exchange Rate App",
    page_icon="🌍",
    layout="wide",
)

st.title("🌍 Real Exchange Rate App")

st.markdown(
    """
This app uses monthly IMF Consumer Price Index (CPI) and exchange-rate data
to calculate the real exchange rate between two countries/economies.

**Definitions**

- **S(t)** = units of Country 2 currency per one unit of Country 1 currency
- **P1(t)** = CPI of Country 1
- **P2(t)** = CPI of Country 2
- **RER(t) = S(t) × P1(t) / P2(t)**
- **RER\\*** = average RER over the user-selected valid sample
- **Real Index(t) = 100 × RER(t) / RER\\***
"""
)


# =========================================================
# COUNTRY / ECONOMY LIST
# =========================================================
#
# pycountry supplies ISO-3 country/economy codes.
# The IMF Euro Area code required by the assignment is G163.
#
# Some countries/economies may have incomplete CPI or FX coverage.
# The app handles missing IMF series gracefully.
# =========================================================

DISPLAY_NAME_OVERRIDES = {
    "BOL": "Bolivia",
    "BRN": "Brunei",
    "COD": "Democratic Republic of the Congo",
    "COG": "Republic of the Congo",
    "CZE": "Czech Republic",
    "GBR": "United Kingdom",
    "IRN": "Iran",
    "KOR": "Korea",
    "LAO": "Laos",
    "MDA": "Moldova",
    "PRK": "North Korea",
    "RUS": "Russia",
    "SYR": "Syria",
    "TUR": "Türkiye",
    "TZA": "Tanzania",
    "USA": "United States",
    "VEN": "Venezuela",
    "VNM": "Vietnam",
}


def build_country_list():
    country_map = {}

    for country in pycountry.countries:
        code = country.alpha_3
        name = DISPLAY_NAME_OVERRIDES.get(code, country.name)
        country_map[name] = code

    # IMF code explicitly required by the assignment
    country_map["Euro Area"] = "G163"

    return dict(sorted(country_map.items()))


COUNTRIES = build_country_list()


# =========================================================
# IMF API SETTINGS
# =========================================================

IMF_BASE_30 = "https://api.imf.org/external/sdmx/3.0"

HEADERS_30 = {
    "Accept": "text/csv",
    "User-Agent": "real-exchange-rate-app/1.0",
}


# =========================================================
# IMF DATA PARSING
# =========================================================

def parse_imf_csv(text):
    """
    Parse IMF SDMX CSV output and return:
        Date
        Value
    """

    if not text or len(text.strip()) == 0:
        return pd.DataFrame(columns=["Date", "Value"])

    df = pd.read_csv(
        io.StringIO(text),
        low_memory=False,
    )

    if df.empty:
        return pd.DataFrame(columns=["Date", "Value"])

    time_col = None
    value_col = None

    for col in df.columns:
        if col.upper() == "TIME_PERIOD":
            time_col = col

        if col.upper() == "OBS_VALUE":
            value_col = col

    if time_col is None or value_col is None:
        raise ValueError(
            "The IMF response did not contain TIME_PERIOD "
            f"and OBS_VALUE. Returned columns: {list(df.columns)}"
        )

    result = df[[time_col, value_col]].copy()

    result.columns = [
        "Date",
        "Value",
    ]

    # IMF monthly dates can appear as:
    # 2024-M01
    # or
    # 2024-01
    result["Date"] = (
        result["Date"]
        .astype(str)
        .str.replace("-M", "-", regex=False)
    )

    result["Date"] = pd.to_datetime(
        result["Date"],
        errors="coerce",
    )

    result["Value"] = pd.to_numeric(
        result["Value"],
        errors="coerce",
    )

    result = (
        result
        .dropna(subset=["Date", "Value"])
        .drop_duplicates(subset=["Date"])
        .sort_values("Date")
        .reset_index(drop=True)
    )

    # Force monthly observations to month-start dates
    result["Date"] = (
        result["Date"]
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    return result


# =========================================================
# IMF API FETCH
# =========================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_imf_series(dataflow, key):
    """
    Retrieve monthly IMF data using the SDMX 3.0 API.

    Primary query:
        IMF SDMX 3.0

    A 2.1 fallback is included only in case the live IMF
    3.0 service temporarily rejects a request.
    """

    start_period = "1976-01"

    url_30 = (
        f"{IMF_BASE_30}/data/"
        f"dataflow/IMF.STA/{dataflow}/~/{key}"
        f"?c[TIME_PERIOD]=ge:{start_period}"
    )

    first_error = None

    try:
        response = requests.get(
            url_30,
            headers=HEADERS_30,
            timeout=40,
        )

        response.raise_for_status()

        parsed = parse_imf_csv(response.text)

        if not parsed.empty:
            return parsed

        first_error = "SDMX 3.0 returned no observations."

    except Exception as exc:
        first_error = str(exc)

    # -----------------------------------------------------
    # Fallback
    # -----------------------------------------------------

    url_21 = (
        "https://api.imf.org/external/sdmx/2.1/data/"
        f"IMF.STA,{dataflow}/{key}"
        f"?startPeriod={start_period}"
    )

    try:
        response = requests.get(
            url_21,
            headers={
                "Accept": (
                    "application/vnd.sdmx.data+csv;"
                    "version=1.0.0"
                ),
                "User-Agent": "real-exchange-rate-app/1.0",
            },
            timeout=40,
        )

        response.raise_for_status()

        parsed = parse_imf_csv(response.text)

        if not parsed.empty:
            return parsed

    except Exception as exc:
        raise RuntimeError(
            "IMF data download failed. "
            f"SDMX 3.0 error: {first_error}. "
            f"Fallback error: {exc}"
        ) from exc

    raise RuntimeError(
        "The IMF returned no observations for this series. "
        "The country/economy may have limited data coverage."
    )


# =========================================================
# CPI
# =========================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_cpi(country_code):
    """
    Monthly IMF CPI.

    Assignment-required IMF key:
        {ISO3}.CPI._T.IX.M
    """

    key = f"{country_code}.CPI._T.IX.M"

    df = fetch_imf_series(
        dataflow="CPI",
        key=key,
    )

    df = df.rename(
        columns={
            "Value": "CPI",
        }
    )

    return df


# =========================================================
# EXCHANGE RATE
# =========================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_fx(country_code):
    """
    Monthly IMF exchange rate.

    Assignment-required IMF key:
        {ISO3}.XDC_USD.PA_RT.M

    IMF convention:
        local currency units per USD.
    """

    # USD per USD is exactly 1.
    # We construct it directly so that the United States
    # can be used cleanly as either Country 1 or Country 2.
    if country_code == "USA":

        dates = pd.date_range(
            start="1976-01-01",
            end=pd.Timestamp.today().to_period("M").to_timestamp(),
            freq="MS",
        )

        return pd.DataFrame(
            {
                "Date": dates,
                "FX_per_USD": 1.0,
            }
        )

    key = f"{country_code}.XDC_USD.PA_RT.M"

    df = fetch_imf_series(
        dataflow="ER",
        key=key,
    )

    df = df.rename(
        columns={
            "Value": "FX_per_USD",
        }
    )

    return df


# =========================================================
# SIDEBAR — COUNTRY SELECTION
# =========================================================

st.sidebar.header("Settings")

country_names = list(COUNTRIES.keys())

uk_index = country_names.index("United Kingdom")
us_index = country_names.index("United States")

country1_name = st.sidebar.selectbox(
    "Country 1",
    options=country_names,
    index=uk_index,
)

country2_name = st.sidebar.selectbox(
    "Country 2",
    options=country_names,
    index=us_index,
)

country1_code = COUNTRIES[country1_name]
country2_code = COUNTRIES[country2_name]


# =========================================================
# CHART TYPE
# =========================================================

chart_type = st.sidebar.radio(
    "Chart",
    options=[
        "Real",
        "Nominal",
        "Both",
    ],
    index=2,
)

st.sidebar.caption(
    "Data source: IMF SDMX API. "
    "Monthly CPI and period-average exchange rates."
)


# =========================================================
# BASIC VALIDATION
# =========================================================

if country1_code == country2_code:
    st.warning(
        "Please select two different countries/economies."
    )
    st.stop()


# =========================================================
# DOWNLOAD IMF DATA
# =========================================================

with st.spinner("Downloading IMF data..."):

    try:
        cpi1 = get_cpi(country1_code)
        cpi2 = get_cpi(country2_code)

        fx1 = get_fx(country1_code)
        fx2 = get_fx(country2_code)

    except Exception as exc:

        st.error(
            "The required IMF data could not be downloaded "
            "for this country combination."
        )

        st.info(
            "IMF data can have gaps or limited historical coverage. "
            "Try another country pair, or try again later."
        )

        with st.expander("Technical details"):
            st.code(str(exc))

        st.stop()


# =========================================================
# MERGE CPI AND FX DATA
# =========================================================

cpi1 = cpi1.rename(
    columns={
        "CPI": "P1",
    }
)

cpi2 = cpi2.rename(
    columns={
        "CPI": "P2",
    }
)

fx1 = fx1.rename(
    columns={
        "FX_per_USD": "FX1_per_USD",
    }
)

fx2 = fx2.rename(
    columns={
        "FX_per_USD": "FX2_per_USD",
    }
)


data = (
    cpi1
    .merge(
        cpi2,
        on="Date",
        how="inner",
    )
    .merge(
        fx1,
        on="Date",
        how="inner",
    )
    .merge(
        fx2,
        on="Date",
        how="inner",
    )
)


data = (
    data
    .replace(
        [np.inf, -np.inf],
        np.nan,
    )
    .dropna()
    .sort_values("Date")
    .reset_index(drop=True)
)


if data.empty:

    st.error(
        "There are no overlapping valid monthly CPI and "
        "exchange-rate observations for this country pair."
    )

    st.stop()


# =========================================================
# ECONOMIC CALCULATIONS
# =========================================================
#
# IMF gives:
#
# FX1 = Country 1 currency / USD
# FX2 = Country 2 currency / USD
#
# Assignment requires:
#
# S = Country 2 currency / Country 1 currency
#
# Therefore:
#
# S = FX2 / FX1
#
#
# Example:
#
# Country 1 = United Kingdom
# Country 2 = United States
#
# FX1 = GBP / USD
# FX2 = USD / USD = 1
#
# S = 1 / (GBP/USD)
#   = USD / GBP
#
# This is exactly the direction required by the assignment.
# =========================================================

data["S"] = (
    data["FX2_per_USD"]
    / data["FX1_per_USD"]
)


# RER(t) = S(t) × P1(t) / P2(t)

data["RER"] = (
    data["S"]
    * data["P1"]
    / data["P2"]
)


data = (
    data
    .replace(
        [np.inf, -np.inf],
        np.nan,
    )
    .dropna(
        subset=[
            "P1",
            "P2",
            "FX1_per_USD",
            "FX2_per_USD",
            "S",
            "RER",
        ]
    )
    .reset_index(drop=True)
)


if data.empty:

    st.error(
        "No valid observations remain after calculating the RER."
    )

    st.stop()


# =========================================================
# MONTH SELECTION
# =========================================================
#
# The assignment explicitly asks users to choose
# START and END MONTHS.
#
# Therefore, use YYYY-MM values instead of daily date inputs.
# =========================================================

available_months = (
    data["Date"]
    .dt.strftime("%Y-%m")
    .tolist()
)

st.sidebar.markdown("---")
st.sidebar.subheader("Sample period")

start_month = st.sidebar.selectbox(
    "Start month",
    options=available_months,
    index=0,
)

end_month = st.sidebar.selectbox(
    "End month",
    options=available_months,
    index=len(available_months) - 1,
)


start_period = pd.Period(
    start_month,
    freq="M",
)

end_period = pd.Period(
    end_month,
    freq="M",
)


if start_period > end_period:

    st.error(
        "Start month must be earlier than or equal to end month."
    )

    st.stop()


data["Month"] = data["Date"].dt.to_period("M")


sample = data[
    (data["Month"] >= start_period)
    & (data["Month"] <= end_period)
].copy()


if sample.empty:

    st.error(
        "No valid observations exist in the selected sample period."
    )

    st.stop()


# =========================================================
# RER* AND REAL INDEX
# =========================================================
#
# IMPORTANT:
# RER* must be recalculated every time start/end months change.
# =========================================================

rer_star = sample["RER"].mean()


if pd.isna(rer_star) or rer_star == 0:

    st.error(
        "RER* could not be calculated for this sample."
    )

    st.stop()


sample["RER_star"] = rer_star


sample["Real_Index"] = (
    100
    * sample["RER"]
    / sample["RER_star"]
)


# =========================================================
# SUMMARY
# =========================================================

st.subheader(
    f"{country1_name} vs. {country2_name}"
)


st.markdown(
    f"""
**Nominal exchange-rate convention**

**S(t) = {country2_name} currency per one unit of {country1_name} currency**

The nominal exchange rate shown below is in actual currency units
and is **not normalized**.
"""
)


col1, col2, col3, col4 = st.columns(4)


col1.metric(
    "RER*",
    f"{rer_star:.6f}",
)


col2.metric(
    "Average Real Index",
    f"{sample['Real_Index'].mean():.4f}",
)


col3.metric(
    "Valid months",
    f"{len(sample):,}",
)


col4.metric(
    "Latest nominal S",
    f"{sample['S'].iloc[-1]:.6f}",
)


# =========================================================
# SPECIAL UK / US CHECK
# =========================================================

if (
    country1_code == "GBR"
    and country2_code == "USA"
):

    st.success(
        "UK–U.S. direction check passed: "
        "S is expressed as USD per GBP."
    )


# =========================================================
# INTERACTIVE CHARTS
# =========================================================

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
        annotation_text="RER* benchmark = 100",
    )

    fig.update_layout(
        title="Real Exchange Rate Index",
        xaxis_title="Date",
        yaxis_title="Real Index",
        hovermode="x unified",
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
            f"per one unit of {country1_name} currency"
        ),
        hovermode="x unified",
    )


else:

    fig = make_subplots(
        specs=[
            [
                {
                    "secondary_y": True,
                }
            ]
        ]
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


# =========================================================
# DATA TABLE
# =========================================================

st.subheader("Selected Sample Data")


output = sample[
    [
        "Date",
        "P1",
        "P2",
        "FX1_per_USD",
        "FX2_per_USD",
        "S",
        "RER",
        "RER_star",
        "Real_Index",
    ]
].copy()


output.columns = [
    "Date",
    f"CPI_{country1_code}",
    f"CPI_{country2_code}",
    f"{country1_code}_currency_per_USD",
    f"{country2_code}_currency_per_USD",
    "Nominal_S",
    "RER",
    "RER_star",
    "Real_Index",
]


output["Date"] = (
    output["Date"]
    .dt.strftime("%Y-%m")
)


st.dataframe(
    output,
    use_container_width=True,
    hide_index=True,
)


# =========================================================
# CSV DOWNLOAD
# =========================================================

csv_data = output.to_csv(
    index=False,
).encode("utf-8")


st.download_button(
    label="⬇️ Download CSV",
    data=csv_data,
    file_name=(
        f"real_exchange_rate_"
        f"{country1_code}_"
        f"{country2_code}_"
        f"{start_month}_"
        f"{end_month}.csv"
    ),
    mime="text/csv",
)


# =========================================================
# MANUAL RER VERIFICATION
# =========================================================

st.subheader("Manual RER Verification")


verification_row = sample.iloc[-1]


verification_month = (
    verification_row["Date"]
    .strftime("%Y-%m")
)


st.markdown(
    f"""
For **{verification_month}**:

- P1 = **{verification_row['P1']:.6f}**
- P2 = **{verification_row['P2']:.6f}**
- S = **{verification_row['S']:.6f}**

Using:

**RER = S × P1 / P2**

Calculation:

**{verification_row['S']:.6f}
× {verification_row['P1']:.6f}
÷ {verification_row['P2']:.6f}
= {verification_row['RER']:.6f}**
"""
)


# =========================================================
# VALIDATION CHECKS
# =========================================================

st.subheader("Validation Checks")


average_real_index = sample["Real_Index"].mean()


check1 = np.isclose(
    average_real_index,
    100.0,
    atol=1e-8,
)


manual_rer = (
    verification_row["S"]
    * verification_row["P1"]
    / verification_row["P2"]
)


check2 = np.isclose(
    manual_rer,
    verification_row["RER"],
    rtol=1e-10,
    atol=1e-10,
)


if check1:
    st.success(
        f"Real Index average check passed: "
        f"{average_real_index:.6f}"
    )
else:
    st.error(
        f"Real Index average check failed: "
        f"{average_real_index:.6f}"
    )


if check2:
    st.success(
        "Manual RER formula check passed."
    )
else:
    st.error(
        "Manual RER formula check failed."
    )


# =========================================================
# DATA NOTES
# =========================================================

with st.expander("Data and methodology notes"):

    st.markdown(
        """
- Data source: IMF SDMX API.
- CPI key: `{ISO3}.CPI._T.IX.M`
- Exchange-rate key: `{ISO3}.XDC_USD.PA_RT.M`
- Euro Area IMF code: `G163`.
- IMF exchange rates are local-currency units per USD.
- Therefore, `S = FX2_per_USD / FX1_per_USD`.
- Only months with valid observations for both CPI series and
  both exchange-rate series are retained.
- Data availability may vary across countries and over time.
- RER* is recalculated whenever the selected sample changes.
- The nominal exchange rate is displayed in actual currency
  units and is never normalized.
"""
    )
