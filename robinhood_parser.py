import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import plotly.express as px  # Ensure 'plotly' is in requirements.txt

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
st.set_page_config(page_title="Robinhood Quant-View", layout="wide")

st.sidebar.title("⚙️ Quant Settings")
st.sidebar.markdown("👨‍💻 **Dev:** Puneeth Rao")
tax_toggle = st.sidebar.checkbox("Apply 25% Est. Tax Leak", value=False)

st.title("🔬 Robinhood Quant-View")
st.markdown("*Advanced Option Analytics & Behavioral Command Center*")

uploaded_file = st.file_uploader("Initialize Quant System: Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    df_res = df_raw[(df_raw['Status'] == 'Closed') & (df_raw['Asset Category'].isin(['Option', 'Covered Call']))].sort_values('Close Date')

    if df_res.empty:
        st.warning("No completed options trades detected.")
    else:
        # --- TOP LEVEL KPIs ---
        total_pnl = df_res['Net Change'].sum()
        winners = df_res[df_res['Net Change'] > 0]
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Gross Profit", f"${total_pnl:,.2f}")
        m2.metric("Win Rate", f"{(len(winners)/len(df_res)*100):.1f}%")
        m3.metric("Profit/Trade", f"${(total_pnl/len(df_res)):,.2f}")
        m4.metric("Avg Exposure", f"{df_res['Days Held'].mean():.1f} Days")

        st.markdown("---")

        t_cal, t1, t2, t3, t4 = st.tabs(["📅 Daily P&L Heatmap", "🗓️ Monthly Matrix", "📈 Growth Curve", "🏆 Asset Leaderboard", "🧠 Behavioral Analysis"])

        with t_cal:
            st.markdown("### Interactive Daily P&L Heatmap")
            df_cal = df_res.copy()
            df_cal['Date'] = df_cal['Close Date'].dt.date
            daily_pnl = df_cal.groupby('Date')['Net Change'].sum().reset_index()
            daily_pnl['Date'] = pd.to_datetime(daily_pnl['Date'])
            
            # Formatting for the heatmap
            daily_pnl['Day'] = daily_pnl['Date'].dt.day_name()
            daily_pnl['Week'] = daily_pnl['Date'].dt.isocalendar().week
            daily_pnl['Month_Year'] = daily_pnl['Date'].dt.strftime('%b %Y')

            # Sort days properly
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            
            fig = px.density_heatmap(
                daily_pnl,
                x="Week",
                y="Day",
                z="Net Change",
                histfunc="sum",
                color_continuous_scale="RdYlGn",
                category_orders={"Day": day_order},
                title="P&L Concentration by Day & Week",
                labels={'Net Change': 'P&L ($)'},
                template="plotly_dark"
            )
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("#### Daily Activity Log")
            st.dataframe(daily_pnl.sort_values('Date', ascending=False)[['Date', 'Net Change']].style.format({'Net Change': '${:,.2f}'}), hide_index=True)

        with t1:
            st.markdown("### Monthly Performance Matrix")
            df_res['Month'] = df_res['Close Date'].dt.strftime('%B %Y')
            df_res['Month_Sort'] = df_res['Close Date'].dt.to_period('M')
            df_res['Is_Put'] = df_res['Description'].str.contains('Put', case=False, na=False)
            df_res['Is_Call'] = df_res['Description'].str.contains('Call', case=False, na=False)
            
            monthly = df_res.groupby(['Month_Sort', 'Month']).agg(
                Trades=('Ticker', 'count'),
                Wins=('Net Change', lambda x: (x > 0).sum()),
                Net_Profit=('Net Change', 'sum'),
                Tickers=('Ticker', 'nunique'),
                Puts=('Is_Put', 'sum'),
                Calls=('Is_Call', 'sum')
            ).reset_index().sort_values('Month_Sort', ascending=False)
            
            st.dataframe(monthly.drop(columns=['Month_Sort']).style.format({'Net_Profit': '${:,.2f}'}), width='stretch')

        with t2:
            st.subheader("Account Equity Curve")
            df_res['Cumulative P&L'] = df_res['Net Change'].cumsum()
            st.line_chart(df_res.set_index('Close Date')['Cumulative P&L'])

        with t3:
            st.markdown("### High-Conviction Asset Ranking")
            ticker_stats = df_res.groupby('Ticker').agg(PNL=('Net Change', 'sum'), Trades=('Ticker', 'count')).reset_index()
            c1, c2 = st.columns(2)
            c1.write("**✅ Top Alpha Generators**")
            c1.dataframe(ticker_stats.sort_values('PNL', ascending=False).head(5), hide_index=True)
            c2.write("**❌ Top Wealth Destroyers**")
            c2.dataframe(ticker_stats.sort_values('PNL', ascending=True).head(5), hide_index=True)

        with t4:
            st.markdown("### Behavioral Audit & Coaching")
            b_left, b_right = st.columns([2, 1])
            with b_left:
                strat_df = df_res.groupby('Strategy').agg(PNL=('Net Change', 'sum'), ROI=('ROI %', 'mean'), count=('Ticker', 'count'))
                st.table(strat_df.style.format({'PNL': '${:,.2f}', 'ROI': '{:.1f}%'}))
            
            with b_right:
                losers = df_res[df_res['Net Change'] < 0]
                avg_loss_val = abs(losers['Net Change'].mean()) if not losers.empty else 0
                st.write(f"Measured Avg Loss: **${avg_loss_val:,.2f}**")
                risk_val = st.number_input("Risk Limit Target ($)", value=float(round(avg_loss_val,0)) if avg_loss_val > 0 else 100.0)
                st.success(f"**Action Plan:** Position size limit: **${risk_val * 10:,.0f}**")

        st.markdown("---")
        with st.expander("🔍 Deep-Dive: Historical Audit Log"):
            st.dataframe(df_res.drop(columns=['Status', 'Asset Category', 'Cumulative P&L', 'Month', 'Month_Sort', 'Is_Put', 'Is_Call']), width='stretch')

        csv_out = df_res.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Export Command Data", csv_out, "QuantView_Audit_Report.csv", "text/csv")
