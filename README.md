# 🏦 Credit Risk MLOps Pipeline

Hệ thống dự đoán rủi ro vỡ nợ tín dụng cá nhân tích hợp pipeline tự động hoàn chỉnh: **Google Sheets → ETL → Machine Learning → Docker Swarm → Real-time Dashboard**.

---

## 📋 Mục lục

- [Tổng quan hệ thống](#tổng-quan-hệ-thống)
- [Kiến trúc](#kiến-trúc)
- [Công nghệ sử dụng](#công-nghệ-sử-dụng)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Cài đặt và chạy](#cài-đặt-và-chạy)
- [Các Endpoint API](#các-endpoint-api)
- [Triển khai Docker Swarm](#triển-khai-docker-swarm)
- [Luồng dữ liệu tự động](#luồng-dữ-liệu-tự-động)

---

## Tổng quan hệ thống

Hệ thống sử dụng bộ dữ liệu **UCI Default of Credit Card Clients** (30,000 mẫu, 25 features) để huấn luyện mô hình **XGBoost** dự đoán khả năng vỡ nợ của khách hàng trong tháng tới.

Điểm khác biệt so với demo thông thường: hệ thống được thiết kế theo mô hình **MLOps thực tế**, trong đó dữ liệu khách hàng mới được nhập vào **Google Sheets**, tự động được kéo về xử lý mỗi ngày qua cơ chế **Webhook + BackgroundTasks**, kết quả dự đoán hiển thị trực tiếp trên **Web Dashboard real-time** không cần reload trang.

Toàn bộ hệ thống được triển khai trên **Docker Swarm Cluster 3 node** với load balancing, rolling update và fault tolerance.

---

## Kiến trúc

```
Google Sheets (4 sheets)
       │
       │  Apps Script – Time trigger 6:00 AM
       │  UrlFetchApp.fetch() POST /etl-trigger
       ▼
┌─────────────────────────────────────────┐
│          FastAPI (Python)               │
│  /etl-trigger  → 202 Accepted ngay      │
│  BackgroundTask: ETL + Inference        │
│  /dashboard-data → SSE stream           │
└──────────┬──────────────────────────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
preprocessor.pkl  model.pkl
(feature eng +   (XGBoost –
 RobustScaler)    predict_proba)
    │             │
    └──────┬──────┘
           │
           ▼
    SQLite Database
    (predictions, etl_log)
           │
           │  SSE push "new_predictions"
           ▼
    Web Dashboard
    (auto-refresh, DataTables, Chart.js)
           │
    ┌──────┴──────────────┐
    │  Docker Swarm       │
    │  vps1 (manager)     │
    │  vps2 (worker)      │
    │  vps3 (worker)      │
    │  3 replicas – IPVS  │
    └─────────────────────┘
```

### Tại sao tách `preprocessor.pkl` và `model.pkl`?

Thay vì gộp chung thành một `pipeline.pkl`, hệ thống tách thành hai artifact độc lập:

| Artifact | Nội dung | Cập nhật khi nào |
|---|---|---|
| `preprocessor.pkl` | `CreditFeatureEngineer` + `ColumnTransformer` (RobustScaler + OHE) | Khi định nghĩa features thay đổi hoặc data drift ở tầng features |
| `model.pkl` | XGBoost đã train | Khi concept drift – phân phối target thay đổi theo thời gian |

Lợi ích: có thể swap `model.pkl` mới mà không cần refit scaler; debug độc lập từng tầng.

---

## Công nghệ sử dụng

### API & Backend
- **FastAPI** – REST API, BackgroundTasks, Server-Sent Events (SSE)
- **Uvicorn** – ASGI server
- **APScheduler** – Cron job fallback khi không có Webhook
- **SQLite** – WAL mode, index tối ưu cho Dashboard queries

### Machine Learning
- **XGBoost** – Mô hình chính (scale_pos_weight xử lý imbalanced)
- **scikit-learn** – Pipeline, ColumnTransformer, RobustScaler, OneHotEncoder
- **imbalanced-learn** – SMOTE
- **SHAP** – Giải thích mô hình

### Feature Engineering (`CreditFeatureEngineer`)
8 derived features được tạo tự động từ 23 features gốc:

| Feature | Ý nghĩa tài chính |
|---|---|
| `max_delay` | Số tháng trễ tệ nhất – chỉ báo rủi ro trực tiếp |
| `avg_delay` | Mức độ trễ trung bình 6 tháng |
| `count_overdue` | Số tháng thực sự trễ (PAY > 0) |
| `avg_bill` | Dư nợ trung bình 6 tháng |
| `bill_trend` | Xu hướng dư nợ (BILL_AMT1 − BILL_AMT6) |
| `payment_ratio` | Tổng đã trả / tổng hóa đơn |
| `limit_category` | Phân tầng hạn mức (bins học từ train set) |
| `age_group` | Nhóm tuổi theo ngữ nghĩa tài chính |

### Data & ETL
- **gspread** – Kết nối Google Sheets API
- **pandas** – Pivot long → wide format, join 4 bảng
- **Google Apps Script** – Webhook trigger tự động 6:00 AM

### Frontend Dashboard
- **Bootstrap 5** – Layout responsive
- **DataTables.js** – Bảng sortable, searchable, export CSV
- **Chart.js** – Pie chart, Line chart
- **EventSource API (SSE)** – Auto-refresh real-time

### HPC Infrastructure
- **Docker** – Containerization
- **Docker Swarm** – Orchestration, load balancing (IPVS), rolling update
- **Docker Machine + Hyper-V** – 3 Virtual Machines

---

## Cấu trúc dự án

```
credit_risk_predictor/
│
├── requirements.txt            # Python dependencies
├── service-account.json        # Google Service Account (KHÔNG commit lên Git)
├── credit_risk.db              # SQLite database (tự tạo khi chạy)
├── .env                        # Biến môi trường (KHÔNG commit lên Git)
│
├── docker/
│   ├── Dockerfile              # Build image API service
│   └── swarm-stack.yml         # Cấu hình Docker Swarm: 3 replicas, health check, rolling update
│
├── api/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app: endpoints, SSE, startup event
│   ├── database.py             # SQLite schema, insert, get_high_risk, get_stats
│   └── scheduler.py            # BackgroundTask ETL + Inference, load_trained_model()
│
├── etl/
│   ├── __init__.py
│   └── sheets_to_df.py         # pull_sheets(), sort_by_recency(), pivot_to_wide()
│
├── model/
│   ├── preprocessor.pkl        # CreditFeatureEngineer + ColumnTransformer (fit trên X_train)
│   ├── model.pkl               # XGBoost đã train
│   ├── feature_names.pkl       # Tên 23 features đầu vào raw
│   └── config.json             # model_type, optimal_threshold
│
├── notebooks/
│   └── EDA.ipynb               # Phân tích EDA + training pipeline
│
└── dashboard/
    ├── index.html              # Web UI – Bootstrap 5, DataTables, Chart.js
    ├── style.css               # Conditional formatting (High/Medium/Low colors)
    └── app.js                  # SSE EventSource, fetchAndRenderStats(), DataTable
```

---

## Cài đặt và chạy

### Yêu cầu
- Python 3.10+
- pip

### Bước 1 – Clone và cài thư viện

```bash
git clone <repo-url>
cd credit_risk_predictor

pip install -r requirements.txt
```

### Bước 2 – Tạo file `.env`

```bash
# .env
SECRET_TOKEN=your-secret-token-here
GOOGLE_SHEETS_KEY=your-spreadsheet-id-here
NODE_ID=local-dev
```

- `SECRET_TOKEN`: token để xác thực webhook từ Apps Script
- `GOOGLE_SHEETS_KEY`: ID của Google Spreadsheet (lấy từ URL)
- `NODE_ID`: tên node, dùng để verify load balancing trên Swarm

### Bước 3 – Đặt `service-account.json`

Tải file JSON Service Account từ Google Cloud Console và đặt vào thư mục gốc dự án.  
Hướng dẫn: **Google Cloud Console → IAM & Admin → Service Accounts → Create Key → JSON**.

> ⚠️ Không commit `service-account.json` và `.env` lên Git. Thêm vào `.gitignore`.

### Bước 4 – Đảm bảo có model artifacts

```
model/
├── preprocessor.pkl   ✅
├── model.pkl          ✅
├── feature_names.pkl  ✅
└── config.json        ✅
```

Nếu chưa có, chạy notebook `notebooks/EDA.ipynb` để train và export.

### Bước 5 – Chạy API

```bash
uvicorn api.main:app --reload --port 8000
```

### Bước 6 – Mở Dashboard

```
http://localhost:8000/dashboard
```

Swagger UI (test API):
```
http://localhost:8000/docs
```

### Bước 7 – Trigger thủ công để test

```bash
curl -X POST http://localhost:8000/etl-trigger \
  -H "Authorization: Bearer your-secret-token-here" \
  -H "Content-Type: application/json" \
  -d "{}"
```

Kết quả đúng: `{"status":"Accepted","message":"..."}` và log uvicorn hiện pipeline chạy.

---

## Các Endpoint API

| Endpoint | Method | Mô tả | Auth |
|---|---|---|---|
| `GET /health` | GET | Health check: node_id, model_loaded, uptime | Không |
| `POST /etl-trigger` | POST | Nhận webhook từ Apps Script → 202 ngay → BackgroundTask | Bearer token |
| `GET /etl-trigger` | GET | Trigger thủ công từ browser | Bearer token |
| `POST /predict` | POST | Predict 1 khách hàng (23 features JSON) | Bearer token |
| `POST /batch-predict` | POST | Predict batch danh sách khách hàng | Bearer token |
| `GET /dashboard-data` | GET | SSE stream – push "new_predictions" khi có dữ liệu mới | Không |
| `GET /api/high-risk` | GET | JSON danh sách khách hàng risk=High | Không |
| `GET /api/stats` | GET | Thống kê: total, high, medium, low | Không |
| `GET /dashboard` | GET | Web dashboard static files | Không |
| `GET /docs` | GET | Swagger UI tự động | Không |

### Ví dụ request `POST /predict`

```json
{
  "limit_bal": 50000,
  "sex": 2,
  "education": 2,
  "marriage": 1,
  "age": 34,
  "pay_0": 2,
  "pay_2": 0,
  "pay_3": 0,
  "pay_4": 0,
  "pay_5": 0,
  "pay_6": 0,
  "bill_amt1": 15000,
  "bill_amt2": 14000,
  "bill_amt3": 13000,
  "bill_amt4": 12000,
  "bill_amt5": 11000,
  "bill_amt6": 10000,
  "pay_amt1": 0,
  "pay_amt2": 1000,
  "pay_amt3": 1000,
  "pay_amt4": 500,
  "pay_amt5": 500,
  "pay_amt6": 0
}
```

### Ví dụ response

```json
{
  "node_served": "vps1",
  "probability": 0.7842,
  "risk_level": "High",
  "model_used": "SKLEARN",
  "timestamp": "2026-05-29 10:30:00"
}
```

---

## Triển khai Docker Swarm

### Yêu cầu
- Docker Machine
- Hyper-V (Windows) hoặc VirtualBox (Mac/Linux)

### Bước 1 – Build và push image

```bash
docker build -f docker/Dockerfile -t your-dockerhub-username/credit-risk-api:latest .
docker push your-dockerhub-username/credit-risk-api:latest
```

### Bước 2 – Tạo 3 Virtual Machines

```powershell
docker-machine create --driver hyperv vps1
docker-machine create --driver hyperv vps2
docker-machine create --driver hyperv vps3

docker-machine ls
```

### Bước 3 – Khởi tạo Swarm Cluster

```bash
# SSH vào vps1 (Manager)
docker-machine ssh vps1
docker swarm init --advertise-addr <VPS1_IP>

# SSH vào vps2 và vps3 (Workers) – paste lệnh join từ output trên
docker swarm join --token <TOKEN> <VPS1_IP>:2377

# Verify từ vps1
docker node ls
```

### Bước 4 – Deploy Stack

```bash
# Trên vps1
docker stack deploy -c swarm-stack.yml credit-risk-stack

# Verify
docker stack services credit-risk-stack
docker service ps credit-risk-stack_api
```

Kết quả đúng: 3 replicas đều `Running`, mỗi node 1 replica.

### Bước 5 – Test load balancing

```bash
# Gọi /health 10 lần – node_id phải xoay vòng 3 nodes
for i in {1..10}; do curl -s http://<VPS1_IP>:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['node_id'])"; done
```

### Cấu hình Swarm (`swarm-stack.yml`)

| Tham số | Giá trị | Mục đích |
|---|---|---|
| `replicas` | 3 | 1 replica/node |
| `max_replicas_per_node` | 1 | Đảm bảo phân tán đều |
| `update_config.parallelism` | 1 | Rolling update từng replica |
| `update_config.failure_action` | rollback | Tự rollback nếu update lỗi |
| `resources.limits.memory` | 512M | Giới hạn RAM mỗi container |
| `healthcheck.interval` | 30s | Kiểm tra `/health` định kỳ |

---

## Luồng dữ liệu tự động

### Cách nhập dữ liệu mới

Nhập dữ liệu khách hàng vào **4 sheets** trong Google Spreadsheet:

| Sheet | Columns | Ghi chú |
|---|---|---|
| `customer_info` | id, limit_bal, sex, education, marriage, age | Mỗi KH 1 dòng |
| `billing_statement` | id, bill_amount, statement_date (MM/YYYY) | 6 dòng/KH |
| `payment_record` | id, pay_amount, payment_date (MM/YYYY) | 6 dòng/KH |
| `repayment_status` | id, repayment_status, status_date (MM/YYYY) | Giá trị: −2 đến 9 |

### Cách hoạt động tự động

```
6:00 AM hàng ngày
    └── Apps Script Time trigger
            ├── validateData()       – kiểm tra range, tô đỏ cell lỗi
            ├── normalizeCategories() – EDUCATION {0,5,6}→4, MARRIAGE {0}→3
            ├── addTimestamp()       – ghi last_updated
            └── triggerETL()         – POST /etl-trigger + Bearer token
                    │
                    └── FastAPI: 202 Accepted ngay lập tức
                            │
                            └── BackgroundTask (async):
                                    ├── pull_sheets()      – gspread API
                                    ├── pivot_to_wide()    – join 4 bảng → 25 cột
                                    ├── preprocessor.pkl   – feature engineering
                                    ├── model.pkl          – predict_proba()
                                    ├── insert_predictions() – lưu SQLite
                                    └── sse_queue.put()    – broadcast dashboard
```

> **Tại sao trả 202 thay vì 200?**  
> ETL + predict mất 30–60 giây. Apps Script timeout sau 30 giây. Trả 202 ngay để Apps Script không báo lỗi giả, trong khi Python tiếp tục xử lý bất đồng bộ.

### Dashboard tự refresh

Khi `sse_queue` nhận tín hiệu `new_predictions`, tất cả browser đang mở dashboard tự động fetch lại `/api/high-risk` và `/api/stats` mà không cần reload trang – thông qua cơ chế **Server-Sent Events (SSE)**.

---

## Dataset

**UCI Default of Credit Card Clients**  
- Nguồn: [UCI ML Repository](https://archive.ics.uci.edu/dataset/350)  
- Tác giả: Yeh, I. C., & Lien, C. H. (2009)  
- 30,000 mẫu · 23 features · 1 target (`default payment next month`)  
- Phân phối: 77.88% non-default / 22.12% default (imbalanced)

---

## Lưu ý bảo mật

```gitignore
# .gitignore
.env
service-account.json
credit_risk.db
model/preprocessor.pkl
model/model.pkl
__pycache__/
*.pyc
venv/
```

`SECRET_TOKEN` được lưu trong **Apps Script Properties** (không hardcode trong code) và trong file `.env` ở server.
