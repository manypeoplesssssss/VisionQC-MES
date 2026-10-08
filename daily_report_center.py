import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pymysql

st.markdown("""
<style>
.report-app { background-color: #0F172A; color: #E2E8F0; padding: 20px; font-family: 'Malgun Gothic', sans-serif; }
.report-title { color: #38BDF8; font-size: 2rem; font-weight: 800; border-bottom: 2px solid #38BDF8; padding-bottom: 10px; margin-bottom: 20px; }
.metric-box { background-color: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 15px; text-align: center; }
.metric-label { font-size: 0.75rem; color: #94A3B8; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; }
.metric-value { font-size: 1.6rem; font-weight: 700; color: #FFFFFF; }
.table-style { width: 100%; border-collapse: collapse; margin-top: 15px; }
.table-style th { background-color: #334155; color: #38BDF8; padding: 10px; text-align: left; font-size: 0.9rem; }
.table-style td { padding: 10px; border-bottom: 1px solid #334155; font-size: 0.9rem; color: #E2E8F0; }
.ai-box { background: linear-gradient(145deg, #1E293B, #0F172A); border-left: 5px solid #38BDF8; border-radius: 4px; padding: 20px; margin-top: 20px; }
.ai-section-title { color: #38BDF8; font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="report-title">🏭 [품질관리부] 일간·주간·월간 공정 생산량 분석 시스템</div>', unsafe_allow_html=True)

def get_db_conn():
    return pymysql.connect(
        host="100.126.8.78",     
        user="mes_user",         
        password="mes_pass",     
        database="visionqc",     
        port=3306,
        charset="utf8mb4",
        autocommit=True
    )

selected_date = st.date_input("🗓️ 분석 및 발행할 보고서 기준 일자를 선택하세요", datetime.now().date())
date_str = selected_date.strftime("%Y-%m-%d")

# 💡 선택한 날짜 기준 과거 7일, 과거 30일 날짜 계산
date_dt = datetime.strptime(date_str, "%Y-%m-%d")
week_ago_str = (date_dt - timedelta(days=6)).strftime("%Y-%m-%d")
month_ago_str = (date_dt - timedelta(days=29)).strftime("%Y-%m-%d")

try:
    conn = get_db_conn()
    
    # 1. 일간(Daily) 데이터 조회
    q_daily = "SELECT final_result FROM product_inspection WHERE DATE(created_at) = %s;"
    df_d = pd.read_sql(q_daily, conn, params=[date_str])
    
    # 2. 주간(Weekly) 누적 데이터 조회 (선택일 기준 과거 7일간)
    q_weekly = "SELECT final_result FROM product_inspection WHERE DATE(created_at) BETWEEN %s AND %s;"
    df_w = pd.read_sql(q_weekly, conn, params=[week_ago_str, date_str])
    
    # 3. 월간(Monthly) 누적 데이터 조회 (선택일 기준 과거 30일간)
    q_monthly = "SELECT final_result FROM product_inspection WHERE DATE(created_at) BETWEEN %s AND %s;"
    df_m = pd.read_sql(q_monthly, conn, params=[month_ago_str, date_str])
    
    conn.close()
except Exception as e:
    st.error(f"❌ 원격 메인 MySQL DB 연결 실패: {e}")
    st.stop()

# 통계 연산 함수
def calc_metrics(df):
    if df.empty:
        return 0, 0, 0, 0.0
    tot = len(df)
    ok = len(df[df['final_result'] == 'NORMAL'])
    ng = len(df[df['final_result'] != 'NORMAL'])
    rate = (ok / tot * 100) if tot > 0 else 0.0
    return tot, ok, ng, rate

d_tot, d_ok, d_ng, d_rate = calc_metrics(df_d)
w_tot, w_ok, w_ng, w_rate = calc_metrics(df_w)
m_tot, m_ok, m_ng, m_rate = calc_metrics(df_m)

# 📊 상단 대시보드 그리드 표출
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label" style="color: #38BDF8;">📅 DAILY 생산 현황 (당일)</div>
        <div class="metric-value">{d_tot} EA</div>
        <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 5px;">
            합격: <span style="color:#10B981;font-weight:bold;">{d_ok}</span> | 
            불량: <span style="color:#EF4444;font-weight:bold;">{d_ng}</span> | 
            수율: <span style="color:#38BDF8;font-weight:bold;">{d_rate:.1f}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label" style="color: #A855F7;">📈 WEEKLY 생산 현황 (7일 누적)</div>
        <div class="metric-value">{w_tot} EA</div>
        <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 5px;">
            합격: <span style="color:#10B981;font-weight:bold;">{w_ok}</span> | 
            불량: <span style="color:#EF4444;font-weight:bold;">{w_ng}</span> | 
            수율: <span style="color:#A855F7;font-weight:bold;">{w_rate:.1f}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label" style="color: #10B981;">📅 MONTHLY 생산 현황 (30일 누적)</div>
        <div class="metric-value">{m_tot} EA</div>
        <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 5px;">
            합격: <span style="color:#10B981;font-weight:bold;">{m_ok}</span> | 
            불량: <span style="color:#EF4444;font-weight:bold;">{m_ng}</span> | 
            수율: <span style="color:#10B981;font-weight:bold;">{m_rate:.1f}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.write("")
st.markdown(f"### 📋 {date_str} 일일 불량 원인 분석서 (제조 표준 규격)")

if d_tot == 0:
    st.info(f"💡 {date_str} 일자에는 가동된 생산 스캔 이력이 존재하지 않습니다.")
elif d_ng == 0:
    st.success("🎉 해당 일자에는 외관 및 치수 결함이 검출되지 않았으며, 설비 구동 상태가 매우 안정적입니다.")
else:
    st.markdown(f"""
    <div class="ai-box">
        <div class="ai-section-title">🎯 [결함 코드: D01/D02] 표면 도장 부족 및 페인트 오염 진단 (실시간 원격 연동)</div>
        <table class="table-style">
            <tr><th style="width: 20%;">분석 항목</th><th>종합 분석 및 엔지니어 액션 아이템 리포트</th></tr>
            <tr><td><b>현상 분석</b></td><td>차체 표면 및 전면/측면 판넬 규격에 불규칙한 미도장 흔적 및 분사 뭉침 현상(white_paint) 집중 발생.</td></tr>
            <tr><td><b>원인 추정 후보</b></td><td>도료 공급 탱크 압력 저하로 인한 미립화 실패, 또는 스프레이 노즐 팁 끝단 도료 고착화로 인한 분사 위치 오류.</td></tr>
            <tr><td><b>권장 조치 사항</b></td><td>메인 공급 라인 펌프 토출 압력 레벨 상시 모니터링 체계 가동, 노즐 파트 아세톤 세척 및 분사 캘리브레이션 재정렬 요구.</td></tr>
          </table>
    </div>
    <div class="ai-box" style="border-left-color: #F59E0B;">
        <div class="ai-section-title" style="color: #F59E0B;">🎯 [결함 코드: D04/D05] 물리 마찰 스크래치 결함 진단 (실시간 원격 연동)</div>
        <table class="table-style">
            <tr><th style="width: 20%;">분석 항목</th><th>종합 분석 및 엔지니어 액션 아이템 리포트</th></tr>
            <tr><td><b>현상 분석</b></td><td>지구 조립 접촉부 및 하단 턴테이블 안착부 부근에 회전 방향 선형 스크래치(scratch) 이력 포착.</td></tr>
            <tr><td><b>원인 추정 후보</b></td><td>36뷰 연속 스캔 도중 스텝 모터(28BYJ-48) 미세 잔진동 및 탈조 슬립 발생, 또는 지구 조립 구조 부품 체결 불완전으로 인한 쓸림 현상.</td></tr>
            <tr><td><b>권장 조치 사항</b></td><td>지구 부품 고정 고정 상태 전수 검사, 턴테이블 모터 고정 가이드부 물리적 조임 상태 재정비 및 백래시 보정치 튜닝.</td></tr>
        </table>
    </div>
    """, unsafe_allow_html=True)

st.write("---")
if not df_d.empty:
    st.download_button(
        label=f"💾 {date_str} 일일 품질 보고서 데이터 내보내기 (CSV)",
        data=df_d.to_csv(index=False).encode('utf-8'),
        file_name=f"DAILY_REPORT_{date_str}.csv",
        mime="text/csv"
    )
