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
    """Fetches the #1 trending article from Google News based on the specific trading gap."""
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

    total_pnl = df_subset['Net Change'].sum()
    total_trades = len(df_subset)
    winners = df_subset[df_subset['Net Change'] > 0]
    losers = df_subset[df_subset['Net Change'] < 0]
    
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = (winning_trades / (winning_trades + losing_trades)) * 100 if (winning_trades + losing_trades) > 0 else 0
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net Profit/Loss", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Trades with Profit", winning_trades)
    col4.metric("Total Trades", total_trades)
    
    st.markdown("---")

    st.markdown(f"### 💡 {category_name} - Highlights")
    ticker_stats = df_subset.groupby('Ticker').agg(
        Net_Profit=('Net Change', 'sum'),
        Trade_Count=('Ticker', 'count')
    ).reset_index()

    if not ticker_stats.empty:
        top_traded = ticker_stats.loc[ticker_stats['Trade_Count'].idxmax()]
        top_profit = ticker_stats.loc[ticker_stats['Net_Profit'].idxmax()]
        top_loss = ticker_stats.loc[ticker_stats['Net_Profit'].idxmin()]
        
        col_in1, col_in2, col_in3 = st.columns(3)
        col_in1.metric("🔥 Most Traded Ticker", f"{top_traded['Ticker']}", f"{int(top_traded['Trade_Count'])} Trades", delta_color="off")
        
        if top_profit['Net_Profit'] > 0:
            col_in2.metric("🏆 Top Profit Maker", f"{top_profit['Ticker']}", f"${top_profit['Net_Profit']:,.2f}")
        else:
            col_in2.metric("🏆 Top Profit Maker", "None", "$0.00")
            
        if top_loss['Net_Profit'] < 0:
            col_in3.metric("📉 Biggest Loss Maker", f"{top_loss['Ticker']}", f"${top_loss['Net_Profit']:,.2f}")
        else:
            col_in3.metric("📉 Biggest Loss Maker", "No Losses!", "$0.00", delta_color="off")

    st.markdown("---")

    st.markdown(f"### 🧠 Trade Behavior & Efficiency")
    avg_win = winners['Net Change'].mean() if not winners.empty else 0
    avg_loss = losers['Net Change'].mean() if not losers.empty else 0
    risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    avg_days_win = winners['Days Held'].mean() if not winners.empty else 0
    avg_days_loss = losers['Days Held'].mean() if not losers.empty else 0

    ticker_win_rates = df_subset.groupby('Ticker').agg(
        Total_Trades=('Net Change', 'count'),
        Wins=('Net Change', lambda x: (x > 0).sum())
    )
    ticker_win_rates['Win_Rate'] = ticker_win_rates['Wins'] / ticker_win_rates['Total_Trades']
    eligible_tickers = ticker_win_rates[ticker_win_rates['Total_Trades'] >= 3]
    
    col_b1, col_b2, col_b3 = st.columns(3)
    
    col_b1.metric(
        "⚖️ Avg Win vs. Avg Loss", 
        f"${avg_win:,.0f} / ${abs(avg_loss):,.0f}", 
        f"Ratio: {risk_reward:.2f}x", 
        delta_color="normal" if risk_reward >= 1 else "inverse"
    )
    
    col_b2.metric(
        "⏱️ Avg Win Hold Time", 
        f"{avg_days_win:.1f} days", 
        f"Losers held {avg_days_loss:.1f} days", 
        delta_color="inverse" if avg_days_loss > avg_days_win else "normal"
    )
    
    if not eligible_tickers.empty:
        best_ticker_wr = eligible_tickers.loc[eligible_tickers['Win_Rate'].idxmax()]
        col_b3.metric(
            "🎯 Most Reliable Ticker (3+ Trades)", 
            f"{best_ticker_wr.name}", 
            f"{best_ticker_wr['Win_Rate'] * 100:.0f}% Win Rate"
        )
    else:
        col_b3.metric("🎯 Most Reliable Ticker", "Need more data", "Min 3 trades required", delta_color="off")

    st.markdown("### 🛠️ Actionable Recommendations & Learning")
    
    recommendations = []
    
    if risk_reward > 0 and risk_reward < 1.0:
        article = fetch_dynamic_article("how to improve trading risk reward ratio strategy")
        recommendations.append(f"🚨 **Risk/Reward Warning:** Your average loss is larger than your average win. \n\n* **Action:** Consider setting tighter stop-losses to cut losers faster. \n* **Trending Read:** {article}")
    elif risk_reward >= 1.5:
        article = fetch_dynamic_article("how to use trailing stop loss to maximize trading profits")
        recommendations.append(f"✅ **Excellent Risk/Reward:** Your winners are significantly outperforming your losers! \n\n* **Action:** Consider using trailing stop-losses to protect these larger gains. \n* **Trending Read:** {article}")
        
    if avg_days_loss > avg_days_win and avg_days_win > 0:
        article = fetch_dynamic_article("trading psychology cutting losses short")
        recommendations.append(f"📉 **Bag Holding Alert:** You hold onto losing trades longer than winning trades, tying up capital. \n\n* **Action:** Try implementing a strict 'time-stop' (e.g., if a trade doesn't move in your favor after a few days, cut it). \n* **Trending Read:** {article}")
    elif avg_days_win > avg_days_loss and avg_days_loss > 0:
        recommendations.append("📈 **Great Holding Discipline:** You are cutting losers faster than you close winners. Keep trusting your early exit indicators on losing setups.")
        
    if win_rate < 40 and total_trades >= 5:
        article = fetch_dynamic_article("how to improve trading win rate setup criteria")
        recommendations.append(f"⚠️ **Low Win Rate:** With a win rate below 40%, you might be forcing trades. \n\n* **Action:** Review your entry criteria. Trade less frequently and wait for A+ setups. \n* **Trending Read:** {article}")
        
    if not eligible_tickers.empty and best_ticker_wr['Win_Rate'] >= 0.7:
        article = fetch_dynamic_article("position sizing strategy in stock options trading")
        recommendations.append(f"⭐ **Double Down on {best_ticker_wr.name}:** You have a highly successful track record ({best_ticker_wr['Win_Rate'] * 100:.0f}% win rate) trading **{best_ticker_wr.name}**. \n\n* **Action:** Consider scaling up your position sizing on A+ setups for this specific ticker. \n* **Trending Read:** {article}")

    if recommendations:
        for rec in recommendations:
            if "Warning" in rec or "Alert" in rec or "Low" in rec:
                st.warning(rec)
            else:
                st.success(rec)
    else:
        st.info("Keep trading! Once you have more data, advanced behavioral recommendations and live trending articles will appear here.")

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
        
        valid_dates['Is_Put'] = valid_dates['Contract Description'].str.contains('Put', case=False, na=False)
        valid_dates['Is_Call'] = valid_dates['Contract Description'].str.contains('Call', case=False, na=False)
        
        monthly_summary = valid_dates.groupby(['Month_Sort', 'Month']).agg(
            Total_Trades=('Ticker', 'count'),
            Wins=('Net Change', lambda x: (x > 0).sum()),
            Losses=('Net Change', lambda x: (x < 0).sum()),
            Net_Profit=('Net Change', 'sum'),
            Unique_Tickers=('Ticker', 'nunique'),
            Puts=('Is_Put', 'sum'),
            Calls=('Is_Call', 'sum')
        ).reset_index().sort_values('Month_Sort')
        
        monthly_summary = monthly_summary.drop(columns=['Month_Sort'])
        monthly_summary.rename(columns={
            'Wins': 'Trades with Profit', 
            'Losses': 'Trades with Loss', 
            'Net_Profit': 'Total Net Profit/Loss',
            'Unique_Tickers': 'Unique Tickers',
            'Puts': 'No of PUTS',
            'Calls': 'No of CALLS'
        }, inplace=True)
        
        st.dataframe(monthly_summary.style.format({'Total Net Profit/Loss': '${:,.2f}'}), width='stretch')
        
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("#### P&L By Month")
            chart_data = monthly_summary[['Month', 'Total Net Profit/Loss']].set_index('Month')
            st.bar_chart(chart_data)
            
        with col_chart2:
            if category_name == "All Data":
                st.markdown("#### Trades by Category")
                cat_counts = df_subset['Asset Category'].value_counts()
                st.bar_chart(cat_counts)
            else:
                st.markdown("#### Win vs Loss Ratio")
                wl_data = pd.DataFrame({'Count': [winning_trades, losing_trades]}, index=['Wins', 'Losses'])
                st.bar_chart(wl_data)
    else:
        st.info("Not enough dated transactions to generate monthly tracking.")

    st.markdown("---")
    
    st.markdown(f"### 📋 {category_name} - Trade Details")
    display_df = df_temp.drop(columns=['Sell_DT', 'Buy_DT', 'Month_Date', 'Month', 'Month_Sort', 'Is_Put', 'Is_Call', 'Status'], errors='ignore')
    st.dataframe(display_df, width='stretch')


# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood P&L Dashboard", layout="wide")

st.sidebar.markdown("## About the Creator")
# --- UPDATED TEXT HERE ---
st.sidebar.markdown("This tool was built to automate Robinhood options and stock P&L tracking, specifically optimized for options trading.")
st.sidebar.markdown("---")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")

st.title("📈 Interactive Robinhood P&L Dashboard")
st.write("Upload your raw Robinhood statement CSV to generate your dynamic trading tracker.")

with st.expander("ℹ️ How to get your Robinhood CSV"):
    st.markdown("""
    **From a Web Browser (Recommended):**
    1. Log in to your [Robinhood Account](https://robinhood.com).
    2. Go directly to your [Reports and Statements page](https://robinhood.com/account/reports) (or click **Account** > **Reports and Statements**).
    3. Under **Account History**, click **Export as CSV**.
    
    **From the Mobile App ([iOS](https://apps.apple.com/us/app/robinhood-investing-for-all/id938003185) / [Android](https://play.google.com/store/apps/details?id=com.robinhood.android)):**
    1. Tap your **Profile** icon in the bottom right corner.
    2. Tap the **Menu** (three lines) in the top left corner.
    3. Tap **Investing**.
    4. Scroll down and tap **Reports and statements**.
    5. Tap **Account History** and export the file.
    """)

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file is not None:
    with st.spinner("Processing your trades..."):
        try:
            df_result = process_robinhood_csv(uploaded_file)
            df_result['Net Change'] = pd.to_numeric(df_result['Net Change'], errors='coerce').fillna(0)
            
            open_options_mask = df_result['Asset Category'].isin(['Option', 'Covered Call']) & (df_result['Status'] == 'Open')
            df_result = df_result[~open_options_mask]
            
            available_categories = sorted(df_result['Asset Category'].unique().tolist())
            tab_names = ["All Data"] + available_categories
            
            tabs = st.tabs(tab_names)
            
            for i, tab in enumerate(tabs):
                with tab:
                    if tab_names[i] == "All Data":
                        render_dashboard_view(df_result, "All Data")
                    else:
                        cat = tab_names[i]
                        render_dashboard_view(df_result[df_result['Asset Category'] == cat].copy(), cat)
            
            st.markdown("---")
            
            st.markdown("### Export Full Report")
            df_export = df_result.drop(columns=['Status'], errors='ignore')
            csv_data = df_export.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="📥 Download Processed CSV File (Completed Trades)",
                data=csv_data,
                file_name="Robinhood_PL_Summary.csv",
                mime="text/csv"
            )
            
        except Exception as e:
            st.error(f"An error occurred while processing the file: {e}")
