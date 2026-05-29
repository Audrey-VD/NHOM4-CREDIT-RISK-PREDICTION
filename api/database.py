import sqlite3
import os
import time

DB_PATH = "credit_risk.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    
    return conn

def create_tables():
    """Khởi tạo cấu trúc cơ sở dữ liệu hệ thống kèm theo thiết lập Tối ưu hóa Chỉ mục (Index)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Bảng lưu trữ kết quả dự đoán
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT UNIQUE,
            limit_bal REAL,
            age INTEGER,
            pay_0 INTEGER,
            probability REAL,
            risk_level TEXT,
            shap_features TEXT,
            predicted_at TEXT
        )
    """)
    
    # 2. Bảng lưu lịch sử vận hành ETL Pipeline
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etl_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT,
            rows_processed INTEGER,
            status TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_predictions_risk_prob 
        ON predictions (risk_level, probability DESC)
    """)
    
    conn.commit()
    conn.close()

def insert_predictions(records_list):
    if not records_list:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.executemany("""
            INSERT OR IGNORE INTO predictions   -- ← ĐỔI TỪ INSERT THÀNH INSERT OR IGNORE
            (customer_id, limit_bal, age, pay_0, probability, risk_level, shap_features, predicted_at)
            VALUES (:customer_id, :limit_bal, :age, :pay_0, :probability, :risk_level, :shap_features, :predicted_at)
        """, records_list)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def log_etl_run(rows_processed, status):
    """Ghi log phiên chạy ETL"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO etl_log (run_at, rows_processed, status)
            VALUES (?, ?, ?)
        """, (time.strftime("%Y-%m-%d %H:%M:%S"), rows_processed, status))
        conn.commit()
    finally:
        conn.close()

def get_high_risk():
    """Lấy danh sách các khách hàng nguy cơ cao phục vụ DataTables UI"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_id as id, limit_bal, age, pay_0, probability, risk_level, shap_features, predicted_at 
        FROM predictions 
        WHERE risk_level = 'High' 
        ORDER BY probability DESC LIMIT 1000
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN risk_level = 'Medium' THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN risk_level = 'Low' THEN 1 ELSE 0 END) as low
        FROM predictions
    """)
    
    row = cursor.fetchone()
    conn.close()

    return {
        "total": row["total"] if row["total"] else 0,
        "high": row["high"] if row["high"] else 0,
        "medium": row["medium"] if row["medium"] else 0,
        "low": row["low"] if row["low"] else 0
    }