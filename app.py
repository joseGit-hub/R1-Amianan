import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
import os
import numpy as np
from datetime import datetime, timedelta

# Import everything from your new consolidated file
from price_scraper import get_region1_weather, get_diesel_price

# --- 0. CONFIGURATION & DESIGN ---
st.set_page_config(page_title="Region I - Amianan Presyo", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    .stTable { font-size: 10px; }
    .block-container { padding-top: 1.5rem; padding-bottom: 0rem; }
    h1 { font-size: 1.4rem !important; margin-bottom: 0px; }
    h2 { font-size: 1.1rem !important; margin-top: 10px; }
    .stAlert { padding: 0.5rem; }
    .vertical-line {
        border-left: 2px solid #ddd;
        height: 70px;
        margin-left: auto;
        margin-right: auto;
        width: 1px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. LIVE DATA FETCHING ---
@st.cache_data(ttl=300) 
def fetch_all_live_data():
    weather = get_region1_weather()
    diesel = get_diesel_price()
    
    prices = {
        "Rice": 52.0, "Red Onion": 145.0, "White Onion": 160.0,
        "Garlic": 130.0, "White Corn": 28.0, "Yellow Corn": 22.0,
        "Diesel": diesel
    }
    return prices, weather

current_prices, weather_data = fetch_all_live_data()

# --- 2. AUTOMATIC DATA PERSISTENCE ---
def log_data_to_csv(data):
    file_path = 'region1_prices.csv'
    log_entry = data.copy()
    log_entry['Timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df_new = pd.DataFrame([log_entry])
    
    if not os.path.isfile(file_path):
        df_new.to_csv(file_path, index=False)
    else:
        if data.get("Diesel", 0) > 0:
            df_new.to_csv(file_path, mode='a', header=False, index=False)
    return pd.read_csv(file_path)

history_df = log_data_to_csv(current_prices)

# --- 3. HEADER ---
t1, t2 = st.columns([2, 1])
with t1:
    st.title("🌾 Region I - Amianan Presyo")
with t2:
    st.write("") 
    st.caption(f"Last Sync: {datetime.now().strftime('%H:%M:%S')}")

# --- 4. LIVE MARKET MONITOR ---
mon_cols = st.columns([1, 1, 1, 1, 1, 1, 0.1, 1.2])
items = ["Rice", "Red Onion", "White Onion", "Garlic", "White Corn", "Yellow Corn"]

for i, item in enumerate(items):
    price = current_prices.get(item, 0.0)
    mon_cols[i].metric(label=item, value=f"₱{price:,.2f}")

with mon_cols[6]:
    st.markdown('<div class="vertical-line"></div>', unsafe_allow_html=True)

d_curr = current_prices.get("Diesel", 0.0)
mon_cols[7].metric(label="⛽ Diesel (Live Avg)", value=f"₱{d_curr:,.2f}")

st.markdown("---")

# --- 5. PRICE TRENDS & EXPORT ---
c1, c2 = st.columns([2, 1])

with c1:
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.subheader("Historical Price Trends")
    with col_b:
        if os.path.exists('region1_prices.csv'):
            with open('region1_prices.csv', 'rb') as f:
                st.download_button(
                    label="📤 Export CSV",
                    data=f,
                    file_name='region1_prices.csv',
                    mime='text/csv'
                )

    numeric_items = items + ["Diesel"]
    selected = st.multiselect("Select Commodities to View:", numeric_items, default=["Rice", "Diesel"])
    
    if not history_df.empty and len(history_df) >= 2:
        fig = go.Figure()
        
        for item in selected:
            fig.add_trace(go.Scatter(
                x=pd.to_datetime(history_df['Timestamp']), 
                y=history_df[item],
                name=f"{item}",
                line=dict(width=2)
            ))
        
        fig.update_layout(template="plotly_white", height=300, margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Collecting historical data...")

with c2:
    st.subheader("Regional Weather")
    st.table(pd.DataFrame(weather_data))

st.markdown("---")

# --- 6. LOGISTICS CALCULATOR ---
st.subheader("Logistics Calculator")
calc_col1, calc_col2, calc_col3 = st.columns([1, 1, 1])

with calc_col1:
    sel_item = st.selectbox("Commodity", items)
with calc_col2:
    weight = st.number_input("Volume (kg)", min_value=1, value=100)
with calc_col3:
    base_val = current_prices.get(sel_item, 0.0) * weight
    logistics = (weight * 2.2) + (d_curr * 0.4)
    st.metric(label="Estimated Landed Cost", value=f"₱{base_val + logistics:,.2f}")

# --- 7. AUTO-REFRESH ---
time.sleep(120) 
st.rerun()