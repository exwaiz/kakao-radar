# Kakao Radar — Agent Guide

## Mission

대규모 KakaoTalk 오픈채팅의 알림을 서브폰에서 신뢰성 있게 수집하고, 후속 서버 단계에서 사용자 관심사에 맞는 요약만 전달하는 개인용 서비스다.

## Current milestone

**M1 real-device capture validation.**

2026-09-16 실기기에서 KakaoTalk callback은 들어오지만 현재 MessagingStyle-only parser가 전부 unsupported로 분류하는 현상을 확인했다. **이 문제를 해결하고 실제 notification format과 room identity를 검증하기 전에는 backend/AI 단계로 넘어가지 않는다.**

## Read before coding

1. `docs/DECISIONS.md` — 이미 정한 것. 함부로 뒤집지 않는다.
2. `docs/DEBUG_NOTES.md` — 최신 실기기 사실과 다음 실험.
3. `docs/PROJECT_BRIEF.md` — 사용자 문제, scope, milestones.
4. `docs/ARCHITECTURE.md` — 목표 구조와 경계.
5. `docs/DEVICE_TEST.md` — 실기기 검증 절차.

## Working rules

- 실제 실기기 관찰이 parser 가정보다 우선한다.
- callback 수를 메시지 수나 수집률로 표현하지 않는다.
- 현재 task 범위를 넘는 backend/AI 기능을 선행 구현하지 않는다.
- notification parsing 실패는 원인별로 관찰 가능해야 한다. 하나의 `unsupported` 숫자로 뭉개지 않는다.
- 채팅 원문·닉네임·비밀 키를 일반 diagnostic, test fixture, repository에 넣지 않는다.
- 다른 방을 대상 방으로 추정해 저장하거나 업로드하지 않는다. fallback parser는 보수적으로 설계한다.
- `sbn.key`를 영구적인 room ID로 간주하지 않는다.
- 메시지 재노출 중복과 업로드 재시도 중복은 서로 다른 문제로 취급한다.
- 문서의 **확정 / 실기기 확인 / 가설 / 제안** 상태를 섞지 않는다.
- 새로운 실기기 결과나 architecture decision이 나오면 같은 작업에서 `DEBUG_NOTES.md` 또는 `DECISIONS.md`를 갱신한다.
- 테스트가 통과했다는 사실을 실기기 수집 성공으로 표현하지 않는다.

## Session hygiene

같은 버그를 수정하고 빌드/로그를 반복하는 동안은 같은 Codex 세션을 사용한다. milestone 또는 독립 기능이 끝나면 결정과 결과를 Markdown에 저장하고 다음 작업은 새 세션으로 시작한다. 과거 장문 채팅을 영구 컨텍스트처럼 유지하지 않는다.
