# File: model/feature_engineering.py
from sklearn.base import BaseEstimator, TransformerMixin
import pandas as pd
import numpy as np

class CreditFeatureEngineer(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.pay_cols = ['PAY_0', 'PAY_2', 'PAY_3', 'PAY_4', 'PAY_5', 'PAY_6']
        self.bill_cols = ['BILL_AMT1', 'BILL_AMT2', 'BILL_AMT3', 'BILL_AMT4', 'BILL_AMT5', 'BILL_AMT6']
        self.pay_amt_cols = ['PAY_AMT1', 'PAY_AMT2', 'PAY_AMT3', 'PAY_AMT4', 'PAY_AMT5', 'PAY_AMT6']

    def fit(self, X, y=None):
        _, self.limit_bins_ = pd.qcut(
            X['LIMIT_BAL'], q=3, retbins=True, duplicates='drop'
        )
        self.limit_bins_[0] = -np.inf
        self.limit_bins_[-1] = np.inf
        return self

    def transform(self, X, y=None):
        X_new = X.copy()

        # 1. Nhóm PAY: Trễ hạn
        X_new['max_delay'] = X_new[self.pay_cols].max(axis=1)
        X_new['avg_delay'] = X_new[self.pay_cols].mean(axis=1)
        X_new['count_overdue'] = (X_new[self.pay_cols] > 0).sum(axis=1)

        # 2. Nhóm BILL_AMT: Hóa đơn
        X_new['avg_bill'] = X_new[self.bill_cols].mean(axis=1)
        X_new['bill_trend'] = X_new['BILL_AMT1'] - X_new['BILL_AMT6']

        # 3. Nhóm PAY_AMT: Tỷ lệ trả nợ
        total_pay = X_new[self.pay_amt_cols].sum(axis=1)
        total_bill = X_new[self.bill_cols].sum(axis=1)
        X_new['payment_ratio'] = total_pay / (total_bill + 1e-5)

        # 4. Rời rạc hóa
        X_new['limit_category'] = pd.cut(X_new['LIMIT_BAL'], bins=self.limit_bins_, labels=[0, 1, 2], include_lowest=True).astype(float)
        X_new['age_group'] = pd.cut(X_new['AGE'], bins=[20, 30, 45, 60, 100], labels=[0, 1, 2, 3]).astype(float)


        return X_new

    def get_feature_names_out(self, input_features=None):
        if input_features is None:
            return None

        # Danh sách các cột mới được sinh ra thêm từ hàm transform
        new_features = [
            'max_delay', 'avg_delay', 'count_overdue',
            'avg_bill', 'bill_trend', 'payment_ratio',
            'limit_category', 'age_group'
        ]

        # Đầu ra sẽ bao gồm toàn bộ cột gốc + các cột mới sinh ra
        return np.array(list(input_features) + new_features, dtype=object)