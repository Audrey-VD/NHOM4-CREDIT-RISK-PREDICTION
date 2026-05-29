import os
import io
import json
import time
import asyncio
from typing import List, Set
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from api.database import create_tables, get_high_risk, get_stats, insert_predictions
import api.scheduler as scheduler

load_dotenv()
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "super-secret-mops-token")
NODE_ID = os.getenv("NODE_ID", "vps-unknown-node")
START_TIME = time.time()

app = FastAPI(
    title="Credit Risk MLOps Pipeline API",
    description="Hệ thống API dịch vụ dự đoán rủi ro vỡ nợ tín dụng cá nhân tích hợp HPC Docker Swarm Cluster.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security_scheme = HTTPBearer()

connected_clients: Set[asyncio.Queue] = set()
main_loop = None

@app.on_event("startup")
async def startup():
    global main_loop
    main_loop = asyncio.get_running_loop()
    create_tables()

    scheduler.loop = main_loop
    scheduler.sse_queue = asyncio.Queue()

    asyncio.create_task(broadcast_coordinator())

async def broadcast_coordinator():
    while True:
        event = await scheduler.sse_queue.get()
        if event == "new_predictions":
            for client_queue in list(connected_clients):
                await client_queue.put("new_predictions")

class CreditFeatures(BaseModel):
    limit_bal: float = Field(..., example=50000)
    sex: int = Field(..., description="1 = Male, 2 = Female", example=2)
    education: int = Field(..., description="1=grad, 2=undergrad, 3=highschool, 4=others", example=2)
    marriage: int = Field(..., description="1=married, 2=single, 3=others", example=1)
    age: int = Field(..., example=34)
    pay_0: int = Field(..., description="Tình trạng trả nợ tháng gần nhất (-1=đúng hạn, 1=trễ 1 tháng...)", example=0)
    pay_2: int = Field(..., example=0)
    pay_3: int = Field(..., example=0)
    pay_4: int = Field(..., example=0)
    pay_5: int = Field(..., example=0)
    pay_6: int = Field(..., example=0)
    bill_amt1: float = Field(..., example=3913)
    bill_amt2: float = Field(..., example=3102)
    bill_amt3: float = Field(..., example=2833)
    bill_amt4: float = Field(..., example=2893)
    bill_amt5: float = Field(..., example=2920)
    bill_amt6: float = Field(..., example=2950)
    pay_amt1: float = Field(..., example=0)
    pay_amt2: float = Field(..., example=1500)
    pay_amt3: float = Field(..., example=1000)
    pay_amt4: float = Field(..., example=1000)
    pay_amt5: float = Field(..., example=0)
    pay_amt6: float = Field(..., example=2000)

def verify_bearer_token(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)):
    if credentials.credentials != SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc không có quyền truy cập!"
        )
    return credentials.credentials

# --- ENDPOINT 1: GET /health (Kiểm tra An Toàn Kiến Trúc Dynamic Inference thực tế) ---
@app.get("/health", tags=["Infrastructure"])
def health_check():
    uptime_seconds = time.time() - START_TIME
    model_path = os.path.join("model", "model.pkl")
    preprocessor_path = os.path.join("model", "preprocessor.pkl")
    
    is_model_ok = os.path.exists(model_path)
    is_preprocessor_ok = os.path.exists(preprocessor_path)
    system_healthy = is_model_ok and is_preprocessor_ok
    
    return {
        "status": "healthy" if system_healthy else "unhealthy",
        "node_id": NODE_ID,
        "dynamic_inference_check": {
            "model_artifact_loaded": is_model_ok,
            "preprocessor_artifact_loaded": is_preprocessor_ok
        },
        "uptime": f"{uptime_seconds:.2f}s"
    }

# --- ENDPOINT 2: POST /etl-trigger ---
@app.post("/etl-trigger", status_code=status.HTTP_202_ACCEPTED, tags=["Data Pipeline"])
def etl_trigger_endpoint(
        payload: dict,
        background_tasks: BackgroundTasks,
        token: str = Depends(verify_bearer_token)
):
    background_tasks.add_task(scheduler.run_etl_and_predict, scheduler.sse_queue, main_loop)
    return {
        "status": "Accepted",
        "message": "Webhook hợp lệ. Tiến trình ETL và Inference đã bắt đầu chạy ngầm."
    }

# --- ENDPOINT 3: POST /predict ---
@app.post("/predict", status_code=status.HTTP_200_OK, tags=["Machine Learning"])
def predict_single_customer(features: CreditFeatures, token: str = Depends(verify_bearer_token)):
    try:
        import pandas as pd
        df_raw = pd.DataFrame([features.model_dump()])

        model, preprocessor, threshold, model_type = scheduler.load_trained_model()
        if model is None:
            raise HTTPException(status_code=500, detail="Chưa cấu hình hoặc thiếu file model.pkl.")

        from api.scheduler import predict_probabilities
        probs = predict_probabilities(model, preprocessor, model_type, df_raw)
        p = float(probs[0])

        if p >= threshold:
            risk_level = "High"
        elif p >= (threshold * 0.5):
            risk_level = "Medium"
        else:
            risk_level = "Low"
            
        return {
            "node_served": NODE_ID,
            "probability": p,
            "risk_level": risk_level,
            "model_used": model_type.upper(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi xử lý Inference đơn lẻ: {str(e)}"
        )

# --- ENDPOINT 4: POST /batch-predict ---
@app.post("/batch-predict", status_code=status.HTTP_200_OK, tags=["Machine Learning"])
def batch_predict_endpoint(records: List[CreditFeatures], token: str = Depends(verify_bearer_token)):
    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Danh sách bản ghi đầu vào không được để trống!"
        )
        
    try:
        processed_count = len(records)
        import pandas as pd
        import numpy as np
        
        df_raw = pd.DataFrame([r.model_dump() for r in records])
        model, preprocessor, threshold, model_type = scheduler.load_trained_model()
        
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Hệ thống chưa tìm thấy tệp tin model.pkl trên Server."
            )

        from api.scheduler import predict_probabilities
        probs = predict_probabilities(model, preprocessor, model_type, df_raw)
            
        records_to_insert = []
        for i in range(processed_count):
            p = float(probs[i])
            if p >= threshold:
                risk = "High"
            elif p >= (threshold * 0.5):
                risk = "Medium"
            else:
                risk = "Low"
                
            records_to_insert.append({
                "limit_bal": float(df_raw.iloc[i]["limit_bal"]),
                "age": int(df_raw.iloc[i]["age"]),
                "pay_0": int(df_raw.iloc[i]["pay_0"]),
                "probability": p,
                "risk_level": risk,
                "predicted_at": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            
        insert_predictions(records_to_insert)
    
        if main_loop and scheduler.sse_queue:
            asyncio.run_coroutine_threadsafe(scheduler.sse_queue.put("new_predictions"), main_loop)
    
        return {
            "status": "Success",
            "message": f"Đã xử lý batch gồm {processed_count} khách hàng thành công qua mô hình {model_type.upper()}.",
            "node_id": NODE_ID
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi tính toán hệ thống Pipeline tại Endpoint Batch: {str(e)}"
        )

# --- ENDPOINT 5: GET /etl-trigger ---
@app.get("/etl-trigger", status_code=status.HTTP_202_ACCEPTED, tags=["Data Pipeline"])
def manual_etl_trigger_get(background_tasks: BackgroundTasks, token: str = Depends(verify_bearer_token)):
    background_tasks.add_task(scheduler.run_etl_and_predict, scheduler.sse_queue, main_loop)
    return {
        "status": "Accepted",
        "message": "Kích hoạt thủ công thành công. Pipeline ETL đang thực thi ngầm."
    }

# --- ENDPOINT 6: GET /dashboard-data ---
@app.get("/dashboard-data", tags=["Real-Time Dashboard"])
async def dashboard_data_stream():
    async def event_generator():
        my_queue = asyncio.Queue()
        connected_clients.add(my_queue)
        try:
            while True:
                event = await my_queue.get()
                if event == "new_predictions":
                    yield "data: new_predictions\n\n"
        except asyncio.CancelledError:
            connected_clients.discard(my_queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- ENDPOINT 7: GET /api/high-risk ---
@app.get("/api/high-risk", tags=["Real-Time Dashboard"])
def api_high_risk_customers():
    db_data = get_high_risk()
    if not db_data:
        return {"status": "success", "count": 0, "data": []}

    for row in db_data:
        if row.get("shap_features"):
            try:
                row["shap_features"] = json.loads(row["shap_features"])
            except Exception:
                row["shap_features"] = None


    return {"status": "success", "count": len(db_data), "data": db_data}

# --- ENDPOINT 8: GET /api/stats ---
@app.get("/api/stats", tags=["Real-Time Dashboard"])
def api_dashboard_stats():
    stats = get_stats()  
    if isinstance(stats, dict):
        total = stats.get("total", 0)
        high = stats.get("high", 0)
        medium = stats.get("medium", 0)
        low = stats.get("low", 0)
    elif isinstance(stats, (list, tuple)) and len(stats) >= 4:
        total, high, medium, low = stats[0], stats[1], stats[2], stats[3]
    else:
        total, high, medium, low = 0, 0, 0, 0

    return {
        "node_id": NODE_ID,
        "metrics": {
            "total": total, "high": high, "medium": medium, "low": low
        }
    }

# --- ENDPOINT 9: GET / (Chuyển hướng trang chủ về thẳng Dashboard) ---
@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/dashboard")

app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")