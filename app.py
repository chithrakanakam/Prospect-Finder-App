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
# FMCG FILTER (SHOP NAME ONLY)
# ============================================================

EXCLUDE_WORDS = [
    "flower","florist","book","fish","meat","restaurant","cafe","coffee",
    "salon","barber","spa","vegetable","computer","electronics","mobile",
    "school","college","university","police","post","atm","bank",
    "petrol","station","parking","camp","beach","office","hotel",
    "taxi","bus","cycle","tyre","garage","workshop","laundry",
    "bakery","cake","sweets","pharmacy","clinic","hospital",
    "mall","jewellery","gold","diamond","veg","pet","petrol",
    "lulu","carrefour","starbucks","dunkin","costa",
    "guest","villa","industry","studio","roastery","rostery",
    "butchery","park","adcb","fab","nbd","atm","city","villas","adnoc","spinney"
]


def is_valid_shop(name):
    if pd.isna(name):
        return False
    name = str(name).lower()
    return not any(x in name for x in EXCLUDE_WORDS)


# ============================================================
# TRANSLATION
# ============================================================

def contains_arabic(text):
    if pd.isna(text):
        return False
    return bool(re.search(r'[\u0600-\u06FF]', str(text)))


def translate_text(text):
    try:
        if pd.isna(text):
            return text
        if not contains_arabic(text):
            return text

        return GoogleTranslator(
            source="auto",
            target="en"
        ).translate(str(text))
    except:
        return text


def format_shop_name(name):
    if pd.isna(name):
        return name

    name_str = str(name)

    if contains_arabic(name_str):
        translated = translate_text(name_str)
        return f"{translated} ({name_str})"

    return name_str


# ============================================================
# DISTANCE CALC
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
        sin(dlat/2)**2 +
        cos(lat1)*cos(lat2)*sin(dlon/2)**2
    )

    return 2 * atan2(sqrt(a), sqrt(1-a)) * R


# ============================================================
# DRIVER
# ============================================================

def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


# ============================================================
# SCRAPER
# ============================================================

def scroll_feed(driver):
    try:
        feed = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]'))
        )
    except:
        return

    last_count = 0
    stable = 0

    for _ in range(50):
        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollHeight",
            feed
        )

        time.sleep(2)

        cards = driver.find_elements(By.XPATH, '//div[@role="feed"]//div[contains(@class,"Nv2PK")]')
        current = len(cards)

        if current == last_count:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0

        last_count = current


def parse_card(card):
    try:
        lines = [x for x in card.text.split("\n") if x.strip()]
        if not lines:
            return None

        name = lines[0]
        address = ""

        for t in lines:
            if any(x in t.lower() for x in ["street","road","market","uae","abu"]):
                address = t
                break

        try:
            url = card.find_element(By.XPATH, './/a[contains(@href,"/maps/place/")]')
            place_url = url.get_attribute("href")
        except:
            place_url = ""

        return {
            "Shop Name": name,
            "Address": address,
            "Place URL": place_url
        }

    except:
        return None


def extract_lat_lon(url):
    if not isinstance(url, str):
        return None, None

    m = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
    if m:
        return float(m.group(1)), float(m.group(2))

    m2 = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if m2:
        return float(m2.group(1)), float(m2.group(2))

    return None, None


def run_query(driver, query):
    url = "https://www.google.com/maps/search/" + quote_plus(query)
    driver.get(url)

    time.sleep(6)
    scroll_feed(driver)

    cards = driver.find_elements(By.XPATH, '//div[@role="feed"]//div[contains(@class,"Nv2PK")]')

    return [parse_card(c) for c in cards if parse_card(c)]


# ============================================================
# NEAREST CUSTOMER
# ============================================================

def nearest_customer(lat, lon, cust_df):
    if pd.isna(lat) or pd.isna(lon):
        return pd.Series([None]*7)

    temp = cust_df.copy()

    temp["dist"] = temp.apply(
        lambda r: haversine(lat, lon, r["Latitude"], r["Longitude"]),
        axis=1
    )

    nearest = temp.loc[temp["dist"].idxmin()]

    km = round(nearest["dist"], 3)
    meters = round(km * 1000, 0)

    status = "Customer" if meters <= 200 else "Prospect"

    return pd.Series([
        nearest["Customer Code"],
        nearest["Customer Name"],
        nearest["Latitude"],
        nearest["Longitude"],
        km,
        meters,
        status
    ])


# ============================================================
# STREAMLIT APP
# ============================================================

st.set_page_config("FMCG Prospect Finder", layout="wide")
st.title("FMCG Prospect Finder (Multi City Intelligence)")

# INPUTS
cities_input = st.text_input("Cities (comma separated)", "Abu Dhabi,Dubai,Sharjah")

categories_input = st.text_area(
    "Categories",
    "baqala\ngrocery\nsupermarket\nhypermarket\nmini mart\nconvenience store"
)

customer_file = st.file_uploader("Customer Master", type=["xlsx","csv"])


# ============================================================
# RUN
# ============================================================

if st.button("Start"):

    if customer_file is None:
        st.error("Upload Customer Master")
        st.stop()

    # LOAD CUSTOMER FILE
    if customer_file.name.endswith("csv"):
        cust = pd.read_csv(customer_file)
    else:
        cust = pd.read_excel(customer_file)

    cust.columns = cust.columns.str.strip()

    lat_col = [c for c in cust.columns if "lat" in c.lower()][0]
    lon_col = [c for c in cust.columns if "lon" in c.lower() or "lng" in c.lower()][0]

    cust["Latitude"] = pd.to_numeric(cust[lat_col], errors="coerce")
    cust["Longitude"] = pd.to_numeric(cust[lon_col], errors="coerce")

    driver = make_driver()

    all_data = []
    progress = st.progress(0)

    cities = [c.strip() for c in cities_input.split(",") if c.strip()]
    queries = [q.strip() for q in categories_input.split("\n") if q.strip()]

    try:
        total = len(cities) * len(queries)
        counter = 0

        for city in cities:
            st.write("City:", city)

            for q in queries:
                full_query = f"{q} in {city}"
                st.write("Searching:", full_query)

                rows = run_query(driver, full_query)

                for r in rows:
                    r["City"] = city
                    r["Query"] = full_query
                    all_data.append(r)

                counter += 1
                progress.progress(counter / total)

                time.sleep(random.uniform(2, 4))

    finally:
        driver.quit()

    df = pd.DataFrame(all_data)

    if df.empty:
        st.error("No data found")
        st.stop()

    # CLEAN + TRANSLATE
    df["Shop Name"] = df["Shop Name"].apply(format_shop_name)
    df["Address"] = df["Address"].apply(translate_text)

    # FMCG FILTER
    df = df[df["Shop Name"].apply(is_valid_shop)].reset_index(drop=True)

    # COORDINATES
    df[["Shop Lat","Shop Lon"]] = df["Place URL"].apply(
        lambda x: pd.Series(extract_lat_lon(x))
    )

    # DROP NULL + DEDUPE
    df = df.dropna(subset=["Shop Lat", "Shop Lon"])
    df = df.drop_duplicates(subset=["Shop Lat", "Shop Lon"]).reset_index(drop=True)

    # NEAREST CUSTOMER
    df[
        ["Cust Code","Cust Name","Cust Lat","Cust Lon","Dist KM","Dist M","Status"]
    ] = df.apply(
        lambda r: nearest_customer(r["Shop Lat"], r["Shop Lon"], cust),
        axis=1
    )

    # PROSPECT ONLY
    df = df[df["Status"] == "Prospect"].reset_index(drop=True)

    # FINAL FORMAT
    df = df[
        [
            "Cust Code",
            "Cust Name",
            "Shop Name",
            "Address",
            "Dist M",
            "Place URL",
            "Shop Lat",
            "Shop Lon",
            "Cust Lat",
            "Cust Lon"
        ]
    ]

    st.success(f"Final Prospects Found: {len(df)}")
    st.dataframe(df, use_container_width=True)

    # DOWNLOAD
    file = "fmcg_output.xlsx"
    df.to_excel(file, index=False)

    with open(file, "rb") as f:
        st.download_button("Download Excel", f, file_name=file)