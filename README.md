# 🏦 Credit Risk MLOps Pipeline

Hệ thống dự đoán rủi ro vỡ nợ tín dụng cá nhân tích hợp pipeline tự động hoàn chỉnh: **Google Sheets → ETL → Machine Learning → Docker Swarm → Real-time Dashboard**.

---

## 📋 Mục lục

- [Tổng quan hệ thống](#tổng-quan-hệ-thống)
- [Kiến trúc](#kiến-trúc)
- [Công nghệ sử dụng](#công-nghệ-sử-dụng)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Cài đặt và chạy](#cài-đặt-và-chạy)
- [Luồng dữ liệu tự động](#luồng-dữ-liệu-tự-động)

---

## Tổng quan hệ thống

Hệ thống sử dụng bộ dữ liệu **UCI Default of Credit Card Clients** (30,000 mẫu, 25 features) để huấn luyện mô hình **LightGBM** dự đoán khả năng vỡ nợ của khách hàng trong tháng tới.

Điểm khác biệt so với demo thông thường: hệ thống được thiết kế theo mô hình **MLOps thực tế**, trong đó dữ liệu khách hàng mới được nhập vào **Google Sheets**, tự động được kéo về xử lý mỗi ngày qua cơ chế **Webhook + BackgroundTasks**, kết quả dự đoán hiển thị trực tiếp trên **Web Dashboard real-time** không cần reload trang.

Toàn bộ hệ thống được triển khai trên **Docker Swarm Cluster 3 node** với load balancing, rolling update và fault tolerance.

---

## Kiến trúc

```
<img width="836" height="541" alt="Screenshot 2026-05-28 001231" src="https://github.com/user-attachments/assets/3c8b3b0f-eaa0-4f61-a36a-5fa04904429a" />
```

## Công nghệ sử dụng

### API & Backend
- **FastAPI** – REST API, BackgroundTasks, Server-Sent Events (SSE)
- **Uvicorn** – ASGI server
- **APScheduler** – Cron job fallback khi không có Webhook
- **SQLite** – WAL mode, index tối ưu cho Dashboard queries

### Machine Learning
- **LightGBM** – Mô hình chính 
- **scikit-learn** – Pipeline, ColumnTransformer, RobustScaler, OneHotEncoder
- **imbalanced-learn** – SMOTE or Undersampling
- **SHAP** – Giải thích mô hình

### Feature Engineering
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
- **Google Apps Script** – Webhook trigger tự động xx:00 AM

### Frontend Dashboard
- **Bootstrap 5** – Layout responsive
- **DataTables.js** – Bảng sortable, searchable, export CSV
- **Chart.js** – Pie chart, Line chart
- **EventSource API (SSE)** – Auto-refresh real-time

### HPC Infrastructure
- **Docker** – Containerization
- **Docker Swarm** – Orchestration, load balancing (IPVS), rolling update

---

## Cấu trúc dự án

```
credit_risk_predictor/
│
├── requirements.txt
├── service-account.json
├── credit_risk.db
├── .env
│
├── docker/
│   ├── Dockerfile
│   └── swarm-stack.yml
│
├── api/
│   ├── __init__.py
│   ├── main.py  
│   ├── database.py
│   └── scheduler.py 
│
├── etl/
│   ├── __init__.py
│   └── sheets_to_df.py
│
├── model/
│   ├── preprocessor.pkl
│   ├── model.pkl    
│   ├── feature_names.pkl     
│   └── config.json            
│
├── notebooks/
│   └── eda.ipynb
│   └── preprocessing.ipynb
│   └── training.ipynb
│
└── dashboard/
    ├── index.html              
    ├── style.css               
    └── app.js               
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
```

- `SECRET_TOKEN`: token để xác thực webhook từ Apps Script
- `GOOGLE_SHEETS_KEY`: ID của Google Spreadsheet (lấy từ URL)

### Bước 3 – Đặt `service-account.json`

Tải file JSON Service Account từ Google Cloud Console và đặt vào thư mục gốc dự án.  
Hướng dẫn: **Google Cloud Console → IAM & Admin → Service Accounts → Create Key → JSON**.

### Bước 4 – Đảm bảo có model artifacts

```
model/
├── preprocessor.pkl   ✅
├── model.pkl          ✅
├── feature_names.pkl  ✅
└── config.json        ✅
```

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

## Luồng dữ liệu tự động

### Cách nhập dữ liệu mới

Nhập dữ liệu khách hàng vào **4 sheets** trong Google Spreadsheet:

| Sheet | Columns | Ghi chú |
|---|---|---|
| `customer_info` | id, limit_bal, sex, education, marriage, age |
| `billing_statement` | id, bill_amount, statement_date (MM/YYYY) |
| `payment_record` | id, pay_amount, payment_date (MM/YYYY) |
| `repayment_status` | id, repayment_status, status_date (MM/YYYY) |

### Cách hoạt động tự động

```
xx:00 AM hàng ngày
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

`SECRET_TOKEN` được lưu trong **Apps Script Properties** và trong file `.env` ở server.
