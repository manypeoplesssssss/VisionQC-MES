// placement.ino — 십자형 놓임 검사: KY-008 x2 (레이저) + KY-018 x2 (LDR)
// 별도 아두이노(인터락/턴테이블 보드와 다른 보드)용. 시리얼 115200: C=검사, K=보정, A1/A0=정렬 모드
// 응답: PLACE,OK / PLACE,ERR,<OFFSET_X|OFFSET_Y|MISSING|BEAM_FAULT|UNSTABLE> / CAL,OK|ERR / BEAM,a,b
// (2026-10-06 sketch_oct6b에서 복사. 아직 PC 코드(turntable_scan 등)와 연결되지 않음)
const uint8_t LASER_PIN[2] = {6, 7};
const uint8_t LDR_PIN[2]   = {A0, A1};
const uint8_t BUZZER_PIN = 8, LED_PIN = 13;

const uint16_t AMBIENT_MS = 500;   // 레이저 OFF 상태 안정화 시간
const uint16_t WARMUP_MS  = 400;   // 레이저 ON 후 안정화 시간
const uint16_t SETTLE_MS  = 1500;  // 같은 패턴이 이만큼 유지돼야 확정
const uint16_t TIMEOUT_MS = 8000;  // 이 시간 안에 안정 안 되면 UNSTABLE
const uint16_t SAMPLE_MS  = 10;
const uint16_t ALARM_MS   = 3000;
const int MIN_SPAN  = 80;          // ADC 차이가 이보다 작으면 빔 불량
const int LIT_PCT   = 60;          // 이 이상이면 '통과'
const int BLOCK_PCT = 40;          // 이 이하이면 '차단'
const bool CROSS_MODE = true;      // true: 십자(둘 다 차단=OK), false: 게이트(둘 다 통과=OK)
const bool USE_BUZZER = true;

int  offBase[2];                   // 보정 시 레이저 OFF 값
int  spanV[2];                     // on - off (부호 있음)
bool calOk[2] = {false, false};
int  ema[2];
bool blocked[2];

int readLdr(uint8_t i) { analogRead(LDR_PIN[i]); return analogRead(LDR_PIN[i]); }

int readAvg(uint8_t i) {
  long s = 0;
  for (uint8_t k = 0; k < 16; k++) { s += readLdr(i); delay(2); }
  return (int)(s / 16);
}

void lasers(bool a, bool b) {
  digitalWrite(LASER_PIN[0], a);
  digitalWrite(LASER_PIN[1], b);
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

// ---------- 보정 (빔 사이에 아무것도 없을 때 실행) ----------
bool calibrate() {
  uint8_t bad = 0;
  for (uint8_t i = 0; i < 2; i++) {
    lasers(false, false);
    delay(AMBIENT_MS);
    int off = readAvg(i);
    digitalWrite(LASER_PIN[i], HIGH);
    delay(WARMUP_MS);
    int on = readAvg(i);
    lasers(false, false);
    offBase[i] = off;
    spanV[i]   = on - off;
    calOk[i]   = abs(spanV[i]) >= MIN_SPAN;
    if (!calOk[i]) bad |= (1 << i);
    Serial.print(F("HINT,CAL")); Serial.print(i);
    Serial.print(F(" off=")); Serial.print(off);
    Serial.print(F(" on="));  Serial.println(on);
  }
  if (bad) { Serial.print(F("CAL,ERR,")); Serial.println(bad); return false; }
  Serial.println(F("CAL,OK"));
  return true;
}

// ---------- 결과 보고 ----------
void alarm() {
  if (USE_BUZZER) tone(BUZZER_PIN, 1000, ALARM_MS);
}

void reportErr(const __FlashStringHelper* code) {
  Serial.print(F("PLACE,ERR,")); Serial.println(code);
  alarm();
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

// ---------- 검사 ----------
void doCheck() {
  if (!calOk[0] || !calOk[1]) { reportErr(F("BEAM_FAULT")); return; }

  // 1) 주변광 재측정 (레이저 OFF)
  lasers(false, false);
  delay(AMBIENT_MS);
  int offNow[2] = { readAvg(0), readAvg(1) };

  // 2) 레이저 ON
  lasers(true, true);
  delay(WARMUP_MS);
  for (uint8_t i = 0; i < 2; i++) { ema[i] = readLdr(i); blocked[i] = true; }

  // 3) 패턴이 SETTLE_MS 동안 유지되면 확정
  uint8_t last = 255;
  unsigned long start = millis(), since = start, tS = start;
  while (millis() - start < TIMEOUT_MS) {
    if (millis() - tS >= SAMPLE_MS) {
      tS += SAMPLE_MS;
      sampleLdr();
      uint8_t p = readPattern(offNow);
      if (p != last) { last = p; since = millis(); }
      if (millis() - since >= SETTLE_MS) {
        lasers(false, false);
        reportPlace(p);
        return;
      }
    }
  }
  lasers(false, false);
  reportErr(F("UNSTABLE"));
}

// ---------- 정렬 모드 ----------
bool alignOn = false;
unsigned long tAlign = 0, tAlignS = 0;

void setAlign(bool on) {
  alignOn = on;
  lasers(on, on);
  digitalWrite(LED_PIN, LOW);
  if (on) {
    for (uint8_t i = 0; i < 2; i++) ema[i] = readLdr(i);
    Serial.println(F("HINT,ALIGN_ON"));
  } else {
    Serial.println(F("HINT,ALIGN_OFF"));
  }
}

void updateAlign() {
  if (millis() - tAlignS >= SAMPLE_MS) { tAlignS += SAMPLE_MS; sampleLdr(); }
  if (millis() - tAlign >= 300) {
    tAlign = millis();
    int a = levelPct(0, offBase[0]), b = levelPct(1, offBase[1]);
    Serial.print(F("BEAM,")); Serial.print(a); Serial.print(','); Serial.println(b);
    digitalWrite(LED_PIN, (a >= 90 && b >= 90) ? HIGH : LOW);
  }
}

// ---------- 명령 처리 ----------
void handleSerial() {
  static char buf[8];
  static uint8_t n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[n] = 0; n = 0;
      if (buf[0] == 'C')                    { setAlign(false); doCheck(); }
      else if (buf[0] == 'K')               { setAlign(false); calibrate(); }
      else if (buf[0] == 'A')               setAlign(buf[1] == '1');
      return;
    }
    if (n < sizeof(buf) - 1) buf[n++] = c;
  }
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < 2; i++) pinMode(LASER_PIN[i], OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  lasers(false, false);
  Serial.println(F("READY,PLACEMENT"));
}

void loop() {
  handleSerial();
  if (alignOn) updateAlign();
}