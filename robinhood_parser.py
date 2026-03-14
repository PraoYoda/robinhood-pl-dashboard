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
st.markdown("""
    <style>
    .stTable { width: 100%; }
    th { text-align: center !important; background-color: #f0f2f6; font-weight: bold; }
    td { text-align: center !important; width: 14.28%; height: 70px; vertical-align: middle !important; font-size: 14px; }
    </style>
    """, unsafe_allow_html=True)

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
            'Ticker': ticker, 'Contract Description': core_desc, '# Cons/Shares': total_buy_qty if total_buy_qty > 0 else sells['Quantity_Clean'].sum(),
            'Avg Buy': round(total_buy_amt / total_buy_qty, 2) if total_buy_qty > 0 else 0,
            'Total Buy': round(total_buy_amt, 2), 'Avg Sell': round(total_sell_amt / sells['Quantity_Clean'].sum(), 2) if not sells.empty and sells['Quantity_Clean'].sum() > 0 else 0,
            'Total Sell': round(total_sell_amt, 2), '% Change': round(net_change / total_buy_amt, 4) if total_buy_amt > 0 else 0,
            'Net Change': round(net_change, 2), 'Buy Date': buy_date, 'Sell Date': sell_date, 'Let Exp?': 'Yes' if any(group['Trans Code'] == 'OEXP') else 'No',
            'Asset Category': group['Asset Type'].iloc[0], 'Status': status
        })
    return pd.DataFrame(summary_rows)

def render_dashboard_view(df_subset, category_name):
    df_closed = df_subset[df_subset['Status'] == 'Closed'].copy()
    if df_closed.empty:
        st.info(f"No completed trades available for {category_name}.")
        return

    # Metadata Calculations
    df_closed['Days Held'] = (df_closed['Sell Date'] - df_closed['Buy Date']).dt.days
    df_closed['Buy DoW'] = df_closed['Buy Date'].dt.day_name()
    df_closed['Is_Put'] = df_closed['Contract Description'].str.contains('Put', case=False, na=False)
    df_closed['Is_Call'] = df_closed['Contract Description'].str.contains('Call', case=False, na=False)
    df_closed['Trade Style'] = np.where(df_closed['Days Held'] == 0, 'Day Trade', 'Swing Trade')

    # Main Metrics
    total_pnl = df_closed['Net Change'].sum()
    winners = df_closed[df_closed['Net Change'] > 0]
    win_rate = (len(winners) / len(df_closed)) * 100
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net Profit/Loss", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Avg ROI", f"{(total_pnl / df_closed['Total Buy'].sum() * 100) if df_closed['Total Buy'].sum() > 0 else 0:.1f}%")
    col4.metric("Total Trades", len(df_closed))
    
    st.markdown("---")
    
    # REINSTATED DEEP DIVE ANALYTICS
    st.markdown(f"### 🔬 Deep Dive: {category_name} Analytics")
    ana_col1, ana_col2, ana_col3 = st.columns(3)
    with ana_col1:
        st.markdown("**Trade Style Performance**")
        st.write(f"📈 **Swing:** ${df_closed[df_closed['Trade Style'] == 'Swing Trade']['Net Change'].sum():,.2f}")
        st.write(f"⚡ **Day:** ${df_closed[df_closed['Trade Style'] == 'Day Trade']['Net Change'].sum():,.2f}")
    with ana_col2:
        st.markdown("**Call vs. Put Focus**")
        st.write(f"🐂 **Calls Net:** ${df_closed[df_closed['Is_Call']]['Net Change'].sum():,.2f}")
        st.write(f"🐻 **Puts Net:** ${df_closed[df_closed['Is_Put']]['Net Change'].sum():,.2f}")
    with ana_col3:
        st.markdown("**Entry Day of Week**")
        dow_stats = df_closed.groupby('Buy DoW')['Net Change'].sum()
        st.write(f"✅ **Best:** {dow_stats.idxmax()} (${dow_stats.max():,.0f})")
        st.write(f"❌ **Worst:** {dow_stats.idxmin()} (${dow_stats.min():,.0f})")

    st.markdown("---")
    st.markdown("### 🧠 Trade Behavior & Efficiency")
    avg_win = winners['Net Change'].mean() if not winners.empty else 0
    losers = df_closed[df_closed['Net Change'] < 0]
    avg_loss = losers['Net Change'].mean() if not losers.empty else 0
    st.metric("⚖️ Avg Win vs. Avg Loss", f"${avg_win:,.0f} / ${abs(avg_loss):,.0f}", f"Ratio: {abs(avg_win/avg_loss) if avg_loss != 0 else 0:.2f}x")

    st.markdown("---")
    st.markdown(f"### 📅 {category_name} - Monthly Calendar")
    df_closed['Month_Sort'] = df_closed['Buy Date'].dt.to_period('M')
    df_closed['Month_Str'] = df_closed['Buy Date'].dt.strftime('%B %Y')
    
    month_options = df_closed.sort_values('Month_Sort')['Month_Str'].unique().tolist()
    selected_month = st.selectbox("Select Month", month_options, key=f"cal_{category_name}")
    
    cal_data = df_closed[df_closed['Month_Str'] == selected_month].copy()
    daily_pnl = cal_data.groupby(cal_data['Buy Date'].dt.day)['Net Change'].sum().to_dict()
    year, month_idx = cal_data['Buy Date'].iloc[0].year, cal_data['Buy Date'].iloc[0].month
    matrix = calendar.monthcalendar(int(year), int(month_idx))
    cal_df = pd.DataFrame(matrix, columns=['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
    
    styled_cal = cal_df.map(lambda d: f"{d}\n${daily_pnl.get(d, 0):,.0f}" if d != 0 and daily_pnl.get(d, 0) != 0 else (str(d) if d != 0 else ""))
    
    def color_pnl(val):
        if "$" not in str(val): return 'text-align: center;'
        amt = float(val.split('$')[1].replace(',', ''))
        color = '#d4edda' if amt > 0 else '#f8d7da'
        return f'background-color: {color}; font-weight: bold; text-align: center;'

    st.table(styled_cal.style.map(color_pnl))
    
    st.markdown("---")
    st.markdown(f"### 📋 Trade Details")
    display_df = df_subset.copy()
    display_df['Buy Date'] = display_df['Buy Date'].dt.strftime('%m/%d/%Y')
    display_df['Sell Date'] = display_df['Sell Date'].dt.strftime('%m/%d/%Y').replace('NaT', 'OPEN')
    st.dataframe(display_df.drop(columns=['Month_Sort', 'Month_Str'], errors='ignore'), use_container_width=True)

# --- APP START ---
st.set_page_config(page_title="Robinhood Dashboard", layout="wide")
st.sidebar.title("📊 Account Insights")
st.sidebar.info("This interactive dashboard summarizes your Robinhood options and covered calls history.")
st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    open_ops = df_raw[(df_raw['Status'] == 'Open') & (df_raw['Asset Category'].isin(['Option', 'Covered Call']))]
    st.sidebar.metric("Open Position Count", len(open_ops))
    st.sidebar.metric("Open Options Equity", f"${open_ops['Total Buy'].sum():,.2f}")
    st.sidebar.markdown("---")
    st.sidebar.markdown("👨‍💻 **Puneeth Rao**")

    df_final = df_raw[df_raw['Asset Category'].isin(['Option', 'Covered Call'])]
    categories = ["All Data"] + sorted(df_final['Asset Category'].unique().tolist())
    tabs = st.tabs(categories)
    for i, tab in enumerate(tabs):
        with tab:
            render_dashboard_view(df_final if categories[i] == "All Data" else df_final[df_final['Asset Category'] == categories[i]], categories[i])
