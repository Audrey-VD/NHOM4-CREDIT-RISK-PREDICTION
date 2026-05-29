import os
import gspread
import pandas as pd
import numpy as np
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")

def pull_sheets():
    # Đường dẫn tới file JSON chứng thực của Google Service Account của bạn
    service_account_file = "service-account.json"

    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = Credentials.from_service_account_file(service_account_file, scopes=scopes)
    gc = gspread.authorize(credentials)

    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_KEY)

    df_info = pd.DataFrame(spreadsheet.worksheet('customer_info').get_all_records())
    df_bill = pd.DataFrame(spreadsheet.worksheet('billing_statement').get_all_records())
    df_pay = pd.DataFrame(spreadsheet.worksheet('payment_record').get_all_records())
    df_status = pd.DataFrame(spreadsheet.worksheet('repayment_status').get_all_records())

    return df_info, df_bill, df_pay, df_status


def sort_by_recency(df, date_col, id_col='id'):
    """
    Hàm phụ trợ xử lý thứ tự tháng
    Chuyển chuỗi định dạng MM/YYYY thành kiểu dữ liệu thời gian, sắp xếp giảm dần
    """
    df_sorted = df.copy()

    df_sorted['parsed_date'] = pd.to_datetime(df_sorted[date_col], format='%m/%Y')
    df_sorted = df_sorted.sort_values(by=[id_col, 'parsed_date'], ascending=[True, False])
    df_sorted['month_rank'] = df_sorted.groupby(id_col).cumcount() + 1
    df_sorted = df_sorted[df_sorted['month_rank'] <= 6]

    return df_sorted


def pivot_to_wide(df_info, df_bill, df_pay, df_status):
    """
    Thực hiện quy trình xoay trục dữ liệu từ Long sang Wide Format
    """
    df_bill_sorted = sort_by_recency(df_bill, date_col='statement_date')
    df_bill_pivot = df_bill_sorted.pivot_table(
        index='id',
        columns='month_rank',
        values='bill_amount'
    )

    df_bill_pivot.columns = [f'BILL_AMT{i}' for i in df_bill_pivot.columns]
    df_bill_wide = df_bill_pivot.reset_index()

    df_pay_sorted = sort_by_recency(df_pay, date_col='payment_date')
    df_pay_pivot = df_pay_sorted.pivot_table(
        index='id',
        columns='month_rank',
        values='pay_amount'
    )

    df_pay_pivot.columns = [f'PAY_AMT{i}' for i in df_pay_pivot.columns]
    df_pay_wide = df_pay_pivot.reset_index()

    df_status_sorted = sort_by_recency(df_status, date_col='status_date')
    df_status_pivot = df_status_sorted.pivot_table(
        index='id',
        columns='month_rank',
        values='repayment_status'
    )  #

    status_col_names = {1: 'PAY_0'}
    for r in range(2, 7):
        status_col_names[r] = f'PAY_{r}'

    df_status_pivot = df_status_pivot.rename(columns=status_col_names)
    df_status_wide = df_status_pivot.reset_index()

    df_final = pd.merge(df_info, df_status_wide, on='id', how='left')  #
    df_final = pd.merge(df_final, df_bill_wide, on='id', how='left')  #
    df_final = pd.merge(df_final, df_pay_wide, on='id', how='left')  #

    df_final = df_final.fillna(0)

    expected_columns = [
        'id', 'limit_bal', 'sex', 'education', 'marriage', 'age',
        'PAY_0', 'PAY_2', 'PAY_3', 'PAY_4', 'PAY_5', 'PAY_6',
        'BILL_AMT1', 'BILL_AMT2', 'BILL_AMT3', 'BILL_AMT4', 'BILL_AMT5', 'BILL_AMT6',
        'PAY_AMT1', 'PAY_AMT2', 'PAY_AMT3', 'PAY_AMT4', 'PAY_AMT5', 'PAY_AMT6'
    ]

    df_final = df_final[expected_columns]

    return df_final