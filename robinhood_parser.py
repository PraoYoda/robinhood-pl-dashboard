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

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Robinhood Mastery Dashboard", layout="wide")

st.sidebar.title("🛠️ Trader's Toolkit")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")
tax_toggle = st.sidebar.checkbox("Show Est. 25% Tax Deduction", value=False)

st.title("📈 Robinhood Options Mastery Dashboard")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    # Filter for realized options/covered calls
    df_res = df_raw[(df_raw['Status'] == 'Closed') & (df_raw['Asset Category'].isin(['Option', 'Covered Call']))].sort_values('Close Date')

    if df_res.empty:
        st.warning("No completed options trades found.")
    else:
        # --- TIMEFRAME HEADER ---
        start_date = df_res['Buy Date'].min().strftime('%b %d, %Y')
        end_date = df_res['Close Date'].max().strftime('%b %d, %Y')
        st.info(f"🗓️ **Report Timeframe:** {start_date} to {end_date} ({len(df_res)} Trades)")

        # --- TOP LEVEL KPIs ---
        total_pnl = df_res['Net Change'].sum()
        winners = df_res[df_res['Net Change'] > 0]
        losers = df_res[df_res['Net Change'] < 0]
        
        m1, m2, m3, m4 = st.columns(4)
        
        display_pnl = total_pnl * 0.75 if tax_toggle and total_pnl > 0 else total_pnl
        pnl_label = "Net Profit (After Tax)" if tax_toggle else "Gross Profit"
        
        m1.metric(pnl_label, f"${display_pnl:,.2f}")
        m2.metric("Win Rate", f"{(len(winners)/len(df_res)*100):.1f}%")
        m3.metric("Avg Trade ROI", f"{df_res['ROI %'].mean():.1f}%")
        m4.metric("Avg Hold Time", f"{df_res['Days Held'].mean():.1f} Days")

        st.markdown("---")

        # --- TABS ---
        t1, t2, t3, t4 = st.tabs(["🗓️ Monthly Summary", "📈 Equity Curve", "🏆 Leaderboard", "🧠 Strategy & Coaching"])

        with t1:
            st.markdown("### 🗓️ Monthly Performance Tracker")
            df_res['Month'] = df_res['Close Date'].dt.strftime('%B %Y')
            df_res['Month_Sort'] = df_res['Close Date'].dt.to_period('M')
            df_res['Is_Put'] = df_res['Description'].str.contains('Put', case=False, na=False)
            df_res['Is_Call'] = df_res['Description'].str.contains('Call', case=False, na=False)
            
            monthly = df_res.groupby(['Month_Sort', 'Month']).agg(
                Total_Trades=('Ticker', 'count'),
                Wins=('Net Change', lambda x: (x > 0).sum()),
                Losses=('Net Change', lambda x: (x < 0).sum()),
                Net_Profit=('Net Change', 'sum'),
                Unique_Tickers=('Ticker', 'nunique'),
                No_of_PUTS=('Is_Put', 'sum'),
                No_of_CALLS=('Is_Call', 'sum')
            ).reset_index().sort_values('Month_Sort', ascending=False)

            if tax_toggle:
                monthly['Net_Profit_After_Tax'] = monthly['Net_Profit'].apply(lambda x: x * 0.75 if x > 0 else x)
                monthly.rename(columns={'Net_Profit_After_Tax': 'Net P&L (Post-Tax)'}, inplace=True)
            
            monthly.rename(columns={
                'Wins': 'Profit Trades', 
                'Losses': 'Loss Trades', 
                'Net_Profit': 'Total Net P&L',
                'Unique_Tickers': 'Tickers'
            }, inplace=True)
            
            st.dataframe(monthly.drop(columns=['Month_Sort']).style.format({'Total Net P&L': '${:,.2f}', 'Net P&L (Post-Tax)': '${:,.2f}'}), width='stretch')
            st.bar_chart(monthly.set_index('Month')['Total Net P&L'])

        with t2:
            st.subheader("📈 Cumulative P&L (Equity Curve)")
            df_res['Cumulative P&L'] = df_res['Net Change'].cumsum()
            st.line_chart(df_res.set_index('Close Date')['Cumulative P&L'])

        with t3:
            st.markdown("### 🏆 Ticker Leaderboard")
            ticker_stats = df_res.groupby('Ticker').agg(PNL=('Net Change', 'sum'), Trades=('Ticker', 'count')).reset_index()
            c_left, c_right = st.columns(2)
            c_left.write("**Top Profit Makers**")
            c_left.dataframe(ticker_stats.sort_values('PNL', ascending=False).head(5), hide_index=True)
            c_right.write("**Top Account Killers**")
            c_right.dataframe(ticker_stats.sort_values('PNL', ascending=True).head(5), hide_index=True)

        with t4:
            st.markdown("### 🧠 Strategy & Behavior")
            b_left, b_right = st.columns([2, 1])
            with b_left:
                strat_df = df_res.groupby('Strategy').agg(PNL=('Net Change', 'sum'), ROI=('ROI %', 'mean'), count=('Ticker', 'count'))
                st.table(strat_df.style.format({'PNL': '${:,.2f}', 'ROI': '{:.1f}%'}))
            
            with b_right:
                avg_loss_val = abs(losers['Net Change'].mean()) if not losers.empty else 0
                st.write(f"Avg Loss: **${avg_loss_val:,.2f}**")
                risk_val = st.number_input("Risk Limit per Trade ($)", value=float(round(avg_loss_val,0)) if avg_loss_val > 0 else 100.0)
                st.success(f"**Max Capital Suggestion:** ${risk_val * 10:,.0f}")

            st.markdown("#### Dynamic Coaching Insights")
            if not losers.empty and not winners.empty:
                if losers['Days Held'].mean() > winners['Days Held'].mean():
                    st.warning(f"🚨 **Bag Holding Alert:** Read: {fetch_dynamic_article('psychology of cutting losses short')}")
                else:
                    st.success("✅ Excellent exit discipline—you cut losers fast.")

        st.markdown("---")
        with st.expander("📋 View Full Detailed Trade Log"):
            st.dataframe(df_res.drop(columns=['Status', 'Asset Category', 'Cumulative P&L', 'Month', 'Month_Sort', 'Is_Put', 'Is_Call']), width='stretch')

        csv_out = df_res.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Analysis CSV", csv_out, "Robinhood_Mastery_Report.csv", "text/csv")
