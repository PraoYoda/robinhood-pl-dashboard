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

# --- CSS FOR CALENDAR (SCOPED) & TOOLTIPS ---
st.markdown("""
    <style>
    /* SCOPED CALENDAR STYLING - Won't break other tables */
    .cal-table { 
        width: 100%; 
        border-radius: 10px; 
        overflow: hidden; 
        border: 1px solid rgba(128, 128, 128, 0.2);
        table-layout: fixed; 
        border-collapse: collapse;
    }
    .cal-table th { 
        text-align: center !important; 
        background-color: rgba(128, 128, 128, 0.1) !important; 
        color: inherit !important;
        font-weight: bold; 
        padding: 10px !important;
        width: 14.28%; 
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .cal-table td { 
        text-align: center !important; 
        height: 100px; 
        vertical-align: middle !important; 
        border: 1px solid rgba(128, 128, 128, 0.1);
        width: 14.28%;
        padding: 0;
    }
    .cal-cell {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 100px;
        padding: 5px;
    }
    .cal-date { align-self: flex-start; font-weight: bold; font-size: 13px; opacity: 0.5; }
    .cal-pnl { align-self: center; font-size: 18px; font-weight: 900; }
    .cal-trades { align-self: center; font-size: 11px; font-weight: 600; opacity: 0.7; }
    
    .instruction-box {
        background-color: rgba(128, 128, 128, 0.05);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid rgba(128, 128, 128, 0.2);
        margin-bottom: 25px;
    }
    .metric-hover {
        cursor: help;
        border-bottom: 1px dotted rgba(128, 128, 128, 0.5);
        display: inline-block;
        margin-bottom: 8px;
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

        # 1. TICKER PERFORMANCE (NATIVE ST.DATAFRAME FOR AUTO ROW HEIGHT)
        st.markdown("### 📊 Ticker Edge Intelligence")
        ticker_stats = df_closed.groupby('Ticker').agg(
            Net_Profit=('Net Change', 'sum'),
            Total_Trades=('Net Change', 'count'),
            Wins=('Net Change', lambda x: (x > 0).sum()),
            Avg_Win=('Net Change', lambda x: x[x > 0].mean() if not x[x > 0].empty else 0),
            Avg_Loss=('Net Change', lambda x: x[x < 0].mean() if not x[x < 0].empty else 0)
        ).fillna(0)
        
        ticker_stats['Win_Rate'] = ticker_stats['Wins'] / ticker_stats['Total_Trades']
        ticker_stats['Expectancy'] = (ticker_stats['Win_Rate'] * ticker_stats['Avg_Win']) + ((1 - ticker_stats['Win_Rate']) * ticker_stats['Avg_Loss'])

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.subheader("🏆 Top 5 by Expectancy")
            st.markdown("*Ranked by mathematical edge per trade.*")
            top_5 = ticker_stats.sort_values(by='Expectancy', ascending=False).head(5)[['Expectancy', 'Net_Profit']]
            st.dataframe(top_5.style.format("${:,.2f}"), use_container_width=True)
        with col_t2:
            st.subheader("📉 Bottom 5 by Expectancy")
            st.markdown("*Tickers where the math is working against you.*")
            bot_5 = ticker_stats.sort_values(by='Expectancy', ascending=True).head(5)[['Expectancy', 'Net_Profit']]
            bot_5 = bot_5.rename(columns={'Net_Profit': 'Net Loss'}) # RENAMED HERE
            st.dataframe(bot_5.style.format("${:,.2f}"), use_container_width=True)

        st.markdown("---")

        # 2. DEEP DIVE: PORTFOLIO INTELLIGENCE
        st.markdown("### 🔬 Portfolio Intelligence")
        
        daily_perf = df_closed.groupby(df_closed['Buy Date'].dt.date)['Net Change'].sum()
        worst_day_val = daily_perf.min() if not daily_perf.empty else 0
        worst_day_date = daily_perf.idxmin().strftime('%m/%d/%Y') if not daily_perf.empty else "N/A"
        profit_factor = wins['Net Change'].sum() / abs(losses['Net Change'].sum()) if not losses.empty else 0
        total_roi = (total_pnl / df_closed['Total Buy'].sum() * 100) if df_closed['Total Buy'].sum() > 0 else 0
        
        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            st.markdown("**Profitability Metrics**")
            st.markdown(f'<div class="metric-hover" title="The average dollar amount gained on every winning trade.">🟢 <b>Avg $ Win:</b> ${wins["Net Change"].mean() if not wins.empty else 0:,.2f}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-hover" title="The average dollar amount lost on every losing trade.">🔴 <b>Avg $ Loss:</b> ${losses["Net Change"].mean() if not losses.empty else 0:,.2f}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-hover" title="Ratio of gross profit to gross loss. Above 1.5 indicates a strong statistical edge.">📊 <b>Profit Factor:</b> {profit_factor:.2f}</div>', unsafe_allow_html=True)
        with d_col2:
            st.markdown("**Directional Totals**")
            st.markdown(f'<div class="metric-hover" title="Cumulative profit/loss from all Call options.">🐂 <b>Total Calls $:</b> ${df_closed[df_closed["Is_Call"]]["Net Change"].sum():,.2f}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-hover" title="Cumulative profit/loss from all Put options.">🐻 <b>Total Puts $:</b> ${df_closed[~df_closed["Is_Call"]]["Net Change"].sum():,.2f}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-hover" title="Total net profit divided by total capital invested.">📈 <b>Total ROI %:</b> {total_roi:.1f}%</div>', unsafe_allow_html=True)
        with d_col3:
            st.markdown("**Risk Intelligence**")
            st.markdown(f'<div class="metric-hover" title="The single most negative P/L day in your selected history.">💀 <b>Worst Day:</b> ${worst_day_val:,.2f}</div>', unsafe_allow_html=True)
            st.caption(f"Date: {worst_day_date}")
            st.markdown(f'<div class="metric-hover" title="The average time elapsed between opening and closing a position.">⏱️ <b>Avg Days Held:</b> {df_closed["Days Held"].mean():.1f} Days</div>', unsafe_allow_html=True)

        st.markdown("---")

        # 3. MONTHLY CALENDAR (CUSTOM HTML TO REMOVE INDEX COLUMN & FIX WIDTH)
        st.markdown("### 📅 Monthly P&L Journal")
        df_closed['Month_Str'] = df_closed['Buy Date'].dt.strftime('%B %Y')
        selected_month = st.selectbox("Select Month", df_closed['Month_Str'].unique(), key=f"cal_{category_name}")
        
        cal_subset = df_closed[df_closed['Month_Str'] == selected_month].copy()
        daily_stats = cal_subset.groupby(cal_subset['Buy Date'].dt.day).agg(PNL=('Net Change', 'sum'), Count=('Net Change', 'count')).to_dict('index')
        
        first_date = cal_subset['Buy Date'].iloc[0]
        matrix = calendar.monthcalendar(first_date.year, first_date.month)
        
        cal_html = '<table class="cal-table"><thead><tr>'
        for day_name in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']:
            cal_html += f'<th>{day_name}</th>'
        cal_html += '</tr></thead><tbody>'
        
        for week in matrix:
            cal_html += '<tr>'
            for day in week:
                if day == 0:
                    cal_html += '<td></td>'
                else:
                    stats = daily_stats.get(day, {'PNL': 0, 'Count': 0})
                    pnl = stats['PNL']
                    count = stats['Count']
                    
                    bg_color = ""
                    if pnl > 0: bg_color = "background-color: rgba(40, 167, 69, 0.25);"
                    elif pnl < 0: bg_color = "background-color: rgba(220, 53, 69, 0.25);"
                    
                    pnl_str = f"${pnl:,.0f}" if pnl != 0 else ""
                    trade_str = f"{count} Trades" if count > 0 else ""
                    
                    cal_html += f'<td style="{bg_color}"><div class="cal-cell"><div class="cal-date">{day}</div><div class="cal-pnl">{pnl_str}</div><div class="cal-trades">{trade_str}</div></div></td>'
            cal_html += '</tr>'
        cal_html += '</tbody></table>'
        
        st.markdown(cal_html, unsafe_allow_html=True)

    # --- 4. TRADE LOG & DOWNLOAD BUTTON RE-ADDED ---
    st.markdown("---")
    st.subheader(f"📋 {category_name} Trade Log")
    csv = df_subset.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Trade Log as CSV", data=csv, file_name=f"{category_name.lower()}_log.csv", mime="text/csv", key=f"dl_{category_name}")
    st.dataframe(df_subset, use_container_width=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Trade Intelligence", layout="wide", page_icon="📈")
st.header("🎯 Trade Intelligence Dashboard")

# Instructions
st.markdown("""<div class="instruction-box">Go to <b><a href="https://robinhood.com/account/reports" target="_blank" style="color:#00d395">Robinhood Reports</a></b>, export <b>Account Activity</b> as CSV, and upload here.</div>""", unsafe_allow_html=True)

# Sidebar
st.sidebar.subheader("🔍 Filter")
search_query = st.sidebar.text_input("Ticker Search", "").strip().upper()
st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    df_raw = df_raw[df_raw['Asset Category'] != 'Other']
    if search_query:
        df_raw = df_raw[df_raw['Ticker'].str.contains(search_query, na=False)]
    
    open_options_count = len(df_raw[(df_raw['Status'] == 'Open') & (df_raw['Asset Category'] == 'Option')])
    st.sidebar.metric("Open Option Positions", open_options_count, help="Total number of distinct Option contracts currently open.")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("👨‍💻 **Puneeth Rao** | [🔗 LinkedIn](https://www.linkedin.com/in/puneeth-rao-9154b511/)")

    t1, t2, t3 = st.tabs(["Portfolio Overview", "Options", "Covered Calls"])
    with t1: render_dashboard_view(df_raw, "Portfolio")
    with t2: render_dashboard_view(df_raw[df_raw['Asset Category'] == 'Option'], "Options")
    with t3: render_dashboard_view(df_raw[df_raw['Asset Category'] == 'Covered Call'], "Covered Calls")
