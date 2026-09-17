# Kakao Radar — Agent Guide

## Mission

대규모 KakaoTalk 오픈채팅의 알림을 서브폰에서 신뢰성 있게 수집하고, 후속 서버 단계에서 사용자 관심사에 맞는 요약만 전달하는 개인용 서비스다.

## Current milestone

**M2 implementation with synthetic data; M1 field validation remains pending.**

2026-09-17 사용자는 폰 조작이 불가능하여 ‘방이 발견됐다고 가정하고 다음 마일스톤 개발’을 명시적으로 승인했다. 이 지시는 이전 M1 선행 조건보다 우선한다. M2 저장·동기화를 합성 데이터로 개발/검증한다. M1 실제 방 발견·신규 저장·수집률을 성공한 것으로 기록하지 않는다. 실제 업로드는 단말의 서버·기기 인증·대상 방 설정 전까지 비활성화한다.

2026-09-17 v0.2.0을 실제 Redmi에 업데이트했다. KakaoTalk 26.8.0은 그룹 알림에서 conversationTitle 없이 android.title을 제공했고, 보수적 제목 fallback 적용 후 기존 실제 방 알림 3개를 해석해 방 3개를 발견했다. 묶음 요약 1개는 제외됐다. **대상 방 미선택으로 신규 실제 메시지 저장·수집률·야간 지속성은 미검증이다. 사용자의 후속 지시에 따라 M2는 합성 데이터로 개발했다. 실제 운영 검증과 M3/M4는 별도로 남는다.**

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

## Build note

GitHub connector로 가져온 저장소에는 바이너리 `android/gradle/wrapper/gradle-wrapper.jar`가 포함되지 않을 수 있다. 파일이 없으면 빌드 전에 설치된 Gradle로 `gradle wrapper --gradle-version 8.9`를 실행해 wrapper를 재생성한다. `gradle-wrapper.properties`와 wrapper 스크립트는 저장소에 있다.

## Session hygiene

같은 버그를 수정하고 빌드/로그를 반복하는 동안은 같은 Codex 세션을 사용한다. milestone 또는 독립 기능이 끝나면 결정과 결과를 Markdown에 저장하고 다음 작업은 새 세션으로 시작한다. 과거 장문 채팅을 영구 컨텍스트처럼 유지하지 않는다.
