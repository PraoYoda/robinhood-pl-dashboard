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

# --- CSS FOR DARK MODE COMPATIBILITY & SYMMETRY ---
st.markdown("""
    <style>
    .stTable { 
        width: 100%; 
        border-radius: 10px; 
        overflow: hidden; 
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    th { 
        text-align: center !important; 
        background-color: rgba(128, 128, 128, 0.1) !important; 
        color: inherit !important;
        font-weight: bold; 
        padding: 10px !important;
    }
    td { 
        text-align: center !important; 
        height: 65px; 
        vertical-align: middle !important; 
        font-size: 14px; 
        border-bottom: 1px solid rgba(128, 128, 128, 0.1) !important;
    }
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
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
        # Calculations
        df_closed['Days Held'] = (df_closed['Sell Date'] - df_closed['Buy Date']).dt.days
        df_closed['Trade Style'] = np.where(df_closed['Days Held'] == 0, 'Day Trade', 'Swing Trade')
        df_closed['Is_Call'] = df_closed['Contract Description'].str.contains('Call', case=False, na=False)
        df_closed['Buy DoW'] = df_closed['Buy Date'].dt.day_name()
        total_pnl = df_closed['Net Change'].sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Net P/L", f"${total_pnl:,.2f}")
        m2.metric("Win Rate", f"{(len(df_closed[df_closed['Net Change'] > 0]) / len(df_closed)) * 100:.1f}%")
        m3.metric("Avg Trade P/L", f"${total_pnl/len(df_closed):,.2f}")
        m4.metric("Trades Count", len(df_closed))

        st.markdown("---")

        # 1. PERFORMANCE ANALYTICS
        st.markdown("### 📊 Performance Analytics")
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

        # 2. MARKET INTELLIGENCE
        st.markdown("### 📡 Market Intelligence & Strategy")
        top_t = ticker_stats['Net_Profit'].idxmax()
        worst_t = ticker_stats['Net_Profit'].idxmin()
        call_perf = df_closed[df_closed['Is_Call']]['Net Change'].sum()
        put_perf = df_closed[~df_closed['Is_Call']]['Net Change'].sum()
        
        intel_col1, intel_col2 = st.columns(2)
        with intel_col1:
            st.success(f"🔥 **Strength Lead:** {top_t}")
            st.write(f"News: {fetch_dynamic_intel(top_t)}")
            bias = "Calls" if call_perf > put_perf else "Puts"
            st.write(f"**Strategy:** Edge detected in **{bias}**.")
        with intel_col2:
            st.error(f"⚠️ **Efficiency Gap:** {worst_t}")
            st.write(f"News: {fetch_dynamic_intel(worst_t)}")
            st.write(f"**Risk:** Review strikes on {worst_t} to preserve alpha.")

        st.markdown("---")

        # 3. DEEP DIVE
        st.markdown(f"### 🔬 Deep Dive: {category_name} Intelligence")
        ana_col1, ana_col2, ana_col3 = st.columns(3)
        with ana_col1:
            st.markdown("**Style Performance**")
            st.write(f"📈 **Swing Net:** ${df_closed[df_closed['Trade Style'] == 'Swing Trade']['Net Change'].sum():,.2f}")
            st.write(f"⚡ **Day Net:** ${df_closed[df_closed['Trade Style'] == 'Day Trade']['Net Change'].sum():,.2f}")
        with ana_col2:
            st.markdown("**Directional Bias**")
            st.write(f"🐂 **Calls Net:** ${call_perf:,.2f}")
            st.write(f"🐻 **Puts Net:** ${put_perf:,.2f}")
        with ana_col3:
            st.markdown("**Efficiency**")
            dow = df_closed.groupby('Buy DoW')['Net Change'].sum()
            st.write(f"✅ **Best Day:** {dow.idxmax() if not dow.empty else 'N/A'}")
            st.write(f"⏱️ **Avg Days Held:** {df_closed['Days Held'].mean():.1f} Days")

        st.markdown("---")

        # 4. MONTHLY CALENDAR
        st.markdown("### 📅 Monthly Journal")
        df_closed['Month_Str'] = df_closed['Buy Date'].dt.strftime('%B %Y')
        selected_month = st.selectbox("Select Month", df_closed['Month_Str'].unique(), key=f"cal_{category_name}")
        cal_data = df_closed[df_closed['Month_Str'] == selected_month].copy()
        daily_pnl = cal_data.groupby(cal_data['Buy Date'].dt.day)['Net Change'].sum().to_dict()
        year, month_idx = cal_data['Buy Date'].iloc[0].year, cal_data['Buy Date'].iloc[0].month
        matrix = calendar.monthcalendar(int(year), int(month_idx))
        cal_df = pd.DataFrame(matrix, columns=['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
        styled_cal = cal_df.map(lambda d: f"{d}\n${daily_pnl.get(d, 0):,.0f}" if d != 0 and daily_pnl.get(d, 0) != 0 else (str(d) if d != 0 else ""))
        
        def color_pnl(val):
            if "$" not in str(val): return 'text-align: center;'
            amt = float(val.split('$')[1].replace(',', ''))
            color = 'rgba(40, 167, 69, 0.3)' if amt > 0 else 'rgba(220, 53, 69, 0.3)'
            return f"background-color: {color}; font-weight: bold; text-align: center;"
        st.table(styled_cal.style.map(color_pnl))

    # --- 5. TRADE LOG (BOTTOM) ---
    st.markdown("---")
    st.subheader(f"📋 {category_name} Trade Log")
    csv = df_subset.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download View as CSV", data=csv, file_name=f"{category_name.lower()}_log.csv", mime="text/csv", key=f"dl_{category_name}")
    
    display_df = df_subset.copy()
    display_df['Buy Date'] = display_df['Buy Date'].dt.strftime('%m/%d/%Y')
    display_df['Sell Date'] = display_df['Sell Date'].dt.strftime('%m/%d/%Y').replace('NaT', 'OPEN')
    st.dataframe(display_df, use_container_width=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood Dashboard", layout="wide", page_icon="📈")
st.title("📈 Interactive Robinhood Options Dashboard")

# --- TOP SECTION: DATA DOWNLOAD INSTRUCTIONS ---
with st.container():
    st.markdown("""
    <div class="instruction-box">
        <h3>📥 How to get your Robinhood CSV Data</h3>
        <p>Follow these steps to export your history for analysis:</p>
        <ol>
            <li>Go to the direct <b><a href="https://robinhood.com/account/reports" target="_blank">Robinhood Reports Portal</a></b> on your desktop.</li>
            <li>Look for the <b>Account History</b> or <b>Custom Account Activity</b> section.</li>
            <li>Select <b>Export as CSV</b> (make sure it's the <u>Activity Report</u>, not just a PDF statement).</li>
            <li>Choose your desired date range and click <b>Generate Report</b>.</li>
            <li>Once ready, download the file and upload it below.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)

# --- SIDEBAR ---
st.sidebar.subheader("🎯 Trade Edge Intelligence")
st.sidebar.info("Analyze behavioral edge and directional bias to refine your income path.")
st.sidebar.markdown("---")

search_query = st.sidebar.text_input("🔍 Search Ticker or Contract", "").strip().upper()
st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    df_raw = df_raw[df_raw['Asset Category'] != 'Other']
    
    if search_query:
        df_raw = df_raw[df_raw['Ticker'].str.contains(search_query, na=False) | 
                        df_raw['Contract Description'].str.contains(search_query, na=False)]
    
    st.sidebar.metric("Open Positions", len(df_raw[df_raw['Status'] == 'Open']))
    
    st.sidebar.markdown("### ⚡ Trade Confidence")
    df_c = df_raw[df_raw['Status'] == 'Closed'].copy()
    if not df_c.empty:
        df_c['Days Held'] = (df_c['Sell Date'] - df_c['Buy Date']).dt.days
        day_t = df_c[df_c['Days Held'] == 0]
        swing_t = df_c[df_c['Days Held'] > 0]
        st.sidebar.write(f"**Day Trade Win Rate:** {(len(day_t[day_t['Net Change'] > 0]) / len(day_t) * 100) if not day_t.empty else 0:.1f}%")
        st.sidebar.write(f"**Swing Trade Win Rate:** {(len(swing_t[swing_t['Net Change'] > 0]) / len(swing_t) * 100) if not swing_t.empty else 0:.1f}%")

st.sidebar.markdown("---")
st.sidebar.markdown("👨‍💻 **Puneeth Rao**")
st.sidebar.markdown("[🔗 LinkedIn Profile](https://www.linkedin.com/in/puneeth-rao-9154b511/)")

if uploaded_file:
    t1, t2, t3 = st.tabs(["All Portfolio", "Options Only", "Covered Calls Only"])
    with t1: render_dashboard_view(df_raw, "Portfolio")
    with t2: render_dashboard_view(df_raw[df_raw['Asset Category'] == 'Option'], "Options")
    with t3: render_dashboard_view(df_raw[df_raw['Asset Category'] == 'Covered Call'], "Covered Calls")
