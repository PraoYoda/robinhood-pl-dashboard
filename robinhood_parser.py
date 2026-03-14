import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import calendar
from datetime import datetime

# --- 1. CORE UTILITIES (PRESERVED & IMPROVED) ---
def clean_amount(val):
    if pd.isna(val) or val == '': return 0.0
    val = str(val).replace('$', '').replace(',', '')
    if '(' in val and ')' in val:
        val = '-' + val.replace('(', '').replace(')', '')
    try: return float(val)
    except: return 0.0

def clean_quantity(val):
    if pd.isna(val) or val == '': return 0.0
    val = str(val).replace('S', '')
    try: return float(val)
    except: return 0.0

def get_asset_type(row):
    trans = str(row['Trans Code'])
    desc = str(row['Description']).upper()
    if trans == 'CDIV': return 'Dividend'
    if any(x in desc for x in [' CALL ', ' PUT ', ' CALL $', ' PUT $']):
        if trans == 'STO': return 'Covered Call'
        return 'Option'
    return 'Stock'

def get_core_desc(row):
    desc = str(row['Description'])
    if row['Trans Code'] == 'OEXP':
        match = re.search(r'Option Expiration for (.*)', desc)
        if match: return match.group(1).strip()
    return desc.strip()

@st.cache_data(ttl=3600)
def fetch_dynamic_article(query):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        item = root.find('.//channel/item')
        if item is not None:
            title = item.find('title').text
            link = item.find('link').text
            return f"[{title.split(' - ')[0]}]({link})"
    except: pass
    return f"[Search: {query}](https://www.google.com/search?q={urllib.parse.quote(query)})"

# --- 2. THE SUNDAY-START CALENDAR GRID ---
def render_calendar_grid(df_subset, selected_month_str):
    dt_obj = datetime.strptime(selected_month_str, '%B %Y')
    year, month = dt_obj.year, dt_obj.month
    
    df_subset['Date_Only'] = pd.to_datetime(df_subset['Sell Date']).dt.date
    daily_pnl = df_subset.groupby('Date_Only')['Net Change'].sum().to_dict()

    cal_obj = calendar.Calendar(firstweekday=6) # Sunday Start
    weeks = cal_obj.monthdayscalendar(year, month)
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    
    st.markdown("""
        <style>
        .cal-day { border-radius: 5px; padding: 10px; height: 85px; display: flex; flex-direction: column; align-items: center; border: 1px solid #eee; margin-bottom: 5px; }
        .day-num { font-size: 0.8rem; color: #888; margin-bottom: 5px; width: 100%; text-align: left; }
        .day-pnl { font-size: 0.95rem; font-weight: bold; margin-top: 5px; }
        .pos { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .neg { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .neu { background-color: #ffffff; color: #ccc; }
        </style>
    """, unsafe_allow_html=True)

    cols = st.columns(7)
    for i, d in enumerate(days): 
        cols[i].markdown(f"<p style='text-align:center;font-weight:bold;'>{d}</p>", unsafe_allow_html=True)

    for week in weeks:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0: 
                cols[i].markdown("<div></div>", unsafe_allow_html=True)
            else:
                curr_date = datetime(year, month, day).date()
                pnl = daily_pnl.get(curr_date, 0)
                style_class = "pos" if pnl > 0 else ("neg" if pnl < 0 else "neu")
                pnl_text = f"${pnl:,.0f}" if pnl != 0 else ""
                cols[i].markdown(f"<div class='cal-day {style_class}'><div class='day-num'>{day}</div><div class='day-pnl'>{pnl_text}</div></div>", unsafe_allow_html=True)

# --- 3. ACCURATE DATA PROCESSING ENGINE ---
def process_robinhood_csv(uploaded_file):
    df = pd.read_csv(uploaded_file, on_bad_lines='skip')
    df['Activity Date'] = pd.to_datetime(df['Activity Date'])
    df['Amount_Clean'] = df['Amount'].apply(clean_amount)
    df['Quantity_Clean'] = df['Quantity'].apply(clean_quantity)
    df['Asset Type'] = df.apply(get_asset_type, axis=1)
    df['Core_Description'] = df.apply(get_core_desc, axis=1)

    trade_codes = ['BTO', 'STC', 'STO', 'BTC', 'Buy', 'Sell', 'OEXP']
    trades = df[df['Trans Code'].isin(trade_codes)].copy()
    trades = trades.sort_values(['Instrument', 'Core_Description', 'Activity Date'])

    summary_rows = []
    for (ticker, core_desc), group in trades.groupby(['Instrument', 'Core_Description']):
        # Improved logic for cost basis and P&L
        buys = group[group['Trans Code'].isin(['BTO', 'Buy', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'Sell', 'STO', 'OEXP'])]
        
        net_change = group['Amount_Clean'].sum()
        total_buy_amt = abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum())
        
        # Determine Status: If any "Closing" action exists in this file, it's a realized trade for this period
        buy_date = buys['Activity Date'].min() if not buys.empty else np.nan
        sell_date = sells['Activity Date'].max() if not sells.empty else np.nan
        
        # A trade is 'Closed' if we have a closing transaction (even if the Buy happened in a previous month)
        status = 'Closed' if pd.notna(sell_date) else 'Open'
        
        summary_rows.append({
            'Ticker': ticker,
            'Contract Description': core_desc,
            'Total Buy': round(total_buy_amt, 2),
            'Net Change': round(net_change, 2),
            'Buy Date': buy_date.strftime('%m/%d/%Y') if pd.notna(buy_date) else None,
            'Sell Date': sell_date.strftime('%m/%d/%Y') if pd.notna(sell_date) else None,
            'Days Held': (sell_date - buy_date).days if pd.notna(sell_date) and pd.notna(buy_date) else 0,
            'Asset Category': group['Asset Type'].iloc[0],
            'Status': status,
            'Is_Put': 'Put' in core_desc,
            'Is_Call': 'Call' in core_desc
        })
    return pd.DataFrame(summary_rows)

# --- 4. RENDER DASHBOARD (PRESERVED ANALYTICS) ---
def render_dashboard_view(df_subset, category_name):
    if df_subset.empty:
        st.info(f"No completed trades found.")
        return

    # Preserved KPI Logic
    total_pnl = df_subset['Net Change'].sum()
    winners = df_subset[df_subset['Net Change'] > 0]
    losers = df_subset[df_subset['Net Change'] < 0]
    win_rate = (len(winners) / len(df_subset)) * 100 if len(df_subset) > 0 else 0
    total_cost = df_subset['Total Buy'].sum()
    overall_roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net Profit/Loss", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Avg Trade ROI", f"{overall_roi:.1f}%")
    col4.metric("Total Trades", len(df_subset))
    
    st.markdown("---")

    # --- PRESERVED DEEP DIVE ---
    st.markdown(f"### 🔬 Deep Dive: {category_name} Analytics")
    ana_col1, ana_col2 = st.columns(2)
    with ana_col1:
        st.write(f"🐂 **Calls Net P&L:** ${df_subset[df_subset['Is_Call']]['Net Change'].sum():,.2f}")
    with ana_col2:
        st.write(f"🐻 **Puts Net P&L:** ${df_subset[df_subset['Is_Put']]['Net Change'].sum():,.2f}")

    # --- MONTHLY SUMMARY TABLE (ASCENDING) ---
    st.markdown("---")
    df_subset['Month_Date'] = pd.to_datetime(df_subset['Sell Date']).fillna(pd.to_datetime(df_subset['Buy Date']))
    df_subset['Month'] = df_subset['Month_Date'].dt.strftime('%B %Y')
    df_subset['Month_Sort'] = df_subset['Month_Date'].dt.to_period('M')
    
    monthly_summary = df_subset.groupby(['Month_Sort', 'Month']).agg(
        Total_Trades=('Ticker', 'count'), Wins=('Net Change', lambda x: (x > 0).sum()),
        Net_Profit=('Net Change', 'sum'), Unique_Tickers=('Ticker', 'nunique'),
        Puts=('Is_Put', 'sum'), Calls=('Is_Call', 'sum')
    ).reset_index().sort_values('Month_Sort', ascending=True)

    st.markdown("### 📅 Monthly Summary Table")
    st.dataframe(monthly_summary.drop(columns=['Month_Sort']).style.format({'Net_Profit': '${:,.2f}'}), width='stretch')

    # --- SUNDAY-START CALENDAR GRID ---
    st.markdown("---")
    st.markdown(f"### 🗓️ Daily Profit/Loss Grid")
    month_list = monthly_summary['Month'].tolist()
    selected_month = st.selectbox(f"Select Month for Grid Audit", month_list, key=f"sel_{category_name}")
    render_calendar_grid(df_subset, selected_month)

    st.markdown("---")
    st.markdown(f"### 📋 Trade Details Audit Log")
    st.dataframe(df_subset.drop(columns=['Month_Date', 'Month', 'Month_Sort', 'Is_Put', 'Is_Call']), width='stretch')

# --- 5. STREAMLIT UI ---
st.set_page_config(page_title="Robinhood Mastery", layout="wide")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")
st.title("📈 Interactive Robinhood P&L Dashboard")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_res = process_robinhood_csv(uploaded_file)
    # Only show 'Closed' trades for accuracy in realized P&L
    df_res = df_res[df_res['Status'] == 'Closed']
    df_res = df_res[df_res['Asset Category'].isin(['Option', 'Covered Call'])]
    
    t_names = ["All Data"] + sorted(df_res['Asset Category'].unique().tolist())
    tabs = st.tabs(t_names)
    for i, tab in enumerate(tabs):
        with tab: render_dashboard_view(df_res if t_names[i] == "All Data" else df_res[df_res['Asset Category'] == t_names[i]], t_names[i])
