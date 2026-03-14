import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import openpyxl

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
    """Generates the full dashboard UI for a specific subset of data."""
    if df_subset.empty:
        st.info(f"No completed trades available for {category_name}.")
        return

    # Calculate Top-Level KPIs
    total_pnl = df_subset['Net Change'].sum()
    total_trades = len(df_subset)
    winning_trades = len(df_subset[df_subset['Net Change'] > 0])
    losing_trades = len(df_subset[df_subset['Net Change'] < 0])
    win_rate = (winning_trades / (winning_trades + losing_trades)) * 100 if (winning_trades + losing_trades) > 0 else 0
    
    # --- KPI ROW ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net Profit/Loss", f"${total_pnl:,.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Trades with Profit", winning_trades)
    col4.metric("Total Trades", total_trades)
    
    st.markdown("---")
    
    # --- MONTHLY SUMMARY ---
    st.markdown(f"### {category_name} - Monthly Summary")
    df_temp = df_subset.copy()
    df_temp['Sell_DT'] = pd.to_datetime(df_temp['Sell Date'], errors='coerce')
    df_temp['Buy_DT'] = pd.to_datetime(df_temp['Buy Date'], errors='coerce')
    df_temp['Month_Date'] = df_temp['Sell_DT'].fillna(df_temp['Buy_DT'])
    
    # Filter rows that have a valid date
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
        
        # --- CHARTS ---
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
    
    # --- DATA TABLE ---
    st.markdown(f"### {category_name} - Trade Details")
    display_df = df_temp.drop(columns=['Sell_DT', 'Buy_DT', 'Month_Date', 'Month', 'Month_Sort', 'Is_Put', 'Is_Call', 'Status'], errors='ignore')
    st.dataframe(display_df, width='stretch')


# --- STREAMLIT UI ---
st.set_page_config(page_title="Robinhood P&L Dashboard", layout="wide")

# --- SIDEBAR: AUTHOR INFO ---
st.sidebar.markdown("## About the Creator")
st.sidebar.markdown("This tool was built to automate Robinhood options and stock P&L tracking, specifically optimized for covered calls and monthly tracking.")
st.sidebar.markdown("---")
st.sidebar.markdown("👨‍💻 **Created by Puneeth Rao**")
st.sidebar.markdown("🔗 [Connect with me on LinkedIn](https://www.linkedin.com/in/puneeth-rao/)")

# --- MAIN DASHBOARD ---
st.title("📈 Interactive Robinhood P&L Dashboard")
st.write("Upload your raw Robinhood statement CSV to generate your dynamic trading tracker.")

uploaded_file = st.file_uploader("Upload Robinhood CSV", type=["csv"])

if uploaded_file is not None:
    with st.spinner("Processing your trades..."):
        try:
            # Process the file
            df_result = process_robinhood_csv(uploaded_file)
            df_result['Net Change'] = pd.to_numeric(df_result['Net Change'], errors='coerce').fillna(0)
            
            # Remove Open Options and Open Covered Calls before rendering dashboard
            # This ensures only realized/completed option trades affect the charts and P&L
            open_options_mask = df_result['Asset Category'].isin(['Option', 'Covered Call']) & (df_result['Status'] == 'Open')
            df_result = df_result[~open_options_mask]
            
            # Determine available categories
            available_categories = sorted(df_result['Asset Category'].unique().tolist())
            tab_names = ["All Data"] + available_categories
            
            # Create Tabs
            tabs = st.tabs(tab_names)
            
            # Populate Tabs
            for i, tab in enumerate(tabs):
                with tab:
                    if tab_names[i] == "All Data":
                        render_dashboard_view(df_result, "All Data")
                    else:
                        cat = tab_names[i]
                        render_dashboard_view(df_result[df_result['Asset Category'] == cat].copy(), cat)
            
            st.markdown("---")
            
            # --- GLOBAL DOWNLOAD BUTTON ---
            st.markdown("### Export Full Report")
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                # We export the full dataset regardless of what tab is open
                df_export = df_result.drop(columns=['Status'], errors='ignore')
                df_export.to_excel(writer, index=False, sheet_name='P&L Summary')
            
            st.download_button(
                label="📥 Download Raw Processed Excel File (Completed Trades)",
                data=buffer.getvalue(),
                file_name="Robinhood_PL_Summary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        except Exception as e:
            st.error(f"An error occurred while processing the file: {e}")
