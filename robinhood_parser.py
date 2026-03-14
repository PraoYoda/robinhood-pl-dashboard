import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# --- 1. CORE UTILITIES ---
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
    if any(x in desc for x in [' CALL ', ' PUT ', ' CALL $', ' PUT $']):
        if trans == 'STO': return 'Covered Call'
        return 'Option'
    return 'Stock'

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

def process_robinhood_csv(uploaded_file):
    df = pd.read_csv(uploaded_file, on_bad_lines='skip')
    df['Activity Date'] = pd.to_datetime(df['Activity Date'])
    df['Amount_Clean'] = df['Amount'].apply(clean_amount)
    df['Quantity_Clean'] = df['Quantity'].apply(clean_quantity)
    df['Asset Category'] = df.apply(get_asset_type, axis=1)
    
    trade_codes = ['BTO', 'STC', 'STO', 'BTC', 'Buy', 'Sell', 'OEXP']
    trades = df[df['Trans Code'].isin(trade_codes)].copy()
    
    summary_rows = []
    for (ticker, desc), group in trades.groupby(['Instrument', 'Description']):
        net_pnl = group['Amount_Clean'].sum()
        total_cost = abs(group[group['Amount_Clean'] < 0]['Amount_Clean'].sum())
        buy_date = group['Activity Date'].min()
        sell_date = group['Activity Date'].max()
        days_held = (sell_date - buy_date).days
        status = 'Closed' if len(group) >= 2 or any(group['Trans Code'] == 'OEXP') else 'Open'
        
        summary_rows.append({
            'Ticker': ticker,
            'Description': desc,
            'Total Buy': round(total_cost, 2),
            'Net Change': round(net_pnl, 2),
            'ROI %': round((net_pnl / total_cost * 100), 2) if total_cost > 0 else 0,
            'Days Held': days_held,
            'Status': status,
            'Asset Category': group['Asset Category'].iloc[0],
            'Close Date': sell_date,
            'Buy Date': buy_date
        })
    return pd.DataFrame(summary_rows)

def render_strategy_view(df, title, is_option=True):
    """Renders the dashboard for a specific strategy."""
    if df.empty:
        st.info(f"No {title} data available.")
        return

    # --- TOP LEVEL KPIs ---
    total_pnl = df['Net Change'].sum()
    winners = df[df['Net Change'] > 0]
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Net P&L", f"${total_pnl:,.2f}")
    m2.metric("Win Rate", f"{(len(winners)/len(df)*100):.1f}%")
    m3.metric("Avg ROI", f"{df['ROI %'].mean():.1f}%")
    m4.metric("Total Trades", len(df))

    st.markdown("---")

    # --- CALENDAR SELECTOR & SUMMARY ---
    st.subheader(f"🗓️ {title} Monthly Calendar View")
    df['MonthYear'] = df['Close Date'].dt.strftime('%B %Y')
    available_months = df['MonthYear'].unique().tolist()
    selected_month = st.selectbox(f"Select Month to Audit ({title})", available_months)

    month_df = df[df['MonthYear'] == selected_month].copy()
    
    # Metrics for the month
    month_pnl = month_df['Net Change'].sum()
    unique_tickers = month_df['Ticker'].nunique()
    puts = month_df['Description'].str.contains('Put', case=False).sum()
    calls = month_df['Description'].str.contains('Call', case=False).sum()

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.write(f"**Monthly P&L:** ${month_pnl:,.2f}")
    col_b.write(f"**Unique Tickers:** {unique_tickers}")
    col_c.write(f"**Puts:** {puts}")
    col_d.write(f"**Calls:** {calls}")

    # Daily Breakdown List (The "Calendar Image" alternative)
    month_df['Date'] = month_df['Close Date'].dt.date
    daily = month_df.groupby('Date')['Net Change'].sum().reset_index()
    st.dataframe(daily.sort_values('Date').style.format({'Net Change': '${:,.2f}'}), width='stretch', hide_index=True)

    # --- DYNAMIC RECOMMENDATIONS (Options Only) ---
    if is_option:
        st.markdown("---")
        st.subheader("💡 Actionable Recommendations")
        avg_loss = abs(df[df['Net Change'] < 0]['Net Change'].mean())
        if not pd.isna(avg_loss):
            st.warning(f"🚨 **Risk Alert:** Your average loss is **${avg_loss:,.2f}**. Read: {fetch_dynamic_article('options risk management strategies')}")
        
        if total_pnl < 0:
            st.error(f"⚠️ **Strategy Leak Detected:** {fetch_dynamic_article('how to fix losing options trades')}")
        else:
            st.success(f"✅ **Performance Note:** {fetch_dynamic_article('scaling winning options strategies')}")

    st.markdown("---")
    st.subheader(f"📋 {title} Detailed Log")
    st.dataframe(df.drop(columns=['Status', 'Asset Category', 'MonthYear']), width='stretch')

# --- 2. MAIN UI ---
st.set_page_config(page_title="Robinhood Quant-View", layout="wide")

# Sidebar Restoration
st.sidebar.title("🛠️ Settings")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")
st.sidebar.info("Optimized for Options & Covered Call Mastery")

st.title("🔬 Robinhood Quant-View")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    df_closed = df_raw[df_raw['Status'] == 'Closed'].copy()

    # Strategy Split
    df_options = df_closed[df_closed['Asset Category'] == 'Option']
    df_cc = df_closed[df_closed['Asset Category'] == 'Covered Call']

    tab1, tab2 = st.tabs(["🔥 Standard Options", "🛡️ Covered Calls"])

    with tab1:
        render_strategy_view(df_options, "Standard Options", is_option=True)
    
    with tab2:
        render_strategy_view(df_cc, "Covered Calls", is_option=False)
