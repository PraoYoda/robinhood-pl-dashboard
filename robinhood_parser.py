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

# --- 1. CORE UTILITIES (PRESERVED FROM REVERTED VERSION) ---
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
    return f"[Click here to search trending articles for '{query}'](https://www.google.com/search?q={urllib.parse.quote(query)})"

# --- 2. THE SUNDAY-START CALENDAR ENGINE (IMAGE MATCHED) ---
def render_calendar_grid(df_subset, selected_month_str):
    dt_obj = datetime.strptime(selected_month_str, '%B %Y')
    year, month = dt_obj.year, dt_obj.month
    
    # Prep Daily P&L for the selected month
    df_subset['Date_Only'] = pd.to_datetime(df_subset['Sell Date']).dt.date
    daily_pnl = df_subset.groupby('Date_Only')['Net Change'].sum().to_dict()

    # Sunday-Start Logic
    cal_obj = calendar.Calendar(firstweekday=6)
    weeks = cal_obj.monthdayscalendar(year, month)
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    
    # CSS for the Square Card Look
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
        cols[i].markdown(f"<p style='text-align:center;font-weight:bold;margin-bottom:10px;'>{d}</p>", unsafe_allow_html=True)

    for week in weeks:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0: 
                cols[i].markdown("<div></div>", unsafe_allow_html=True)
            else:
                curr_date = datetime(year, month, day).date()
                pnl = daily_pnl.get(curr_date, 0)
                
                style_class = "neu"
                pnl_text = ""
                if pnl > 0: 
                    style_class = "pos"
                    pnl_text = f"+${pnl:,.0f}"
                elif pnl < 0: 
                    style_class = "neg"
                    pnl_text = f"-${abs(pnl):,.0f}"
                
                cols[i].markdown(f"""
                    <div class='cal-day {style_class}'>
                        <div class='day-num'>{day}</div>
                        <div class='day-pnl'>{pnl_text}</div>
                    </div>
                """, unsafe_allow_html=True)

# --- 3. THE RENDER DASHBOARD (MERGED ANALYTICS) ---
def render_dashboard_view(df_subset, category_name):
    if df_subset.empty:
        st.info(f"No completed trades available for {category_name}.")
        return

    # Basic Metrics Setup
    df_subset['Days Held'] = pd.to_numeric(df_subset['Days Held'], errors='coerce')
    df_subset['Buy DoW'] = pd.to_datetime(df_subset['Buy Date']).dt.day_name()
    df_subset['Is_Put'] = df_subset['Contract Description'].str.contains('Put', case=False, na=False)
    df_subset['Is_Call'] = df_subset['Contract Description'].str.contains('Call', case=False, na=False)
    df_subset['Trade Style'] = np.where(df_subset['Days Held'] == 0, 'Day Trade', 'Swing Trade')

    total_pnl = df_subset['Net Change'].sum()
    total_trades = len(df_subset)
    winners, losers = df_subset[df_subset['Net Change'] > 0], df_subset[df_subset['Net Change'] < 0]
    win_rate = (len(winners) / (len(winners) + len(losers))) * 100 if (len(winners) + len(losers)) > 0 else 0
    total_cost_basis = df_subset['Total Buy'].sum()
    overall_roi = (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0
    
    # Top KPI Row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net Profit/Loss", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Avg Trade ROI", f"{overall_roi:.1f}%")
    col4.metric("Total Trades", total_trades)
    
    st.markdown("---")

    # Deep Dive Analytics Section
    st.markdown(f"### 🔬 Deep Dive: {category_name} Analytics")
    ana_col1, ana_col2, ana_col3 = st.columns(3)
    dt_df, sw_df = df_subset[df_subset['Trade Style'] == 'Day Trade'], df_subset[df_subset['Trade Style'] == 'Swing Trade']
    
    with ana_col1:
        st.markdown("**Trade Style Performance**")
        st.write(f"📈 **Swing Trades (>0 Days):** ${sw_df['Net Change'].sum():,.2f}")
        st.write(f"⚡ **Day Trades (0 Days):** ${dt_df['Net Change'].sum():,.2f}")
    with ana_col2:
        st.markdown("**Call vs. Put Focus**")
        st.write(f"🐂 **Calls Net P&L:** ${df_subset[df_subset['Is_Call']]['Net Change'].sum():,.2f}")
        st.write(f"🐻 **Puts Net P&L:** ${df_subset[df_subset['Is_Put']]['Net Change'].sum():,.2f}")
    
    dow_stats = df_subset.groupby('Buy DoW').agg(Net_Profit=('Net Change', 'sum')).reset_index()
    if not dow_stats.empty:
        with ana_col3:
            st.markdown("**Entry Day Analysis**")
            st.write(f"✅ **Best Entry:** {dow_stats.loc[dow_stats['Net_Profit'].idxmax()]['Buy DoW']}")
            st.write(f"❌ **Worst Entry:** {dow_stats.loc[dow_stats['Net_Profit'].idxmin()]['Buy DoW']}")

    # --- MONTHLY SUMMARY & CALENDAR (ASCENDING) ---
    st.markdown("---")
    df_temp = df_subset.copy()
    df_temp['Month_Date'] = pd.to_datetime(df_temp['Sell Date'], errors='coerce').fillna(pd.to_datetime(df_temp['Buy Date'], errors='coerce'))
    valid_dates = df_temp.dropna(subset=['Month_Date']).copy()
    
    if not valid_dates.empty:
        valid_dates['Month'] = valid_dates['Month_Date'].dt.strftime('%B %Y')
        valid_dates['Month_Sort'] = valid_dates['Month_Date'].dt.to_period('M')
        
        # Monthly Summary Table - Sorted Ascending
        monthly_summary = valid_dates.groupby(['Month_Sort', 'Month']).agg(
            Total_Trades=('Ticker', 'count'), Wins=('Net Change', lambda x: (x > 0).sum()),
            Losses=('Net Change', lambda x: (x < 0).sum()), Net_Profit=('Net Change', 'sum'),
            Unique_Tickers=('Ticker', 'nunique'), Puts=('Is_Put', 'sum'), Calls=('Is_Call', 'sum')
        ).reset_index().sort_values('Month_Sort', ascending=True)

        st.markdown(f"### 📅 {category_name} - Monthly Summary")
        st.dataframe(monthly_summary.drop(columns=['Month_Sort']).rename(columns={'Wins': 'Profit Trades', 'Losses': 'Loss Trades', 'Net_Profit': 'Total P&L', 'Unique_Tickers': 'Tickers'}), width='stretch')

        st.markdown("---")
        st.markdown(f"### 🗓️ {category_name} - Daily Profit/Loss Grid")
        
        # Calendar Selectbox - Sorted Ascending
        month_list = monthly_summary['Month'].tolist()
        selected_month = st.selectbox(f"Select Month for {category_name} Audit", month_list, key=f"sel_{category_name}")
        render_calendar_grid(df_subset, selected_month)

    # Behavioral Recommendations
    if category_name != "Covered Call":
        st.markdown("---")
        st.markdown("### 🛠️ Actionable Recommendations")
        avg_loss = abs(losers['Net Change'].mean()) if not losers.empty else 0
        if avg_loss > 0:
            st.warning(f"🚨 **Risk Tip:** Your average loss is ${avg_loss:,.2f}. {fetch_dynamic_article('options stop loss strategy')}")

    st.markdown("---")
    st.markdown(f"### 📋 {category_name} - Trade Details Audit Log")
    st.dataframe(df_subset.drop(columns=['Is_Put', 'Is_Call', 'Trade Style', 'Buy DoW'], errors='ignore'), width='stretch')

# --- 4. DATA PROCESSING & MAIN ---
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
        asset_types = group['Asset Type'].unique()
        final_type = 'Stock'
        if 'Covered Call' in asset_types: final_type = 'Covered Call'
        elif 'Option' in asset_types: final_type = 'Option'
        
        buys = group[group['Trans Code'].isin(['BTO', 'Buy', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'Sell', 'STO', 'OEXP', 'CDIV'])]
        
        total_buy_qty, total_buy_amt = buys['Quantity_Clean'].sum(), abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum())
        total_sell_amt = sells[sells['Amount_Clean'] > 0]['Amount_Clean'].sum()
        net_change = group['Amount_Clean'].sum()
        buy_date, sell_date = buys['Activity Date'].min(), sells['Activity Date'].max()
        
        summary_rows.append({
            'Ticker': ticker, 'Contract Description': core_desc, '# Cons/Shares': total_buy_qty if total_buy_qty > 0 else 0,
            'Total Buy': round(total_buy_amt, 2), 'Total Sell': round(total_sell_amt, 2),
            'Net Change': round(net_change, 2),
            'Buy Date': buy_date.strftime('%m/%d/%Y') if pd.notna(buy_date) else None,
            'Sell Date': sell_date.strftime('%m/%d/%Y') if pd.notna(sell_date) else None,
            'Days Held': (sell_date - buy_date).days if pd.notna(sell_date) and pd.notna(buy_date) else None,
            'Asset Category': final_type, 'Status': 'Closed' if pd.notna(buy_date) and pd.notna(sell_date) else 'Open'
        })
    return pd.DataFrame(summary_rows)

st.set_page_config(page_title="Robinhood Mastery", layout="wide")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [LinkedIn Profile](https://www.linkedin.com/in/puneeth-rao/)")
st.title("📈 Interactive Robinhood P&L Dashboard")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_res = process_robinhood_csv(uploaded_file)
    df_res = df_res[df_res['Asset Category'].isin(['Option', 'Covered Call'])]
    t_names = ["All Data"] + sorted(df_res['Asset Category'].unique().tolist())
    tabs = st.tabs(t_names)
    for i, tab in enumerate(tabs):
        with tab: render_dashboard_view(df_res if t_names[i] == "All Data" else df_res[df_res['Asset Category'] == t_names[i]], t_names[i])
