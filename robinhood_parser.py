import streamlit as st
import pandas as pd
import numpy as np
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import calendar

# --- DATA CLEANING FUNCTIONS ---
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

# --- CORE PROCESSING ---
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
        # Split into buys and sells to check status
        buys = group[group['Trans Code'].isin(['BTO', 'Buy', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'Sell', 'STO', 'OEXP', 'CDIV'])]
        
        # STATUS LOGIC: Closed if Qty is balanced OR if an Expiration code exists
        net_qty = buys['Quantity_Clean'].sum() - sells['Quantity_Clean'].sum()
        is_expired = any(group['Trans Code'] == 'OEXP')
        status = 'Closed' if (abs(net_qty) < 0.0001 or is_expired) else 'Open'
        
        net_change = group['Amount_Clean'].sum()
        total_buy_amt = abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum())
        total_sell_amt = sells[sells['Amount_Clean'] > 0]['Amount_Clean'].sum()
        
        avg_buy = total_buy_amt / buys['Quantity_Clean'].sum() if not buys.empty and buys['Quantity_Clean'].sum() > 0 else 0
        avg_sell = total_sell_amt / sells['Quantity_Clean'].sum() if not sells.empty and sells['Quantity_Clean'].sum() > 0 else 0
        
        buy_date = group['Activity Date'].min()
        sell_date = group['Activity Date'].max() if status == 'Closed' else np.nan
        
        summary_rows.append({
            'Ticker': ticker,
            'Contract Description': core_desc,
            '# Cons/Shares': buys['Quantity_Clean'].sum() if not buys.empty else sells['Quantity_Clean'].sum(),
            'Avg Buy': round(avg_buy, 2),
            'Total Buy': round(total_buy_amt, 2),
            'Avg Sell': round(avg_sell, 2),
            'Total Sell': round(total_sell_amt, 2),
            'Net Change': round(net_change, 2),
            'Buy Date': buy_date,
            'Sell Date': sell_date,
            'Status': status,
            'Asset Category': group['Asset Type'].iloc[0]
        })

    df_summary = pd.DataFrame(summary_rows)
    return df_summary.sort_values('Buy Date', ascending=False)

def render_dashboard_view(df_subset, category_name):
    if df_subset.empty:
        st.info(f"No trade data found for {category_name}.")
        return

    # Use .copy() to avoid SettingWithCopyWarnings
    df_subset = df_subset.copy()
    
    # Accurate Metrics: Only calculate P&L for CLOSED trades
    closed_trades = df_subset[df_subset['Status'] == 'Closed'].copy()
    open_trades = df_subset[df_subset['Status'] == 'Open'].copy()
    
    realized_pnl = closed_trades['Net Change'].sum()
    open_cost = open_trades['Total Buy'].sum()
    
    winners = closed_trades[closed_trades['Net Change'] > 0]
    losers = closed_trades[closed_trades['Net Change'] < 0]
    win_rate = (len(winners) / len(closed_trades) * 100) if not closed_trades.empty else 0
    
    # Metric Display
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Realized Net P&L", f"${realized_pnl:,.2f}")
    m2.metric("Open Position Cost", f"${open_cost:,.2f}")
    m3.metric("Win Rate (Closed)", f"{win_rate:.1f}%")
    m4.metric("Total Trades", len(df_subset))
    
    st.markdown("---")

    # --- DEEP DIVE ANALYTICS ---
    st.markdown(f"### 🔬 {category_name} Strategy Breakdown")
    
    # Calculate performance metadata on closed trades
    closed_trades['Days Held'] = (closed_trades['Sell Date'] - closed_trades['Buy Date']).dt.days
    closed_trades['Buy DoW'] = closed_trades['Buy Date'].dt.day_name()
    closed_trades['Trade Style'] = np.where(closed_trades['Days Held'] == 0, 'Day Trade', 'Swing Trade')
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Style Performance**")
        dt_pnl = closed_trades[closed_trades['Trade Style'] == 'Day Trade']['Net Change'].sum()
        sw_pnl = closed_trades[closed_trades['Trade Style'] == 'Swing Trade']['Net Change'].sum()
        st.write(f"⚡ **Day Trades:** ${dt_pnl:,.2f}")
        st.write(f"📈 **Swing Trades:** ${sw_pnl:,.2f}")

    with c2:
        st.markdown("**Best Performer**")
        if not closed_trades.empty:
            best_t = closed_trades.groupby('Ticker')['Net Change'].sum().idxmax()
            st.write(f"🏆 **Ticker:** {best_t}")
            st.write(f"📰 {fetch_dynamic_article(best_t)}")
        else:
            st.write("N/A")

    with c3:
        st.markdown("**Entry Timing**")
        if not closed_trades.empty:
            dow_stats = closed_trades.groupby('Buy DoW')['Net Change'].sum()
            st.write(f"✅ **Best Day:** {dow_stats.idxmax()}")
            st.write(f"❌ **Worst Day:** {dow_stats.idxmin()}")

    # --- CALENDAR VIEW ---
    st.markdown("---")
    st.markdown(f"### 📅 {category_name} - Monthly P&L")
    
    # Use Sell Date for Calendar if closed, else Buy Date
    df_subset['Cal_Date'] = pd.to_datetime(df_subset['Sell Date']).fillna(df_subset['Buy Date'])
    df_subset['Month_Str'] = df_subset['Cal_Date'].dt.strftime('%B %Y')
    
    months = df_subset['Month_Str'].unique()
    if len(months) > 0:
        sel_month = st.selectbox("Select Calendar Month", months, key=f"cal_{category_name}")
        cal_data = df_subset[df_subset['Month_Str'] == sel_month]
        daily_pnl = cal_data.groupby(cal_data['Cal_Date'].dt.day)['Net Change'].sum().to_dict()
        
        # Matrix creation
        year, month_idx = cal_data['Cal_Date'].iloc[0].year, cal_data['Cal_Date'].iloc[0].month
        matrix = calendar.monthcalendar(int(year), int(month_idx))
        cal_df = pd.DataFrame(matrix, columns=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
        
        def format_day(d):
            if d == 0: return ""
            p = daily_pnl.get(d, 0)
            return f"{d}: ${p:,.0f}" if p != 0 else str(d)

        # UPDATED: Use .map instead of .applymap
        styled_cal = cal_df.map(format_day)
        
        def color_logic(val):
            if ":" not in str(val): return ''
            try:
                amt = float(val.split('$')[1].replace(',', ''))
                if amt > 0: return 'background-color: #d4edda; color: #155724; font-weight: bold'
                if amt < 0: return 'background-color: #f8d7da; color: #721c24; font-weight: bold'
            except: pass
            return ''

        st.table(styled_cal.style.map(color_logic))

    # --- DETAILS TABLE ---
    st.markdown("---")
    st.markdown(f"### 📋 {category_name} - Raw Trade Log")
    display_df = df_subset.drop(columns=['Cal_Date', 'Month_Str']).copy()
    display_df['Buy Date'] = display_df['Buy Date'].dt.strftime('%m/%d/%Y')
    display_df['Sell Date'] = pd.to_datetime(display_df['Sell Date']).dt.strftime('%m/%d/%Y').replace('NaT', 'OPEN')
    st.dataframe(display_df, use_container_width=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood P&L Dashboard", layout="wide", page_icon="📈")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.title("📈 Robinhood P&L Master Dashboard")

uploaded_file = st.file_uploader("Upload your Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    # Narrowing focus to user's specified categories
    df_final = df_raw[df_raw['Asset Category'].isin(['Option', 'Covered Call'])]
    
    tabs = st.tabs(["All Positions", "Standard Options", "Covered Calls"])
    with tabs[0]: render_dashboard_view(df_final, "All Positions")
    with tabs[1]: render_dashboard_view(df_final[df_final['Asset Category'] == 'Option'], "Options")
    with tabs[2]: render_dashboard_view(df_final[df_final['Asset Category'] == 'Covered Call'], "Covered Calls")
else:
    st.info("Upload your CSV from Robinhood (Account > History > Export) to view your performance.")
