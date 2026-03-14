import streamlit as st

import pandas as pd

import numpy as np

import re

import io

import urllib.request

import urllib.parse

import xml.etree.ElementTree as ET

import calendar # New import for calendar logic



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

    winners, losers = df_subset[df_subset['Net Change'] > 0], df_subset[df_subset['Net Change'] < 0]

    win_rate = (len(winners) / (len(winners) + len(losers))) * 100 if (len(winners) + len(losers)) > 0 else 0

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

    dt_df, sw_df = df_subset[df_subset['Trade Style'] == 'Day Trade'], df_subset[df_subset['Trade Style'] == 'Swing Trade']

    dt_pnl, sw_pnl = dt_df['Net Change'].sum(), sw_df['Net Change'].sum()

    with ana_col1:

        st.markdown("**Trade Style Performance**")

        st.write(f"📈 **Swing Trades:** ${sw_pnl:,.2f} ({len(sw_df)} trades)")

        st.write(f"⚡ **Day Trades:** ${dt_pnl:,.2f} ({len(dt_df)} trades)")



    call_df, put_df = df_subset[df_subset['Is_Call'] == True], df_subset[df_subset['Is_Put'] == True]

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

            st.write(f"✅ **Best Day:** {best_day['Buy DoW']} (${best_day['Net_Profit']:,.0f})")

            st.write(f"❌ **Worst Day:** {worst_day['Buy DoW']} (${worst_day['Net_Profit']:,.0f})")



    st.markdown("---")



    # (Behavioral Logic kept intact as requested)

    st.markdown(f"### 🧠 Trade Behavior & Efficiency")

    avg_win, avg_loss = winners['Net Change'].mean() if not winners.empty else 0, losers['Net Change'].mean() if not losers.empty else 0

    risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    col_b1, col_b2, col_b3 = st.columns(3)

    col_b1.metric("⚖️ Avg Win vs. Avg Loss", f"${avg_win:,.0f} / ${abs(avg_loss):,.0f}", f"Ratio: {risk_reward:.2f}x")

    

    # --- MONTHLY SUMMARY & CALENDAR VIEW ---

    st.markdown("---")

    st.markdown(f"### 📅 {category_name} - Monthly Calendar")

    df_temp = df_subset.copy()

    df_temp['Month_Date'] = pd.to_datetime(df_temp['Sell Date'], errors='coerce').fillna(pd.to_datetime(df_temp['Buy Date'], errors='coerce'))

    valid_dates = df_temp.dropna(subset=['Month_Date']).copy()

    

    if not valid_dates.empty:

        valid_dates['Month'] = valid_dates['Month_Date'].dt.strftime('%B %Y')

        valid_dates['Month_Sort'] = valid_dates['Month_Date'].dt.to_period('M')

        monthly_summary = valid_dates.groupby(['Month_Sort', 'Month']).agg(

            Total_Trades=('Ticker', 'count'), Wins=('Net Change', lambda x: (x > 0).sum()),

            Net_Profit=('Net Change', 'sum'), Unique_Tickers=('Ticker', 'nunique'),

            Puts=('Is_Put', 'sum'), Calls=('Is_Call', 'sum')

        ).reset_index().sort_values('Month_Sort', ascending=False)

        

        st.dataframe(monthly_summary.drop(columns=['Month_Sort']).rename(columns={'Wins': 'Profit Trades', 'Net_Profit': 'Total P&L'}), width='stretch')



        # CALENDAR LOGIC

        st.markdown("#### Monthly Day-by-Day Audit")

        selected_month = st.selectbox(f"Select Month to View Calendar ({category_name})", monthly_summary['Month'].tolist(), key=f"cal_{category_name}")

        

        cal_data = valid_dates[valid_dates['Month'] == selected_month].copy()

        cal_data['Day'] = cal_data['Month_Date'].dt.day

        cal_data['Weekday'] = cal_data['Month_Date'].dt.weekday # 0=Monday, 6=Sunday

        

        daily_pnl = cal_data.groupby('Day')['Net Change'].sum().to_dict()

        

        # Build Calendar Matrix

        year = int(cal_data['Month_Date'].iloc[0].year)

        month_idx = int(cal_data['Month_Date'].iloc[0].month)

        month_cal = calendar.monthcalendar(year, month_idx)

        

        cal_df = pd.DataFrame(month_cal, columns=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])

        

        def format_cell(day):

            if day == 0: return ""

            pnl = daily_pnl.get(day, 0)

            if pnl == 0: return f"{day}"

            return f"{day}: ${pnl:,.0f}"



        styled_cal = cal_df.applymap(format_cell)

        

        # Color Coding

        def color_pnl(val):

            if ":" not in val: return ''

            try:

                pnl_val = float(val.split('$')[1].replace(',', ''))

                if pnl_val > 0: return 'background-color: #d4edda; color: #155724; font-weight: bold'

                if pnl_val < 0: return 'background-color: #f8d7da; color: #721c24; font-weight: bold'

            except: pass

            return ''



        st.table(styled_cal.style.applymap(color_pnl))

        

    st.markdown("---")

    st.markdown(f"### 📋 {category_name} - Trade Details")

    st.dataframe(df_temp.drop(columns=['Month_Date'], errors='ignore'), width='stretch')



# --- STREAMLIT UI ---

st.set_page_config(page_title="Robinhood P&L Dashboard", layout="wide")

st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")

st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")

st.title("📈 Interactive Robinhood P&L Dashboard")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])



if uploaded_file is not None:

    df_result = process_robinhood_csv(uploaded_file)

    df_result = df_result[df_result['Asset Category'].isin(['Option', 'Covered Call'])]

    available_categories = sorted(df_result['Asset Category'].unique().tolist())

    tab_names = ["All Data"] + available_categories

    tabs = st.tabs(tab_names)

    for i, tab in enumerate(tabs):

        with tab:

            render_dashboard_view(df_result if tab_names[i] == "All Data" else df_result[df_result['Asset Category'] == tab_names[i]], tab_names[i])
