// VisionQC Uno / 28BYJ-48 / ULN2003; AccelStepper required.
// IN1=D8, IN2=D9, IN3=D10, IN4=D11. Motor external 5V, common GND.
// 115200 baud, newline terminated commands:
// R<degrees>, A<degrees>, Z -> DONE; P -> angle.
// S -> STARTED; X -> stop pulses, hold 1 second, DONE.
//
// 턴테이블 펌웨어 (PC 쪽은 turntable.py 가 이 명령들을 보낸다)
//   R<각도> : 현재 목표 위치에서 상대 회전        → 도착 + 1초 안정화 후 DONE
//   A<각도> : 0도 기준 절대 위치로 이동           → 도착 + 1초 안정화 후 DONE
//   Z       : 현재 위치를 0도로 설정              → DONE
//   P       : 현재 각도 출력 (소수 둘째 자리)
//   S       : 저속 연속 회전 시작/재개            → STARTED
//   X       : 즉시 정지, 코일 유지한 채 1초 안정화 → DONE
//   이해 못한 명령은 ERR, 동작 중이라 받을 수 없는 명령은 BUSY
// loop() 가 막히지 않는 구조라 회전 중에도 P, X 같은 명령을 바로 처리한다.
#include <AccelStepper.h>
#include <math.h>
#include <stdlib.h>

// HALF4WIRE(하프 스텝) 모드. 핀 순서는 8, 10, 9, 11 (ULN2003 + 28BYJ-48 배선 순서)
AccelStepper motor(AccelStepper::HALF4WIRE, 8, 10, 9, 11);
const float STEPS_PER_REV = 4075.7728;  // 28BYJ-48 하프 스텝 기준 1바퀴 스텝 수 (기어비 반영)
const float ROTATION_SPEED = 100.0; // about 1.47 rpm  (S 연속 회전 속도, 스텝/초)

// 동작 상태
//   IDLE     : 멈춰 있음, 모든 명령 가능
//   MOVING   : R/A 로 목표 위치까지 이동 중
//   SPINNING : S 로 연속 회전 중
//   SETTLING : 멈춘 뒤 1초 안정화 대기 (끝나면 DONE 출력)
enum State { IDLE, MOVING, SPINNING, SETTLING };
State state = IDLE;
float targetDeg = 0;            // 현재 목표(또는 현재) 각도. R 은 여기에 더한다
unsigned long stoppedAt = 0;    // 안정화를 시작한 시각 (millis)
char buffer[48];                // 시리얼로 받는 한 줄 명령
byte used = 0;                  // buffer 에 채운 글자 수
bool overflow = false;          // 한 줄이 buffer 보다 길었는지

// 정지 후 안정화 시작 (1초 뒤 loop() 에서 DONE 출력)
void settle() {
  state = SETTLING;
  stoppedAt = millis();
}

// 한 줄 명령 해석 + 실행
void command(char *text) {
  // 앞 공백 건너뛰고, 빈 줄은 무시
  while (*text == ' ' || *text == '\t') ++text;
  if (!*text) return;
  // 첫 글자가 명령 코드 (소문자도 대문자로)
  char code = *text++;
  if (code >= 'a' && code <= 'z') code -= 32;
  while (*text == ' ' || *text == '\t') ++text;
  // R, A 는 뒤에 각도 숫자가 붙는다
  float degrees = 0;
  if (code == 'R' || code == 'A') {
    char *end;
    degrees = strtod(text, &end);
    if (end == text || !isfinite(degrees)) {
      Serial.println("ERR"); return;
    }
    text = end;
    while (*text == ' ' || *text == '\t') ++text;
  }
  // 명령 뒤에 다른 글자가 남아 있으면 잘못된 명령
  if (*text) { Serial.println("ERR"); return; }
  if (code == 'P') {
    // 현재 각도 = 현재 스텝 위치를 각도로 환산
    Serial.println(motor.currentPosition() * 360.0 / STEPS_PER_REV, 2);
  } else if (code == 'X') {
    // 이미 안정화 중이면 무시. 아니면 지금 위치에서 바로 멈추고 안정화 시작
    if (state != SETTLING) {
      long position = motor.currentPosition();
      motor.setCurrentPosition(position);   // 남은 이동 목표를 지워 즉시 정지
      targetDeg = position * 360.0 / STEPS_PER_REV;
      motor.enableOutputs();                // 코일에 전류를 유지해 위치를 붙잡는다
      settle();
    }
  } else if (code == 'S') {
    // 이동·안정화 중에는 시작할 수 없음
    if (state == SETTLING || state == MOVING) {
      Serial.println("BUSY"); return;
    }
    motor.enableOutputs();
    motor.setSpeed(ROTATION_SPEED);
    state = SPINNING;
    Serial.println("STARTED");
  } else if (code == 'R' || code == 'A' || code == 'Z') {
    // 위치 명령은 완전히 멈춘 상태에서만
    if (state != IDLE) { Serial.println("BUSY"); return; }
    if (code == 'Z') {
      motor.setCurrentPosition(0);
      targetDeg = 0;
      Serial.println("DONE"); return;
    }
    // R: 목표 각도 + degrees / A: degrees 그대로
    float next = code == 'R' ? targetDeg + degrees : degrees;
    float steps = next / 360.0 * STEPS_PER_REV;
    // 스텝 수가 long 범위를 넘지 않게 막는다
    if (!isfinite(steps) || fabs(steps) > 2000000000.0) {
      Serial.println("ERR"); return;
    }
    targetDeg = next;
    motor.enableOutputs();
    motor.moveTo(lround(steps));
    state = MOVING;
  } else { Serial.println("ERR"); }
}

void setup() {
  Serial.begin(115200);
  motor.setMaxSpeed(700);       // R/A 이동 최대 속도 (스텝/초)
  motor.setAcceleration(350);   // R/A 이동 가감속 (스텝/초²)
  motor.disableOutputs();       // 대기 중에는 코일 전류를 끈다 (발열 방지)
  Serial.println("READY");      // turntable.py 가 이 줄을 기다린다
  Serial.println("VISIONQC_SX_V1");
}

void loop() {
  // 1) 시리얼 입력: 한 번에 최대 16글자만 읽어 모터 구동이 밀리지 않게 한다
  for (byte i = 0; i < 16 && Serial.available(); ++i) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      // 줄 끝 → 명령 실행 (너무 길었던 줄은 ERR)
      if (overflow) Serial.println("ERR");
      else { buffer[used] = 0; command(buffer); }
      used = 0;
      overflow = false;
    } else if (!overflow) {
      if (used < sizeof(buffer) - 1) buffer[used++] = c;
      else overflow = true;
    }
  }
  // 2) 상태별 모터 구동
  if (state == SPINNING) {
    // 일정 속도로 계속 회전, 목표 각도는 현재 위치를 따라간다
    motor.runSpeed();
    targetDeg = motor.currentPosition() * 360.0 / STEPS_PER_REV;
  } else if (state == MOVING) {
    // 가감속하며 목표 위치로 이동, 도착하면 안정화 시작
    motor.run();
    if (!motor.distanceToGo()) settle();
  } else if (state == SETTLING && millis() - stoppedAt >= 1000) {
    // 1초 안정화가 끝나면 DONE
    state = IDLE;
    Serial.println("DONE");
  }
}
