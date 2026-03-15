import streamlit as st
import pandas as pd
import numpy as np
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import calendar 

# Set calendar to start on Sunday
calendar.setfirstweekday(calendar.SUNDAY)

# --- CSS FOR SYMMETRY, DARK MODE & EQUAL CALENDAR COLUMNS ---
st.markdown("""
    <style>
    .stTable { 
        width: 100%; 
        border-radius: 10px; 
        overflow: hidden; 
        border: 1px solid rgba(128, 128, 128, 0.2);
        table-layout: fixed; 
    }
    th { 
        text-align: center !important; 
        background-color: rgba(128, 128, 128, 0.1) !important; 
        color: inherit !important;
        font-weight: bold; 
        padding: 10px !important;
        width: 14.28%; 
    }
    td { 
        text-align: center !important; 
        height: 100px; 
        vertical-align: middle !important; 
        font-size: 14px; 
        border: 1px solid rgba(128, 128, 128, 0.1) !important;
        width: 14.28%;
    }
    .cal-cell {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 90px;
        padding: 2px;
    }
    .cal-date { align-self: flex-start; font-weight: bold; font-size: 13px; opacity: 0.5; }
    .cal-pnl { align-self: center; font-size: 17px; font-weight: 900; margin-top: -5px; }
    .cal-trades { align-self: center; font-size: 10px; font-weight: 600; opacity: 0.7; }
    
    .instruction-box {
        background-color: rgba(128, 128, 128, 0.05);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid rgba(128, 128, 128, 0.2);
        margin-bottom: 25px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- UTILITY FUNCTIONS ---
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
    if any(x in desc for x in [' CALL ', ' PUT ']):
        if trans == 'STO': return 'Covered Call'
        return 'Option'
    return 'Other'

def get_core_desc(row):
    desc = str(row['Description'])
    if row['Trans Code'] == 'OEXP':
        match = re.search(r'Option Expiration for (.*)', desc)
        if match: return match.group(1).strip()
    return desc.strip()

@st.cache_data(ttl=3600)
def fetch_dynamic_intel(ticker):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(ticker + ' stock options analysis')}"
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
    return f"[Analyze {ticker} Volatility](https://www.google.com/search?q={urllib.parse.quote(ticker + ' implied volatility')})"

# --- CORE PROCESSING ---
def process_robinhood_csv(uploaded_file):
    df = pd.read_csv(uploaded_file, on_bad_lines='skip')
    df['Activity Date'] = pd.to_datetime(df['Activity Date'])
    df['Amount_Clean'] = df['Amount'].apply(clean_amount)
    df['Quantity_Clean'] = df['Quantity'].apply(clean_quantity)
    df['Asset Type'] = df.apply(get_asset_type, axis=1)
    df['Core_Description'] = df.apply(get_core_desc, axis=1)

    trade_codes = ['BTO', 'STC', 'STO', 'BTC', 'OEXP']
    trades = df[df['Trans Code'].isin(trade_codes)].copy()
    trades = trades.sort_values(['Instrument', 'Core_Description', 'Activity Date'])

    summary_rows = []
    for (ticker, core_desc), group in trades.groupby(['Instrument', 'Core_Description']):
        buys = group[group['Trans Code'].isin(['BTO', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'STO', 'OEXP'])]
        net_change = group['Amount_Clean'].sum()
        buy_date = buys['Activity Date'].min() if not buys.empty else np.nan
        sell_date = sells['Activity Date'].max() if not sells.empty else np.nan
        status = 'Closed' if pd.notna(buy_date) and pd.notna(sell_date) else 'Open'

        summary_rows.append({
            'Ticker': ticker, 'Contract Description': core_desc, 
            '# Cons': buys['Quantity_Clean'].sum() if not buys.empty else sells['Quantity_Clean'].sum(),
            'Total Buy': abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum()),
            'Total Sell': sells[sells['Amount_Clean'] > 0]['Amount_Clean'].sum(),
            'Net Change': round(net_change, 2), 'Buy Date': buy_date, 'Sell Date': sell_date,
            'Asset Category': group['Asset Type'].iloc[0], 'Status': status
        })
    return pd.DataFrame(summary_rows)

def render_dashboard_view(df_subset, category_name):
    df_closed = df_subset[df_subset['Status'] == 'Closed'].copy()
    if df_closed.empty:
        st.info("No completed trades found.")
    else:
        # Metrics Calculations
        df_closed['Days Held'] = (df_closed['Sell Date'] - df_closed['Buy Date']).dt.days
        df_closed['Is_Call'] = df_closed['Contract Description'].str.contains('Call', case=False, na=False)
        total_pnl = df_closed['Net Change'].sum()
        wins = df_closed[df_closed['Net Change'] > 0]
        losses = df_closed[df_closed['Net Change'] < 0]
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Net P/L", f"${total_pnl:,.2f}")
        m2.metric("Win Rate", f"{(len(wins) / len(df_closed)) * 100:.1f}%")
        m3.metric("Avg Trade P/L", f"${total_pnl/len(df_closed):,.2f}")
        m4.metric("Trades Count", len(df_closed))

        st.markdown("---")

        # 1. PERFORMANCE ANALYTICS
        st.markdown("### 📊 Ticker Performance")
        ticker_stats = df_closed.groupby('Ticker').agg(
            Net_Profit=('Net Change', 'sum'),
            Avg_Win=('Net Change', lambda x: x[x > 0].mean() if not x[x > 0].empty else 0),
            Avg_Loss=('Net Change', lambda x: x[x < 0].mean() if not x[x < 0].empty else 0)
        ).fillna(0)

        p_col1, p_col2 = st.columns(2)
        with p_col1:
            st.subheader("🏆 Top 5 Winners")
            st.table(ticker_stats.sort_values(by='Net_Profit', ascending=False).head(5)[['Net_Profit', 'Avg_Win']].style.format("${:,.2f}"))
        with p_col2:
            st.subheader("📉 Bottom 5 Losers")
            st.table(ticker_stats.sort_values(by='Net_Profit', ascending=True).head(5)[['Net_Profit', 'Avg_Loss']].style.format("${:,.2f}"))

        st.markdown("---")

        # 2. RECOMMENDATIONS
        st.markdown("### 📡 Intelligence & Strategy")
        top_t = ticker_stats['Net_Profit'].idxmax()
        worst_t = ticker_stats['Net_Profit'].idxmin()
        intel_col1, intel_col2 = st.columns(2)
        with intel_col1:
            st.success(f"🔥 **Strength Lead:** {top_t}")
            st.write(f"News: {fetch_dynamic_intel(top_t)}")
        with intel_col2:
            st.error(f"⚠️ **Efficiency Gap:** {worst_t}")
            st.write(f"News: {fetch_dynamic_intel(worst_t)}")

        st.markdown("---")

        # 3. DEEP DIVE: PORTFOLIO INTELLIGENCE
        st.markdown(f"### 🔬 Deep Dive: {category_name} Intelligence")
        
        daily_perf = df_closed.groupby(df_closed['Buy Date'].dt.date)['Net Change'].sum()
        worst_day_val = daily_perf.min() if not daily_perf.empty else 0
        worst_day_date = daily_perf.idxmin().strftime('%m/%d/%Y') if not daily_perf.empty else "N/A"
        
        profit_factor = (wins['Net Change'].sum() / abs(losses['Net Change'].sum())) if not losses.empty else wins['Net Change'].sum()
        total_roi = (total_pnl / df_closed['Total Buy'].sum() * 100) if df_closed['Total Buy'].sum() > 0 else 0

        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            st.markdown("**Profitability Metrics**")
            st.write(f"🟢 **Avg $ Per Win:** ${wins['Net Change'].mean():,.2f}" if not wins.empty else "N/A")
            st.write(f"🔴 **Avg $ Per Loss:** ${losses['Net Change'].mean():,.2f}" if not losses.empty else "N/A")
            st.write(f"📊 **Profit Factor:** {profit_factor:.2f}")
        with d_col2:
            st.markdown("**Directional Totals**")
            st.write(f"🐂 **Total Calls $:** ${df_closed[df_closed['Is_Call']]['Net Change'].sum():,.2f}")
            st.write(f"🐻 **Total Puts $:** ${df_closed[~df_closed['Is_Call']]['Net Change'].sum():,.2f}")
            st.write(f"📈 **Total ROI %:** {total_roi:.1f}%")
        with d_col3:
            st.markdown("**Risk Intelligence**")
            st.write(f"💀 **Worst Trading Day:** ${worst_day_val:,.2f}")
            st.caption(f"Date: {worst_day_date}")
            st.write(f"⏱️ **Avg Days Held:** {df_closed['Days Held'].mean():.1f} Days")

        st.markdown("---")

        # 4. MONTHLY CALENDAR (SYMMETRICAL)
        st.markdown("### 📅 Monthly P&L Journal")
        df_closed['Month_Str'] = df_closed['Buy Date'].dt.strftime('%B %Y')
        selected_month = st.selectbox("Select Month", df_closed['Month_Str'].unique(), key=f"cal_{category_name}")
        
        cal_subset = df_closed[df_closed['Month_Str'] == selected_month].copy()
        daily_stats = cal_subset.groupby(cal_subset['Buy Date'].dt.day).agg(PNL=('Net Change', 'sum'), Count=('Net Change', 'count')).to_dict('index')
        
        first_date = cal_subset['Buy Date'].iloc[0]
        matrix = calendar.monthcalendar(first_date.year, first_date.month)
        cal_df = pd.DataFrame(matrix, columns=['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
        
        def format_cell(day):
            if day == 0: return ""
            stats = daily_stats.get(day, {'PNL': 0, 'Count': 0})
            pnl_str = f"${stats['PNL']:,.0f}" if stats['PNL'] != 0 else ""
            trade_str = f"{stats['Count']} Trades" if stats['Count'] > 0 else ""
            return f'<div class="cal-cell"><div class="cal-date">{day}</div><div class="cal-pnl">{pnl_str}</div><div class="cal-trades">{trade_str}</div></div>'

        styled_cal = cal_df.map(format_cell)
        
        def color_cells(val):
            if "$" not in val: return ''
            try:
                amt = float(re.search(r'\$(-?[\d,]+)', val).group(1).replace(',', ''))
                return f"background-color: {'rgba(40, 167, 69, 0.25)' if amt > 0 else 'rgba(220, 53, 69, 0.25)'};"
            except: return ''

        st.write(styled_cal.style.map(color_cells).to_html(escape=False), unsafe_allow_html=True)

    # --- 5. TRADE LOG (BOTTOM) ---
    st.markdown("---")
    st.subheader(f"📋 {category_name} Trade Log")
    csv = df_subset.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Log", data=csv, file_name=f"{category_name.lower()}_log.csv", mime="text/csv", key=f"dl_{category_name}")
    st.dataframe(df_subset, use_container_width=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood Dashboard", layout="wide", page_icon="📈")

# 🏷️ TITLE
st.header("🎯 Trade Intelligence Dashboard")

# Instructions
st.markdown("""
<div class="instruction-box">
    Go to <b><a href="https://robinhood.com/account/reports" target="_blank" style="color:#00d395">Robinhood Reports</a></b>, export <b>Account Activity</b> as CSV, and upload here.
</div>
""", unsafe_allow_html=True)

# Sidebar
st.sidebar.subheader("🔍 Search")
search_query = st.sidebar.text_input("Ticker Search", "").strip().upper()
st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    df_raw = df_raw[df_raw['Asset Category'] != 'Other']
    if search_query:
        df_raw = df_raw[df_raw['Ticker'].str.contains(search_query, na=False)]
    
    st.sidebar.metric("Open Positions", len(df_raw[df_raw['Status'] == 'Open']))
    st.sidebar.markdown("---")
    st.sidebar.markdown("👨‍💻 **Puneeth Rao**")
    st.sidebar.markdown("[🔗 LinkedIn Profile](https://www.linkedin.com/in/puneeth-rao-9154b511/)")

    t1, t2, t3 = st.tabs(["Portfolio Overview", "Options", "Covered Calls"])
    with t1: render_dashboard_view(df_raw, "Portfolio")
    with t2: render_dashboard_view(df_raw[df_raw['Asset Category'] == 'Option'], "Options")
    with t3: render_dashboard_view(df_raw[df_raw['Asset Category'] == 'Covered Call'], "Covered Calls")
