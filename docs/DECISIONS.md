# Kakao Radar — Decision Log

이 문서는 프로젝트에서 이미 합의했거나 실기기 결과로 확정된 결정을 기록한다. 새 Codex 세션은 장문의 과거 대화보다 이 문서와 `AGENTS.md`를 우선한다.

## D-001 — 실시간 수집, 배치 분석

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: 카카오톡 알림은 도착 시 로컬에 즉시 저장한다. AI 분석과 본폰 알림은 서버에서 배치 또는 조건 기반으로 수행한다.
- 이유: 수집과 분석을 분리하면 서브폰의 배터리·발열 부담을 낮추고, AI 모델·프롬프트·주기를 서버에서 교체하기 쉽다.
- 결과: Android 앱은 수집기 역할에 집중한다. 온디바이스 LLM은 MVP 범위 밖이다.

## D-002 — 공식 카카오 대화 조회 API에 의존하지 않음

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: 기존 일반 오픈채팅방의 전체 대화를 공식 API로 조회할 수 있다고 가정하지 않는다. Android `NotificationListenerService`를 M1의 주 수집 경로로 검증한다.
- 결과: 알림에 노출되지 않은 메시지의 복구는 보장하지 않는다. 전체 아카이브 제품으로 표현하지 않는다.

## D-003 — M1 실기기 검증 전 서버/AI 확장 금지

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: Redmi Note 14 5G / Android 15에서 실제 KakaoTalk notification format과 room identity가 검증되기 전에는 M2 서버·M3 AI 구현을 본격 진행하지 않는다.
- 이유: 수집 경로가 틀리면 이후 파이프라인 전체가 의미가 없다.

## D-004 — 현재 MessagingStyle-only parser는 실기기에서 실패

- 상태: **실기기 확인**
- 결정일: 2026-09-16
- 근거: 사용자 실기기 export에서 `unsupported_kakao_callbacks`만 반복 기록되고 `selected_callbacks` 및 저장 메시지가 발생하지 않았다. Listener callback 자체는 발생했다.
- 해석: Notification access·Listener 생존이 1차 병목이 아니다. 현재 `NotificationParser.parse()`의 엄격한 조건이 KakaoTalk 실제 notification representation과 맞지 않는 것이 현재 최우선 가설이다.
- 현재 parser의 필수 조건:
  1. `FLAG_GROUP_SUMMARY`가 아님
  2. `NotificationCompat.MessagingStyle` 추출 성공
  3. `conversationTitle` 존재
  4. `isGroupConversation == true`
- 후속 결정: parser는 실패 원인을 구조화해 반환하고, 실기기 notification metadata를 개인정보 원문 없이 진단할 수 있어야 한다.

## D-005 — parser는 다단계 전략으로 재설계

- 상태: **다음 구현 방향 확정**
- 결정일: 2026-09-16
- 우선순위:
  1. `MessagingStyle`
  2. `EXTRA_MESSAGES`
  3. 표준 extras (`EXTRA_TITLE`, `EXTRA_TEXT`, `EXTRA_SUB_TEXT`, `EXTRA_SUMMARY_TEXT`)
- 주의: fallback은 개인 대화나 다른 방을 대상 오픈채팅으로 오인하지 않도록 보수적으로 설계한다.
- 실제 필드 매핑은 추측으로 확정하지 않고 실기기 diagnostic 결과를 source of truth로 삼는다.

## D-006 — unsupported는 하나의 숫자로 뭉개지 않음

- 상태: **다음 구현 방향 확정**
- 결정일: 2026-09-16
- 결정: `ParsedNotification?` 형태의 성공/null API를 `ParseResult` 계열로 바꾸고 실패 원인을 구분한다.
- 최소 진단 범주 후보:
  - group summary
  - no MessagingStyle
  - no conversation title
  - not group conversation
  - no title
  - no text
  - unknown
- UI/진단은 최소 다음 단계를 별도 집계한다.
  - Kakao callbacks
  - parsed callbacks
  - unsupported callbacks by reason
  - selected-room callbacks
  - saved messages
  - suppressed duplicates

## D-007 — 진단 metadata에 채팅 원문을 넣지 않음

- 상태: **확정**
- 결정일: 2026-09-16
- 저장 가능한 구조 정보 예:
  - extras key names
  - title/text/subText/summary/messages 존재 여부
  - messages count
  - MessagingStyle 감지 여부
  - group summary 여부
  - shortcutId 존재 여부
  - tag 존재 여부
  - 필요한 경우 안정성 확인용 해시
- 실제 메시지·닉네임·방 제목은 일반 diagnostic에 복제하지 않는다.

## D-008 — room identity는 notification key 하나에 의존하지 않음

- 상태: **설계 결정, 실기기 검증 필요**
- 결정일: 2026-09-16
- 문제: 현재 `RoomCandidate.matches()`는 shortcut이 없으면 동일 title이어도 `sbn.key`가 바뀌면 다른 방으로 본다.
- 목표 우선순위:
  1. 실제 Kakao chat/channel 식별자, 존재하고 안정적일 때
  2. `shortcutId`
  3. 안정적인 tag/식별 정보
  4. 단일 대상방 MVP에서 검증된 exact room title fallback
- 동일 제목 방 충돌 가능성은 명시적으로 탐지·경고한다.

## D-009 — Codex 작업 방식

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: 장기 지식은 repo Markdown에 저장하고, Codex 채팅은 기능/버그 단위로 나눈다.
- 같은 버그의 수정→빌드→로그 확인은 같은 세션에서 이어간다. 하나의 milestone이 끝나면 문서를 갱신하고 다음 milestone은 새 세션으로 시작한다.
- `AGENTS.md`는 지도 역할만 하며 상세 이력은 이 문서와 `DEBUG_NOTES.md`에 둔다.
