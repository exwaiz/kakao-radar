# 다중 KakaoTalk 방 수집과 Telegram 토픽 라우팅 설계안

- 상태: **구현 전 설계 확정**
- 작성일: 2026-09-19
- 기준선: GitHub `master` / v1.0.0 이후
- 목적: Xiaomi 수집 APK 한 대에서 사용자가 명시적으로 선택한 N개의 KakaoTalk 방을 독립적으로 수집하고, WSL에서 방별로 저장·분석·진도를 관리한 뒤 하나의 Telegram 봇 대화 안에서 방별 토픽으로 전달한다.

## 1. 결정

기본 전달 구조는 다음과 같다.

```text
KakaoTalk 방 A -> room_id A -> 저장/분석/진도 A -> Telegram 토픽 A
KakaoTalk 방 B -> room_id B -> 저장/분석/진도 B -> Telegram 토픽 B
KakaoTalk 방 C -> room_id C -> 저장/분석/진도 C -> Telegram 토픽 C
                                           \-> 공용 bot_token + chat_id
```

- Telegram 봇 토큰은 하나만 운영한다.
- 기본 대상은 기존 본인 개인 채팅 하나다.
- KakaoTalk 방마다 별도의 Telegram `message_thread_id`를 매핑한다.
- 필요할 때만 여러 방의 중요 항목을 모은 선택적 `전체 브리핑` 토픽을 둔다.
- 방별 수신자·관리자·보안 경계가 실제로 달라질 때만 별도 봇 또는 별도 Telegram 채팅을 검토한다.
- 봇 자격 증명과 전달 목적지는 분리한다. 봇 토큰은 서버 비밀 설정에 한 번만 저장하고 DB 라우트에는 넣지 않는다.

## 2. 핵심 불변 조건

1. 사용자가 명시적으로 선택한 방만 원문을 저장하거나 업로드한다.
2. 방 식별은 `sbn.key`나 표시 제목 하나에 의존하지 않는다. 검증된 `shortcutId` 등 기존 보수적 identity 규칙을 유지한다.
3. 서로 다른 방의 원문을 같은 AI 입력 작업에 섞지 않는다.
4. 메시지, 분석 작업, 요약, 중복 억제 receipt, 전달 진도는 항상 `(device_id, room_id)` 범위로 분리한다.
5. 하나의 Telegram 채팅을 공유하더라도 발송 항목은 원본 `room_id`와 토픽을 잃지 않는다.
6. 방 선택 해제는 이후 수집만 중단한다. 기존 로컬·서버 데이터를 암묵적으로 삭제하지 않는다.
7. 기존 단일방 사용자 설정과 미전송 큐를 손실 없이 다중방 모델로 이관한다.
8. 실제 단말 검증 전에는 테스트 통과를 다중방 실수집 성공으로 표현하지 않는다.

## 3. 현재 구현과 변경 경계

### Android APK

현재 로컬 메시지와 dedup snapshot은 이미 `roomId`를 가진다. 그러나 수집 설정의 `binding`, `roomId`와 동기화 설정의 `SyncTarget.room`은 단일값이다.

변경 방향:

- 단일 `binding`을 안정적인 `room_id -> RoomBinding` 집합으로 이관한다.
- 발견된 방 목록에서 여러 방을 선택·해제할 수 있는 UI를 제공한다.
- 알림 도착 시 선택 집합에서 정확히 하나의 binding과 일치할 때만 저장한다.
- 둘 이상의 binding과 일치하는 모호한 알림은 저장하지 않고 충돌 진단을 남긴다.
- 방마다 독립 snapshot, 최근 수집 시각, 저장·억제·오류 카운터를 유지한다.
- 서버 주소, device ID, 인증 토큰은 기기 단위 설정으로 바꾸고 room ID를 자격 증명에서 분리한다.
- 업로드 큐는 선택된 모든 방을 공정하게 순환한다. 메시지가 많은 한 방이 다른 방의 업로드를 계속 막지 않도록 방별 batch/round-robin을 적용한다.
- 기존 단일 binding과 room ID는 migration 시 첫 번째 선택 방으로 그대로 보존한다.

### WSL 수신·분석

현재 PostgreSQL의 `rooms`, `messages`, `analysis_jobs`, `delivery_progress`는 이미 room 범위를 가진다. 수신 API도 항목별 `room_id` 허용 여부를 검사한다.

변경 방향:

- 한 device에 N개의 허용 room을 등록·조회·비활성화할 수 있는 관리 경로를 제공한다.
- `rooms`에 사용자 표시용 label과 필요한 최소 상태 메타데이터를 추가한다. KakaoTalk 방 제목 변경과 안정적인 room ID를 구분한다.
- 상태 API에서 방별 마지막 수신, 저장 건수, 분석 backlog, 전달 진도를 반환한다.
- 분석 작업은 기존처럼 방별 lease와 방별 메시지 집합을 사용한다.
- 전체 관심 프로필은 우선 공유하되, 후속 요구가 생기면 방별 override를 추가할 수 있게 경계를 유지한다.

### Telegram 전달

현재 발송 큐는 기기 단위 digest 하나를 만들 수 있고 Telegram 설정은 단일 `chat_id`를 사용한다.

목표 라우트:

```text
TelegramRoute {
  device_id
  room_id
  chat_id
  message_thread_id
  display_name
  enabled
  version
}
```

- 같은 `chat_id`를 여러 room 라우트가 공유하는 것을 허용한다.
- 방 구분 키는 `(chat_id, message_thread_id)`다.
- outbox 항목은 `room_id`, 라우트 버전, 대상 chat/thread snapshot을 가진다.
- 설정 변경 뒤 오래된 대상에 pending 메시지가 발송되지 않도록 라우트 버전을 재검사한다.
- Telegram API 호출에는 `chat_id`와 선택적 `message_thread_id`를 함께 전달한다.
- 발송 성공 응답의 chat/thread가 요청 대상과 일치하는지 확인한다.
- 방별 dedup과 `delivery_progress`를 유지한다.
- quota는 전체 안전 상한과 방별 알림량을 함께 제한할 수 있게 한다.
- 기본 출력은 방별 토픽에 방별 digest 한 건이다. 선택적 전체 브리핑은 별도 산출물이며 방별 진도나 dedup을 대체하지 않는다.

## 4. 스키마와 API 초안

서버 스키마 후보:

- `rooms`: `display_name`, `enabled`, `updated_at`
- `telegram_routes`: device/room별 chat/thread 라우트와 version
- `delivery_outbox`: `room_id`, `destination_chat_id`, `message_thread_id`, `route_version`

관리 API 후보:

- `GET /v1/rooms`
- `PUT /v1/rooms/{room_id}`
- `GET /v1/delivery/routes`
- `PUT /v1/delivery/routes`
- `GET /v1/status/rooms`

쓰기 API는 기존 기기 인증과 optimistic version 검사를 유지한다. 같은 room의 중복 라우트나 존재하지 않거나 비활성인 room 라우트는 거부한다.

## 5. 마이그레이션

1. Android의 기존 `binding + room_id`를 선택 방 목록의 단일 항목으로 변환한다.
2. 기존 메시지, snapshot, upload queue의 room ID는 변경하지 않는다.
3. 기존 WSL room 허용 목록과 메시지·분석·전달 진도를 그대로 유지한다.
4. 기존 `RADAR_TELEGRAM_CHAT_ID`를 기본 chat ID로 사용한다.
5. topic mapping이 준비되지 않은 방은 Telegram 발송을 보류하고 수집·업로드·분석은 계속한다.
6. 기존 미발송 outbox를 새 라우트로 자동 재지정하지 않는다. 상태를 명시적으로 이관하거나 안전하게 취소한다.
7. migration과 rollback 전후의 행 수·미전송 수·room별 최신 진도를 검증한다.

## 6. 구현·검증 순서

1. Android 설정 모델 migration과 다중 선택 UI
2. 방별 capture/dedup 및 공정한 다중방 sync
3. WSL room 관리·방별 status
4. Telegram route/outbox/thread 지원
5. Android 단위·계측 테스트와 서버 단위·PostgreSQL 통합 테스트
6. 합성 N개 방 end-to-end 검증
7. Xiaomi에 APK 업데이트
8. 사용자가 고른 소수 방으로 단계적 실기기 검증
9. 수집률·재부팅·야간 지속성·방 오분류·Telegram 토픽 도착을 별도 기록

## 7. 완료 기준

- 기존 단일방 설정과 미전송 데이터가 유지된다.
- N개의 선택 방에서 온 알림이 올바른 room ID로만 저장된다.
- 선택하지 않은 방과 identity 충돌 알림의 원문은 저장·업로드되지 않는다.
- 서버에서 room별 저장·분석·진도·삭제가 서로 영향을 주지 않는다.
- 한 room의 폭주나 오류가 다른 room의 업로드·분석을 무기한 막지 않는다.
- 하나의 Telegram 봇/채팅에서 각 room digest가 지정된 topic으로 전달된다.
- 재시도, 설정 변경, Worker 중단 뒤에도 다른 room/topic으로 잘못 발송되지 않는다.
- 테스트 결과와 실제 Xiaomi 관찰 결과를 구분해 문서화한다.

## 8. 범위 밖

- 여러 사용자가 공유하는 공개 서비스
- KakaoTalk 알림에 나타나지 않은 과거 대화 복구
- 방 간 원문을 섞은 기본 AI 분석
- 방마다 별도 Telegram 봇 토큰 생성
- 사용자가 요청하지 않은 외부 공개 터널 또는 공개 웹 대시보드
