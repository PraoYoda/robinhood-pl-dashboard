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

def calculate_streaks(df):
    """Calculates current and longest win/loss streaks."""
    if df.empty: return 0, 0
    df = df.sort_values('Close Date')
    results = (df['Net Change'] > 0).astype(int).tolist()
    
    current_streak = 0
    if results:
        last_val = results[-1]
        for r in reversed(results):
            if r == last_val: current_streak += 1
            else: break
        if last_val == 0: current_streak = -current_streak
    
    # Calculate Max Streak
    max_win_streak = 0
    temp_streak = 0
    for r in results:
        if r == 1:
            temp_streak += 1
            max_win_streak = max(max_win_streak, temp_streak)
        else: temp_streak = 0
            
    return current_streak, max_win_streak

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
            'Close Date': sell_date,
            'Buy Date': buy_date
        })
    return pd.DataFrame(summary_rows)

def render_strategy_dashboard(df, title, show_coaching=True):
    if df.empty:
        st.info(f"No completed {title} trades found.")
        return

    # --- TIMEFRAME ---
    start_date = df['Buy Date'].min().strftime('%b %d, %Y')
    end_date = df['Close Date'].max().strftime('%b %d, %Y')
    st.subheader(f"📊 {title} Performance ({start_date} - {end_date})")

    # --- MOMENTUM & KPIs ---
    current_streak, max_win = calculate_streaks(df)
    
    m1, m2, m3, m4 = st.columns(4)
    total_pnl = df['Net Change'].sum()
    tax_toggle = st.session_state.get('tax_toggle', False)
    display_pnl = total_pnl * 0.75 if tax_toggle and total_pnl > 0 else total_pnl
    
    m1.metric("Total P&L", f"${display_pnl:,.2f}")
    m2.metric("Win Rate", f"{(len(df[df['Net Change'] > 0])/len(df)*100):.1f}%")
    
    # Momentum Metric
    streak_label = "🔥 Current Win Streak" if current_streak > 0 else "❄️ Current Loss Streak"
    m3.metric(streak_label, f"{abs(current_streak)} Trades", f"Best: {max_win}")
    
    m4.metric("Total Trades", len(df))

    # --- EQUITY CURVE ---
    df = df.sort_values('Close Date')
    df['Cumulative P&L'] = df['Net Change'].cumsum()
    st.line_chart(df.set_index('Close Date')['Cumulative P&L'])

    # --- MONTHLY SUMMARY ---
    st.markdown("### 🗓️ Monthly Summary")
    df['Month'] = df['Close Date'].dt.strftime('%B %Y')
    df['Month_Sort'] = df['Close Date'].dt.to_period('M')
    
    monthly = df.groupby(['Month_Sort', 'Month']).agg(
        Trades=('Ticker', 'count'),
        Wins=('Net Change', lambda x: (x > 0).sum()),
        Losses=('Net Change', lambda x: (x < 0).sum()),
        Net_P_L=('Net Change', 'sum'),
        Tickers=('Ticker', 'nunique')
    ).reset_index().sort_values('Month_Sort', ascending=False)
    
    st.dataframe(monthly.drop(columns=['Month_Sort']).style.format({'Net_P_L': '${:,.2f}'}), width='stretch')

    # --- TICKER LEADERBOARD ---
    st.markdown("### 🏆 Ticker Leaderboard")
    ticker_stats = df.groupby('Ticker').agg(PNL=('Net Change', 'sum'), Count=('Ticker', 'count')).reset_index()
    c1, c2 = st.columns(2)
    c1.write("**Best Tickers**")
    c1.dataframe(ticker_stats.sort_values('PNL', ascending=False).head(5), hide_index=True)
    c2.write("**Worst Tickers**")
    c2.dataframe(ticker_stats.sort_values('PNL', ascending=True).head(5), hide_index=True)

    if show_coaching:
        st.markdown("---")
        st.markdown("### 🧠 Momentum Coaching")
        if current_streak >= 3:
            st.success(f"You're on a roll with {current_streak} wins! Trust your process, but don't get overconfident with position sizes.")
        elif current_streak <= -3:
            st.error(f"Tough run of {abs(current_streak)} losses. Consider cutting your position size in half until you land your next win.")

# --- 2. MAIN UI ---
st.set_page_config(page_title="Robinhood Mastery", layout="wide")

st.sidebar.title("🛠️ Settings")
st.session_state['tax_toggle'] = st.sidebar.checkbox("Show Est. 25% Tax Deduction", value=False)
st.sidebar.markdown("---")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")

st.title("📈 Robinhood Strategy Dashboard")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file:
    df_raw = process_robinhood_csv(uploaded_file)
    df_all = df_raw[df_raw['Status'] == 'Closed'].copy()

    df_options = df_all[df_all['Asset Category'] == 'Option']
    df_cc = df_all[df_all['Asset Category'] == 'Covered Call']

    tab1, tab2, tab3 = st.tabs(["🔥 Standard Options", "🛡️ Covered Calls", "📋 Full Trade Log"])

    with tab1:
        render_strategy_dashboard(df_options, "Standard Options", show_coaching=True)
    with tab2:
        render_strategy_dashboard(df_cc, "Covered Calls", show_coaching=False)
    with tab3:
        st.subheader("Full Historical Log")
        st.dataframe(df_all.drop(columns=['Status', 'Asset Category']), width='stretch')
        csv_out = df_all.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Clean CSV", csv_out, "Robinhood_Clean_History.csv", "text/csv")
