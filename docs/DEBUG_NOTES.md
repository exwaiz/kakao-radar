# Kakao Radar — Real-device Debug Notes

실기기에서 확인된 사실과 아직 검증되지 않은 가설을 분리해 기록한다. 채팅 원문은 이 문서에 저장하지 않는다.

## 2026-09-18 — 실제 Telegram 반복·시간 역행 수정

- 실제 metadata 이력: 08:20 보고의 원문 관찰 상한은 오늘 07:40:07.703, 08:30은 어젯밤 23:21, 08:40은 어젯밤 23:32, 08:50은 어젯밤 23:24, 09:00은 어젯밤 23:31이었다. 서로 다른 summary_id/요약 표현이 동일 원문을 반복 참조했다. 원문/방 제목/닉네임은 진단 보고서에 넣지 않았다.
- 원인은 전체 적체 후보의 중요도 우선 선택과 표현이 완전히 같은 fingerprint만 비교하는 구조였다. schema 5는 기존 모든 발송에서 가장 최신 observed_at 진도(오늘 07:40:07)를 복원한다. 이후 새 구간만 선택하고 과거 잔여 후보를 자동 보고에 이월하지 않는다.
- 서버 테스트 183 passed, 24.78초, skip/failure 0. WSL DB 이관 seeded room 1 / 취소할 legacy queue 0. 운영 원문은 그대로 보존했다. 새 ledger에는 원문/닉네임이 없다.
- 수집 enabled/collector bound/sync enabled, sync_error 없음. 서버 실제 원문 354건, 마지막 수집 07:40:07, 마지막 업로드 07:41:41. 수정 후 fresh preview 0, 워커 다음 슬롯 09:20. 방에 새 메시지가 없는지 알림에 노출되지 않는지는 이 metadata만으로 판단하지 않는다.
- 제목/첫 요점 bold·emoji·literal 인용을 구현했고 변경 안내 한 건의 Telegram API 수락/DB quota 기록을 확인했다. 새 방 요약/본폰 표시 실측으로 기록하지 않는다. 10분 테스트 시간표·자정 복귀·AI $1/day 유지.

## 2026-09-17 — WSL 실제 통합

2026-09-18 사용자 보고로 Telegram 실제 수신을 확인했다. 사용자가 테스트 메시지를 더 많이 요청해 오늘은 10분마다 최대 3개 주제로 늘린다. 정확한 폰 표시 시각/latency 측정과 사용자 유용성 평가는 별도다.

- Redmi Android 0.3.1 업데이트, 기존 선택/DB 보존. 폰 350건 저장·sent 350·pending 0·처리 오류 0, WSL 350건 저장 확인. 전체 카카오 메시지 수집률은 미검증이다.
- WSL loopback HTTPS + USB reverse를 사용한다. 공개 터널 자동 승인 거절 후 로컬 방식으로 전환했다. 비밀은 Git에서 제외하며 승인된 기존 파일만 읽는다.
- 실제 OpenAI에서 certainty none 오용, topic 누락/중복, evidence scope 오류가 검증에 차단됐다. 불확실성 enum 제한, 필수 topic 객체 키, topic별 evidence ID enum, 동일 근거 중복 정규화로 보강했다. 잘못된 ID를 만들어 채우지 않는다.
- systemd 실행에서 tools 디렉터리만 import 경로에 있어 Worker가 모듈을 찾지 못했다. runtime.py에 server 경로를 명시했고 서비스 active와 연속 completed를 확인했다.
- Telegram 입력 서버의 sandbox 네트워크 제한으로 WinError 10013을 재현했다. 허용된 네트워크 실행으로 수정해 정상 저장·요약 API 수락을 확인했다. 오류는 단계별로 안내하며 토큰/응답 본문은 출력하지 않는다.
- DeviceDiagnosticsTest가 production 프로세스를 종료하여 수집 listener가 끊겼다. 기존 권한 disallow→allow로 복구하고 Bound=true를 확인했다. 앱 시작 requestRebind를 추가했다. 진단 뒤 실제 바인딩까지 확인한다. 제목 parser 변경은 사용자 요청대로 후속이다.
- 삼성전자 등 지정 관심사, 하루 $1, Telegram 23:00/하루 1회, urgent off를 반영했다. 최신 원문 없는 집계는 outputs의 runtime/phone/Telegram check JSON이다. 상세는 WSL_RUNTIME.md, M5_LATENCY.md.

## 2026-09-17 — M3 선행 구현 세션

- 사용자 요청: M3 문서를 읽고 아키텍처와 실제 구현을 선행 개발. 이어 사용자가 다른 세션에서 M2 커밋 완료를 알려 GitHub의 최신 `672092c`를 가져와 기준을 갱신했다.
- M3 서버 프로필/주제/근거 요약/영속 작업/예산/평가를 구현하고 전용 PostgreSQL 합성 검사 66개와 비교 도구 5개를 통과했다. 자세한 결과는 VALIDATION.md, 계약은 M3_ANALYSIS.md.
- 실제 collector/단말은 이번 작업에서 변경하거나 조회하지 않았다. 새로운 실기기 결과는 없다. 이전 M1 미검증 항목은 그대로 대기다.
- 외부 API 키의 존재 여부만 확인했고 사용 가능한 키를 발견하지 못했다. 외부 AI 연결 선택은 대기이며 키 생성/쓰기/실제 API 호출은 수행하지 않았다. 기준선 결과를 실제 LLM 결과라고 기록하지 않는다.
- 다음 검증: 운영 관심/제외/예시와 예산 설정, 외부 공급자 어댑터/자격 증명 연결 후 사용자 주제 50개와 근거 문장 검토. 실제 단말 대상 방/수집률은 별도 이어간다.

## 2026-09-17 — v0.2.0 수정 및 실기기 확인

### 후속 대상 방 지정 시도

- 사용자가 지정한 방 이름의 포함 검색을 실행했으나 현재 발견된 3개 방 중 일치 항목이 0개였다. Unicode NFKC·공백·보이지 않는 문자 정규화 후에도 0개였다. 따라서 대상 방 설정이나 수집 활성화는 수행하지 않았다.
- 이 단말은 ADB input tap/swipe에 INJECT_EVENTS 권한 오류를 반환한다. OS 보안 설정은 변경하지 않았다.
- 테스트 전용 DeviceSetupTest를 추가했다. 명시적 `action=start_capture`와 `room_filter_base64` 인자가 있어야 실행되고, 기존 알림 접근 권한·정확히 하나의 이름 일치·shortcutId를 확인한 뒤에만 Config.select/enabled를 변경한다. 일반 테스트 실행에서는 건너뛴다. 프로덕션 APK 변경은 없다.
- 다음 단계: 대상 카톡방에서 알림을 켜고 카톡 화면을 닫은 뒤 새 알림을 받는다. 발견 후 같은 명시적 필터로 설정을 재시도한다. 설정 테스트 종료 후 앱을 다시 열고 Listener 연결을 확인한다.
- 전체 방 이름이나 DB 원문을 PC로 복사하는 방식으로 대상을 확인하지 않는다.

### 확인한 원인

- GitHub 기준 commit: `61f9042d374d4cc096775bbf26ec5af70ff0f6f9`.
- Redmi Note 14 5G / Android 15 / HyperOS 2.0.5(사용자 제공), KakaoTalk 26.8.0.
- 실제 child 알림 3개 모두 MessagingStyle와 messages, 명시적 group=true, shortcutId가 있었다. 방 제목은 android.title에 있고 conversationTitle은 없었다.
- 기존 parser는 conversationTitle을 필수로 요구해 해당 알림을 버렸다. 이 관측의 직접 원인은 권한/배터리가 아니라 제목 필드 가정 불일치다.

### 수정과 설치

- 버전 0.2.0/code 2, parser version 2. `adb install -r`로 기존 앱/데이터를 유지한 업데이트 성공.
- 제목 fallback, raw messages/standard text fallback, 방 충돌 보류, 사유별 카운터, 원문 없는 구조 진단과 진단 전용 export 추가. 상세 조건은 D-010.
- schema 1→2 migration 성공. 이전 unsupported 진단 44회가 유지됐다. 시작 시 기존 알림은 방 발견에만 사용하고 과거 원문으로 저장하지 않는다.
- 디버그 테스트 APK의 DeviceDiagnosticsTest가 단말 내에서 집계한다. DB/채팅 원문을 PC로 복사할 필요가 없다.

### 측정 결과 (앱 설치 후 기존 active notification 조회)

| 항목 | 0.1.0 확인값 | 0.2.0 확인값 |
|---|---:|---:|
| 기존 버전 미지원 기록 | 44 | 44 보존 |
| 발견된 방 | 0 | 3 |
| 기존 알림 조회 / 정상 해석 | 별도 계수 없음 | 4 / 3 |
| 제목 fallback 성공 | 미지원 | 3 |
| 묶음 요약 제외 | 미지원에 합산 | 1 |
| 처리 오류 | 별도 계수 없음 | 0 |
| 저장 메시지 | 0 | 0 (방 미선택·수집 중지) |

세 child의 messages 배열 길이는 각각 3, 7, 6이었다. 이는 알림 창의 항목 수이며 신규 메시지 수·저장 수·수집률이 아니다. 세 child 모두 tag와 shortcutId가 같았으나 연속 알림에서의 안정성은 아직 검증하지 않았다. 자동 저장은 의도적으로 활성화하지 않았다.

### 검증과 남은 일

- JVM/Robolectric 33개, Python 5개 통과. 실제 관찰 필드로 만든 합성 fixture 12개가 포함된다. fixture에 실제 원문·방명·닉네임을 넣지 않았다.
- lint 오류 0개/경고 11개. 실제 단말 instrumentation 2개 통과(집계/스키마 확인, 별도 테스트 DB의 재열기/롤백).
- **실기기 확인:** 기존 알림의 파싱과 방 발견 복구, schema migration, 업데이트/실행.
- **아직 미검증:** 새 실제 callback→선택한 방→원문 저장, 메시지 중복/누락 실측, 알림 키 변경/재부팅 시 동일 방 추적, 화면 꺼짐/야간 수집, 배터리.
- 다음 행동: 사용자가 수집할 방을 지정하거나 앱에서 발견한 방 1개를 선택하고 수집 시작. 새 메시지 후 카톡 도착/해석/대상/저장 카운터와 원본 표본을 비교한다. 알림만으로 일반 그룹과 오픈채팅 여부까지 보장하지 않으므로 대상 선택이 필요하다.
- 현재 M1은 완료로 표시하지 않는다. 서버/AI 개발을 시작하지 않는다.

## 2026-09-16 — M1 첫 실기기 사용

### 환경

- 기기: Xiaomi 24094RAD4G / Redmi Note 14 5G 계열
- Android: 15
- Build: `AP3A.240905.015.A2`
- 앱: Kakao Radar `0.1.0`
- export retention: 7일
- sender 저장 형식: installation HMAC-SHA256

### 사용자가 관찰한 증상

- 앱의 `미지원/요약 카톡 알림` 수가 계속 증가함.
- 기대한 대상/지원 알림 수와 저장 메시지는 증가하지 않음.
- 실제 KakaoTalk 메시지는 단말에 들어오고 있음.

### export 관찰

사용자가 제공한 JSONL diagnostic에는 다수의 다음 레코드만 존재했다.

```json
{"type":"diagnostic","code":"unsupported_kakao_callbacks","value":1}
```

동일 millisecond timestamp에 여러 callback이 기록된 사례도 있었다. 이는 메시지 개수와 1:1 대응한다고 해석하지 않는다. listener 연결 시 기존 active notification 검사, KakaoTalk의 child/summary/update notification 등 여러 원인이 가능하다.

중요한 점:

- Kakao package callback은 앱까지 도달했다.
- `selected_callbacks`와 message record는 관찰되지 않았다.
- 따라서 현재 1차 병목은 `CollectorService.inspect()` 이후의 `NotificationParser.parse()`가 `null`을 반환하는 구간이다.

### 코드 분석 결과

현재 `NotificationParser`는 아래 조건을 모두 만족해야 성공한다.

```kotlin
if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return null
val style = NotificationCompat.MessagingStyle
    .extractMessagingStyleFromNotification(notification) ?: return null
val title = style.conversationTitle?.toString()
    ?.takeIf { it.isNotBlank() } ?: return null
if (!style.isGroupConversation) return null
```

즉 실제 KakaoTalk notification이 표준 extras 중심이거나, `MessagingStyle`이더라도 conversationTitle/group flag가 기대와 다르면 전부 하나의 `unsupported_kakao_callbacks`로 뭉쳐진다.

현재 unit test는 앱이 직접 만들어낸 MessagingStyle fixture를 통과시키므로, 실제 KakaoTalk notification representation을 검증한 테스트가 아니다.

### 현재 결론

**확정:** NotificationListener callback 자체는 동작한다.

**확정:** 현재 앱은 callback을 의미 있는 메시지로 parse하지 못하고 있다.

**강한 가설:** 실제 KakaoTalk notification 구조와 MessagingStyle-only parser의 가정이 불일치한다.

**아직 모름:** 정확히 어느 조건에서 대부분 탈락하는지. 현재 코드가 모든 실패를 동일 diagnostic code로 기록해서 구분할 수 없다.

### 다음 실험 APK 요구사항

1. `ParseResult.Success / Unsupported(reason)` 구조 도입.
2. 실패 reason histogram 제공.
3. 원문 없는 구조 metadata 저장.
4. standard extras fallback parser 추가.
5. actual Kakao-style standard-extras fixture 테스트 추가.
6. room identity stability 관찰.
7. UI 카운터를 callback→parsed→selected→saved→dedup 단계로 분리.

### 다음 실험에서 필요한 최소 데이터

메시지 10~50개 정도만으로도 아래를 확인할 수 있다.

- `MessagingStyle` 감지 비율
- `EXTRA_MESSAGES` 존재 비율/count
- `EXTRA_TITLE` / `TEXT` / `SUB_TEXT` / `SUMMARY_TEXT` 존재 여부
- shortcutId/tag 존재와 안정성
- 같은 방의 연속 알림에서 `sbn.key`가 유지되는지

이 결과를 확인하기 전에는 HyperOS 배터리 최적화나 background kill을 1차 원인으로 다루지 않는다.

## 다음 Codex 세션 시작 프롬프트

```text
Read AGENTS.md, docs/DECISIONS.md, and docs/DEBUG_NOTES.md first.
Work only on M1 notification-format diagnostics and parser robustness.
Do not start backend or AI work.
Implement structured parse failure reasons, privacy-safe notification-structure diagnostics,
a standard-extras fallback parser, realistic fixtures, and stage-separated counters.
Then update DEBUG_NOTES.md with exactly what the code can now observe on the next real-device run.
```

## 2026-09-17 — M2 합성 개발 및 장시간 callback 관찰

사용자 승인으로 M1 대상 방 발견/저장 검증을 대기하며 M2를 진행했다. 사용량 제한으로 도구 다운로드가 일시 중단됐다가 resume 요청 후 작업을 재개했다.

- 새 실제 집계: schema 3, 기존 unsupported 44회 유지, live Kakao callback 532회/해석 272회, discovery 16회/해석 12회, summary 제외 264회, 처리 오류 0회. 진단은 보관 범위 내 수치이며 메시지 수/수집률이 아니다.
- 대상 방 미선택·capture=false·sync=false이며 실제 저장/전송 0건. 삼성전자 대상의 실제 원문 저장은 아직 확인하지 않았다.
- 같은 shortcut/key 해시에서 제목 해시가 바뀌는 여러 live callback을 확인했다. 제목 정확 일치를 영구 room identity 조건으로 두면 바인딩이 끊기고 후보가 중복될 수 있다. v0.3.0은 shortcut 우선 identity와 후보 중복 제거로 수정했다. 정확한 제목 필드가 항상 방 이름인지는 별도 확인이 필요하다.
- 기존 후보 목록 20개는 최신 시점에 같은 shortcut의 여러 표시 제목이었다. 최종 후보 getter 중복 제거 후 후보/고유 대화 ID는 1개다. 초기 발견했던 3개와 현재 목록이 다르며 이 후보 숫자를 실제 가입 방 개수로 해석하지 않는다.
- 실제 Redmi의 별도 테스트 DB에서 합성 메시지 2건을 localhost HTTPS→FastAPI→PostgreSQL로 전송했다. 서버 커밋 뒤 응답 유실을 재현하고 DB를 다시 열어 재전송했을 때 2건 모두 duplicate로 완료됐다. 서버 원문은 2건 유지. 다른 방의 합성 항목 1건은 로컬 pending으로 남았고 전송되지 않았다.
- 임시 인증서를 OS에 설치하거나 프로덕션 TLS 검증을 끄지 않았다. 인증서 신뢰는 테스트 transport 객체에만 한정했다. 별도 설정/Keystore alias로 토큰 암호화·재열기·중지를 검증했다.
- 실제 앱 업데이트는 데이터 삭제 없이 schema 2→3 전환. 서버 등록·실제 동기화 활성화·외부 배포는 수행하지 않았다.

남은 실측: 정확한 대상 방 선택/표본 수집, 방 ID의 재부팅 안정성, 화면 꺼짐 WorkManager/WAN/TLS 운영, 실제 500건 누락/중복·배터리. 다음 구현 milestone은 M3 관심 프로필·요약 평가이며 공급자/자격 증명/예산 연결과 사용자 평가를 별도로 진행한다.

## 2026-09-18 — Redmi 알림 지연 ADB 진단 (설정 변경 없음)

상태: **실기기 확인 — 충전·화면 ON의 현재 상태만 관찰**. 사용자가 카카오톡 알림 지연·묶음 도착에 대해 ADB 진단 후 최소 변경을 요청했다. 화면 OFF 지연을 이번 작업에서 재현하거나 해결했다고 기록하지 않는다.

- Authorized 기기 정확히 1대. Redmi Note 14 5G / 24094RAD4G, Android 15 / SDK 35, HyperOS OS2.0(code 2), build display AP3A.240905.015.A2 / incremental V816.0.2.0.ULJSZXM. Android user 0.
- KakaoTalk 26.8.0과 Google Play Services 26.33.32 설치·실행 확인. 두 패키지는 stopped=false, suspended=false, hidden=false, enabled=0(default).
- KakaoTalk은 user Doze whitelist, GMS는 system 및 system-excidle whitelist에 이미 포함. 두 앱은 bucket 5(EXEMPTED), inactive=false. 재검증에서 동일.
- RUN_IN_BACKGROUND는 두 앱 모두 개별 조회에서 Default mode: allow. RUN_ANY_IN_BACKGROUND는 allow. START_FOREGROUND는 카카오톡 allow / GMS default allow. POST_NOTIFICATION은 둘 다 default allow. 카카오톡 POST_NOTIFICATIONS 런타임 권한 granted=true.
- GMS .gcm.GcmService 실행 중. 두 앱 프로세스 cached=false. UID별 netpolicy effective=NONE, Data Saver 및 저전력 모드 OFF. 프로세스·서비스 존재는 화면 OFF FCM 연결 유지나 실제 메시지 도착의 증거가 아니다.
- DeviceIdle/Light ACTIVE, mCharging=true, mScreenOn=true, deep/light Doze 기능 enabled. Wi-Fi 현재 VALIDATED 및 NOT_SUSPENDED, RSSI -35 dBm. Wi-Fi suspend optimization enabled 자체는 연결 단절의 증거가 아니다.
- stay_on_while_plugged_in=15, mStayOn=true. 자연 Doze 테스트는 USB/충전기를 분리하고 화면 OFF·정지 상태에서 수행한다. 재연결 후 ACTIVE만 보고 과거 Doze 진입 여부를 판정하지 않는다.
- wifi_sleep_policy=2를 읽었으며 변경하지 않았다. Android 플랫폼에서는 API 30부터 사용 중단된 설정이다.
- 표준 설정에 실제 제한이 없어 **Android 설정 변경 0건 / rollback 명령 없음**. 기존 예외를 제거하거나 AppOps를 임의로 덮어쓰지 않았다. MIUI 비공개 AppOps 번호 의미를 추측하거나 변경하지 않았다.
- 원인 조사 우선순위(미확정): 화면 OFF FCM 연결/재접속, HyperOS의 별도 절전/자동 시작, FCM 우선순위 또는 카카오톡 처리·재동기화. HyperOS UI 현재값·FCM 발신 우선순위·화면 OFF 재현은 미확인.
- 초기/재검증 dump·명령·변경 내역·상세 보고서·메타데이터 로그 스크립트는 PC의 로컬 `AppData/Local/Codex/adb-diagnostics/2026-09-18_10-00-52`에 저장. 저장소에 채팅 원문·닉네임·토큰·dump를 추가하지 않았다.
- 다음 실험: 비충전 상태로 화면 OFF 20~30분 → 외부 기기에서 메시지 발송 시각 기록 → USB 재연결 즉시 보존된 logcat 메타데이터 수집. logcat main/system 각각 2 MiB로 일부 로그가 덮어써질 수 있다. M1 실제 수집률·M3 개인 AI 품질 평가의 성공으로 해석하지 않는다.

### 2026-09-18 후속 — 로그 검증 취소, 상시 충전 배터리 정책 조치

- 사용자가 로그 검증을 취소하고 카카오톡 배터리 최적화 예외·폰 전체 배터리 절약 확인과 조치를 지시했다. 상시 충전 예정이며 Radar 신뢰성을 우선한다.
- **실기기 확인:** Android 일반·적응형 Battery Saver 모두 OFF(full=false, adaptive=false), 자동 절전 threshold=0 / automatic=0, sticky=false. HyperOS POWER_SAVE_MODE_OPEN=0. null인 설정값을 임의로 enable/disable하지 않았다.
- **발견 및 조치:** dev.kakaoradar.collector는 user/system Doze whitelist에 없었고 bucket 40(RARE)이었다. 변경 전 값을 PC의 로컬 배터리 감사 폴더에 기록한 후 `cmd deviceidle whitelist +dev.kakaoradar.collector`를 실행했다. user whitelist 추가 성공·재조회 확인, bucket 5(EXEMPTED)로 변화. bucket set 명령은 실행하지 않았다.
- KakaoTalk은 기존 user whitelist, GMS는 기존 system whitelist를 유지하며 둘 다 bucket 5. Radar의 RUN_IN_BACKGROUND/RUN_ANY_IN_BACKGROUND default allow. 세 앱 모두 inactive=false.
- Radar 알림 접근 enabled 및 CollectorService가 Android 시스템에 바인딩되어 실행 중임을 확인했다. 실제 채팅 저장·수집률·지연 해결의 검증은 아니다.
- 변경 1건의 rollback: `adb shell cmd deviceidle whitelist -dev.kakaoradar.collector`. 해제 후 bucket은 사용 이력에 따라 재계산되므로 조회해 확인한다. 카카오톡/GMS 원래 예외는 제거하지 않는다.
- **미완료 경계:** HyperOS 앱별 절전/자동 시작 UI는 ADB input의 INJECT_EVENTS 권한 부족으로 조작 불가. 설치된 PowerKeeper provider도 signature 권한으로 읽기 거부되어 중단했다. 비공개 AppOps 번호 추측/변경 및 root/권한 우회 없음. 사용자에게 별도 'USB 디버깅(보안 설정)' 활성화 입력을 요청했고 답변을 기다린다.
- 기존 로그 필터 검증은 취소되었으며 완료로 기록하지 않는다. 상세 전후 값/명령/rollback은 로컬 `battery-focus/report.md`, `radar-whitelist-change.json`, `final-state.json`에 있다. 아래 추가 실제 UI 조치가 없다면 현재 변경은 Radar 배터리 예외 추가 1건이다.

### 2026-09-18 후속 — KakaoTalk 실행 후 Radar 복귀, 주기적 깨우기 검토

- **사용자 관찰:** HyperOS에서 알림이 지연되다가 한꺼번에 오는 현상이 KakaoTalk Activity를 열었다가 Radar로 돌아오면 일시적으로 해소된다고 보고했다. 이번 작업에서 메시지를 보내거나 로그로 효과를 검증하지 않았다.
- **실기기 확인:** 10:42 KST, Android user 0의 KakaoTalk launcher `com.kakao.talk/.activity.SplashActivity`를 `am start -W`로 실행했다. `Status: ok`, WARM 실행, 실제 Activity `com.kakao.talk/.activity.main.MainActivity`를 반환했다. 약 3초 뒤 기존 Radar launcher `dev.kakaoradar.collector/.MainActivity`를 실행했고 `Status: ok`를 반환했다. 별도 `dumpsys window`의 `mCurrentFocus`와 `dumpsys activity activities`의 `topResumedActivity`로 Radar가 전면에 있음을 확인했다. 채팅 내용이나 화면은 읽거나 저장하지 않았다.
- 이번 앱 전환에서 설정 변경은 0건이며 force-stop, 데이터 삭제, 로그아웃을 하지 않았다. 앞선 Radar Doze 예외 추가 1건은 유지된다. 실행 결과는 PC의 비공개 `battery-focus/activity-wake.json`에 기록했다.
- **구현 상태:** 10분마다 자동 깨우기는 아이디어 검토 단계이며 앱 기능이나 예약 실행을 추가하지 않았다. 현재 앱은 targetSdk 35이고 NotificationListenerService 및 15분 WorkManager 업로드를 사용한다.
- **플랫폼 제약:** 앱 프로세스에서 `am start`를 실행해도 ADB shell UID 권한을 얻지 않는다. 화면 OFF/백그라운드에서 다른 앱의 Activity를 실행하는 동작은 Android BAL 제한을 받으며 Doze 예외만으로 실행 권한이 생기지 않는다. WorkManager 정기 작업의 최소 주기는 15분이고 정확한 실행 시각은 보장하지 않는다. Radar가 화면에 보이는 동안의 일반 Intent 실행은 별도의 조건이다.
- **제안:** PC에 USB를 계속 연결하는 운영이면 PC의 ADB가 10분마다 KakaoTalk 실행 → 짧은 대기 → Radar 복귀를 수행하도록 구성할 수 있다. 충전기만 연결한 폰 단독 운영이면 Shizuku 등 별도의 ADB 권한 연동과 주기 실행 설계가 필요하다. 잠금/화면 OFF에서 실제 수신 개선과 10분 주기의 적절성은 아직 검증하지 않았다.
- 근거: [Android 앱 sandbox](https://source.android.com/docs/security/app-sandbox), [백그라운드 Activity 실행 제한](https://developer.android.com/guide/components/activities/secure-bal), [WorkManager 정기 작업](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work), [ADB Activity 실행](https://developer.android.com/tools/adb), [Shizuku 사용자 안내](https://shizuku.rikka.app/guide/setup/).


### 2026-09-18 최신 지시 — 주기적 KakaoTalk 깨우기 보류

사용자가 주기적 KakaoTalk 깨우기 기능을 없던 일로 하도록 지시했다. 구현·권한 추가·예약 실행을 진행하지 않는다. 이어서 Telegram 테스트 전송 10분→1시간 변경, 현재 구현의 GitHub 반영과 master 통합, 1.0 버전 표시를 요청했다.

### 2026-09-18 최신 조치 — Telegram 1시간 설정과 v1.0.0 통합 검증

- 사용자 지시로 주기적 KakaoTalk 깨우기는 보류하고, 실제 Telegram 테스트 설정을 version 3→4로 갱신했다. 시간표 144개(10분)→24개(매시 정각), 최대 3개 주제다. 변경 시 next_due 12:00 KST를 확인했다.
- 기존 오늘 17회 발송 시도와 quota 144회를 보존했다. quota를 중간에 낮춰 오늘 발송이 막히지 않도록 `--preserve-daily-limit`을 추가했다. 자정 23:00/하루 1회/최대 5개 주제 복귀, 실제 대사 인용·진도·중복 억제·AI $1/day를 유지한다.
- 변경 전/후 정책과 rollback 스크립트/명령은 PC 비공개 `battery-focus/hourly-telegram-{before,after}.json`, `rollback-hourly-telegram.py`, `rollback-hourly-telegram.txt`에 기록했다. 원문·계정 비밀은 저장소에 추가하지 않았다.
- GitHub 기존 M1/M2/M3/M4/WSL 구현을 master 기준으로 통합하고 Android versionCode 5 / versionName 1.0.0, 서버 1.0.0을 표시한다. 최신 WSL 기능 코드가 동일하게 보존됐는지 비교했다. 상세 범위는 RELEASE_1_0.md, architecture 결정은 D-017이다.
- **합성 검증:** 서버 183개 + 수집 비교 도구 5개 + Android 단위 테스트 43개 통과. Android assembleDebug/lintDebug 성공(error 0, 기존 warning 9). 폰 APK 업데이트나 새 외부 전송은 실행하지 않았다. 화면 OFF 지연 해결이나 장기 수집률·개인 품질 평가 통과와 구분한다.
