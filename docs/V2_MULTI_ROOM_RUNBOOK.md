# Kakao Radar 2.0 다중 방 전환 절차

이 문서는 코드 배포와 실제 기기 검증을 분리한다. 저장소 테스트 통과만으로 Redmi 수집이나 Telegram 표시 성공을 선언하지 않는다.

## Telegram 전제

`message_thread_id`는 Telegram forum topic에서만 사용할 수 있다. 기존 봇과의 1:1 개인 채팅은 topic을 지원하지 않는다. Kakao 방 여러 개를 Telegram 방 하나에 분리해서 담으려면 다음 조건이 필요하다.

1. 비공개 Telegram supergroup을 만들고 Topics를 활성화한다.
2. 기존 Kakao Radar 봇을 그 그룹에 추가하고 메시지 전송 권한을 준다.
3. Kakao 방마다 topic을 하나씩 만들고 각 topic의 양의 정수 `message_thread_id`를 확인한다.
4. 모든 route는 같은 `chat_id`와 서로 다른 `message_thread_id`를 사용한다.

개인 채팅 fallback은 v1 단일 방 호환용이다. 허용된 Kakao 방이 둘 이상이면 명시 route 없이 자동 발송하지 않는다.

## 안전한 배포 순서

1. 운영 PostgreSQL을 백업하고 현재 앱·서버 버전과 대기 outbox를 기록한다.
2. 서버 코드를 배포하고 `python -m radar_server.manage migrate`로 schema 7을 적용한다. schema 6의 다중 방 구조와 숫자 Telegram update cursor만 추가하며 원문이나 기존 방 ID를 다시 쓰지 않는다.
3. Android 2.0 APK를 업데이트 설치한다. 기존 단일 선택은 같은 `room_id`의 선택 집합으로 자동 승격된다.
4. 앱의 다중 선택 화면에서 방을 추가한다. 선택이 바뀌면 수집은 자동으로 일시 중지된다. 화면에 표시된 각 방의 UUID를 복사한다.
5. 각 새 UUID를 같은 기기 UUID와 같은 기기 token으로 provision한다. token은 CLI의 숨김 입력으로만 제공한다.

```text
python -m radar_server.manage provision --device <device-uuid> --room <room-uuid> --name <display-name>
```

6. 방마다 forum route를 등록한다. 신규 route의 `expected-version`은 0이고, 변경 시 `list-rooms`에 표시된 현재 version을 사용한다.

```text
python -m radar_server.manage set-route --device <device-uuid> --room <room-uuid> --chat-id <forum-chat-id> --thread-id <topic-id> --name <display-name> --expected-version 0
python -m radar_server.manage list-rooms --device <device-uuid>
```

7. 기존 private 환경 파일에 명령을 보낼 본인의 양수 Telegram user ID를 `RADAR_TELEGRAM_ADMIN_USER_ID`로 저장한다. 기존 양수 `RADAR_TELEGRAM_CHAT_ID`가 본인의 private chat ID라면 생략해도 된다. forum supergroup의 음수 chat ID를 관리자 ID로 사용하지 않는다.

```text
python -m radar_server.manage migrate
sudo systemctl enable --now kakao-radar-telegram-commands
```

각 방의 Telegram 토픽에서 `/name 새 이름`을 보내고 같은 토픽으로 확인 응답이 오는지 확인한다. `/name`은 현재 이름, `/help`는 사용법을 표시한다. 명령은 관리자 ID가 일치하고 `(chat_id, message_thread_id)`에 활성 route가 정확히 하나 있을 때만 반영된다. webhook이나 다른 long-poll 프로세스가 같은 봇의 update를 소비하고 있으면 이 worker와 함께 사용할 수 없다.

8. `/v1/status`에서 방별 최근 수신·저장 수·분석 backlog를, `/v1/delivery/status`에서 미라우팅 방을 확인한다. 모든 방이 provision·route된 뒤 Android 수집과 동기화를 다시 켠다.
9. 한 방씩 합성 아닌 새 메시지를 보내 APK 방별 저장, WSL 방별 수신, 해당 Telegram topic 수신을 순서대로 확인한다. callback 수를 메시지 수나 수집률로 기록하지 않는다.

## 롤백

- Android에서 문제가 생기면 수집·동기화를 끈다. 기존 로컬 메시지와 UUID는 삭제하지 않는다.
- route 문제는 같은 room의 route를 `--disable`로 version 증가시켜 중단한다. 아직 보내지 않은 해당 방 outbox는 취소되며, 이미 전송을 시작한 unknown outcome은 자동 재시도하지 않는다.
- 방 데이터 삭제 API는 원문·receipt·분석·route를 제거하고 allowlist를 해제하는 별도 파괴 작업이다. 단순 중지 용도로 사용하지 않는다.

## 아직 별도 검증인 항목

- Redmi의 실제 N개 KakaoTalk 방 식별과 장시간/화면 OFF 수집률
- 기존 v1 설치에서 실제 preference 및 Room DB 보존
- 운영 WSL schema 5 → 7 적용과 서비스 재시작
- 실제 관리자 `/name` 명령 수신과 해당 forum topic 확인 응답
- 실제 비공개 Telegram forum의 topic ID 및 봇 권한
- 방별 요약 유용성과 일일 AI $1 예산 안에서의 N방 부하
