# Kakao Radar — Real-device Debug Notes

실기기에서 확인된 사실과 아직 검증되지 않은 가설을 분리해 기록한다. 채팅 원문은 이 문서에 저장하지 않는다.

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
