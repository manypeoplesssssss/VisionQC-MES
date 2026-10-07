-- VisionQC AI MES - MySQL 8.0.16 이상 스키마 (테이블 5개, 검사 1회 단위)
-- 검사 허용: 센터링 OFF(정위치) AND 인터락 0(정상). ON / 1 / UNKNOWN(미확인·센서 응답 끊김)이면 검사 금지
-- 서버(backend)를 처음 실행하면 테이블은 자동 생성되므로, 여기서는 DB와 계정만 만들어도 된다.
-- 이 파일의 테이블 정의는 backend/app/models.py 와 같은 구조 (구조 확인 / Workbench 에서 직접 만들 때용)
--
-- 관계
--   product_inspection.inspection_id ─ 1 : 0..1 ─ product_dimension_inspection.inspection_id   (실제 외래키)
--   product_inspection.yolo_defect_data[*].defect_code ··· defect_type.defect_code            (JSON 안 논리 참조, 외래키 없음)
--   product_inspection.inspection_id ─ 1 : 0..N ─ equipment_safety_alarm.inspection_id      (실제 외래키, 시작 전 알람은 NULL)
--   admin_user ··· 검사 결과 조회 · 리포트 수신                                                  (논리 참조)
--
-- [자동] 컬럼 = GENERATED ALWAYS AS (...) STORED. 애플리케이션이 값을 넣지 않고 MySQL 이 계산한다.
-- 결과값 컬럼의 허용값은 CHECK 로 제한 (MySQL 8.0.16 부터 CHECK 가 실제로 검사됨)

CREATE DATABASE IF NOT EXISTS visionqc_mes DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'mes_user'@'%' IDENTIFIED BY 'mes_pass';
GRANT ALL PRIVILEGES ON visionqc_mes.* TO 'mes_user'@'%';
FLUSH PRIVILEGES;

USE visionqc_mes;

-- ---------------------------------------------------------------------------
-- 전체 검사: 제품 한 개의 검사 1회 = 한 행 (같은 제품을 재검사하면 새 inspection_id)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_inspection (
    id                      INT AUTO_INCREMENT PRIMARY KEY,                    -- 검사 행 식별번호
    inspection_id           VARCHAR(64)  NOT NULL UNIQUE,                       -- 검사 고유번호 (날짜 포함, 예: 20261006_inspection_143000_001)
    product_name            VARCHAR(50)  NOT NULL,                              -- 제품 모델명 (redcar)
    product_serial          VARCHAR(64)  NULL,                                  -- 개별 제품 식별번호
    centering_state         VARCHAR(8)   NOT NULL DEFAULT 'UNKNOWN',            -- 센터링: OFF 정위치 / ON 위치 이상 / UNKNOWN 미확인 (마지막 확인 값)
    interlock_state         VARCHAR(8)   NOT NULL DEFAULT 'UNKNOWN',            -- 인터락: 0 정상 / 1 비정상 / UNKNOWN 미확인 (마지막 확인 값)
    dimension_result        VARCHAR(16)  NOT NULL DEFAULT 'PENDING',            -- 3D 치수 합불 판정 (치수 테이블 결과를 서버가 반영)
    dimension_data          JSON         NULL,                                  -- 치수 상세 데이터
    scan_file_path          VARCHAR(500) NULL,                                  -- 3D 스캔 파일 경로
    patchcore_result        VARCHAR(16)  NOT NULL DEFAULT 'PENDING',            -- PatchCore 합불 판정 (점수 >= 기준이면 FAIL)
    patchcore_score         DOUBLE       NULL,                                  -- 이상 점수
    patchcore_threshold     DOUBLE       NULL,                                  -- 검사 당시 판정 기준
    patchcore_model_version VARCHAR(50)  NULL,                                  -- PatchCore 모델 버전
    yolo_status             VARCHAR(16)  NOT NULL DEFAULT 'NOT_STARTED',        -- YOLO 검사 진행 상태
    yolo_defect_data        JSON         NOT NULL,                              -- 불량별 검출 정보 배열 [{capture_number, defect_class, confidence, box, angle_deg, defect_code}]
    yolo_model_version      VARCHAR(50)  NULL,                                  -- YOLO 모델 버전
    capture_folder          VARCHAR(500) NULL,                                  -- 검사 사진 폴더 경로 (검사 PC)
    image_files             JSON         NOT NULL,                              -- 이미지별 파일 경로 배열 [{capture_number, original_path, annotated_path, metadata_path}]
    final_result            VARCHAR(32)  GENERATED ALWAYS AS (                  -- [자동] 최종 검사 결과
        CASE
            WHEN dimension_result IS NULL OR dimension_result IN ('PENDING', 'RECHECK') THEN 'DIMENSION_PENDING'   -- 재검은 다시 스캔할 때까지 대기
            WHEN dimension_result = 'FAIL' THEN 'DIMENSION_DEFECT'
            WHEN patchcore_result IS NULL OR patchcore_result = 'PENDING' THEN 'PATCHCORE_PENDING'
            WHEN patchcore_result = 'PASS' THEN 'NORMAL'
            WHEN yolo_status = 'COMPLETED' THEN 'PROCESS_DEFECT'
            ELSE 'YOLO_PENDING'
        END) STORED NOT NULL,
    recommended_action      TEXT         NULL,                                  -- 원인 후보 및 권장 조치 (지정된 불량 코드에서 모음)
    report_path             VARCHAR(500) NULL,                                  -- 생성한 리포트 파일 경로
    report_sent_at          DATETIME     NULL,                                  -- 리포트 발송 성공 시각
    created_at              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,    -- 검사 행 생성 시각 (검사 시작 시각)
    updated_at              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT ck_pi_dimension_result CHECK (dimension_result IN ('PENDING','PASS','RECHECK','FAIL')),
    CONSTRAINT ck_pi_patchcore_result CHECK (patchcore_result IN ('PENDING','PASS','FAIL')),
    CONSTRAINT ck_pi_yolo_status      CHECK (yolo_status IN ('NOT_STARTED','IN_PROGRESS','COMPLETED')),
    CONSTRAINT ck_pi_centering_state  CHECK (centering_state IN ('OFF','ON','UNKNOWN')),
    CONSTRAINT ck_pi_interlock_state  CHECK (interlock_state IN ('0','1','UNKNOWN')),
    INDEX ix_pi_product_created (product_name, created_at),
    INDEX ix_product_inspection_product_serial (product_serial),
    INDEX ix_product_inspection_final_result (final_result),
    INDEX ix_product_inspection_created_at (created_at)
);

-- ---------------------------------------------------------------------------
-- 3D 치수: 전체 검사 1회당 0~1행. 기준 치수는 검사 당시 값으로 보관.
-- 판정 한계 (mm, inspection/station_3d/config.py 와 같은 값. 정상 차 5회 스캔 표준편차의 2배·3배)
--          정상(재검) 한계   불량 한계
--   가로        1.5            2.5
--   길이(전폭)   3.5            5.5
--   높이        1.5            2.0
-- 축별: |편차| <= 정상 한계 PASS, ~ 불량 한계 RECHECK(재검, 다시 스캔), 초과 FAIL, 값 없음 PENDING (경계값은 좋은 쪽)
-- 종합: 하나라도 FAIL → FAIL, (FAIL 없이) 하나라도 누락 → PENDING, 하나라도 RECHECK → RECHECK, 나머지 PASS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_dimension_inspection (
    id                 INT AUTO_INCREMENT PRIMARY KEY,                         -- 치수 검사 행 식별번호
    inspection_id      VARCHAR(64) NOT NULL UNIQUE,                            -- 전체 검사와 연결하는 검사번호
    centering_state    VARCHAR(8)  NOT NULL DEFAULT 'UNKNOWN',                 -- 측정 시점 센터링 (OFF / ON / UNKNOWN)
    interlock_state    VARCHAR(8)  NOT NULL DEFAULT 'UNKNOWN',                 -- 측정 시점 인터락 (0 / 1 / UNKNOWN)
    width_mm           DOUBLE NULL,                                            -- 실측 가로 (mm)
    length_mm          DOUBLE NULL,                                            -- 실측 길이 (mm)
    height_mm          DOUBLE NULL,                                            -- 실측 높이 (mm)
    standard_width_mm  DOUBLE NULL,                                            -- 기준 가로 (mm)
    standard_length_mm DOUBLE NULL,                                            -- 기준 길이 (mm)
    standard_height_mm DOUBLE NULL,                                            -- 기준 높이 (mm)
    width_result       VARCHAR(16) GENERATED ALWAYS AS (                       -- [자동] 가로 판정
        CASE WHEN width_mm IS NULL OR standard_width_mm IS NULL THEN 'PENDING'
             WHEN ABS(width_mm - standard_width_mm) > 2.500001 THEN 'FAIL'
             WHEN ABS(width_mm - standard_width_mm) > 1.500001 THEN 'RECHECK'
             ELSE 'PASS' END) STORED NOT NULL,
    length_result      VARCHAR(16) GENERATED ALWAYS AS (                       -- [자동] 길이 판정
        CASE WHEN length_mm IS NULL OR standard_length_mm IS NULL THEN 'PENDING'
             WHEN ABS(length_mm - standard_length_mm) > 5.500001 THEN 'FAIL'
             WHEN ABS(length_mm - standard_length_mm) > 3.500001 THEN 'RECHECK'
             ELSE 'PASS' END) STORED NOT NULL,
    height_result      VARCHAR(16) GENERATED ALWAYS AS (                       -- [자동] 높이 판정
        CASE WHEN height_mm IS NULL OR standard_height_mm IS NULL THEN 'PENDING'
             WHEN ABS(height_mm - standard_height_mm) > 2.000001 THEN 'FAIL'
             WHEN ABS(height_mm - standard_height_mm) > 1.500001 THEN 'RECHECK'
             ELSE 'PASS' END) STORED NOT NULL,
    dimension_result   VARCHAR(16) GENERATED ALWAYS AS (                       -- [자동] 세 치수 종합 판정
        CASE
            WHEN (width_mm IS NOT NULL AND standard_width_mm IS NOT NULL AND ABS(width_mm - standard_width_mm) > 2.500001)
              OR (length_mm IS NOT NULL AND standard_length_mm IS NOT NULL AND ABS(length_mm - standard_length_mm) > 5.500001)
              OR (height_mm IS NOT NULL AND standard_height_mm IS NOT NULL AND ABS(height_mm - standard_height_mm) > 2.000001) THEN 'FAIL'
            WHEN width_mm IS NULL OR standard_width_mm IS NULL
              OR length_mm IS NULL OR standard_length_mm IS NULL
              OR height_mm IS NULL OR standard_height_mm IS NULL THEN 'PENDING'
            WHEN ABS(width_mm - standard_width_mm) > 1.500001
              OR ABS(length_mm - standard_length_mm) > 3.500001
              OR ABS(height_mm - standard_height_mm) > 1.500001 THEN 'RECHECK'
            ELSE 'PASS'
        END) STORED NOT NULL,
    scan_file_path     VARCHAR(500) NULL,                                      -- 3D 스캔 원본 경로
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT ck_pdi_centering_state CHECK (centering_state IN ('OFF','ON','UNKNOWN')),
    CONSTRAINT ck_pdi_interlock_state CHECK (interlock_state IN ('0','1','UNKNOWN')),
    CONSTRAINT fk_pdi_inspection FOREIGN KEY (inspection_id)
        REFERENCES product_inspection (inspection_id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------------
-- 불량 종류: 5가지 공정 케이스 · 원인 후보 (원인은 확정 원인과 구분하여 '후보'로 관리)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS defect_type (
    defect_code        VARCHAR(10)  PRIMARY KEY,                               -- 불량 코드 (D01~D05)
    defect_name        VARCHAR(100) NOT NULL,                                  -- 불량 이름
    defect_category    VARCHAR(50)  NOT NULL,                                  -- 도장 부족 / 스크래치
    defect_location    VARCHAR(100) NULL,                                      -- 불량 발생 위치
    description        TEXT         NULL,                                      -- 불량 상세 설명
    cause_candidates   JSON         NOT NULL,                                  -- 원인 후보 배열
    recommended_action TEXT         NULL,                                      -- 권장 점검 및 조치
    is_active          BOOLEAN      NOT NULL DEFAULT TRUE,                     -- 불량 분류 사용 여부
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT IGNORE INTO defect_type (defect_code, defect_name, defect_category, defect_location, description, cause_candidates, recommended_action) VALUES
('D01', '측면 도장 부족', '도장 부족', '측면', '제품 측면의 도장이 부족함',
 JSON_ARRAY('페인트 공급 부족', '노즐 막힘', '분사 위치 오류'), '페인트 공급 상태, 노즐, 측면 분사 위치 확인'),
('D02', '정면 도장 부족', '도장 부족', '정면', '제품 정면의 도장이 부족함',
 JSON_ARRAY('페인트 공급 부족', '노즐 막힘', '분사 위치 오류'), '페인트 공급 상태, 노즐, 정면 분사 위치 확인'),
('D03', '상단(천장) 도장 부족', '도장 부족', '상단', '제품 상단(천장)의 도장이 부족함',
 JSON_ARRAY('페인트 공급 부족', '노즐 막힘', '분사 위치 오류'), '페인트 공급 상태, 노즐, 상단 분사 위치 확인'),
('D04', '지그 조립 불완전으로 인한 스크래치', '스크래치', '지그 접촉부', '지그 부품이 덜 조립되어 작동 중 제품과 접촉',
 JSON_ARRAY('지그 부품 조립 불완전'), '지그 조립·고정 상태와 작동 중 제품 접촉 확인'),
('D05', '턴테이블 안착 중 발생한 스크래치', '스크래치', '하단·턴테이블 접촉부', '턴테이블에 올리는 과정에서 접촉',
 JSON_ARRAY('안착 과정에서 발생한 접촉'), '제품 안착 과정과 턴테이블 접촉 부위 확인');

-- ---------------------------------------------------------------------------
-- 관리자: 계정 · 권한 · 리포트 수신 설정. 비밀번호는 평문 저장 금지 (애플리케이션이 bcrypt 해시 생성)
-- 계정은 backend 폴더에서 python seed.py 로 만든다 (admin / admin1234 최고관리자 등)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_user (
    id                     INT AUTO_INCREMENT PRIMARY KEY,                     -- 관리자 식별번호
    username               VARCHAR(50)  NOT NULL UNIQUE,                       -- 로그인 아이디
    password_hash          VARCHAR(100) NOT NULL,                              -- 비밀번호 해시값
    name                   VARCHAR(50)  NOT NULL,                              -- 관리자 이름
    email                  VARCHAR(255) NULL UNIQUE,                           -- 이메일 및 리포트 수신 주소
    role                   VARCHAR(16)  NOT NULL DEFAULT 'VIEWER',             -- 최고관리자 / 관리자 / 조회 전용
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE,                 -- 계정 활성 여부
    receive_defect_reports BOOLEAN      NOT NULL DEFAULT FALSE,                -- 불량 리포트 수신 여부
    last_login_at          DATETIME     NULL,                                  -- 마지막 로그인 성공 시각
    created_at             DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT ck_admin_role CHECK (role IN ('SUPER_ADMIN','ADMIN','VIEWER'))
);

-- ---------------------------------------------------------------------------
-- 장비 안전 알람: 센터링 · 인터락 발생 / 해제 이력
-- 한 검사에 여러 알람 가능. 두 조건 모두 이상이면 각각 1행. 정지 후 이력을 저장하며,
-- 알람 해제만으로 검사가 자동으로 다시 시작되지는 않는다 (DB 는 기록용, 장비 정지는 검사 프로그램이 함)
-- 검사를 지워도 알람 이력은 남는다 (inspection_id 만 NULL)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equipment_safety_alarm (
    id               INT AUTO_INCREMENT PRIMARY KEY,                           -- 알람 식별번호
    inspection_id    VARCHAR(64)  NULL,                                        -- 관련 검사번호 (시작 전이면 NULL)
    alarm_type       VARCHAR(16)  NOT NULL,                                    -- CENTERING 센터링 / INTERLOCK 인터락
    alarm_status     VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE',                   -- ACTIVE 발생 중 / CLEARED 해제됨
    centering_state  VARCHAR(8)   NOT NULL,                                    -- 알람 시점 센터링 상태
    interlock_state  VARCHAR(8)   NOT NULL,                                    -- 알람 시점 인터락 상태
    inspection_stage VARCHAR(16)  NOT NULL,                                    -- PRECHECK 사전 확인 / DIMENSION 치수 / PATCHCORE / YOLO
    alarm_message    TEXT         NULL,                                        -- 알람 상세 내용
    occurred_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,          -- 알람 발생 시각
    cleared_at       DATETIME     NULL,                                        -- 알람 해제 확인 시각
    CONSTRAINT ck_alarm_type            CHECK (alarm_type IN ('CENTERING','INTERLOCK')),
    CONSTRAINT ck_alarm_status          CHECK (alarm_status IN ('ACTIVE','CLEARED')),
    CONSTRAINT ck_alarm_centering_state CHECK (centering_state IN ('OFF','ON','UNKNOWN')),
    CONSTRAINT ck_alarm_interlock_state CHECK (interlock_state IN ('0','1','UNKNOWN')),
    CONSTRAINT ck_alarm_stage           CHECK (inspection_stage IN ('PRECHECK','DIMENSION','PATCHCORE','YOLO')),
    INDEX ix_equipment_safety_alarm_inspection_id (inspection_id),
    INDEX ix_alarm_status_time (alarm_status, occurred_at),
    INDEX ix_equipment_safety_alarm_occurred_at (occurred_at),
    CONSTRAINT fk_alarm_inspection FOREIGN KEY (inspection_id)
        REFERENCES product_inspection (inspection_id) ON DELETE SET NULL ON UPDATE CASCADE
);
