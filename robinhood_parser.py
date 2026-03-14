import streamlit as st
import pandas as pd
import numpy as np
import re
import io

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
            'Asset Category': final_type
        })

    df_summary = pd.DataFrame(summary_rows)
    df_summary['Sort_Date'] = pd.to_datetime(df_summary['Buy Date'], errors='coerce')
    df_summary = df_summary.sort_values('Sort_Date', ascending=False).drop(columns=['Sort_Date'])
    
    return df_summary

def render_dashboard_view(df_subset, category_name):
    """Generates the full dashboard UI for a specific subset of data."""
    if df_subset.empty:
        st.info(f"No data available for {category_name}.")
        return

    # Calculate Top-Level KPIs
    total_pnl = df_subset['Net Change'].sum()
    total_trades = len(df_subset)
    winning_trades = len(df_subset[df_subset['Net Change'] > 0
