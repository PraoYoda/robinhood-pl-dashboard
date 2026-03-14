import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# --- CORE UTILITIES ---
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

def get_strategy(row):
    desc = str(row['Description']).upper()
    if 'CALL' in desc: return 'Long Call' if row['Asset Category'] == 'Option' else 'Covered Call'
    if 'PUT' in desc: return 'Long Put'
    return 'Equity'

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
            'Strategy': get_strategy(group.iloc[0]),
            'Close Date': sell_date
        })
    return pd.DataFrame(summary_rows)

# --- UI LAYOUT ---
st.set_page_config(page_title="Robinhood Elite Dashboard", layout="wide")

# Sidebar
st.sidebar.title("🛠️ Trader's Toolkit")
st.sidebar.markdown("👨‍💻 **Puneeth Rao** | [LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")
st.sidebar.info("Optimized for Options Mastery")

# Main
st.title("📈 Robinhood Options Mastery Dashboard")

uploaded_file = st.file_uploader("Upload Your Robinhood Account History CSV", type=["csv"])

if uploaded_file:
    df_res = process_robinhood_csv(uploaded_file)
    df_res = df_res[df_res['Status'] == 'Closed']
    df_res = df_res[df_res['Asset Category'].isin(['Option', 'Covered Call'])]
    df_res = df_res.sort_values('Close Date')

    # Top Metrics
    total_pnl = df_res['Net Change'].sum()
    tax_est = total_pnl * 0.25 if total_pnl > 0 else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Gross Profit", f"${total_pnl:,.2f}")
    m2.metric("Est. After-Tax Net", f"${(total_pnl - tax_est):,.2f}", delta=f"-${tax_est:,.0f} Tax", delta_color="inverse")
    m3.metric("Win Rate", f"{(len(df_res[df_res['Net Change'] > 0]) / len(df_res) * 100):.1f}%")
    m4.metric("Avg Trade ROI", f"{df_res['ROI %'].mean():.1f}%")

    st.markdown("---")

    # EQUITY CURVE
    st.subheader("📈 Cumulative P&L (Equity Curve)")
    df_res['Cumulative P&L'] = df_res['Net Change'].cumsum()
    equity_data = df_res[['Close Date', 'Cumulative P&L']].set_index('Close Date')
    st.line_chart(equity_data)
    
    st.markdown("---")

    # NEW: TICKER LEADERBOARD SECTION
    st.subheader("🏆 Ticker Leaderboard")
    tick_col1, tick_col2 = st.columns(2)
    
    ticker_stats = df_res.groupby('Ticker').agg(
        Total_PNL=('Net Change', 'sum'),
        Trade_Count=('Ticker', 'count'),
        Avg_ROI=('ROI %', 'mean')
    ).reset_index()
    
    ticker_stats['Profit_Per_Trade'] = ticker_stats['Total_PNL'] / ticker_stats['Trade_Count']

    with tick_col1:
        st.markdown("**Top 5 Profit Makers (Best Friends)**")
        top_5 = ticker_stats.sort_values('Total_PNL', ascending=False).head(5)
        st.dataframe(top_5[['Ticker', 'Total_PNL', 'Trade_Count']].style.format({'Total_PNL': '${:,.2f}'}), hide_index=True)

    with tick_col2:
        st.markdown("**Top 5 Loss Makers (Account Killers)**")
        bottom_5 = ticker_stats.sort_values('Total_PNL', ascending=True).head(5)
        st.dataframe(bottom_5[['Ticker', 'Total_PNL', 'Trade_Count']].style.format({'Total_PNL': '${:,.2f}'}), hide_index=True)

    st.markdown("---")

    # ANALYTICS TABS
    t1, t2 = st.tabs(["📊 Strategy Matrix", "📋 Detailed Log"])
    
    with t1:
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            st.markdown("### Performance by Strategy Type")
            strat_stats = df_res.groupby('Strategy').agg(
                Total_PNL=('Net Change', 'sum'),
                Win_Rate=('Net Change', lambda x: (x > 0).mean() * 100),
                Avg_ROI=('ROI %', 'mean'),
                Trades=('Ticker', 'count')
            ).sort_values('Total_PNL', ascending=False)
            st.table(strat_stats.style.format({'Total_PNL': '${:,.2f}', 'Win_Rate': '{:.1f}%', 'Avg_ROI': '{:.1f}%'}))
            
        with col_s2:
            st.markdown("### ⚖️ Risk Coach")
            avg_loss = abs(df_res[df_res['Net Change'] < 0]['Net Change'].mean())
            if pd.isna(avg_loss): avg_loss = 0
            st.write(f"Your Avg Loss: **${avg_loss:,.2f}**")
            risk_input = st.number_input("Desired Risk per Trade ($)", value=float(round(avg_loss, 0)) if avg_loss > 0 else 100.0)
            st.success(f"**Actionable Advice:** Limit total capital per trade to **${risk_input * 10:,.0f}**.")

        # RECOMMENDATIONS
        st.markdown("---")
        st.markdown("### 💡 Behavioral Coaching")
        # Find the ticker with the most trades but negative P&L
        bad_habit_ticker = ticker_stats[ticker_stats['Total_PNL'] < 0].sort_values('Trade_Count', ascending=False).head(1)
        
        if not bad_habit_ticker.empty:
            ticker_name = bad_habit_ticker.iloc[0]['Ticker']
            st.warning(f"**Overtrading Alert:** You have traded **{ticker_name}** {int(bad_habit_ticker.iloc[0]['Trade_Count'])} times but have a net loss of ${abs(bad_habit_ticker.iloc[0]['Total_PNL']):,.2f}. Consider taking a break from this ticker.")
        
        if total_pnl > 0:
            st.success(f"Keep it up! Your best ticker is **{ticker_stats.sort_values('Total_PNL', ascending=False).iloc[0]['Ticker']}**.")

    with t2:
        st.dataframe(df_res.drop(columns=['Asset Category', 'Status', 'Cumulative P&L']), width='stretch')

    # Download
    csv_out = df_res.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Export Analysis", csv_out, "Trader_Edge_Analysis.csv", "text/csv")
