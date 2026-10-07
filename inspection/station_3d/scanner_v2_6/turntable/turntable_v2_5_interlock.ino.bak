// turntable.ino — 28BYJ-48 턴테이블 + 초음파 인터락 (Arduino Uno R3)
// (2026-10-06 sketch_oct6a 병합본. 호스트: turntable.py 가 STAT/EVT/HINT 무시, ERR,INTERLOCK 처리)
// 필요 라이브러리: AccelStepper
//
// 배선
//   ULN2003  IN1→D2, IN2→D3, IN3→D6, IN4→D7  (드라이버 +5V는 외부 전원, GND 공통)
//   HC-SR04 #1  TRIG→D9,  ECHO→D10
//   HC-SR04 #2  TRIG→D11, ECHO→D12
//   KY-006 S→D8 / − → GND
//   리셋 버튼 D4↔GND, 릴레이 입력 D5 (선택: 드라이버 +5V 라인 차단), LED D13
//
// 시리얼 명령 (115200bps, '\n'으로 끝):
//   R<deg> : 현재 위치에서 deg만큼 회전        -> 완료 시 "DONE"
//   A<deg> : 절대 각도로 이동                  -> "DONE"
//   Z      : 현재 위치를 0도로                 -> "DONE"
//   P      : 현재 각도 출력
// 추가 응답:
//   ERR,INTERLOCK[,deg] : 인터락 정지/명령 거부 (RUN 복귀 전까지 R/A 거부)
//   ERR,BUSY            : 이동 중에 새 R/A/Z
//   STAT,/EVT,/HINT,    : 인터락 상태 보고 (호스트는 무시하면 됨)
//
// 주의: Uno는 PC에서 포트를 열 때마다 리셋됩니다. 포트를 연 뒤 약 2초 기다렸다가 명령을 보내세요.

#include <avr/wdt.h>
#include <AccelStepper.h>

// ───────── 턴테이블 ─────────
const float STEPS_PER_REV = 4075.7728;      // 하프스텝 기준 한 바퀴
const unsigned long SETTLE_MS = 400;        // 도착 후 잔진동 대기

// HALF4WIRE는 (IN1, IN3, IN2, IN4) 순서. 마지막 false: 전역 생성 시 pinMode 호출 방지
AccelStepper stepper(AccelStepper::HALF4WIRE, 2, 6, 3, 7, false);

enum MoveState : uint8_t { MV_IDLE, MV_RUNNING, MV_SETTLING };
MoveState moveState = MV_IDLE;
unsigned long settleEnd = 0;
float targetDeg = 0.0;

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

// ───────── 턴테이블 동작 (논블로킹) ─────────
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
  digitalWrite(LED_PIN,   run ? LOW : HIGH);
  if (!run) stepper.disableOutputs();                // 정지 상태에선 코일도 계속 OFF
}

void setTone(uint16_t f) {
  if (f == curTone) return;
  curTone = f;
  if (f) tone(BUZZER_PIN, f); else noTone(BUZZER_PIN);
}

void updateBuzzer() {
  unsigned long t = millis();
  if (state == ST_RUN)        { setTone(0); return; }
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
  if (n != ST_RUN) abortMotion();       // 진행 중인 이동 취소 + 호스트에 ERR 통지
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
  float value = atof(s + 1);

  if (cmd == 'R' || cmd == 'A') {
    if (state != ST_RUN)       { Serial.println(F("ERR,INTERLOCK")); return; }
    if (moveState != MV_IDLE)  { Serial.println(F("ERR,BUSY"));      return; }
    startMove(cmd == 'R' ? targetDeg + value : value);
  } else if (cmd == 'Z') {
    if (moveState != MV_IDLE)  { Serial.println(F("ERR,BUSY")); return; }
    stepper.setCurrentPosition(0);
    targetDeg = 0.0;
    Serial.println(F("DONE"));
  } else if (cmd == 'P') {
    Serial.println(currentDeg(), 2);
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

  stepper.setMaxSpeed(700);              // 하프스텝/초 (약 10rpm)
  stepper.setAcceleration(350);
  stepper.enableOutputs();               // pinMode 설정
  stepper.disableOutputs();              // 코일 OFF

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

  if (state == ST_RUN) updateMotion();             // 정지 상태에선 절대 구동하지 않음
  handleSerial();
  applyOutputs();
  updateBuzzer();
  if (millis() - lastStat >= STAT_PERIOD_MS) sendStat();
}