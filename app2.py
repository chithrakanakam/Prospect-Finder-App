import streamlit as st
import time
import re
import random
from urllib.parse import quote_plus

import pandas as pd
import numpy as np

from math import radians, sin, cos, sqrt, atan2

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

from deep_translator import GoogleTranslator


# ============================================================
# DISTANCE FUNCTION
# ============================================================

def haversine(lat1, lon1, lat2, lon2):

    R = 6371

    lat1 = radians(float(lat1))
    lon1 = radians(float(lon1))
    lat2 = radians(float(lat2))
    lon2 = radians(float(lon2))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    return R * c


# ============================================================
# TRANSLATOR
# ============================================================

def translate_text(text):

    try:

        if pd.isna(text):
            return text

        return GoogleTranslator(
            source="auto",
            target="en"
        ).translate(str(text))

    except:
        return text


# ============================================================
# DRIVER
# ============================================================

def make_driver():

    options = webdriver.ChromeOptions()

    options.add_argument("--start-maximized")
    options.add_argument(
        "--disable-blink-features=AutomationControlled"
    )

    options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"]
    )

    driver = webdriver.Chrome(
        service=Service(
            ChromeDriverManager().install()
        ),
        options=options
    )

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return driver


# ============================================================
# SCROLL RESULTS
# ============================================================

def scroll_feed(driver):

    try:

        feed = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@role="feed"]')
            )
        )

    except:

        return None

    last_height = 0
    stable_count = 0

    for _ in range(60):

        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollHeight",
            feed
        )

        time.sleep(2)

        new_height = driver.execute_script(
            "return arguments[0].scrollHeight",
            feed
        )

        if new_height == last_height:

            stable_count += 1

            if stable_count >= 3:
                break

        else:

            stable_count = 0

        last_height = new_height

    return feed


# ============================================================
# FIND CARDS
# ============================================================

def find_cards(driver):

    selectors = [
        '//div[@role="feed"]//div[contains(@class,"Nv2PK")]',
        '//div[@role="feed"]//a[contains(@href,"/maps/place/")]/ancestor::div[3]'
    ]

    for selector in selectors:

        cards = driver.find_elements(
            By.XPATH,
            selector
        )

        if len(cards) > 0:
            return cards

    return []


# ============================================================
# PARSE CARD
# ============================================================

def parse_card(card):

    try:

        lines = [
            x.strip()
            for x in card.text.split("\n")
            if x.strip()
        ]

        if len(lines) == 0:
            return None

        name = lines[0]

        rating = ""
        review_count = ""
        address = ""

        for line in lines:

            m = re.match(
                r"^(\d\.\d)\s*\(([\d,]+)\)",
                line
            )

            if m:

                rating = m.group(1)
                review_count = m.group(2)
                break

        for line in lines:

            if any(
                x in line.lower()
                for x in [
                    "road",
                    "street",
                    "market",
                    "mall",
                    "abu dhabi",
                    "ruwais"
                ]
            ):
                address = line
                break

        try:

            link = card.find_element(
                By.XPATH,
                './/a[contains(@href,"/maps/place/")]'
            )

            place_url = link.get_attribute(
                "href"
            )

        except:

            place_url = ""

        return {
            "Shop Name": name,
            "Rating": rating,
            "Review Count": review_count,
            "Address": address,
            "Place URL": place_url
        }

    except:

        return None


# ============================================================
# LAT LONG EXTRACTION
# ============================================================

def extract_lat_lon(url):

    if not isinstance(url, str):
        return None, None

    lat = re.search(
        r'!3d(-?\d+\.\d+)',
        url
    )

    lon = re.search(
        r'!4d(-?\d+\.\d+)',
        url
    )

    if lat and lon:

        return (
            float(lat.group(1)),
            float(lon.group(1))
        )

    alt = re.search(
        r'@(-?\d+\.\d+),(-?\d+\.\d+)',
        url
    )

    if alt:

        return (
            float(alt.group(1)),
            float(alt.group(2))
        )

    return None, None


# ============================================================
# RUN SEARCH
# ============================================================

def run_query(driver, query):

    url = (
        "https://www.google.com/maps/search/"
        + quote_plus(query)
    )

    driver.get(url)

    time.sleep(8)

    scroll_feed(driver)

    cards = find_cards(driver)

    rows = []

    for card in cards:

        result = parse_card(card)

        if result:
            rows.append(result)

    return rows


# ============================================================
# FIND NEAREST CUSTOMER
# ============================================================

def nearest_customer(
    lat,
    lon,
    customer_df
):

    if pd.isna(lat) or pd.isna(lon):

        return pd.Series(
            [None] * 7
        )

    temp = customer_df.copy()

    temp["Distance KM"] = temp.apply(
        lambda x: haversine(
            lat,
            lon,
            x["Latitude"],
            x["Longitude"]
        ),
        axis=1
    )

    nearest = temp.loc[
        temp["Distance KM"].idxmin()
    ]

    distance_km = round(
        nearest["Distance KM"],
        3
    )

    distance_m = round(
        distance_km * 1000,
        0
    )

    status = (
        "Customer"
        if distance_m <= 200
        else "Prospect"
    )

    return pd.Series(
        [
            nearest["Customer Code"],
            nearest["Customer Name"],
            nearest["Latitude"],
            nearest["Longitude"],
            distance_km,
            distance_m,
            status
        ]
    )


# ============================================================
# STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Prospect Finder",
    layout="wide"
)

st.title(
    "Google Maps Prospect Finder"
)

city = st.text_input(
    "Enter City",
    "Ruwais, Abu Dhabi"
)

categories = st.text_area(
    "Categories (one per line)",
    """baqala
grocery
supermarket
hypermarket"""
)

customer_file = st.file_uploader(
    "Upload Customer Master",
    type=["xlsx", "csv"]
)

if st.button("Start Scraping"):

    if customer_file is None:

        st.error(
            "Please upload customer master."
        )

        st.stop()

    if customer_file.name.endswith(".csv"):

        customer_df = pd.read_csv(
            customer_file
        )

    else:

        customer_df = pd.read_excel(
            customer_file
        )

    customer_df["Latitude"] = pd.to_numeric(
        customer_df["Latitude"],
        errors="coerce"
    )

    customer_df["Longitude"] = pd.to_numeric(
        customer_df["Longitude"],
        errors="coerce"
    )

    queries = [

        f"{cat.strip()} in {city}"

        for cat in categories.split("\n")

        if cat.strip()
    ]

    driver = make_driver()

    all_rows = []

    progress = st.progress(0)

    try:

        for i, query in enumerate(
            queries
        ):

            st.write(
                f"Searching: {query}"
            )

            rows = run_query(
                driver,
                query
            )

            for row in rows:

                row["Search Query"] = query

                all_rows.append(row)

            progress.progress(
                (i + 1) / len(queries)
            )

            time.sleep(
                random.uniform(2, 4)
            )

    finally:

        driver.quit()

    if len(all_rows) == 0:

        st.error(
            "No shops found."
        )

        st.stop()

    df = pd.DataFrame(all_rows)

    df["unique_key"] = df.apply(

        lambda x:
        x["Place URL"]
        if x["Place URL"]
        else x["Shop Name"],

        axis=1
    )

    df = (
        df.drop_duplicates(
            "unique_key"
        )
        .drop(
            columns=["unique_key"]
        )
    )

    df[
        ["Shop Latitude", "Shop Longitude"]
    ] = df["Place URL"].apply(
        lambda x: pd.Series(
            extract_lat_lon(x)
        )
    )

    with st.spinner(
        "Translating..."
    ):

        df["Shop Name English"] = (
            df["Shop Name"]
            .apply(
                translate_text
            )
        )

        df["Address English"] = (
            df["Address"]
            .apply(
                translate_text
            )
        )

    df[
        [
            "Nearest Customer Code",
            "Nearest Customer Name",
            "Customer Latitude",
            "Customer Longitude",
            "Distance KM",
            "Distance Meter",
            "Status"
        ]
    ] = df.apply(

        lambda x:
        nearest_customer(
            x["Shop Latitude"],
            x["Shop Longitude"],
            customer_df
        ),

        axis=1
    )

    st.success(
        f"{len(df)} shops found"
    )

    st.dataframe(
        df,
        use_container_width=True
    )

    output_file = (
        "Prospect_Output.xlsx"
    )

    with pd.ExcelWriter(
        output_file,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False
        )

    with open(
        output_file,
        "rb"
    ) as f:

        st.download_button(
            "Download Excel",
            f,
            file_name=output_file,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )