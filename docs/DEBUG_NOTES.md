# Kakao Radar — Real-device Debug Notes

실기기에서 확인된 사실과 아직 검증되지 않은 가설을 분리해 기록한다. 채팅 원문은 이 문서에 저장하지 않는다.

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
