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

# --- CSS FOR SYMMETRY AND STYLE ---
st.markdown("""
    <style>
    .stTable { width: 100%; }
    th { text-align: center !important; background-color: #f0f2f6; font-weight: bold; }
    td { text-align: center !important; height: 60px; vertical-align: middle !important; font-size: 14px; }
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
    if any(x in desc for x in [' CALL ', ' PUT ', ' CALL $', ' PUT $']):
        return 'Option'
    return 'Stock'

def get_core_desc(row):
    desc = str(row['Description'])
    if row['Trans Code'] == 'OEXP':
        match = re.search(r'Option Expiration for (.*)', desc)
        if match: return match.group(1).strip()
    return desc.strip()

@st.cache_data(ttl=3600)
def fetch_dynamic_intel(ticker):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(ticker + ' options market')}"
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

    trade_codes = ['BTO', 'STC', 'STO', 'BTC', 'Buy', 'Sell', 'OEXP']
    trades = df[df['Trans Code'].isin(trade_codes)].copy()
    trades = trades.sort_values(['Instrument', 'Core_Description', 'Activity Date'])

    summary_rows = []
    for (ticker, core_desc), group in trades.groupby(['Instrument', 'Core_Description']):
        buys = group[group['Trans Code'].isin(['BTO', 'Buy', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'Sell', 'STO', 'OEXP'])]
        
        total_buy_qty = buys['Quantity_Clean'].sum()
        total_buy_amt = abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum())
        total_sell_amt = sells[sells['Amount_Clean'] > 0]['Amount_Clean'].sum()
        
        net_change = group['Amount_Clean'].sum()
        buy_date = buys['Activity Date'].min() if not buys.empty else np.nan
        sell_date = sells['Activity Date'].max() if not sells.empty else np.nan
        status = 'Closed' if pd.notna(buy_date) and pd.notna(sell_date) else 'Open'

        summary_rows.append({
            'Ticker': ticker, 'Contract Description': core_desc, '# Cons': total_buy_qty if total_buy_qty > 0 else sells['Quantity_Clean'].sum(),
            'Total Buy': round(total_buy_amt, 2), 'Total Sell': round(total_sell_amt, 2),
            'Net Change': round(net_change, 2), 'Buy Date': buy_date, 'Sell Date': sell_date,
            'Asset Category': group['Asset Type'].iloc[0], 'Status': status
        })
    return pd.DataFrame(summary_rows)

def render_dashboard_view(df_subset, category_name):
    df_closed = df_subset[df_subset['Status'] == 'Closed'].copy()
    if df_closed.empty:
        st.info("No completed trades found.")
        return

    df_closed['Days Held'] = (df_closed['Sell Date'] - df_closed['Buy Date']).dt.days
    df_closed['Is_Call'] = df_closed['Contract Description'].str.contains('Call', case=False, na=False)
    
    total_pnl = df_closed['Net Change'].sum()
    win_rate = (len(df_closed[df_closed['Net Change'] > 0]) / len(df_closed)) * 100
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net P/L", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Avg Trade P/L", f"${total_pnl/len(df_closed):,.2f}")
    col4.metric("Total Trades", len(df_closed))
    
    st.markdown("---")
    
    # --- PERFORMANCE ANALYTICS: TOP/BOTTOM 5 ---
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

    # --- DYNAMIC RECOMMENDATIONS & INTEL ---
    st.markdown("### 💡 Dynamic Options Intelligence")
    top_ticker = ticker_stats['Net_Profit'].idxmax()
    worst_ticker = ticker_stats['Net_Profit'].idxmin()
    call_pnl = df_closed[df_closed['Is_Call']]['Net Change'].sum()
    put_pnl = df_closed[~df_closed['Is_Call']]['Net Change'].sum()

    rec_col1, rec_col2 = st.columns(2)
    with rec_col1:
        st.success(f"🔥 **Strength Lead:** {top_ticker}")
        st.write(f"Latest Intel: {fetch_dynamic_intel(top_ticker)}")
        bias = "Calls" if call_pnl > put_pnl else "Puts"
        st.write(f"**Strategy Note:** Your data suggests a profitable bias toward **{bias}**.")
    with rec_col2:
        st.error(f"⚠️ **Efficiency Gap:** {worst_ticker}")
        st.write(f"Market Context: {fetch_dynamic_intel(worst_ticker)}")
        st.write(f"**Risk Note:** High frequency of losses in {worst_ticker} may indicate a need to adjust strike selection.")

    st.markdown("---")

    # --- MONTHLY CALENDAR ---
    st.markdown("### 📅 Monthly P&L Journal")
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
        return f"background-color: {'#d4edda' if amt > 0 else '#f8d7da'}; font-weight: bold; text-align: center;"
    st.table(styled_cal.style.map(color_pnl))

# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood Dashboard", layout="wide", page_icon="📈")
st.title("📈 Interactive Robinhood Options Dashboard")

st.sidebar.title("📊 Account Insights")
st.sidebar.markdown("[🔗 View My LinkedIn Profile](https://www.linkedin.com/in/puneeth-rao-9154b511/)")
search_query = st.sidebar.text_input("🔍 Search Ticker or Contract", "").strip().upper()
st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    if search_query:
        df_raw = df_raw[df_raw['Ticker'].str.contains(search_query, na=False) | df_raw['Contract Description'].str.contains(search_query, na=False)]
    
    st.sidebar.metric("Active Options Contracts", len(df_raw[df_raw['Status'] == 'Open']))
    st.sidebar.markdown("👨‍💻 **Puneeth Rao**")

    df_options = df_raw[df_raw['Asset Category'] == 'Option']
    render_dashboard_view(df_options, "Options")
