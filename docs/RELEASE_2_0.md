# Kakao Radar 2.0.0

## 범위

2.0.0은 Xiaomi 수집기 한 대가 사용자가 명시한 여러 KakaoTalk 방을 독립적으로 수집하고, WSL에서 방별 분석·진도·전달 상태를 유지하며, 한 Telegram 봇의 비공개 forum supergroup에서 방별 topic으로 전달하는 버전이다.

- Android versionCode 6 / versionName 2.0.0
- 서버 API 2.0.0 / PostgreSQL schema 6
- 기존 단일 방 `room_id` 보존 preference migration
- 다중 선택 UI와 방별 저장·대기·최근 수집 표시
- 기기 단위 HTTPS 자격 증명과 방별 round-robin batch upload
- `/v1/status`, `/v1/rooms`, `/v1/telegram/routes`, `/v1/delivery/status`의 방별 상태
- 방별 delivery outbox와 chat/thread/route-version snapshot
- Telegram `message_thread_id` 요청·응답 검증
- route version 충돌, 중복 목적지, 미라우팅 다중 방, route 변경 중 안전 취소 처리

## 호환성

- Room DB schema는 3을 유지한다. 기존 로컬 메시지·upload queue·snapshot을 다시 쓰지 않는다.
- 기존 단일 방 preference는 최초 실행 시 같은 UUID의 binding 집합으로 승격한다.
- 기존 서버 message/analysis/delivery progress 자료는 보존한다. schema 6은 additive migration이며, 기존 단일 허용 방은 환경 변수 Telegram chat fallback을 계속 사용할 수 있다.
- 허용 방이 둘 이상이면 명시적인 enabled route만 전달한다. 1:1 개인 채팅은 forum topic을 지원하지 않으므로 다중 topic 운영에는 비공개 supergroup이 필요하다.

## 보존한 안전 계약

- 선택하지 않은 방은 저장·업로드하지 않는다.
- 방 identity가 모호하면 원문을 저장하지 않는다.
- 다른 방의 원문과 요약을 같은 분석 job/outbox/Telegram 메시지에 섞지 않는다.
- accepted/uncertain의 방별 observed-at 진도와 원문 ID/내용 SHA-256 receipt, 과거 후보 미이월, literal 원문 인용을 유지한다.
- 봇 token과 기기 token은 환경/로컬 비밀 파일에만 두며 route DB에는 봇 token을 저장하지 않는다.

## 검증과 미검증

합성 검증 결과는 `VALIDATION.md`에 기록한다. 실제 Redmi 설치, 실제 KakaoTalk N개 방의 장시간 수집률, 운영 WSL schema 적용, 실제 Telegram forum topic 수신과 사용자 품질 평가는 이 릴리스 코드의 자동 테스트에 포함되지 않는다. 배포 순서는 `V2_MULTI_ROOM_RUNBOOK.md`를 따른다.
