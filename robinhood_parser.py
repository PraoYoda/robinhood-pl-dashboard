import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import calendar 

# Set calendar to start on Sunday
calendar.setfirstweekday(calendar.SUNDAY)

# --- CSS FOR SYMMETRY AND STYLE ---
# Fixed the parameter from unsafe_allow_stdio to unsafe_allow_html
st.markdown("""
    <style>
    .stTable {
        width: 100%;
    }
    th {
        text-align: center !important;
        background-color: #f0f2f6;
        font-weight: bold;
    }
    td {
        text-align: center !important;
        width: 14.28%; /* Symmetrical 7-column grid */
        height: 70px;
        vertical-align: middle !important;
        font-size: 14px;
    }
    </style>
    """, unsafe_allow_html=True)

def clean_amount(val):
    if pd.isna(val) or val == '': return 0.0
    val = str(val).replace('$', '').replace(',', '')
    if '(' in val and ')' in val:
        val = '-' + val.replace('(', '').replace(')', '')
    try:
        return float(val)
    except:
        return 0.0

def clean_quantity(val):
    if pd.isna(val) or val == '': return 0.0
    val = str(val).replace('S', '')
    try:
        return float(val)
    except:
        return 0.0

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
            clean_title = title.split(' - ')[0] 
            return f"[{clean_title}]({link})"
    except:
        pass
    return f"[Search '{query}' on Google](https://www.google.com/search?q={urllib.parse.quote(query)})"

def process_robinhood_csv(uploaded_file):
    df = pd.read_csv(uploaded_file, on_bad_lines='skip')
    df['Activity Date'] = pd.to_datetime(df['Activity Date'])
    df['Amount_Clean'] = df['Amount'].apply(clean_amount)
    df['Quantity_Clean'] = df['Quantity'].apply(clean_quantity)
    df['Asset Type'] = df.apply(get_asset_type, axis=1)
    df['Core_Description'] = df.apply(get_core_desc, axis=1)

    trade_codes = ['BTO', 'STC', 'STO', 'BTC', 'Buy', 'Sell', 'OEXP', 'CDIV']
    trades = df[df['Trans Code'].isin(trade_codes)].copy()
    trades = trades.sort_values(['Instrument', 'Core_Description', 'Activity Date'])

    summary_rows = []
    for (ticker, core_desc), group in trades.groupby(['Instrument', 'Core_Description']):
        buys = group[group['Trans Code'].isin(['BTO', 'Buy', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'Sell', 'STO', 'OEXP', 'CDIV'])]
        
        total_buy_qty = buys['Quantity_Clean'].sum()
        total_buy_amt = abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum())
        total_sell_amt = sells[sells['Amount_Clean'] > 0]['Amount_Clean'].sum()
        
        net_change = group['Amount_Clean'].sum()
        buy_date = buys['Activity Date'].min() if not buys.empty else np.nan
        sell_date = sells['Activity Date'].max() if not sells.empty else np.nan
        status = 'Closed' if pd.notna(buy_date) and pd.notna(sell_date) else 'Open'

        summary_rows.append({
            'Ticker': ticker,
            'Contract Description': core_desc,
            'Total Buy': round(total_buy_amt, 2),
            'Net Change': round(net_change, 2),
            'Buy Date': buy_date,
            'Sell Date': sell_date,
            'Asset Category': group['Asset Type'].iloc[0],
            'Status': status
        })

    return pd.DataFrame(summary_rows)

def render_dashboard_view(df_subset, category_name):
    df_closed = df_subset[df_subset['Status'] == 'Closed'].copy()
    if df_closed.empty:
        st.info(f"No completed trades available for {category_name}.")
        return

    # Metrics
    total_pnl = df_closed['Net Change'].sum()
    total_cost = df_closed['Total Buy'].sum()
    roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Realized P&L", f"${total_pnl:,.2f}")
    c2.metric("Avg ROI", f"{roi:.1f}%")
    c3.metric("Closed Trades", len(df_closed))
    
    st.markdown("---")

    # Calendar with Sunday start and chronological Month sort
    st.markdown(f"### 📅 {category_name} - Monthly Journal")
    
    # Sorting logic to ensure Jan, Feb, March... order
    df_closed['Month_Sort'] = df_closed['Buy Date'].dt.to_period('M')
    df_closed['Month_Str'] = df_closed['Buy Date'].dt.strftime('%B %Y')
    
    # Sort by the Period index to maintain chronological order
    month_options = df_closed.sort_values('Month_Sort')['Month_Str'].unique().tolist()
    selected_month = st.selectbox("Select Month", month_options, key=f"cal_{category_name}")
    
    cal_data = df_closed[df_closed['Month_Str'] == selected_month].copy()
    daily_pnl = cal_data.groupby(cal_data['Buy Date'].dt.day)['Net Change'].sum().to_dict()
    
    # Generate Calendar
    year, month_idx = cal_data['Buy Date'].iloc[0].year, cal_data['Buy Date'].iloc[0].month
    matrix = calendar.monthcalendar(int(year), int(month_idx))
    cal_df = pd.DataFrame(matrix, columns=['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
    
    def format_cell(day):
        if day == 0: return ""
        pnl = daily_pnl.get(day, 0)
        return f"{day}\n${pnl:,.0f}" if pnl != 0 else str(day)

    styled_cal = cal_df.map(format_cell)
    
    def color_pnl(val):
        if "$" not in str(val): return 'text-align: center;'
        try:
            amt = float(val.split('$')[1].replace(',', ''))
            if amt > 0: return 'background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;'
            if amt < 0: return 'background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center;'
        except: pass
        return 'text-align: center;'

    st.table(styled_cal.style.map(color_pnl))
    
    st.markdown("---")
    st.markdown(f"### 📋 Trade Details")
    display_df = df_subset.copy()
    display_df['Buy Date'] = display_df['Buy Date'].dt.strftime('%m/%d/%Y')
    display_df['Sell Date'] = display_df['Sell Date'].dt.strftime('%m/%d/%Y').replace('NaT', 'OPEN')
    st.dataframe(display_df.drop(columns=['Month_Sort', 'Month_Str'], errors='ignore'), use_container_width=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood Portfolio Dashboard", layout="wide")

# 4. Sidebar Intro
st.sidebar.title("📊 Account Insights")
st.sidebar.markdown("""
Welcome to your **Interactive P&L Dashboard**. 

This application parses your Robinhood CSV data to track:
* **Realized Gains/Losses** from closed trades.
* **Open Equity** currently at risk in the market.
* **Monthly Performance** via a trading journal view.
""")

st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    
    # 1. Sidebar Metrics for Open Positions (Options only)
    open_ops = df_raw[(df_raw['Status'] == 'Open') & (df_raw['Asset Category'].isin(['Option', 'Covered Call']))]
    st.sidebar.metric("Open Position Count", len(open_ops))
    st.sidebar.metric("Open Options Equity", f"${open_ops['Total Buy'].sum():,.2f}")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("👨‍💻 **Puneeth Rao**")

    # Dashboard Tabs
    df_final = df_raw[df_raw['Asset Category'].isin(['Option', 'Covered Call'])]
    categories = ["All Data"] + sorted(df_final['Asset Category'].unique().tolist())
    tabs = st.tabs(categories)
    
    for i, tab in enumerate(tabs):
        with tab:
            cat = categories[i]
            data = df_final if cat == "All Data" else df_final[df_final['Asset Category'] == cat]
            render_dashboard_view(data, cat)
