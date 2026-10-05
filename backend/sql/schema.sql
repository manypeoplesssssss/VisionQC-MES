-- VisionQC AI MES - MySQL 8.x 스키마
-- 서버를 처음 실행하면 테이블은 자동 생성되므로, 여기서는 DB와 계정만 만들어도 된다.
-- (테이블 정의는 구조 확인/발표 자료용으로 같이 둠)

CREATE DATABASE IF NOT EXISTS visionqc_mes DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'mes_user'@'%' IDENTIFIED BY 'mes_pass';
GRANT ALL PRIVILEGES ON visionqc_mes.* TO 'mes_user'@'%';
FLUSH PRIVILEGES;

USE visionqc_mes;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    name          VARCHAR(50)  NOT NULL,
    role          ENUM('ADMIN','OPERATOR') NOT NULL DEFAULT 'OPERATOR',
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- 품목별 치수 규격 (기준값 ± 공차)
CREATE TABLE IF NOT EXISTS item_specs (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    item           VARCHAR(50) NOT NULL UNIQUE,
    width_nominal  FLOAT NOT NULL, width_tol  FLOAT NOT NULL,
    length_nominal FLOAT NOT NULL, length_tol FLOAT NOT NULL,
    height_nominal FLOAT NOT NULL, height_tol FLOAT NOT NULL,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 검사 1건 = 이미지 1장. inspected_at 이 시계열 기준
CREATE TABLE IF NOT EXISTS inspections (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    serial_no      VARCHAR(50)  NOT NULL,                          -- 제품 개체 ID (공정 간 추적 키)
    item           VARCHAR(50)  NOT NULL,                          -- Redcar / Bluecar / Greencar ...
    process        ENUM('DIM3D','PATCHCORE','YOLO') NOT NULL,      -- 3D치수 / 1차 PatchCore / 2차 YOLO
    inspected_at   DATETIME     NOT NULL,
    result         ENUM('OK','NG') NOT NULL,
    model_version  VARCHAR(50)  NULL,                              -- 사용한 AI 모델 버전
    image_filename VARCHAR(255) NOT NULL UNIQUE,                   -- 2026-10-05-Redcar-DIM3D-SN0001.jpg
    image_path     VARCHAR(500) NOT NULL,                          -- 2026-10-05/2026-10-05-Redcar-...
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_inspections_serial_no (serial_no),
    INDEX ix_insp_time         (inspected_at),
    INDEX ix_insp_process_time (process, inspected_at),
    INDEX ix_insp_item_time    (item, inspected_at),
    INDEX ix_insp_result_time  (result, inspected_at)
);

-- 3D 모델링 치수검사 결과 (검사 1 : 1)
CREATE TABLE IF NOT EXISTS dimension_results (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    inspection_id   INT NOT NULL UNIQUE,
    width_mm        FLOAT NOT NULL,
    length_mm       FLOAT NOT NULL,
    height_mm       FLOAT NOT NULL,
    status          ENUM('OK','NG') NOT NULL,                     -- 최종 판정 (규격 있으면 서버 판정)
    reported_status ENUM('OK','NG') NULL,                         -- 검사 PC가 보낸 판정
    FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE CASCADE
);

-- PatchCore / YOLO 결함 결과 (검사 1 : N, 박스마다 1행)
CREATE TABLE IF NOT EXISTS defect_results (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    inspection_id   INT NOT NULL,
    defect_detected BOOLEAN NOT NULL,
    type            VARCHAR(50) NULL,
    confidence      FLOAT NULL,
    box             JSON NULL,                                    -- [x1, y1, x2, y2] (px)
    INDEX ix_defect_results_inspection_id (inspection_id),
    FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE CASCADE
);
