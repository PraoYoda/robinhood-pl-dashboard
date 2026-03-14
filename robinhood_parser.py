import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

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
    except Exception as e:
        pass
    return f"[Click here to search trending articles for '{query}'](https://www.google.com/search?q={urllib.parse.quote(query)})"

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
        elif 'Dividend' in asset_types: final_type = 'Dividend'
        
        buys = group[group['Trans Code'].isin(['BTO', 'Buy', 'BTC'])]
        sells = group[group['Trans Code'].isin(['STC', 'Sell', 'STO', 'OEXP', 'CDIV'])]
        
        total_buy_qty = buys['Quantity_Clean'].sum()
        total_buy_amt = abs(buys[buys['Amount_Clean'] < 0]['Amount_Clean'].sum())
        
        total_sell_qty = sells['Quantity_Clean'].sum()
        total_sell_amt = sells[sells['Amount_Clean'] > 0]['Amount_Clean'].sum()
        
        net_change = group['Amount_Clean'].sum()
        avg_buy = total_buy_amt / total_buy_qty if total_buy_qty > 0 else 0
        avg_sell = total_sell_amt / total_sell_qty if total_sell_qty > 0 else 0
        
        buy_date = buys['Activity Date'].min() if not buys.empty else np.nan
        sell_date = sells['Activity Date'].max() if not sells.empty else np.nan
        
        let_exp = 'Yes' if any(group['Trans Code'] == 'OEXP') else 'No'
        pct_change = (net_change / total_buy_amt) if total_buy_amt > 0 else 0.0
        
        days_held = (sell_date - buy_date).days if pd.notna(sell_date) and pd.notna(buy_date) else None
        status = 'Closed' if pd.notna(buy_date) and pd.notna(sell_date) else 'Open'

        summary_rows.append({
            'Ticker': ticker,
            'Contract Description': core_desc,
            '# Cons/Shares': total_buy_qty if total_buy_qty > 0 else total_sell_qty,
            'Avg Buy': round(avg_buy, 2),
            'Total Buy': round(total_buy_amt, 2),
            'Avg Sell': round(avg_sell, 2),
            'Total Sell': round(total_sell_amt, 2),
            '% Change': round(pct_change, 4),
            'Net Change': round(net_change, 2),
            'Buy Date': buy_date.strftime('%m/%d/%Y') if pd.notna(buy_date) else None,
            'Sell Date': sell_date.strftime('%m/%d/%Y') if pd.notna(sell_date) else None,
            'Days Held': days_held,
            'Let Exp?': let_exp,
            'Asset Category': final_type,
            'Status': status
        })

    df_summary = pd.DataFrame(summary_rows)
    df_summary['Sort_Date'] = pd.to_datetime(df_summary['Buy Date'], errors='coerce')
    df_summary = df_summary.sort_values('Sort_Date', ascending=False).drop(columns=['Sort_Date'])
    
    return df_summary

def render_dashboard_view(df_subset, category_name):
    if df_subset.empty:
        st.info(f"No completed trades available for {category_name}.")
        return

    df_subset['Days Held'] = pd.to_numeric(df_subset['Days Held'], errors='coerce')
    df_subset['Buy DoW'] = pd.to_datetime(df_subset['Buy Date']).dt.day_name()
    df_subset['Is_Put'] = df_subset['Contract Description'].str.contains('Put', case=False, na=False)
    df_subset['Is_Call'] = df_subset['Contract Description'].str.contains('Call', case=False, na=False)
    df_subset['Trade Style'] = np.where(df_subset['Days Held'] == 0, 'Day Trade', 'Swing Trade')

    total_pnl = df_subset['Net Change'].sum()
    total_trades = len(df_subset)
    winners = df_subset[df_subset['Net Change'] > 0]
    losers = df_subset[df_subset['Net Change'] < 0]
    
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = (winning_trades / (winning_trades + losing_trades)) * 100 if (winning_trades + losing_trades) > 0 else 0
    
    total_cost_basis = df_subset['Total Buy'].sum()
    overall_roi = (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net Profit/Loss", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Avg Trade ROI", f"{overall_roi:.1f}%")
    col4.metric("Total Trades", total_trades)
    
    st.markdown("---")

    st.markdown(f"### 🔬 Deep Dive: {category_name} Analytics")
    ana_col1, ana_col2, ana_col3 = st.columns(3)
    
    dt_df = df_subset[df_subset['Trade Style'] == 'Day Trade']
    sw_df = df_subset[df_subset['Trade Style'] == 'Swing Trade']
    dt_pnl, sw_pnl = dt_df['Net Change'].sum(), sw_df['Net Change'].sum()
    
    with ana_col1:
        st.markdown("**Trade Style Performance**")
        st.write(f"📈 **Swing Trades (>0 Days):** ${sw_pnl:,.2f} ({len(sw_df)} trades)")
        st.write(f"⚡ **Day Trades (0 Days):** ${dt_pnl:,.2f} ({len(dt_df)} trades)")

    call_df = df_subset[df_subset['Is_Call'] == True]
    put_df = df_subset[df_subset['Is_Put'] == True]
    call_pnl, put_pnl = call_df['Net Change'].sum(), put_df['Net Change'].sum()
    
    with ana_col2:
        st.markdown("**Call vs. Put Focus**")
        st.write(f"🐂 **Calls Net P&L:** ${call_pnl:,.2f}")
        st.write(f"🐻 **Puts Net P&L:** ${put_pnl:,.2f}")

    dow_stats = df_subset.groupby('Buy DoW').agg(Net_Profit=('Net Change', 'sum')).reset_index()
    if not dow_stats.empty:
        best_day = dow_stats.loc[dow_stats['Net_Profit'].idxmax()]
        worst_day = dow_stats.loc[dow_stats['Net_Profit'].idxmin()]
        with ana_col3:
            st.markdown("**Entry Day of Week**")
            st.write(f"✅ **Best Day to Enter:** {best_day['Buy DoW']} (${best_day['Net_Profit']:,.0f})")
            st.write(f"❌ **Worst Day to Enter:** {worst_day['Buy DoW']} (${worst_day['Net_Profit']:,.0f})")

    st.markdown("---")

    st.markdown(f"### 🧠 Trade Behavior & Efficiency")
    avg_win = winners['Net Change'].mean() if not winners.empty else 0
    avg_loss = losers['Net Change'].mean() if not losers.empty else 0
    risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    avg_days_win = winners['Days Held'].mean() if not winners.empty else 0
    avg_days_loss = losers['Days Held'].mean() if not losers.empty else 0

    ticker_win_rates = df_subset.groupby('Ticker').agg(Total_Trades=('Net Change', 'count'), Wins=('Net Change', lambda x: (x > 0).sum()))
    ticker_win_rates['Win_Rate'] = ticker_win_rates['Wins'] / ticker_win_rates['Total_Trades']
    eligible_tickers = ticker_win_rates[ticker_win_rates['Total_Trades'] >= 3]
    
    col_b1, col_b2, col_b3 = st.columns(3)
    col_b1.metric("⚖️ Avg Win vs. Avg Loss", f"${avg_win:,.0f} / ${abs(avg_loss):,.0f}", f"Ratio: {risk_reward:.2f}x", delta_color="normal" if risk_reward >= 1 else "inverse")
    col_b2.metric("⏱️ Avg Win Hold Time", f"{avg_days_win:.1f} days", f"Losers held {avg_days_loss:.1f} days", delta_color="inverse" if avg_days_loss > avg_days_win else "normal")
    
    if not eligible_tickers.empty:
        best_ticker_wr = eligible_tickers.loc[eligible_tickers['Win_Rate'].idxmax()]
        col_b3.metric("🎯 Most Reliable Ticker (3+ Trades)", f"{best_ticker_wr.name}", f"{best_ticker_wr['Win_Rate'] * 100:.0f}% Win Rate")
    else:
        col_b3.metric("🎯 Most Reliable Ticker", "Need more data", "Min 3 trades required", delta_color="off")

    if category_name != "Covered Call":
        st.markdown("### 🛠️ Actionable Recommendations & Learning")
        recommendations = []
        if dt_pnl < 0 and sw_pnl > 0 and len(dt_df) >= 3:
            article = fetch_dynamic_article("day trading vs swing trading stock options")
            recommendations.append(f"⚠️ **Day Trading Leak:** Your Swing Trades are profitable, but your 0DTE Day Trades are losing money (${dt_pnl:,.0f}). \n\n* **Action:** Consider banning 0DTE trades from your strategy to instantly boost your bottom line. \n* **Trending Read:** {article}")
        if call_pnl > 0 and put_pnl < 0 and len(put_df) >= 3:
            article = fetch_dynamic_article("how to trade put options effectively")
            recommendations.append(f"🐻 **Bear Trap:** You are successfully making money longing the market (Calls), but losing money shorting it (Puts: ${put_pnl:,.0f}). \n\n* **Action:** Stop trying to catch falling knives. Focus entirely on bullish setups until your put strategy improves. \n* **Trending Read:** {article}")
        if not dow_stats.empty and worst_day['Net_Profit'] < 0:
            article = fetch_dynamic_article("best days of the week to trade options")
            recommendations.append(f"📅 **Toxic Trading Day:** Trades opened on **{worst_day['Buy DoW']}s** are currently your biggest drag on performance. \n\n* **Action:** Review your {worst_day['Buy DoW']} trades. Are you forcing entries before the weekend? \n* **Trending Read:** {article}")
        if risk_reward > 0 and risk_reward < 1.0:
            article = fetch_dynamic_article("how to improve trading risk reward ratio strategy")
            recommendations.append(f"🚨 **Risk/Reward Warning:** Your average loss is larger than your average win. \n\n* **Action:** Consider setting tighter stop-losses to cut losers faster. \n* **Trending Read:** {article}")
        if avg_days_loss > avg_days_win and avg_days_win > 0:
            article = fetch_dynamic_article("trading psychology cutting losses short")
            recommendations.append(f"📉 **Bag Holding Alert:** You hold onto losing trades longer than winning trades, tying up capital. \n\n* **Action:** Try implementing a strict 'time-stop' (e.g., if a trade doesn't move in your favor after a few days, cut it). \n* **Trending Read:** {article}")
        if win_rate < 40 and total_trades >= 5:
            article = fetch_dynamic_article("how to improve trading win rate setup criteria")
            recommendations.append(f"⚠️ **Low Win Rate:** With a win rate below 40%, you might be forcing trades. \n\n* **Action:** Review your entry criteria. Trade less frequently and wait for A+ setups. \n* **Trending Read:** {article}")

        if recommendations:
            for rec in recommendations:
                if any(x in rec for x in ["Warning", "Alert", "Leak", "Toxic", "Trap", "Low"]): st.warning(rec)
                else: st.success(rec)
        else: st.info("Keep trading! Once you have more data, advanced behavioral recommendations will appear here.")
        
    st.markdown("---")
    
    st.markdown(f"### 📅 {category_name} - Monthly Summary")
    df_temp = df_subset.copy()
    df_temp['Sell_DT'] = pd.to_datetime(df_temp['Sell Date'], errors='coerce')
    df_temp['Buy_DT'] = pd.to_datetime(df_temp['Buy Date'], errors='coerce')
    df_temp['Month_Date'] = df_temp['Sell_DT'].fillna(df_temp['Buy_DT'])
    
    valid_dates = df_temp.dropna(subset=['Month_Date']).copy()
    
    if not valid_dates.empty:
        valid_dates['Month'] = valid_dates['Month_Date'].dt.strftime('%B %Y')
        valid_dates['Month_Sort'] = valid_dates['Month_Date'].dt.to_period('M')
        
        monthly_summary = valid_dates.groupby(['Month_Sort', 'Month']).agg(
            Total_Trades=('Ticker', 'count'), Wins=('Net Change', lambda x: (x > 0).sum()), Losses=('Net Change', lambda x: (x < 0).sum()),
            Net_Profit=('Net Change', 'sum'), Unique_Tickers=('Ticker', 'nunique'), Puts=('Is_Put', 'sum'), Calls=('Is_Call', 'sum')
        ).reset_index().sort_values('Month_Sort', ascending=False)
        
        st.dataframe(monthly_summary.drop(columns=['Month_Sort']).rename(columns={'Wins': 'Trades with Profit', 'Losses': 'Trades with Loss', 'Net_Profit': 'Total Net Profit/Loss', 'Unique_Tickers': 'Unique Tickers', 'Puts': 'No of PUTS', 'Calls': 'No of CALLS'}).style.format({'Total Net Profit/Loss': '${:,.2f}'}), width='stretch')

        # --- NEW: DAILY P&L MATRIX (AS REQUESTED) ---
        st.markdown("---")
        st.markdown("### 🗓️ Daily P&L Ledger")
        selected_month = st.selectbox(f"Select Month to View Daily Performance ({category_name})", monthly_summary['Month'].tolist(), key=f"month_select_{category_name}")
        
        daily_data = valid_dates[valid_dates['Month'] == selected_month].copy()
        daily_data['Day_Date'] = daily_data['Month_Date'].dt.date
        daily_pnl = daily_data.groupby('Day_Date')['Net Change'].sum().reset_index()
        daily_pnl['Day_Name'] = pd.to_datetime(daily_pnl['Day_Date']).dt.day_name()
        
        daily_pivot = daily_pnl.pivot(index='Day_Date', columns='Day_Name', values='Net Change').fillna(0)
        day_cols = [c for c in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] if c in daily_pivot.columns]
        st.dataframe(daily_pivot[day_cols].style.applymap(lambda x: 'color: green' if x > 0 else ('color: red' if x < 0 else 'color: gray')).format("${:,.2f}"), width='stretch')
        
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("#### P&L By Month")
            st.bar_chart(monthly_summary[['Month', 'Net_Profit']].set_index('Month'))
        with col_chart2:
            st.markdown("#### P&L by Entry Day of Week")
            dow_chart_data = dow_stats.set_index('Buy DoW').reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']).dropna()
            st.bar_chart(dow_chart_data)
    else: st.info("Not enough dated transactions to generate monthly tracking.")

    st.markdown("---")
    st.markdown(f"### 📋 {category_name} - Trade Details")
    st.dataframe(df_temp.drop(columns=['Sell_DT', 'Buy_DT', 'Month_Date', 'Month', 'Month_Sort', 'Is_Put', 'Is_Call', 'Status', 'Trade Style'], errors='ignore'), width='stretch')


# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood P&L Dashboard", layout="wide")
st.sidebar.markdown("## About the Creator")
st.sidebar.markdown("This tool was built to automate Robinhood options and stock P&L tracking, specifically optimized for options trading.")
st.sidebar.markdown("---")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")

st.title("📈 Interactive Robinhood P&L Dashboard")
uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file is not None:
    with st.spinner("Processing..."):
        try:
            df_result = process_robinhood_csv(uploaded_file)
            df_result['Net Change'] = pd.to_numeric(df_result['Net Change'], errors='coerce').fillna(0)
            df_result = df_result[(~df_result['Asset Category'].isin(['Option', 'Covered Call']) | (df_result['Status'] != 'Open'))]
            df_result = df_result[df_result['Asset Category'].isin(['Option', 'Covered Call'])]
            
            if df_result.empty: st.warning("No completed options or covered call trades found.")
            else:
                available_categories = sorted(df_result['Asset Category'].unique().tolist())
                tab_names = ["All Data"] + available_categories
                tabs = st.tabs(tab_names)
                for i, tab in enumerate(tabs):
                    with tab: render_dashboard_view(df_result if tab_names[i] == "All Data" else df_result[df_result['Asset Category'] == tab_names[i]], tab_names[i])
        except Exception as e: st.error(f"Error: {e}")
