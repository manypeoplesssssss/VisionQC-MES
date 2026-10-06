import streamlit as st
import pandas as pd
import os
import csv
import json
import serial
from datetime import datetime
import pymysql

MEASUREMENT_PATH = "C:\\Users\\user\\Desktop\\measurement.json"
DEFECT_PATH = "C:\\Users\\user\\Desktop\\defect.json"
MES_DB_PATH = "C:\\Users\\user\\Desktop\\mes_production_db.csv"

if 'arduino_serial' not in st.session_state:
    try:
        st.session_state.arduino_serial = serial.Serial(
            port="COM6",
            baudrate=115200,
            timeout=0.05
        )
    except Exception:
        st.session_state.arduino_serial = None

if 'ultrasonic_dist_1' not in st.session_state: st.session_state['ultrasonic_dist_1'] = 99
if 'ultrasonic_dist_2' not in st.session_state: st.session_state['ultrasonic_dist_2'] = 99
if 'hw_interlock_active' not in st.session_state: st.session_state['hw_interlock_active'] = False

st.fragment(run_every=2)

st.markdown("""
<style>
.stApp { background-color: #1A1F2C; color: #FFFFFF !important; }
[data-testid="stSidebar"] { background-color: #111520 !important; border-right: 1px solid #2D3748 !important; }
[data-testid="stSidebar"] .stMarkdown h3 { color: #00F2FE !important; font-weight: 700 !important; border-bottom: 1px solid #2D3748; padding-bottom: 5px; margin-top: 15px; }
[data-testid="stSidebar"] label { color: #E2E8F0 !important; font-weight: 600 !important; font-size: 0.9rem; }
.main-title { font-size: 2.3rem; font-weight: 800; color: #00F2FE; margin-bottom: 0.2rem; text-shadow: 0 0 10px rgba(0,242,254,0.3); }
.sub-title { color: #CBD5E1; font-size: 1.0rem; margin-bottom: 1.5rem; }
.status-banner-ok { background: linear-gradient(90deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.2) 100%); border: 1px solid #10B981; border-radius: 6px; padding: 12px; color: #10B981; font-weight: 600; font-size: 1rem; margin-bottom: 1.5rem; text-align: center; }
.status-banner-ng { background: linear-gradient(90deg, rgba(239, 68, 68, 0.1) 0%, rgba(239, 68, 68, 0.2) 100%); border: 1px solid #EF4444; border-radius: 6px; padding: 12px; color: #EF4444; font-weight: 600; font-size: 1rem; margin-bottom: 1.5rem; text-align: center; animation: blink 1.5s infinite; }
@keyframes blink { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
.neon-card-blue { background-color: #242B3D; border-left: 4px solid #0002FF; padding: 12px; border-radius: 6px; text-align: center; }
.neon-card-green { background-color: #242B3D; border-left: 4px solid #10B981; padding: 12px; border-radius: 6px; text-align: center; }
.neon-card-purple { background-color: #242B3D; border-left: 4px solid #BF5AF2; padding: 12px; border-radius: 6px; text-align: center; }
.neon-card-orange { background-color: #242B3D; border-left: 4px solid #FF9F0A; padding: 12px; border-radius: 6px; text-align: center; }
.neon-card-cyan { background-color: #242B3D; border-left: 4px solid #00F2FE; padding: 12px; border-radius: 6px; text-align: center; }
.neon-card-stop { background-color: #242B3D; border-left: 4px solid #EF4444; padding: 12px; border-radius: 6px; text-align: center; }
.neon-card-idle { background-color: #242B3D; border-left: 4px solid #64748B; padding: 12px; border-radius: 6px; text-align: center; }
.card-label { font-size: 0.75rem; color: #94A3B8; font-weight: 600; text-transform: uppercase; margin-bottom: 2px; }
.card-value { font-size: 1.05rem; font-weight: 700; }
[data-testid="stMetric"] { background-color: #202636 !important; border: 1px solid #334155 !important; border-radius: 8px !important; padding: 12px !important; }
div[data-testid="stNotification"] , .stAlert p , .stAlert span { background-color: #242B3D !important; color: #00F2FE !important; }
.ai-report-box { background: linear-gradient(145deg, #1E293B, #0F172A); border: 1px solid #334155; border-radius: 6px; padding: 15px; overflow-x: auto; }
.stDownloadButton > button { background-color: #00F2FE !important; color: #0F172A !important; font-weight: 700; }
div.stButton > button { background-color: #1E293B !important; color: #E2E8F0 !important; width: 100% !important; height: 35px !important; }
div.stButton > button:hover { border-color: #00F2FE !important; color: #00F2FE !important; }
[data-testid="stMetricValue"] { color: #FFFFFF !important; font-weight: 700 !important; font-size: 1.6rem !important; }
[data-testid="stMetricLabel"] { color: #94A3B8 !important; font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-title">스마트 팩토리 검사 시스템 종합 진단 리포트 (XAI Module)</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-title">Gemma 4 Edge-AI 로컬 텐서 네트워크 및 4채널 공정 관제 시스템</p>', unsafe_allow_html=True)

def get_mysql_conn():
    return pymysql.connect(
        host="localhost", user="root", password="1234", database="visionqc_mes", charset="utf8mb4", autocommit=True
    )

def insert_ai_defect_result(product_id, defect_type, confidence, box_coords=None):
    try:
        conn = get_mysql_conn()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM inspections WHERE serial_no = %s LIMIT 1;", (product_id,))
            result = cursor.fetchone()
            if result:
                inspection_id = result[0]
                sql = """
                    INSERT INTO defect_results (inspection_id, defect_detected, type, confidence, box)
                    VALUES (%s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (inspection_id, True if defect_type != "None" else False, defect_type if defect_type != "None" else None, confidence, json.dumps(box_coords) if box_coords else None))
        conn.close()
    except Exception: pass

def inject_mock_data(status, defect_type, alarm, width_input):
    if not os.path.exists(MES_DB_PATH) or os.path.getsize(MES_DB_PATH) == 0:
        os.makedirs(os.path.dirname(MES_DB_PATH), exist_ok=True)
        with open(MES_DB_PATH, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Product ID", "Width_mm", "Dim_Status", "Defect_Type", "Final_Judgment", "Safety_Alarm", "AI_Report"])
            
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    product_id = f"PROD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    diff_val = abs(width_input - 84.96)
    dim_j = "FAIL" if diff_val > 3.5 else ("RECHECK" if 2.0 < diff_val <= 3.5 else "PASS")
    final_j = "OK" if (dim_j == "PASS" and defect_type == "None") else "NG"
    mock_report = f"[REPATTERN XAI REPORT v1.0]\n-----------------------\n발행일시: {timestamp}\n최종판정: {final_j}\n실물 폭 계측값: {width_input}mm 결과\n오차 판정 [{dim_j}] 및 외관 [{defect_type}] 분석 완료."

    with open(MES_DB_PATH, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, product_id, width_input, dim_j, defect_type, final_j, alarm, mock_report])

    try:
        conn = get_mysql_conn()
        with conn.cursor() as cursor:
            sql = "INSERT INTO inspections (serial_no, item, process, inspected_at, result, model_version, image_filename, image_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            cursor.execute(sql, (product_id, "VisionCar", "YOLO", timestamp, "OK" if final_j == "OK" else "NG", "Gemma-4-EdgeAI", f"{product_id}.jpg", f"storage/{product_id}.jpg"))
        conn.close()
        insert_ai_defect_result(product_id, defect_type, 0.95 if defect_type != "None" else 0.0)
    except Exception: pass
db_exists = os.path.exists(MES_DB_PATH) and os.path.getsize(MES_DB_PATH) > 50
is_interlock = db_exists and pd.read_csv(MES_DB_PATH).iloc[-1]['Safety_Alarm'] == 'EMERGENCY_STOP' or st.session_state['hw_interlock_active']

with st.sidebar:
    st.markdown("### LINE CONTROLLER (SCADA)")
    line_status = st.toggle("1라인: 턴테이블 구동 모터 가동", value=True)
    camera_status = st.toggle("비전 검사용 D435 모듈 감시", value=True)
    
    st.markdown("### VIRTUAL FENCE CONTROLLER")
    fence_status = st.toggle("초음파 가상 펜스 시스템 가동", value=True)
    pipeline_toggle = st.toggle("파이프라인 통신 강제 연동", value=True)
    
    st.markdown("### 실시간 가상 펜스 센서 피드")
    st.write(f"📡 초음파 센서 #1 거리: **{st.session_state['ultrasonic_dist_1']} cm**")
    st.write(f"📡 초음파 센서 #2 거리: **{st.session_state['ultrasonic_dist_2']} cm**")
    if st.button("🚨 인터락 알람 해제 (RESET)"):
        st.session_state['hw_interlock_active'] = False
        st.rerun()
    
    st.markdown("### DATA INJECTOR")
    if st.button("정상품 생성 주입"): inject_mock_data("PASS", "None", "NORMAL", 84.96)
    if st.button("표면 스크래치 불량 주입"): inject_mock_data("PASS", "스크래치", "NORMAL", 84.96)
    if st.button("치수 에러 불량 주입"): inject_mock_data("FAIL", "None", "NORMAL", 88.50)
    
    st.markdown("### SYSTEM CONTROL")
    max_allow_width = st.slider("최대 허용 전폭 공차 한계선 (mm)", 84.00, 90.00, 84.96, step=0.01)

if st.session_state.arduino_serial and st.session_state.arduino_serial.is_open:
    try:
        while st.session_state.arduino_serial.in_waiting > 0:
            line_packet = st.session_state.arduino_serial.readline().decode('utf-8').strip()
            
            # 💡 [핵심 보정] 팀원분의 아두이노 패킷 규격(ERR,INTERLOCK) 완벽 매핑
            if "ERR,INTERLOCK" in line_packet or "EVT,ST_TRIPPED" in line_packet or "EMERGENCY_STOP" in line_packet:
                st.session_state['hw_interlock_active'] = True
                if os.path.exists(MES_DB_PATH):
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    product_id = f"EMG-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    gemma_report = f"[REPATTERN XAI REPORT v1.0]\n발행일시: {timestamp}\n최종판정: FAIL (하드웨어 통합 안전 인터록 활성화)"
                    with open(MES_DB_PATH, mode='a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([timestamp, product_id, 84.96, "PASS", "None", "NG", "EMERGENCY_STOP", gemma_report])
                        
                    try:
                        conn = get_mysql_conn()
                        with conn.cursor() as cursor:
                            sql = "INSERT INTO inspections (serial_no, item, process, inspected_at, result, model_version, image_filename, image_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                            cursor.execute(sql, (product_id, "VisionCar", "YOLO", timestamp, "NG", "Gemma-4-EdgeAI", f"{product_id}.jpg", f"storage/{product_id}.jpg"))
                        conn.close()
                    except Exception: pass
                st.rerun()
            
            elif line_packet.startswith("STAT,") or line_packet.startswith("EVT,"):
                parts = line_packet.split(",")
                if len(parts) >= 4:
                    st.session_state['ultrasonic_dist_1'] = int(parts[2])
                    st.session_state['ultrasonic_dist_2'] = int(parts[3])
    except Exception: pass

if is_interlock:
    st.markdown('<div class="status-banner-ng">CRITICAL SYSTEM ALERT: VIRTUAL FENCE INTERLOCK ACTIVATED</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="status-banner-ok">SYSTEM STATUS: ACTIVE (실시간 결함 탐지 필터 가동 중)</div>', unsafe_allow_html=True)

st.markdown("### 멀티 데이터 스트림 파이프라인 실시간 액추에이터 감시 모니터")
col_l1, col_l2, col_l3, col_l4 = st.columns(4)

with col_l1:
    if is_interlock: st.markdown('<div class="neon-card-stop"><div class="card-label">TURNTABLE MOTOR</div><div class="card-value">MOTOR STOPPED</div></div>', unsafe_allow_html=True)
    elif line_status: st.markdown('<div class="neon-card-blue"><div class="card-label">TURNTABLE MOTOR</div><div class="card-value">MOTOR RUNNING</div></div>', unsafe_allow_html=True)
    else: st.markdown('<div class="neon-card-idle"><div class="card-label">TURNTABLE MOTOR</div><div class="card-value">SIGNAL IDLE</div></div>', unsafe_allow_html=True)

with col_l2:
    if is_interlock: st.markdown('<div class="neon-card-stop"><div class="card-label">VISION CAMERA SENSOR</div><div class="card-value">CAMERA OFF</div></div>', unsafe_allow_html=True)
    elif camera_status: st.markdown('<div class="neon-card-green"><div class="card-label">VISION CAMERA SENSOR</div><div class="card-value">D435 FEED LIVE</div></div>', unsafe_allow_html=True)
    else: st.markdown('<div class="neon-card-idle"><div class="card-label">VISION CAMERA SENSOR</div><div class="card-value">SIGNAL IDLE</div></div>', unsafe_allow_html=True)

with col_l3:
    if is_interlock: st.markdown('<div class="neon-card-stop"><div class="card-label">VIRTUAL FENCE SENSOR</div><div class="card-value">FENCE BREACHED</div></div>', unsafe_allow_html=True)
    elif fence_status: st.markdown('<div class="neon-card-purple"><div class="card-label">VIRTUAL FENCE SENSOR</div><div class="card-value">FENCE RADAR ACTIVE</div></div>', unsafe_allow_html=True)
    else: st.markdown('<div class="neon-card-idle"><div class="card-label">VIRTUAL FENCE SENSOR</div><div class="card-value">SIGNAL IDLE</div></div>', unsafe_allow_html=True)

with col_l4:
    if is_interlock: st.markdown('<div class="neon-card-stop"><div class="card-label">DATA STREAM PIPELINE</div><div class="card-value">STREAM BLOCKED</div></div>', unsafe_allow_html=True)
    elif not pipeline_toggle: st.markdown('<div class="neon-card-idle"><div class="card-label">DATA STREAM PIPELINE</div><div class="card-value">SIGNAL IDLE</div></div>', unsafe_allow_html=True)
    elif os.path.exists(MEASUREMENT_PATH) or os.path.exists(DEFECT_PATH): st.markdown('<div class="neon-card-cyan"><div class="card-label">DATA STREAM PIPELINE</div><div class="card-value">PROCESSING DATA</div></div>', unsafe_allow_html=True)
    else: st.markdown('<div class="neon-card-orange"><div class="card-label">DATA STREAM PIPELINE</div><div class="card-value">SIGNAL IDLE</div></div>', unsafe_allow_html=True)

st.write("---")

if os.path.exists(MEASUREMENT_PATH) and os.path.exists(DEFECT_PATH):
    try:
        with open(MEASUREMENT_PATH, 'r', encoding='utf-8') as f: m_data = json.load(f)
        with open(DEFECT_PATH, 'r', encoding='utf-8') as f: d_data = json.load(f)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        product_id = f"PROD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        width = m_data.get('2d_width_mm', 84.96)
        dim_status = m_data.get('status', 'FAIL')
        defect_detected = d_data.get('defect_detected', False)
        defect_type = d_data.get('type', 'None') if defect_detected else "None"
        confidence_val = d_data.get('confidence', 0.85) if defect_detected else 0.0
        box_val = d_data.get('box', None)
        
        final_j = "OK" if (dim_status == "PASS" and not defect_detected) else "NG"
        ai_report_text = f"[REPATTERN XAI REPORT v1.0]\n발행일시: {timestamp}\n최종판정: {final_j}\n실물 폭 계측값 {width}mm 결과 [{dim_status}] 및 외관 [{defect_type}] 분석 완료."
        
        with open(MES_DB_PATH, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, product_id, width, dim_status, defect_type, final_j, "NORMAL", ai_report_text])
            
        try:
            conn = get_mysql_conn()
            with conn.cursor() as cursor:
                sql = "INSERT INTO inspections (serial_no, item, process, inspected_at, result, model_version, image_filename, image_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                cursor.execute(sql, (product_id, "VisionCar", "YOLO", timestamp, "OK" if final_j == "OK" else "NG", "Gemma-4-EdgeAI", f"{product_id}.jpg", f"storage/{product_id}.jpg"))
            conn.close()
            insert_ai_defect_result(product_id, defect_type, confidence_val, box_val)
        except Exception: pass
            
        os.remove(MEASUREMENT_PATH)
        os.remove(DEFECT_PATH)
        st.toast(f"🎥 캠 동기화 완료! (ID: {product_id})")
        st.rerun()
    except Exception: pass

if db_exists:
    df = pd.read_csv(MES_DB_PATH)
    total_p, ok_c, ng_c = len(df), len(df[df['Final_Judgment'] == 'OK']), len(df[df['Final_Judgment'] == 'NG'])
    yield_rate = (ok_c / total_p * 100) if total_p > 0 else 0.0
    
    col1, col2, col3 = st.columns(3)
    with col1: st.metric(label="총 누적 분석 스캔량", value=f"{total_p} EA")
    with col2: st.metric(label="실시간 라인 종합 수율", value=f"{yield_rate:.1f} %")
    with col3: st.metric(label="실시간 크리티컬 불량 수", value=f"{ng_c} EA")
    st.write("---")
    
    st.markdown("### 비전 캡처 프레임 및 Gemma 4 AI 정밀 진단 해설")
    col_img, col_rep = st.columns(2)
    with col_img:
        mock_img_path = "C:\\Users\\user\\Desktop\\Live_capture.jpg"
        if os.path.exists(mock_img_path): st.image(mock_img_path, use_container_width=True)
        else: st.info("RealSense D435 피드 수신 대기 중...")
    with col_rep:
        if 'AI_Report' in df.columns:
            st.markdown(f'<div class="ai-report-box"><pre style="color: #00F2FE; background: transparent;">{df.iloc[-1]["AI_Report"]}</pre></div>', unsafe_allow_html=True)
    st.write("---")
    
    left_col, right_col = st.columns(2)
    with left_col: st.bar_chart(df['Final_Judgment'].value_counts())
    with right_col: st.line_chart(df['Width_mm'])
    st.write("---")
    st.download_button(label="데이터 아카이브 다운로드 (CSV)", data=df.to_csv(index=False).encode('utf-8'), file_name="REPATTERN_MES_DATA.csv", mime="text/csv", width="stretch")
else:
    st.warning("센서 패킷 수신 대기 중...")

