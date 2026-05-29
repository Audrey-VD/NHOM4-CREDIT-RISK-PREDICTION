import os
import json
import shap
import joblib
import torch
import torch.nn as nn
import numpy as np
import pandas as pd
import time
from etl.sheets_to_df import pull_sheets, pivot_to_wide
from api.database import insert_predictions, log_etl_run

class FeatureTokenizer(nn.Module):
    def __init__(self, n_features, d_token):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(n_features, d_token))
        self.bias = nn.Parameter(torch.zeros(n_features, d_token))
        nn.init.kaiming_uniform_(self.weight, a=np.sqrt(5))
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_token))

    def forward(self, x):
        tokens = x.unsqueeze(-1) * self.weight + self.bias
        cls = self.cls_token.expand(x.size(0), -1, -1)
        return torch.cat([cls, tokens], dim=1)

class FTTransformer(nn.Module):
    def __init__(self, n_features, d_token=64, n_heads=8, n_layers=3, dropout=0.1):
        super().__init__()
        self.tokenizer = FeatureTokenizer(n_features, d_token)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_token, nhead=n_heads, dim_feedforward=d_token * 4,
            dropout=dropout, batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.head = nn.Sequential(nn.LayerNorm(d_token), nn.ReLU(), nn.Linear(d_token, 1))

    def forward(self, x):
        out = self.transformer(self.tokenizer(x))
        return self.head(out[:, 0, :])

loop = None
sse_queue = None

def load_trained_model():
    config_path = "model/config.json"
    if not os.path.exists(config_path):
        return None, None, 0.5, "sklearn"
        
    with open(config_path, "r") as f:
        config = json.load(f)
        
    model_type = config.get("model_type", "sklearn")
    threshold = config.get("optimal_threshold", 0.5)

    preprocessor = None
    if os.path.exists("model/preprocessor.pkl"):
        preprocessor = joblib.load("model/preprocessor.pkl")

    if model_type == "pytorch":
        checkpoint = torch.load("model/model.pkl", map_location="cpu")
        model = FTTransformer(n_features=checkpoint["n_features"])
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
    else:
        model = joblib.load("model/model.pkl")
        
    return model, preprocessor, threshold, model_type

def predict_probabilities(model, preprocessor, model_type, df_input):
    """Hàm wrapper xử lý inference sử dụng chính xác Pipeline biến đổi từ file pickle"""

    df_mapped = df_input.copy()
    df_mapped.columns = [col.upper() for col in df_mapped.columns]

    if preprocessor is not None:
        try:
            X_matrix = preprocessor.transform(df_mapped)
        except Exception as e:
            print(f"⚠️ [Lỗi Preprocessor]: Không thể biến đổi dữ liệu tự động: {str(e)}")
            raise e
    else:
        X_matrix = df_mapped.to_numpy()

    if model_type == "pytorch":
        with torch.no_grad():
            X_tensor = torch.tensor(X_matrix.astype(np.float32))
            logits = model(X_tensor).squeeze()
            probs = torch.sigmoid(logits).numpy()
            return np.array([probs]) if probs.ndim == 0 else probs
    else:
        return model.predict_proba(X_matrix)[:, 1]

def map_features_to_array(features_dict):
    ordered_keys = [
        "pay_0", "limit_bal", "age", "sex", "education", "marriage",
        "pay_2", "pay_3", "pay_4", "pay_5", "pay_6",
        "bill_amt1", "bill_amt2", "bill_amt3", "bill_amt4", "bill_amt5", "bill_amt6",
        "pay_amt1", "pay_amt2", "pay_amt3", "pay_amt4", "pay_amt5", "pay_amt6"
    ]
    return np.array([[features_dict.get(k, 0.0) for k in ordered_keys]])

def run_etl_and_predict(queue_obj, event_loop):
    """ Tiến trình chạy ngầm ETL định kỳ hoặc kích hoạt qua Webhook """
    try:
        df_info, df_bill, df_pay, df_status = pull_sheets()
        df_raw = pivot_to_wide(df_info, df_bill, df_pay, df_status)
        customer_ids = df_raw['id'].tolist()
        df_raw = df_raw.drop(columns=['id'])
        df_raw.columns = [col.upper() for col in df_raw.columns]

        model, preprocessor, threshold, model_type = load_trained_model()
        if model is None:
            raise FileNotFoundError("Chưa tìm thấy tệp tin model.pkl. Vui lòng chạy Train trước!")

        probs = predict_probabilities(model, preprocessor, model_type, df_raw)
        probs_min, probs_max = probs.min(), probs.max()

        if probs_max - probs_min > 0.001:
            probs = (probs - probs_min) / (probs_max - probs_min) * 0.7 + 0.3

        X_matrix = preprocessor.transform(df_raw)

        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_matrix)

            if isinstance(shap_values, list):
                shap_matrix = shap_values[1]
            else:
                shap_matrix = shap_values
        except Exception as e:
            shap_matrix = None

        feature_names = df_raw.columns.tolist()

        records_to_insert = []
        for idx in range(len(df_raw)):
            p = float(probs[idx])
            if p >= 0.6:
                risk = "High"
            elif p >= 0.45:
                risk = "Medium"
            else:
                risk = "Low"

            customer_shap = []
            if shap_matrix is not None:
                for f_idx, f_name in enumerate(feature_names):
                    customer_shap.append({
                        "feature": str(f_name),
                        "value": float(shap_matrix[idx, f_idx])
                    })
            else:
                customer_shap = []

            records_to_insert.append({
                "customer_id": str(customer_ids[idx]),
                "limit_bal": float(df_raw.iloc[idx]["LIMIT_BAL"]),
                "age": int(df_raw.iloc[idx]["AGE"]),
                "pay_0": int(df_raw.iloc[idx]["PAY_0"]),
                "probability": p,
                "risk_level": risk,
                "shap_features": json.dumps(customer_shap),
                "predicted_at": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            
        insert_predictions(records_to_insert)
        log_etl_run(len(df_raw), "Success")

        if event_loop and queue_obj:
            import asyncio
            asyncio.run_coroutine_threadsafe(queue_obj.put("new_predictions"), event_loop)
            
    except Exception as e:
        print(f"❌ [Lỗi Hệ Thống Pipeline]: {str(e)}")
        log_etl_run(0, f"Failed: {str(e)}")