// turntable.ino — 28BYJ-48 턴테이블 + 초음파 인터락 + 레이저 놓임 검사 (Arduino Uno R3, 보드 1개)
// (2026-10-06 v2.6: sketch_oct6a 인터락 병합본 + sketch_oct6b 놓임 검사 병합.
//  호스트: turntable.py 가 STAT/EVT/HINT/BEAM 무시, ERR,INTERLOCK 처리, C/K 로 놓임 검사)
// 필요 라이브러리: AccelStepper
//
// 기능 스위치 (0으로 끄면 해당 기능이 컴파일에서 빠짐. 인터락은 항상 켜짐)
#define ENABLE_TURNTABLE 1     // 스텝모터 턴테이블 (R/A/Z/P). 0이면 인터락 + 놓임 검사만
#define ENABLE_PLACEMENT 1     // 레이저 + 광센서 놓임 검사 (C/K/L1/L0)
//
// 배선
//   ULN2003  IN1→D2, IN2→D3, IN3→D6, IN4→D7  (드라이버 +5V는 외부 전원, GND 공통)
//   HC-SR04 #1  TRIG→D9,  ECHO→D10
//   HC-SR04 #2  TRIG→D11, ECHO→D12
//   KY-006 S→D8 / − → GND            (인터락 경보 + 놓임 오류음 공용)
//   리셋 버튼 D4↔GND, 릴레이 입력 D5 (선택: 드라이버 +5V 라인 차단), LED D13
//   KY-008 레이저 #1 S→A2, #2 S→A3   (v2.5까지 D6/D7이었으나 스텝모터와 겹쳐 이동)
//   KY-018 광센서 #1 S→A0, #2 S→A1
//
// 시리얼 명령 (115200bps, '\n'으로 끝):
//   R<deg> : 현재 위치에서 deg만큼 회전        -> 완료 시 "DONE"
//   A<deg> : 절대 각도로 이동                  -> "DONE"
//   Z      : 현재 위치를 0도로                 -> "DONE"
//   P      : 현재 각도 출력
//   C      : 놓임 검사   -> PLACE,OK / PLACE,ERR,<OFFSET_X|OFFSET_Y|MISSING|BEAM_FAULT|UNSTABLE|INTERLOCK>
//   K      : 레이저/광센서 보정(빔 사이를 비운 상태에서) -> CAL,OK / CAL,ERR,<마스크> / CAL,ERR,INTERLOCK
//   L1/L0  : 빔 정렬 모드 켜기/끄기 (BEAM,<a%>,<b%> 를 0.3초마다 출력, 둘 다 90%↑이면 LED 켬)
// 추가 응답:
//   ERR,INTERLOCK[,deg] : 인터락 정지/명령 거부 (RUN 복귀 전까지 R/A/C/K/L 거부)
//   ERR,BUSY            : 이동·검사 중에 새 명령
//   STAT,/EVT,/HINT,/BEAM, : 상태 보고 (호스트는 응답으로 취급하지 않음)
//
// 주의: Uno는 PC에서 포트를 열 때마다 리셋됩니다. 포트를 연 뒤 약 2초 기다렸다가 명령을 보내세요.
// 주의: 놓임 검사(C)는 보정(K)을 한 번 한 뒤에만 동작합니다 (부팅 직후엔 BEAM_FAULT).

#include <avr/wdt.h>
#if ENABLE_TURNTABLE
#include <AccelStepper.h>
#endif

// ───────── 턴테이블 ─────────
#if ENABLE_TURNTABLE
const float STEPS_PER_REV = 4075.7728;      // 하프스텝 기준 한 바퀴
const unsigned long SETTLE_MS = 400;        // 도착 후 잔진동 대기

// HALF4WIRE는 (IN1, IN3, IN2, IN4) 순서. 마지막 false: 전역 생성 시 pinMode 호출 방지
AccelStepper stepper(AccelStepper::HALF4WIRE, 2, 6, 3, 7, false);

enum MoveState : uint8_t { MV_IDLE, MV_RUNNING, MV_SETTLING };
MoveState moveState = MV_IDLE;
unsigned long settleEnd = 0;
float targetDeg = 0.0;
#endif

// ───────── 인터락: 핀/파라미터 ─────────
const uint8_t NUM_SENSORS = 2;
const uint8_t TRIG[NUM_SENSORS] = {9, 11};
const uint8_t ECHO[NUM_SENSORS] = {10, 12};
const uint8_t BUZZER_PIN = 8;    // KY-006 (S)
const uint8_t RELAY_PIN  = 5;    // (선택) 드라이버 전원 차단용
const uint8_t RESET_PIN  = 4;    // 위험 구역 '바깥'에서 구역 전체가 보이는 위치
const uint8_t LED_PIN    = 13;

const uint8_t MOTOR_RUN  = HIGH; // Active-LOW 릴레이면 서로 바꿈
const uint8_t MOTOR_STOP = LOW;

const int  TRIP_CM          = 30;
const int  RELEASE_CM       = 35;
const uint8_t TRIP_CONFIRM  = 2;
const uint8_t FAULT_CONFIRM = 5;
const bool EXPECT_WALL      = true;
const unsigned long RISE_TIMEOUT_US  = 3000UL;    // 트리거 후 에코가 올라오기까지
const unsigned long ECHO_TIMEOUT_US  = 12000UL;   // 에코 펄스 최대 길이 (약 2m)
const unsigned long STUCK_TIMEOUT_US = 60000UL;   // ECHO가 계속 HIGH면 무응답 처리
const unsigned long SENSOR_GAP_US    = 15000UL;   // 센서 간 대기
const unsigned long CLEAR_HOLD_MS    = 1000;
const unsigned long STAT_PERIOD_MS   = 500;

enum State : uint8_t { ST_RUN, ST_TRIPPED, ST_FAULT };
const char* const STATE_NAME[] = {"RUN", "TRIPPED", "FAULT"};

struct Sensor { int cm; uint8_t tripCnt; uint8_t faultCnt; };
Sensor sensors[NUM_SENSORS];

State state = ST_FAULT;
bool clearTimerOn = false, resetReady = false;
unsigned long clearSince = 0, lastStat = 0, btnT = 0;
bool btnLast = HIGH;
uint16_t curTone = 0;

// ───────── 놓임 검사 (논블로킹 상태 머신) ─────────
// 검사/보정 중에도 loop()가 계속 돌아야 하므로(워치독 500ms, 초음파 측정 타이밍) delay()를 쓰지 않는다.
#if ENABLE_PLACEMENT
const uint8_t LASER_PIN[2] = {A2, A3};
const uint8_t LDR_PIN[2]   = {A0, A1};

const uint16_t AMBIENT_MS = 500;   // 레이저 OFF 상태 안정화 시간
const uint16_t WARMUP_MS  = 400;   // 레이저 ON 후 안정화 시간
const uint16_t SETTLE_PL_MS = 1500;// 같은 패턴이 이만큼 유지돼야 확정
const uint16_t TIMEOUT_MS = 8000;  // 이 시간 안에 안정 안 되면 UNSTABLE
const uint16_t SAMPLE_MS  = 10;
const uint16_t ALARM_MS   = 3000;
const int MIN_SPAN  = 80;          // ADC 차이가 이보다 작으면 빔 불량
const int LIT_PCT   = 60;          // 이 이상이면 '통과'
const int BLOCK_PCT = 40;          // 이 이하이면 '차단'
const bool CROSS_MODE = true;      // true: 십자(둘 다 차단=OK), false: 게이트(둘 다 통과=OK)
const bool USE_BUZZER = true;
const uint8_t AVG_N = 16;          // 평균 샘플 수 (2ms 간격)

enum PlMode : uint8_t { PL_IDLE, PL_CAL, PL_CHECK, PL_ALIGN };
enum PlStep : uint8_t { S_AMB_WAIT, S_AMB_AVG, S_ON_WAIT, S_ON_AVG, S_SETTLE };
PlMode plMode = PL_IDLE;
PlStep plStep = S_AMB_WAIT;
uint8_t plIdx = 0, calBad = 0, plLast = 255;
unsigned long plT = 0, plStart = 0, plSince = 0, plSampleT = 0, plAlignRpt = 0;

long avgSum[2];
uint8_t avgN = 0;
unsigned long avgT = 0;

int  offBase[2];                   // 보정 시 레이저 OFF 값
int  spanV[2];                     // on - off (부호 있음)
int  offNow[2];                    // 검사 직전 주변광
bool calOk[2] = {false, false};
int  ema[2];
bool blocked[2];
bool alignGood = false;            // 정렬 모드에서 두 빔 모두 맞음 → LED
unsigned long alarmUntil = 0;

int readLdr(uint8_t i) { analogRead(LDR_PIN[i]); return analogRead(LDR_PIN[i]); }

void lasers(bool a, bool b) {
  digitalWrite(LASER_PIN[0], a);
  digitalWrite(LASER_PIN[1], b);
}

void avgBegin() { avgSum[0] = avgSum[1] = 0; avgN = 0; avgT = millis(); }

bool avgPoll() {                    // 두 채널을 2ms 간격으로 AVG_N번 평균. 끝나면 true
  if (millis() - avgT >= 2) {
    avgT = millis();
    for (uint8_t i = 0; i < 2; i++) avgSum[i] += readLdr(i);
    avgN++;
  }
  return avgN >= AVG_N;
}

void sampleLdr() {
  for (uint8_t i = 0; i < 2; i++) ema[i] = (ema[i] * 3 + readLdr(i)) / 4;
}

int levelPct(uint8_t i, int base) {
  if (spanV[i] == 0) return 0;
  return (int)(((long)(ema[i] - base) * 100L) / spanV[i]);
}

void updateBlocked(uint8_t i, int base) {
  int lv = levelPct(i, base);
  if (blocked[i] && lv > LIT_PCT) blocked[i] = false;
  else if (!blocked[i] && lv < BLOCK_PCT) blocked[i] = true;
}

uint8_t readPattern(const int base[2]) {
  for (uint8_t i = 0; i < 2; i++) updateBlocked(i, base[i]);
  return (blocked[0] ? 1 : 0) | (blocked[1] ? 2 : 0);
}

bool plBusy() { return plMode == PL_CAL || plMode == PL_CHECK; }

void plAlarm() { if (USE_BUZZER) alarmUntil = millis() + ALARM_MS; }

void reportErr(const __FlashStringHelper* code) {
  Serial.print(F("PLACE,ERR,")); Serial.println(code);
  plAlarm();
}

void reportPlace(uint8_t p) {
  if (CROSS_MODE) {
    if (p == 3)      { Serial.println(F("PLACE,OK")); return; }
    if (p == 1)      reportErr(F("OFFSET_X"));
    else if (p == 2) reportErr(F("OFFSET_Y"));
    else             reportErr(F("MISSING"));
  } else {
    if (p == 0)      { Serial.println(F("PLACE,OK")); return; }
    if (p == 1)      reportErr(F("BLOCK_B0"));
    else if (p == 2) reportErr(F("BLOCK_B1"));
    else             reportErr(F("BLOCK_BOTH"));
  }
}

void plStopAlign() {
  if (plMode != PL_ALIGN) return;
  plMode = PL_IDLE; lasers(false, false); alignGood = false;
  Serial.println(F("HINT,ALIGN_OFF"));
}

void plStartCal() {
  plMode = PL_CAL; plIdx = 0; calBad = 0;
  lasers(false, false);
  plT = millis(); plStep = S_AMB_WAIT;
}

void plStartCheck() {
  if (!calOk[0] || !calOk[1]) { reportErr(F("BEAM_FAULT")); return; }
  plMode = PL_CHECK;
  lasers(false, false);                 // 1) 주변광 재측정(레이저 OFF)
  plT = millis(); plStep = S_AMB_WAIT;
}

void plStartAlign() {
  plMode = PL_ALIGN; alignGood = false;
  lasers(true, true);
  for (uint8_t i = 0; i < 2; i++) ema[i] = readLdr(i);
  plSampleT = plAlignRpt = millis();
  Serial.println(F("HINT,ALIGN_ON"));
}

// 인터락이 걸리면 진행 중인 검사/보정/정렬을 즉시 중단 (레이저 OFF)
void plOnInterlock() {
  PlMode m = plMode;
  if (m == PL_IDLE) return;
  plMode = PL_IDLE; lasers(false, false); alignGood = false;
  if (m == PL_CHECK)      Serial.println(F("PLACE,ERR,INTERLOCK"));
  else if (m == PL_CAL)   Serial.println(F("CAL,ERR,INTERLOCK"));
  else                    Serial.println(F("HINT,ALIGN_OFF"));
}

void plUpdate() {                       // 매 loop 호출
  unsigned long now = millis();
  switch (plMode) {
    case PL_IDLE: return;

    case PL_ALIGN:
      if (now - plSampleT >= SAMPLE_MS) { plSampleT = now; sampleLdr(); }
      if (now - plAlignRpt >= 300) {
        plAlignRpt = now;
        int a = levelPct(0, offBase[0]), b = levelPct(1, offBase[1]);
        Serial.print(F("BEAM,")); Serial.print(a); Serial.print(','); Serial.println(b);
        alignGood = (a >= 90 && b >= 90);
      }
      return;

    case PL_CAL:
      switch (plStep) {
        case S_AMB_WAIT:
          if (now - plT >= AMBIENT_MS) { avgBegin(); plStep = S_AMB_AVG; }
          break;
        case S_AMB_AVG:
          if (avgPoll()) {
            offBase[plIdx] = (int)(avgSum[plIdx] / AVG_N);
            digitalWrite(LASER_PIN[plIdx], HIGH);
            plT = now; plStep = S_ON_WAIT;
          }
          break;
        case S_ON_WAIT:
          if (now - plT >= WARMUP_MS) { avgBegin(); plStep = S_ON_AVG; }
          break;
        case S_ON_AVG:
          if (avgPoll()) {
            int on = (int)(avgSum[plIdx] / AVG_N);
            lasers(false, false);
            spanV[plIdx] = on - offBase[plIdx];
            calOk[plIdx] = abs(spanV[plIdx]) >= MIN_SPAN;
            if (!calOk[plIdx]) calBad |= (1 << plIdx);
            Serial.print(F("HINT,CAL")); Serial.print(plIdx);
            Serial.print(F(" off=")); Serial.print(offBase[plIdx]);
            Serial.print(F(" on="));  Serial.println(on);
            plIdx++;
            if (plIdx >= 2) {
              plMode = PL_IDLE;
              if (calBad) { Serial.print(F("CAL,ERR,")); Serial.println(calBad); }
              else        Serial.println(F("CAL,OK"));
            } else {
              plT = now; plStep = S_AMB_WAIT;
            }
          }
          break;
        default: break;
      }
      return;

    case PL_CHECK:
      switch (plStep) {
        case S_AMB_WAIT:
          if (now - plT >= AMBIENT_MS) { avgBegin(); plStep = S_AMB_AVG; }
          break;
        case S_AMB_AVG:
          if (avgPoll()) {
            for (uint8_t i = 0; i < 2; i++) offNow[i] = (int)(avgSum[i] / AVG_N);
            lasers(true, true);           // 2) 레이저 ON
            plT = now; plStep = S_ON_WAIT;
          }
          break;
        case S_ON_WAIT:
          if (now - plT >= WARMUP_MS) {
            for (uint8_t i = 0; i < 2; i++) { ema[i] = readLdr(i); blocked[i] = true; }
            plLast = 255;
            plStart = plSince = plSampleT = now;
            plStep = S_SETTLE;
          }
          break;
        case S_SETTLE:                    // 3) 패턴이 SETTLE_PL_MS 동안 유지되면 확정
          if (now - plSampleT >= SAMPLE_MS) {
            plSampleT = now;
            sampleLdr();
            uint8_t p = readPattern(offNow);
            if (p != plLast) { plLast = p; plSince = now; }
            if (now - plSince >= SETTLE_PL_MS) {
              lasers(false, false);
              plMode = PL_IDLE;
              reportPlace(p);
              return;
            }
          }
          if (now - plStart >= TIMEOUT_MS) {
            lasers(false, false);
            plMode = PL_IDLE;
            reportErr(F("UNSTABLE"));
          }
          break;
        default: break;
      }
      return;
  }
}
#else
bool plBusy() { return false; }
void plOnInterlock() {}
void plUpdate() {}
#endif

// ───────── 턴테이블 동작 (논블로킹) ─────────
#if ENABLE_TURNTABLE
long degToSteps(float deg) { return lround(deg / 360.0 * STEPS_PER_REV); }
float currentDeg() { return stepper.currentPosition() * 360.0f / STEPS_PER_REV; }

void startMove(float deg) {
  targetDeg = deg;
  stepper.enableOutputs();
  stepper.moveTo(degToSteps(targetDeg));
  moveState = MV_RUNNING;
}

void abortMotion() {
  if (moveState == MV_IDLE) { stepper.disableOutputs(); return; }
  stepper.setCurrentPosition(stepper.currentPosition());   // 감속 없이 즉시 정지
  stepper.disableOutputs();
  targetDeg = currentDeg();                                // 다음 R이 실제 위치 기준이 되도록
  moveState = MV_IDLE;
  Serial.print(F("ERR,INTERLOCK,"));
  Serial.println(currentDeg(), 2);
}

void updateMotion() {
  if (moveState == MV_RUNNING) {
    stepper.run();
    if (stepper.distanceToGo() == 0) {
      moveState = MV_SETTLING;
      settleEnd = millis() + SETTLE_MS;      // 코일을 켠 채 잔진동 대기
    }
  } else if (moveState == MV_SETTLING) {
    if ((long)(millis() - settleEnd) >= 0) {
      stepper.disableOutputs();
      moveState = MV_IDLE;
      Serial.println(F("DONE"));
    }
  }
}

bool motionBusy() { return moveState != MV_IDLE; }
void motorCoilsOff() { stepper.disableOutputs(); }
#else
void abortMotion() {}
void updateMotion() {}
bool motionBusy() { return false; }
void motorCoilsOff() {}
#endif

// ───────── 센서 (논블로킹 상태 머신) ─────────
enum PingPhase : uint8_t { PH_GAP, PH_WAIT_RISE, PH_WAIT_FALL };
PingPhase phase = PH_GAP;
uint8_t curSensor = 0;
unsigned long phaseStartUs = 0, echoStartUs = 0;

void finishPing(uint8_t i, int cm) {
  sensors[i].cm = cm;
  bool noEcho = (cm < 0);

  if (noEcho && EXPECT_WALL) { if (sensors[i].faultCnt < 255) sensors[i].faultCnt++; }
  else sensors[i].faultCnt = 0;

  if (!noEcho && cm <= TRIP_CM) { if (sensors[i].tripCnt < 255) sensors[i].tripCnt++; }
  else sensors[i].tripCnt = 0;
}

bool nextSensor() {                      // true = 센서 한 바퀴 완료
  phaseStartUs = micros();
  phase = PH_GAP;
  curSensor++;
  if (curSensor >= NUM_SENSORS) { curSensor = 0; return true; }
  return false;
}

bool pollSensors() {                     // 매 loop 호출. 한 바퀴 끝나면 true
  unsigned long now = micros();
  switch (phase) {
    case PH_GAP:
      if (now - phaseStartUs < SENSOR_GAP_US) return false;
      if (digitalRead(ECHO[curSensor])) {                 // 이전 에코가 아직 HIGH면 잠시 대기
        if (now - phaseStartUs < STUCK_TIMEOUT_US) return false;
        finishPing(curSensor, -1);                        // 너무 오래 HIGH → 무응답
        return nextSensor();
      }
      digitalWrite(TRIG[curSensor], LOW);  delayMicroseconds(2);
      digitalWrite(TRIG[curSensor], HIGH); delayMicroseconds(10);
      digitalWrite(TRIG[curSensor], LOW);
      phaseStartUs = micros();
      phase = PH_WAIT_RISE;
      return false;

    case PH_WAIT_RISE:
      if (digitalRead(ECHO[curSensor])) { echoStartUs = now; phase = PH_WAIT_FALL; }
      else if (now - phaseStartUs > RISE_TIMEOUT_US) { finishPing(curSensor, -1); return nextSensor(); }
      return false;

    case PH_WAIT_FALL:
      if (!digitalRead(ECHO[curSensor])) {
        finishPing(curSensor, (int)((now - echoStartUs) / 58UL));
        return nextSensor();
      }
      if (now - echoStartUs > ECHO_TIMEOUT_US) { finishPing(curSensor, -1); return nextSensor(); }
      return false;
  }
  return false;
}

bool anyTrip()  { for (uint8_t i = 0; i < NUM_SENSORS; i++) if (sensors[i].tripCnt  >= TRIP_CONFIRM)  return true; return false; }
bool anyFault() { for (uint8_t i = 0; i < NUM_SENSORS; i++) if (sensors[i].faultCnt >= FAULT_CONFIRM) return true; return false; }

bool sensorClear(uint8_t i) {
  int cm = sensors[i].cm;
  if (cm < 0) return !EXPECT_WALL;
  return cm > RELEASE_CM;
}
bool allClear() { for (uint8_t i = 0; i < NUM_SENSORS; i++) if (!sensorClear(i)) return false; return true; }

// ───────── 출력 ─────────
void applyOutputs() {
  bool run = (state == ST_RUN);
  digitalWrite(RELAY_PIN, run ? MOTOR_RUN : MOTOR_STOP);
#if ENABLE_PLACEMENT
  digitalWrite(LED_PIN, run ? (alignGood ? HIGH : LOW) : HIGH);   // 정렬 모드 OK 표시는 RUN일 때만
#else
  digitalWrite(LED_PIN, run ? LOW : HIGH);
#endif
  if (!run) motorCoilsOff();                         // 정지 상태에선 코일도 계속 OFF
}

void setTone(uint16_t f) {
  if (f == curTone) return;
  curTone = f;
  if (f) tone(BUZZER_PIN, f); else noTone(BUZZER_PIN);
}

void updateBuzzer() {
  unsigned long t = millis();
  if (state == ST_RUN) {                             // 인터락 경보가 아닐 때만 놓임 오류음
#if ENABLE_PLACEMENT
    if ((long)(alarmUntil - t) > 0) { setTone(1000); return; }
#endif
    setTone(0); return;
  }
  if (resetReady)             { setTone((t % 1000) < 100 ? 2000 : 0); return; }  // 리셋 가능
  if (state == ST_TRIPPED)    { setTone(3000); return; }                         // 위험 존재
  setTone((t % 600) < 300 ? 1000 : 2500);                                        // FAULT 사이렌
}

// ───────── PC 보고 / 상태 전환 ─────────
void sendStat() {
  Serial.print(F("STAT,")); Serial.print(STATE_NAME[state]);
  for (uint8_t i = 0; i < NUM_SENSORS; i++) { Serial.print(','); Serial.print(sensors[i].cm); }
  Serial.println();
  lastStat = millis();
}

void enterState(State n) {
  state = n;
  applyOutputs();                       // 릴레이/코일 차단을 가장 먼저
  if (n != ST_RUN) {
    abortMotion();                      // 진행 중인 이동 취소 + 호스트에 ERR 통지
    plOnInterlock();                    // 진행 중인 놓임 검사/보정/정렬 중단
#if ENABLE_PLACEMENT
    alarmUntil = 0;
#endif
  }
  clearTimerOn = false; resetReady = false;
  Serial.print(F("EVT,")); Serial.println(STATE_NAME[n]);
  sendStat();
}

// ───────── 리셋 ─────────
bool resetEdge() {
  bool level = digitalRead(RESET_PIN);
  if (level != btnLast && millis() - btnT > 30) {
    btnT = millis(); btnLast = level;
    if (level == LOW) return true;
  }
  return false;
}

void handleLatched(bool pressed) {
  if (!allClear()) { clearTimerOn = false; resetReady = false; return; }
  if (!clearTimerOn) { clearTimerOn = true; clearSince = millis(); }
  resetReady = (millis() - clearSince >= CLEAR_HOLD_MS);
  if (pressed && resetReady) enterState(ST_RUN);
}

// ───────── 시리얼 명령 (논블로킹) ─────────
char cmdBuf[24];
uint8_t cmdLen = 0;

void execCommand(char* s) {
  char cmd = toupper(s[0]);
#if ENABLE_TURNTABLE
  float value = atof(s + 1);
#endif

  if (cmd == 'R' || cmd == 'A') {
#if ENABLE_TURNTABLE
    if (state != ST_RUN)       { Serial.println(F("ERR,INTERLOCK")); return; }
    if (motionBusy() || plBusy()) { Serial.println(F("ERR,BUSY"));   return; }   // 검사 중엔 모터를 돌리지 않음
    startMove(cmd == 'R' ? targetDeg + value : value);
#else
    Serial.println(F("ERR"));
#endif
  } else if (cmd == 'Z') {
#if ENABLE_TURNTABLE
    if (motionBusy())          { Serial.println(F("ERR,BUSY")); return; }
    stepper.setCurrentPosition(0);
    targetDeg = 0.0;
    Serial.println(F("DONE"));
#else
    Serial.println(F("ERR"));
#endif
  } else if (cmd == 'P') {
#if ENABLE_TURNTABLE
    Serial.println(currentDeg(), 2);
#else
    Serial.println(F("ERR"));
#endif
#if ENABLE_PLACEMENT
  } else if (cmd == 'C' || cmd == 'K') {
    if (state != ST_RUN) { Serial.println(cmd == 'C' ? F("PLACE,ERR,INTERLOCK") : F("CAL,ERR,INTERLOCK")); return; }
    if (motionBusy() || plBusy()) { Serial.println(F("ERR,BUSY")); return; }   // 이동 중엔 진동으로 검사가 흔들림
    plStopAlign();
    if (cmd == 'C') plStartCheck(); else plStartCal();
  } else if (cmd == 'L') {
    if (state != ST_RUN) { Serial.println(F("ERR,INTERLOCK")); return; }
    if (motionBusy() || plBusy()) { Serial.println(F("ERR,BUSY")); return; }
    if (s[1] == '1') { if (plMode != PL_ALIGN) plStartAlign(); }
    else plStopAlign();
#endif
  } else {
    Serial.println(F("ERR"));
  }
}

void handleSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      cmdBuf[cmdLen] = 0;
      if (cmdLen) execCommand(cmdBuf);
      cmdLen = 0;
    } else if (!(cmdLen == 0 && c == ' ') && cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    }
  }
}

// ───────── setup / loop ─────────
void setup() {
  MCUSR = 0;  wdt_disable();             // ★ 워치독 리셋 직후 재리셋 루프 방지

  digitalWrite(RELAY_PIN, MOTOR_STOP);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);  digitalWrite(LED_PIN, HIGH);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(RESET_PIN, INPUT_PULLUP);
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    pinMode(TRIG[i], OUTPUT); digitalWrite(TRIG[i], LOW);
    pinMode(ECHO[i], INPUT);
  }
#if ENABLE_PLACEMENT
  for (uint8_t i = 0; i < 2; i++) { pinMode(LASER_PIN[i], OUTPUT); digitalWrite(LASER_PIN[i], LOW); }
#endif

#if ENABLE_TURNTABLE
  stepper.setMaxSpeed(700);              // 하프스텝/초 (약 10rpm)
  stepper.setAcceleration(350);
  stepper.enableOutputs();               // pinMode 설정
  stepper.disableOutputs();              // 코일 OFF
#endif

  Serial.begin(115200);
  btnLast = digitalRead(RESET_PIN);

  tone(BUZZER_PIN, 2000, 80); delay(160);
  tone(BUZZER_PIN, 3000, 80); delay(160);

  phaseStartUs = micros();
  for (uint8_t k = 0; k < FAULT_CONFIRM; k++) { while (!pollSensors()) {} }   // 워밍업 스캔

  for (uint8_t i = 0; i < NUM_SENSORS; i++) {      // 설치 점검용 힌트
    if (sensors[i].cm >= 0 && sensors[i].cm <= RELEASE_CM) {
      Serial.print(F("HINT,S")); Serial.print(i + 1);
      Serial.print(F(" reads ")); Serial.print(sensors[i].cm);
      Serial.println(F("cm: 정지 범위 안에 구조물이 있음. 센서 위치/각도 조정"));
    }
  }

  Serial.println(F("READY"));
  enterState(anyFault() ? ST_FAULT : (anyTrip() ? ST_TRIPPED : ST_RUN));

  wdt_enable(WDTO_500MS);                // ★ 500ms 안에 wdt_reset()이 없으면 리셋
}

void loop() {
  wdt_reset();

  static bool pendingPress = false;
  if (resetEdge()) pendingPress = true;            // 스캔 판정 시점까지 눌림을 보관

  if (pollSensors()) {                             // 센서 한 바퀴 완료 시에만 판정
    if (state == ST_RUN) {
      if      (anyFault()) enterState(ST_FAULT);
      else if (anyTrip())  enterState(ST_TRIPPED);
    } else {
      handleLatched(pendingPress);
    }
    pendingPress = false;
  }

  if (state == ST_RUN) { updateMotion(); plUpdate(); }   // 정지 상태에선 절대 구동/검사하지 않음
  handleSerial();
  applyOutputs();
  updateBuzzer();
  if (millis() - lastStat >= STAT_PERIOD_MS) sendStat();
}
