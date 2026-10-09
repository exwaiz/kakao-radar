# Kakao Radar — Real-device Debug Notes

## 2026-10-06 저녁 — 19:00 분석·발송 경합

- 17:55와 18:55 KakaoTalk wake는 각각 `completed`였다. 18:59에 폰·Pi로 새 메시지 34건이 수집됐고 폰 listener/동기화는 활성, 대기 0건이었다. 18:00 Telegram 2건은 수락됐으나 19:00 outbox는 생성되지 않았다.
- 발송 워커가 19:00:09에 `idle`로 계획을 마치고 다음 due를 20:00으로 이동했다. 첫 분석 후보는 19:00:18, 마지막은 19:01:44에 생성됐다. 따라서 19시 누락은 Telegram API 오류가 아니라 정각 경계에서 계획이 분석보다 앞선 경합이다.
- 미발송 후보를 중복·진도·quota 규칙이 적용되는 `manual` 계획으로 보충했다. 방별 3건 모두 Telegram API `accepted`, 활성 대기 0건, 다음 정기 due 20:00을 확인했다.
- 계획기를 수정해 정기 슬롯을 5분간 유지하고, 같은 방의 정기 outbox를 한 슬롯에 한 번으로 제한했다. 별도 PostgreSQL 테스트 클러스터에서 서버 회귀 207건 통과(기존 dependency 경고 2건). 운영 `kakao-radar-delivery` 워커를 재시작했고 활성 상태를 확인했다. 20시 정기 결과는 별도로 확인한다.

## 2026-10-06 오후 — 12:00 이후 수집 정지와 wake 조건 순환

- 16:42 KST 점검에서 Android collector v3는 listener 연결·수집·동기화 활성, 대기 0건이었다. 폰과 Pi의 마지막 실제 메시지는 11:56:20, 분석 마지막 완료는 11:58, Telegram 마지막 API 수락은 12:00이었다. 4개 Telegram route와 서버 서비스는 활성 상태였다.
- wake timer 로그는 10:55와 11:55에 완료, 12:55부터 매시 `wake_skipped=no_sendable_summary`였다. 기존 스크립트가 이미 분석된 후보가 있어야 카카오톡을 실행하는 구조여서, 잠든 KakaoTalk의 새 알림을 깨우지 못했다.
- 16:43 무렵 ADB로 KakaoTalk을 한 번 실행하고 홈으로 돌아오자 폰 저장 수가 1,099→1,102, 전송 완료 수도 1,102로 증가하고 대기 0건을 확인했다. 따라서 이번 구간은 Telegram API 장애가 아니라 새 알림 수집 중단이 직접 원인이다. 알림이 없던 과거 대화 전체가 복구됐다는 뜻은 아니다.
- 정기 발송이 활성화된 슬롯 5분 전에는 후보/요약과 무관하게 KakaoTalk을 실행하도록 수정했다. 16:55 실제 timer가 `wake_result=completed`로 끝났고 폰 저장 1,102→1,104, Pi 수신 1,104, 분석 후보 2건 추가와 대기 0건을 확인했다. 17:00 슬롯에서 방별 outbox 2건이 각각 Telegram API `accepted`로 기록됐고 다음 due는 18:00이다. 사용자 본폰 표시 여부는 별도다.

## 2026-10-06 — 폰 로컬 수집과 Pi 업로드의 분리 장애

- 샤오미는 Wi-Fi ADB `192.168.50.124:5555`에 연결됐고 알림 listener가 허용됐다. 폰 Room DB는 2026-10-06 09:35 KST까지 저장했으며 당시 저장 1,039건 중 전송 완료 257건·대기 782건이었다. Pi DB 최종 수신은 2026-10-04 20:08 KST, Telegram API 최종 수락은 21:00 KST였다.
- Android 동기화 설정은 `https://localhost:8443`이고 오류는 연결 실패였다. USB 해제 뒤 Wi-Fi ADB는 연결됐으나 `adb reverse --list`가 비어 있었다. 수동 `adb reverse tcp:8443 tcp:8443` 복구 뒤 폰의 TCP 8443 접근과 Pi localhost HTTPS 상태·인증서 일치를 확인했다. WorkManager는 지연 재시도 중이었고 강제 JobScheduler 실행으로도 업로드 진도는 없었다.
- 잠금 해제 뒤 `MainActivity`를 열었으나 Xiaomi의 ADB `input swipe`는 `INJECT_EVENTS` 권한 거부로 막혔다. 사용자 요청에 따라 화면이 필요 없는 ADB 수집기 v3로 교체 개발을 시작했다. 교체·실제 업로드·Telegram 재수신 결과는 검증 전까지 별도로 기록한다.
- **v3 교체 실기기 결과:** 기존 APK와 새 debug APK의 서명 SHA-256 일치를 확인하고 앱 전용 DB·설정을 저장소 밖 0600 백업에 보관한 뒤 `adb install -r` 성공. 방 4개, 로컬 1,042건, 암호화된 기기 동기화 설정을 보존했다. `AdbControlReceiver`의 shell/DUMP 제어로 첫 100건을 즉시 업로드하고 이어 685건을 drain하여 대기 0건·전송 완료 1,042건을 확인했다. Pi는 이번 업로드 785건 수신, 분석 요약도 새로 생성했다. Telegram은 다음 정기 슬롯 전이므로 신규 API 수락은 아직 확인되지 않았다.
- 업데이트 직후 listener 권한은 허용돼 있었으나 실제 바인딩은 빠져 있었다. ADB `cmd notification disallow_listener`→`allow_listener`와 receiver 재연결 명령으로 live listener/앱 `listener_connected=true`를 확인했다. Pi의 5분 ADB 유지 timer가 터널 재설정·대기 업로드·listener 재연결을 수행하도록 설치하고 수동 실행에 성공했다. 이는 장시간 화면 OFF 실측을 대신하지 않는다.
- `adb reverse`를 일부러 제거한 뒤 유지 서비스를 실행해 터널 복구를 확인했다. 앱을 `am force-stop`한 뒤에도 같은 서비스가 앱과 listener를 되살리고 전송 대기 0건을 유지했다. Android lint와 APK 빌드는 통과했고, Pi aarch64에서는 Robolectric native runtime 미지원으로 해당 JVM 테스트 실행이 제한된다. 호스트 ADB CLI 단위 테스트 5개는 통과했다.
- 같은 v3 APK 재설치 직후에는 Xiaomi가 cold broadcast와 notification listener의 자동 시작을 거부했다. ADB broadcast는 `result=0`만 반환하고 receiver 데이터가 없었다. 화면 없는 `Theme.NoDisplay` bootstrap Activity를 shell/DUMP 권한으로 보호해 추가하고, CLI가 빈 응답일 때 이를 한 번 실행한 뒤 명령을 재시도하도록 보강했다. 최종 APK 재설치 뒤 `status`와 bootstrap의 직접 ADB 실행이 성공했고, `force-stop` 뒤 CLI 상태 조회 및 유지 서비스 실행으로 listener live·reverse 8443·pending 0을 다시 확인했다. 자동 fallback 분기는 호스트 단위 테스트에서 검증했다.

## 2026-09-28 — 하루 4회 Telegram 테스트 일정

- 사용자 요청으로 테스트 기간의 정기 발송 시각을 `Asia/Seoul` 11:00, 15:00, 20:00, 23:00으로 변경했다. 종료일은 지정되지 않아 사용자가 다시 변경할 때까지 유지한다.
- 한 슬롯에서 선택된 4개 room이 각각 독립 말풍선을 만들 수 있으므로 일일 Telegram notification 상한을 4에서 16으로 조정했다. room당 최대 관심주제 5개, 원문 인용·중복 억제·AI 일일 $1 상한, 긴급 발송 OFF는 유지한다.
- 변경 직후 정책 version은 7, 다음 due는 2026-09-28 11:00 KST다. 설정 변경 당시 active pending/retry outbox는 없었다.

## 2026-09-27 — 기존 봇 개인 chat에 4개 방별 말풍선 운영

- 사용자 최신 요구로 forum/supergroup 없이 기존 Telegram 봇 하나와 기존 본인 개인 chat 하나를 공유한다. 단위시간마다 각 room의 관심 후보 전체를 요약한 말풍선 한 건을 만들며, 새 후보가 있는 room N개면 최대 N개를 보낸다.
- schema 7은 일반 개인 route(`message_thread_id=NULL`)가 같은 `chat_id`를 공유하도록 허용한다. forum topic route의 목적지 고유성은 유지한다. outbox 생성은 기존처럼 room별이며 payload topic 집합도 해당 room 하나로 제한한다.
- 방별 말풍선 제목에 `카카오방 A/B/C/D` route label을 붙였다. 기존 room의 과거 데이터를 다른 방으로 재분류하지 않았다.
- 격리 WSL PostgreSQL 16에서 서버 회귀 **191 passed**, 기존 dependency warning 2개, 합성 M3/M4 데모 성공, 외부 네트워크 호출 0건이었다.
- 운영 적용 전 `/var/backups/kakao-radar/radar-pre-v21-20260927.dump`와 `server-pre-v21-20260927.tar.gz`를 만들고 SHA-256을 확인했다. schema 6→7 적용 뒤 route 4개가 같은 chat 1개를 공유하며 thread는 모두 NULL이다.
- Redmi에는 5,321건 중 4,233건이 pending이었다. USB reverse와 WSL keepalive를 복구하고 개인정보 안전 round-robin 계측으로 4개 방 적체를 모두 업로드해 pending 0, WSL stored messages 5,321을 확인했다.
- 새 분석 뒤 발송 후보는 A 5개, B 2개, C 2개, D 2개였고 계획 시점의 추가 완료분을 포함해 실제 말풍선은 D 3개 주제, B 4개, C 5개, A 5개 주제로 생성됐다.
- Telegram API는 방별 말풍선 4개를 모두 accepted로 반환했고 provider message ID는 37, 38, 39, 40이다. DB outbox도 4개 모두 accepted이며 서로 다른 room/progress를 유지한다. 사용자가 Telegram 모바일 화면 캡처로 `카카오방 A`와 `카카오방 D`가 서로 다른 라벨의 독립 말풍선으로 표시된 것을 확인했다. 나머지 두 방도 사용자가 4개 말풍선을 잘 받았다고 확인했다.
- 오늘 수동 4개가 quota 4/4를 사용해 오늘 정규분으로 처리했다. 다음 due는 2026-09-28 23:00 KST다. 이후 기본 일정은 매일 23:00, 방별 최대 5개 주제, 최대 4개 말풍선이다.


## 2026-09-22 — Redmi 실제 4개 방 선택과 WSL provision

- 사용자가 외부에 있는 동안 Redmi에서 발견된 Kakao 대화 4개를 모두 선택하도록 명시 승인했다. 방 제목과 원문은 출력하거나 저장소에 복사하지 않았다.
- 단말이 잠금 상태이고 HyperOS가 ADB input에 `INJECT_EVENTS` 권한을 주지 않아 화면 터치 방식은 중단했다. 잠금 해제나 보안 설정 우회 없이, 명시적 action 인자가 필요한 개인정보 안전 계측 테스트를 추가해 앱 내부 선택 API를 실행했다.
- 기존 테스트 APK와 새 테스트 APK의 서명이 달라 최초 업데이트가 거부됐다. 운영 앱/데이터는 삭제하지 않았고 테스트 전용 패키지만 제거했다. 설치된 운영 APK의 인증서 SHA-256과 일치하는 기존 `android-user` debug keystore로 테스트 APK를 다시 서명한 뒤 설치했다.
- 실기기 선택 결과는 발견 후보 4개, 서로 다른 shortcut 대화 ID 4개, 선택 binding 4개, `selection_version=2`다. 기존 단일 방 UUID는 그대로 보존되고 신규 UUID 3개가 생성됐다. 선택 변경 직후 capture는 설계대로 자동 중지됐다.
- WSL 비공개 `.state/device.json`의 기존 기기 UUID/token을 내부에서만 읽어 4개 room을 schema 6 allowlist에 provision했다. 기존 방 데이터 1,688건·분석 job 266건은 원래 room에만 유지되고 신규 3개 room은 각각 0건이다.
- provision 뒤 Redmi capture/sync를 다시 활성화하고 비식별 진단으로 선택 4개, capture=true, sync=true, pending=0을 확인했다. 운영 앱 본체나 기존 Room DB를 재설치·삭제하지 않았다.
- Telegram route는 여전히 0개다. 허용 room이 4개이므로 개인 채팅 단일 방 fallback은 비활성이고 delivery route 계산 결과도 0개다. 비공개 forum supergroup과 방별 topic route가 준비되기 전에는 새 자동 Telegram 발송이 안전하게 보류된다.
- WSL API/analysis/delivery 서비스는 모두 active다. 신규 3개 실제 방에서 새 알림이 도착해 방별 저장·업로드되는지는 아직 관찰하지 않았으므로 N방 실수집 성공으로 기록하지 않는다.

다음 검증: 새 알림 도착 뒤 Redmi/WSL의 4개 방별 증가 확인, Telegram forum의 서로 다른 `message_thread_id` 4개 연결, 방별 실제 수신, 화면 OFF 장시간 및 야간 수집.

## 2026-09-22 — WSL server 2.0.0 / schema 6 운영 이관

- 이관 전 운영 DB는 schema 5, device 1, room 1, messages/receipts 1,008, delivery outbox 28건(accepted 28, active/uncertain 0)이었다. 운영 DB와 기존 서버 소스를 각각 `/var/backups/kakao-radar/radar-pre-v2-20260922-0910.dump`, `server-pre-v2-20260922-0910.tar.gz`에 백업하고 SHA-256을 확인했다.
- WSL Linux 임시 클러스터에서 v2 서버 회귀 189건이 모두 통과했고 합성 M3/M4 데모도 성공했다. 테스트의 외부 네트워크 호출은 0건이었다. 일반 계정이 `/var/run/postgresql`에 test socket을 만들 수 없는 Linux 환경을 위해 `run_local_tests.py`가 자체 `.state` socket 경로를 사용하도록 보완했다.
- 운영 서버 소스를 2.0.0으로 배포하고 schema 5→6 migration을 적용했다. device 1, room 1, messages 1,008, outbox 28건을 보존했다. 기존 `service_update` accepted outbox 1건만 room 없는 과거 항목으로 남았고 다른 기존 outbox는 방을 복원했다. Telegram route는 아직 0개다.
- `kakao-radar-api`, `local-https`, `analysis`, `delivery`, `retention` 5개 서비스가 active이고 `/health`는 `2.0.0`을 반환한다. USB `tcp:8443` reverse와 WSL keepalive를 복구했다.
- Redmi의 기존 backlog 680건을 실제 기존 자격 증명·CA로 100건 단위 전송했다. 모든 batch가 `SENT`, 단말 pending 0, WSL messages/receipts 1,688/1,688을 확인했다. 원문·닉네임·UUID·token은 출력하지 않았다. listener는 계측 뒤 다시 bound 상태다.
- 이 결과는 기존 단일 방의 v2 APK→WSL schema 6 저장 경로를 확인한 것이다. 추가 Kakao 방 선택·provision, 방별 route, 실제 Telegram forum topic 수신, N방 장시간/야간 수집은 아직 검증하지 않았다.

## 2026-09-22 — Redmi 2.0.0 업데이트와 v1 설정 migration 확인

- 연결된 Redmi `24094RAD4G` / Android 15에서 기존 설치본 `versionCode=4`, `versionName=0.3.1`과 2026-09-16의 최초 설치 시각을 확인했다. 업데이트 전 개인정보 안전 집계는 schema 3, 메시지 1,681건, 선택 방 1개, 수집/동기화 활성, upload pending 673 / sent 1,008이었다.
- 첫 2.0.0 APK는 다른 debug keystore로 서명되어 Android가 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`로 거부했다. 앱을 삭제하지 않았다. 기존 0.3.1에 사용한 로컬 debug keystore로 다시 빌드한 뒤 `adb install -r`가 성공했고 `versionCode=6`, `versionName=2.0.0`을 확인했다. 최초 설치 시각은 그대로 유지됐다.
- 최초 실행 뒤 실제 preference migration은 선택 방 1개, `selection_version=1`, 유효한 기존 UUID, legacy `binding`/`room_id` 키 제거 상태였다. 기존 sync preference에 남아 있던 room UUID와 새 단일 `RoomBinding.roomId`가 정확히 일치했다. 따라서 이 단말에서 기존 단일 방 UUID의 보존·단일 항목 집합 승격을 확인했다.
- migration 후 schema 3, 메시지 1,688건, upload pending 680 / sent 1,008, 수집/동기화 활성 상태였다. 두 진단 사이 실제 알림이 계속 들어와 메시지와 pending이 각각 7건 증가했으므로, 이 차이를 migration 생성 데이터로 해석하지 않는다.
- 계측 종료 뒤 앱을 다시 시작하고 notification listener의 enabled/bound `CollectorService`를 확인했다. 원문, 방 제목, 닉네임, token, 전체 room UUID는 PC나 문서에 출력하지 않았다.
- 엄밀한 한계: 이 단말의 업데이트 전 실제 설치본은 이름이 1.0.0인 APK가 아니라 0.3.1이었다. 1.0.0도 사용하는 동일 legacy 단일 방 preference 형식의 migration은 실기기에서 확인했지만, 1.0.0 APK를 먼저 설치한 상태에서의 업데이트 절차 자체는 확인하지 않았다.
- 아직 하지 않은 것: 추가 방의 실제 선택은 수집 범위를 넓히므로 사용자가 방을 지정하기 전 임의로 후보 4개를 선택하지 않았다. 따라서 N개 방의 신규 알림 방별 저장, 화면 OFF 장시간 수집률, 야간 6~8시간 구간은 계속 미검증이다.

## 2026-09-21 — v2.0 다중 방 구현 검증 경계

- Android 단일 방 preference를 동일 `room_id`의 다중 선택 집합으로 승격하는 코드, 방별 snapshot/capture 진도, 선택 방 round-robin 업로드를 구현했다.
- 서버 schema 6에 방 표시명, Telegram route, outbox의 방·chat·thread·route version snapshot을 추가했다. 다중 방은 방별 outbox로만 계획한다.
- 이 작업의 Robolectric/합성 PostgreSQL/Mock Telegram 결과는 실제 Redmi의 다중 방 알림 도착률, 재부팅·야간 지속성, 실제 Telegram forum topic 표시를 증명하지 않는다. 실제 APK 설치·실방 선택·WSL schema 적용·Telegram topic 수신은 별도 실기기 검증으로 남긴다.
- 원문·닉네임·실제 Telegram token/chat ID는 테스트 fixture, 문서, 저장소에 추가하지 않았다.

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

- **GitHub 확인:** M3 진단 브랜치와 master 통합 커밋을 게시했다. master 통합 커밋 254639e의 tree 5db6ae967d643c81923cb73299eae1ae057df048가 검증한 로컬 tree와 정확히 일치한다. GitHub 설정의 기본 브랜치를 main→master로 변경하고 연결 도구에서 default_branch=master를 확인했다. 기존 브랜치는 유지한다.

### 2026-09-18 릴리스 게시와 WSL 상태 확인

- GitHub v1.0.0 릴리스를 https://github.com/exwaiz/kakao-radar/releases/tag/v1.0.0 에 게시했다. 태그 대상은 a7957b40f8cf999191444939f06b21fced545206이며 master의 모든 기존 원격 브랜치 head가 ancestor인지 검사했다. 소스 zip/tar 아카이브 2개를 확인했다.
- APK 빌드·서명 확인은 통과했으나 Chrome 확장의 파일 URL 접근이 허용되지 않아 릴리스 첨부는 실행하지 못했다. 확장 보안 설정은 변경하지 않았고 APK는 로컬 android/app/build/outputs/apk/debug/kakao-radar-1.0.0-debug.apk에 보존했다. 설치된 폰 버전은 유지한다.
- 기존 WSL 작업 트리가 깨끗하고 tree가 공개 WSL baseline과 일치함을 확인한 뒤 master로 전환했다. API만 재시작했다. 초기 시작 직후 상태 요청은 실패했지만 후속 조회에서 /health status=ok / version=1.0.0, API 재시작 횟수 0, API·로컬 HTTPS·분석·전달·retention 서비스 5개 active를 확인했다. 추가 외부 발송·유료 호출은 실행하지 않았다.
- 배포 뒤 Telegram policy version=4, 24개 매시 정각 슬롯, 최대 3개·quota 144회·원문 인용 및 9/19 자정 기존 23:00/1회/5개 복귀가 유지됨을 재조회했다. 조회 시 next_due=2026-09-18 15:00:00+09:00.
- 배포 전/후 상태와 복구 명령은 PC 비공개 battery-focus/runtime-v1-{before,after}.json 및 rollback-runtime-v1.txt에 기록했다. 복구는 기존 feat/wsl-runtime 체크아웃으로 돌아가 API를 재시작하며 DB·앱 데이터 삭제나 다른 Worker 설정 변경이 필요하지 않다.

## 2026-09-22 — WSL v2 적체 처리 후 수동 Telegram 시험

상태: **Telegram API 수락 확인 / 사용자 화면 표시·열람 미확인**.

- 실제 WSL 운영 DB에서 허용된 기기는 1개, 허용 방은 1개였고 versioned Telegram route는 0개였다. 따라서 이번 시험은 v2 다중 forum topic 경로가 아니라 기존 개인 채팅의 단일 방 fallback 경로를 검증했다.
- Redmi의 전송 적체를 처리한 뒤 WSL에는 메시지와 receipt가 각각 1,688건 있었고 단말 pending은 0건이었다. 이 수치는 방별 장시간 수집률이나 야간 지속성 검증이 아니다.
- 2026-09-22 14:05 KST에 정규 `next_due_at=23:00`을 변경하지 않고 `manual=True`로 새 후보 5개를 1건의 digest로 계획했다.
- Telegram `sendMessage` 응답은 `accepted`였고, outbox 최신 행은 `kind=manual`, `status=accepted`, topic 5개로 저장됐다. `delivery_progress`도 갱신되어 같은 근거의 재발송을 막는다.
- 오늘 delivery quota는 0/1에서 1/1이 됐다. 따라서 오늘 23:00 정규 슬롯에서 추가 메시지는 보내지 않으며, 다음 발송 가능 시점은 quota/정책에 따라 다음 날로 넘어간다.
- 발송 전후 `kakao-radar-delivery.service`를 안전하게 중지·재기동했고, 최종 delivery/API 서비스 모두 `active`였다.
- 원문·닉네임·봇 토큰·chat ID는 명령 출력이나 문서에 기록하지 않았다.

계속 미검증: 사용자의 Telegram 앱 실제 표시/열람, v2 forum supergroup의 방별 `message_thread_id`, N개 Kakao 방 동시 선택·방별 저장, 화면 OFF 장시간 수집, 야간 수집, 기존 v1 단말 설정의 실제 migration 정확성.

### 2026-09-22 후속 — 수신 확인과 방 경계 불일치 발견

- 사용자가 수동 digest를 Telegram에서 실제로 받았다고 확인했다. 다만 5개 관심주제가 여러 Kakao 방의 내용처럼 섞여 보여 방별 그룹화가 필요하다고 피드백했다.
- 발송 DB를 비식별 집계로 재검사한 결과, 최신 outbox의 topic 5개와 delivery item은 모두 동일한 `room_id`였다. WSL에는 허용 room 1개, 메시지 1,688건 전부 그 room, 활성 Telegram route 0개만 존재했다.
- Redmi 실기기 안전 진단 결과 발견 후보 4개와 서로 다른 shortcut 기반 대화 ID 4개가 있었지만, 선택 binding은 1개뿐이었다. v1 room ID와 sync room이 그 단일 binding으로 이관된 상태이며 capture/sync는 활성, pending은 0건이었다.
- 따라서 현재 개인 채팅 메시지를 단순히 5개로 분할해도 Kakao 방별 Telegram 그룹화가 되지 않는다. 방별 그룹화에는 N개 binding 선택, WSL N개 room 허용, 비공개 forum supergroup의 방별 `message_thread_id` route가 모두 필요하다.
- 이미 단일 room ID로 저장된 과거 1,688건은 서버 데이터만으로 실제 원본 Kakao 방을 안전하게 재분류할 수 없다. 다른 방으로 추정해 재발송하지 않는다. 방별 실측은 설정 완료 뒤 새 메시지부터 검증한다.
