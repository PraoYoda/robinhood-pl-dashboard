import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# --- 1. CORE UTILITIES & PARSING ---
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
            'Close Date': sell_date,
            'Buy Date': buy_date
        })
    return pd.DataFrame(summary_rows)

# --- 2. DASHBOARD UI LOGIC ---
st.set_page_config(page_title="Robinhood Mastery Dashboard", layout="wide")

st.sidebar.title("🛠️ Trader's Toolkit")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")
st.sidebar.info("Optimized for Options Trading & Behavioral Performance")

st.title("📈 Robinhood Options Mastery Dashboard")

with st.expander("ℹ️ How to get your Robinhood CSV"):
    st.markdown("""
    1. Log in to [Robinhood Reports](https://robinhood.com/account/reports).
    2. Under **Account History**, click **Export as CSV**.
    """)

uploaded_file = st.file_uploader("Upload Your Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    # Filter for realized options/covered calls
    df_res = df_raw[(df_raw['Status'] == 'Closed') & (df_raw['Asset Category'].isin(['Option', 'Covered Call']))].sort_values('Close Date')

    if df_res.empty:
        st.warning("No completed options or covered call trades found.")
    else:
        # --- TOP LEVEL KPIs ---
        total_pnl = df_res['Net Change'].sum()
        tax_est = total_pnl * 0.25 if total_pnl > 0 else 0
        winners = df_res[df_res['Net Change'] > 0]
        losers = df_res[df_res['Net Change'] < 0]
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Gross Profit", f"${total_pnl:,.2f}")
        m2.metric("Net (After 25% Tax)", f"${(total_pnl - tax_est):,.2f}")
        m3.metric("Win Rate", f"{(len(winners)/len(df_res)*100):.1f}%")
        m4.metric("Avg Trade ROI", f"{df_res['ROI %'].mean():.1f}%")

        st.markdown("---")

        # --- 3. EQUITY CURVE & TRENDS ---
        st.subheader("📈 Consistency Tracking")
        df_res['Cumulative P&L'] = df_res['Net Change'].cumsum()
        st.line_chart(df_res.set_index('Close Date')['Cumulative P&L'])

        st.markdown("---")

        # --- 4. THE CONSOLIDATED TABS ---
        t1, t2, t3, t4 = st.tabs(["🗓️ Monthly Summary", "🏆 Ticker Leaderboard", "🧠 Strategy & Behavior", "📋 Detailed Log"])

        with t1:
            st.markdown("### Google Sheet-Style Monthly Summary")
            df_res['Month'] = df_res['Close Date'].dt.strftime('%B %Y')
            monthly = df_res.groupby('Month').agg(
                Total_Trades=('Ticker', 'count'),
                Net_PNL=('Net Change', 'sum'),
                Wins=('Net Change', lambda x: (x > 0).sum()),
                Losses=('Net Change', lambda x: (x < 0).sum())
            ).reset_index()
            st.dataframe(monthly.style.format({'Net_PNL': '${:,.2f}'}), width='stretch')

        with t2:
            st.markdown("### Ticker Performance Leaderboard")
            ticker_stats = df_res.groupby('Ticker').agg(PNL=('Net Change', 'sum'), Trades=('Ticker', 'count')).reset_index()
            c_left, c_right = st.columns(2)
            c_left.write("**Top Profit Makers**")
            c_left.dataframe(ticker_stats.sort_values('PNL', ascending=False).head(5), hide_index=True)
            c_right.write("**Top Account Killers**")
            c_right.dataframe(ticker_stats.sort_values('PNL', ascending=True).head(5), hide_index=True)

        with t3:
            st.markdown("### Behavior & Risk Coaching")
            b_left, b_right = st.columns([2, 1])
            with b_left:
                # Strategy Matrix
                strat_df = df_res.groupby('Strategy').agg(PNL=('Net Change', 'sum'), ROI=('ROI %', 'mean'), count=('Ticker', 'count'))
                st.table(strat_df.style.format({'PNL': '${:,.2f}', 'ROI': '{:.1f}%'}))
            
            with b_right:
                avg_loss = abs(losers['Net Change'].mean()) if not losers.empty else 0
                st.write(f"Avg Loss: **${avg_loss:,.2f}**")
                risk_val = st.number_input("Risk Limit ($)", value=float(round(avg_loss,0)) if avg_loss > 0 else 100.0)
                st.success(f"**Action:** Limit position size to **${risk_val * 10:,.0f}**")

            st.markdown("#### Actionable Insights")
            if not losers.empty and not winners.empty:
                if losers['Days Held'].mean() > winners['Days Held'].mean():
                    st.warning(f"🚨 **Bag Holding Alert:** You hold losers too long. Read: {fetch_dynamic_article('trading psychology cutting losses')}")
                else:
                    st.success("✅ Good exit discipline on losing trades.")

        with t4:
            st.dataframe(df_res.drop(columns=['Status', 'Asset Category', 'Cumulative P&L', 'Month']), width='stretch')

        # --- 5. EXPORT ---
        csv_out = df_res.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Analysis CSV", csv_out, "Robinhood_Mastery_Report.csv", "text/csv")
