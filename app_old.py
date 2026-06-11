import streamlit as st
import time
import re
import random
from urllib.parse import quote_plus

import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import InvalidSessionIdException

from deep_translator import GoogleTranslator


# ============================================================
# DRIVER
# ============================================================
def make_driver():
    opts = webdriver.ChromeOptions()

    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return driver


# ============================================================
# SCROLL
# ============================================================
def scroll_feed_fully(driver):

    try:
        feed = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@role="feed"]')
            )
        )
    except:
        return None

    last_height = 0
    stable = 0

    for _ in range(60):

        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollHeight",
            feed
        )

        time.sleep(3)

        new_height = driver.execute_script(
            "return arguments[0].scrollHeight",
            feed
        )

        if new_height == last_height:
            stable += 1

            if stable >= 3:
                break
        else:
            stable = 0

        last_height = new_height

    return feed


# ============================================================
# FIND CARDS
# ============================================================
def find_cards(driver):

    selectors = [
        '//div[@role="feed"]//div[contains(@class, "Nv2PK")]',
        '//div[@role="feed"]//a[contains(@href, "/maps/place/")]/ancestor::div[3]',
        '//div[@role="feed"]/div/div[@jsaction]'
    ]

    for sel in selectors:

        cards = driver.find_elements(By.XPATH, sel)

        if cards:
            return cards

    return []


# ============================================================
# PARSE CARD
# ============================================================
def parse_card(card):

    try:

        text_lines = [
            t.strip()
            for t in card.text.split("\n")
            if t.strip()
        ]

        if not text_lines:
            return None

        name = text_lines[0]

        rating = ""
        review_count = ""

        for t in text_lines:

            m = re.match(
                r"^(\d\.\d)\s*\(([\d,]+)\)",
                t
            )

            if m:
                rating = m.group(1)
                review_count = m.group(2)
                break

        address = ""

        for t in text_lines:
            if any(
                k in t.lower()
                for k in [
                    "road",
                    "market",
                    "street",
                    "mall"
                ]
            ):
                address = t
                break

        try:
            link = card.find_element(
                By.XPATH,
                './/a[contains(@href,"/maps/place/")]'
            )

            place_url = link.get_attribute("href")

        except:
            place_url = ""

        return {
            "name": name,
            "rating": rating,
            "review_count": review_count,
            "address": address,
            "place_url": place_url
        }

    except:
        return None


# ============================================================
# LAT LONG
# ============================================================
def extract_lat_lon(url):

    if not isinstance(url, str):
        return None, None

    lat = re.search(r'!3d(-?\d+\.\d+)', url)
    lon = re.search(r'!4d(-?\d+\.\d+)', url)

    if lat and lon:
        return lat.group(1), lon.group(1)

    alt = re.search(
        r'@(-?\d+\.\d+),(-?\d+\.\d+)',
        url
    )

    if alt:
        return alt.group(1), alt.group(2)

    return None, None


# ============================================================
# TRANSLATE
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
# QUERY
# ============================================================
def run_query(driver, query):

    url = (
        f"https://www.google.com/maps/search/"
        f"{quote_plus(query)}"
    )

    driver.get(url)

    time.sleep(8)

    scroll_feed_fully(driver)

    cards = find_cards(driver)

    results = []

    for c in cards:

        p = parse_card(c)

        if p:
            results.append(p)

    return results


# ============================================================
# STREAMLIT UI
# ============================================================
st.set_page_config(
    page_title="Google Maps Scraper",
    layout="wide"
)

st.title("Google Maps Shop Scraper")

city = st.text_input(
    "Enter City",
    "Ruwais, Abu Dhabi"
)

categories = st.text_area(
    "Categories (one per line)",
    """baqala
groceries
super market
hyper market"""
)

if st.button("Start Scraping"):

    queries = [
        f"{c.strip()} in {city}"
        for c in categories.split("\n")
        if c.strip()
    ]

    all_rows = []

    progress = st.progress(0)

    driver = make_driver()

    try:

        for i, query in enumerate(queries):

            st.write(f"Searching: {query}")

            results = run_query(driver, query)

            for r in results:
                r["query"] = query
                all_rows.append(r)

            progress.progress(
                (i + 1) / len(queries)
            )

            time.sleep(
                random.uniform(2, 5)
            )

    finally:
        driver.quit()

    if len(all_rows) == 0:

        st.error("No results found")

    else:

        df = pd.DataFrame(all_rows)

        df["__key"] = df.apply(
            lambda r:
            r["place_url"]
            if r["place_url"]
            else f"{r['name']}|{r['address']}",
            axis=1
        )

        df = (
            df.drop_duplicates("__key")
            .drop(columns="__key")
        )

        df[["latitude", "longitude"]] = (
            df["place_url"]
            .apply(
                lambda x:
                pd.Series(
                    extract_lat_lon(x)
                )
            )
        )

        st.write(
            f"Total Unique Shops: {len(df)}"
        )

        with st.spinner("Translating..."):

            df["name_english"] = (
                df["name"]
                .apply(translate_text)
            )

            df["address_english"] = (
                df["address"]
                .apply(translate_text)
            )

        st.dataframe(
            df,
            use_container_width=True
        )

        excel_file = "google_maps_output.xlsx"

        with pd.ExcelWriter(
            excel_file,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False
            )

        with open(
            excel_file,
            "rb"
        ) as f:

            st.download_button(
                label="Download Excel",
                data=f,
                file_name=excel_file,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )