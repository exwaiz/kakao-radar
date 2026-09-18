# WSL 운영 통합 — 2026-09-17

Android 1.0.0 / 서버 1.0.0. 통합 브랜치는 master다. 기준은 기존 M4 브랜치 `12c86a2`이며 `feat/wsl-runtime`에서 통합한다. 라즈베리파이는 필요하지 않다.

## 9/18 최신 지시 — 1시간 테스트와 v1.0.0 통합

Telegram 테스트는 **한국 시간 매시 정각 1시간 간격, 최대 3개 주제**로 변경했다. 운영 설정 version 3→4, 시간표 144슬롯→24슬롯, 적용 직후 next_due 2026-09-18 12:00 KST를 확인했다. 오늘 기존 17회 발송 시도를 보존했으며 테스트 quota 144회는 그대로 두었다. 이 quota는 매시간 추가 발송을 뜻하지 않고 재시도를 포함한 상한이다.

9/19 00:00의 기존 23:00 / 하루 1회 / 최대 5개 주제 복귀, 실제 대사·수집 시각·중복 억제·방별 진도·AI $1/day는 유지한다. 빈 후보는 발송하지 않는다. 아래의 10분·30분 테스트 서술은 이전 이력이며 이 설정이 우선한다.

재현: `configure_test_day.py --interval-minutes 60 --max-topics 3 --preserve-daily-limit`. 기본 interval은 60분, max-topics는 3이다. 신규 테스트일에 quota를 새로 계산할 때는 `--preserve-daily-limit`을 생략하며 24회가 된다. 사용자 요청 없이 도구를 매일 실행하거나 테스트 기간을 연장하지 않는다.

변경 전/후 설정과 실행 가능한 rollback 스크립트는 PC 비공개 `AppData/Local/Codex/adb-diagnostics/2026-09-18_10-00-52/battery-focus/hourly-telegram-{before,after}.json`, `rollback-hourly-telegram.py`, `rollback-hourly-telegram.txt`에 있다. 저장소에는 기기/방 ID, 자격 증명이나 운영 원문을 복제하지 않는다.

카카오톡 주기적 깨우기 기능은 사용자 지시로 보류했다. 배터리 진단에서 적용한 Radar의 Doze 예외 1건과 1회 앱 전환 사실은 DEBUG_NOTES의 별도 관찰이며 알림 지연 해결·수집률 통과를 뜻하지 않는다.

## 9/18 이전 개선 — 보고 진도와 서식

실제 08:20 보고에 오늘 07:40 대화가 있었으나 08:30–09:00 보고는 다시 어젯밤 후보를 보냈다. 전체 후보 중요도순 선택·표현 지문만으로는 중복/역행을 막지 못했다. schema 5의 `delivery_progress`/`delivery_source_receipts`는 기기·방별 최신 원문 observed_at와 전달한 원문 ID·내용 해시를 저장한다. 실제 기존 최신 전달 진도를 **9/18 07:40:07**로 복원했다.

정기 보고는 진도 이후의 새 원문만 근거로 쓰는 요점에서 중요도를 선정해 시간순으로 표시한다. 혼합된 새/옛 근거 요점은 재작성 없이 제외한다. 수락/미확정 발송에는 해당 방의 완료 분석 구간 상한을 함께 저장해 탈락한 과거 후보를 다음 보고에 이월하지 않는다. 뒤늦게 올라온 진도 이전 원문은 아카이브에서 유지하며 정기 업데이트에서는 제외한다. 정확한 내용 해시는 재노출을 억제하지만 모든 다른 표현/새 원문의 의미 중복까지 판정한다고 표현하지 않는다.

Telegram 제목/첫 핵심 요점은 bold entities, header/주제/인용 등에 emoji, 새 근거의 실제 대사와 수집 시각을 표시한다. UTF-16 offset/길이를 계산하고 원문 markup은 파싱하지 않는다. 테스트 183개 통과. 변경 안내 1건은 `service_update`로 기존 일일 quota와 이력에 기록했고 API 수락을 확인했다. 본폰 표시 실측은 별도다.

이관 재현은 delivery 워커를 중지하고 `RADAR_DATABASE_URL`을 기존 보호된 runtime 설정에서 읽어 `server/tools/upgrade_delivery_progress.py`를 실행한 뒤 API/retention/delivery를 재시작한다. 운영 원문/기존 발송 기록은 삭제하지 않는다. 새 ledger는 방 삭제 시 함께 지우며 해시 receipt는 90일 보관한다.

현재 저장 354건, 마지막 수집 07:40:07/업로드 07:41:41, collector bound/capture enabled/sync enabled/error 없음. 새 후보 0이면 10분 슬롯을 건너뛴다. 새 메시지 없음과 알림 비노출은 이 수치만으로 구별하지 않는다. 오늘 10분/3개/144회 및 자정 23:00/1회/5개 복귀·AI $1/day·인용 유지.

## 2026-09-18 테스트 기간 변경 — 최신 지시

후속 요청으로 오늘 테스트 빈도를 **10분 간격, 한 번 최대 3개 주제**로 높인다. 정기 슬롯은 매시 00·10·20·30·40·50분, 일일 테스트 상한은 144회다. 이 설정이 아래 처음 정한 30분 설정보다 우선한다. 9/19 자정에는 23:00/하루 1회/최대 5개 주제로 돌아간다. 원문 인용·중복 억제·AI $1/day는 유지한다. 새 후보가 없으면 빈 요약은 생략한다. 사용자가 Telegram으로 실제 메시지를 받았다고 보고하여 사용자 수신은 확인했으며, 정확한 알림 표시 latency를 측정한 것은 아니다.

현재 설정 재현: `configure_test_day.py --interval-minutes 10 --max-topics 3`. 해당 도구는 현재 노트북에서 사용자 지시가 있을 때만 실행한다.

이전 대화와 새 대화를 구분하도록 원문 인용마다 알림 수집 시각을 Asia/Seoul로 표시한다. 이는 사건 발생 시각을 검증한 것이 아니다. 최종 전용 DB 테스트는 172개 모두 통과했다.

오늘은 Asia/Seoul 매시 00분·30분, 하루 최대 48회 테스트 시간표를 사용한다. 2026-09-19 00:00에 임시 시간표를 자동 해제하고 기존 23:00/하루 1회로 복귀한다. `test_mode_until`, `resume_daily_times`, `resume_daily_notification_limit`은 복귀 계약이며 만료된 미발송 테스트 큐는 취소한다. 신규 관심 후보가 없으면 빈 요약은 보내지 않는다. 중복 억제와 하루 $1 AI 비용 상한은 계속 적용한다.

발송 시 각 주제의 검증된 evidence ID에서 실제 대사 최대 2개를 80자까지 그대로 가져온다. 길면 닫는 인용부호 뒤에 생략 표시를 붙인다. 모델이 인용을 재작성하지 않는다. 기기와 방이 같은 live 원문만 읽고, 다른 방이나 만료된 원문은 인용하지 않는다. 원문 인용은 발송 직전 메모리에서 붙이며 분석 요약/outbox에 별도 원문 사본을 영구 저장하지 않는다. Telegram에 보낸 인용은 해당 채팅에 남는다.

실제 인용을 포함한 검증 요약의 Telegram API 수락을 확인했다. 관심 주제 5개에 실제 대사 5개가 포함됐다. 다음 정기 슬롯은 2026-09-18 08:00이며 검증 발송으로 바꾸지 않았다. 354건 실제 저장, 분석 작업 45건 완료, 요약 351개/관심 후보 272개를 집계 확인했다. 문맥 때문에 요약 개수를 고유 메시지 개수나 수집률로 해석하지 않는다. 측정된 API 비용 누계는 137,506 micro-USD이며 예약량과 다르다.

재부팅/USB 재연결 후 `server/tools/start_wsl_usb.ps1`을 실행하면 설치된 WSL 서비스와 reverse를 복구한다. `install_wsl_runtime.py`, `install_wsl_local_tls.py`, `configure_android_usb.py`, `configure_wsl_profile.py`, `configure_test_day.py`는 현재 노트북의 설정 재현 도구다. 경로·distro·serial은 현재 구성에 맞춰져 있어 다른 환경은 조정해야 한다. private 환경 파일 내용을 출력하지 않는다. `configure_test_day.py`는 다시 실행한 날짜를 테스트 기간으로 설정하므로 사용자 지시 없이 매일 실행하지 않는다.

## 사용자 확정 설정

- OpenAI: 사용자 기존 계정에서 프로젝트용 새 키 생성. Responses `gpt-4.1-mini`, `store:false`, 도구/외부 링크 열람 없음. 하루 최대 1,000,000 micro-USD = $1, Asia/Seoul 자정 기준. 호출 전 최대 비용을 예약하고 실제 토큰으로 정산한다. 원격 과금 여부가 불명확한 실패는 예약을 유지한다.
- 관심사: 삼성전자, 반도체 산업, 산업 흐름, 회사 분위기, 재미있는 이벤트, 놓치면 안 될 정보, gossip/소문, 부동산, 메시지에 관찰된 공감·웃음 반응. 반응 버튼/읽음 수/전체 합의는 알림에 없으면 추정하지 않는다.
- Telegram: 기존 봇, 검증된 본인 개인 chat ID. 한국 시간 23:00, 하루 최대 1회. 첫 설정 검증 요약 한 건은 수동 큐에 기록하며 정기 시간표를 바꾸지 않았다. 조용한 시간은 미지정, urgent는 꺼짐.
- 분석 초기 설정: 최소 30건 또는 300초, 한 작업 최대 10건, 출력 4096토큰. 앞 묶음의 짧은 문맥은 최대 3건 보존한다. 초기 적체만 제한된 수동 처리로 배출한다.

## 실행 구조

Ubuntu 24.04 WSL, native PostgreSQL 16과 `/opt/kakao-radar/venv`를 사용한다. Docker 설치 중 호스트 디스크 부족을 확인하여 경량 native 구성으로 전환했다. 작업 생성물인 Windows PostgreSQL 중복 도구와 과거 빌드 산출물을 정리했으며 사용자 대화/DB는 삭제하지 않았다.

`kakaoradar` 서비스 계정은 DB superuser/createdb/createrole 권한이 없다. 운영 DB `radar`, 별도 통합 테스트 DB `radar_integration_test`, 연결은 `/var/run/postgresql` Unix socket peer 인증이다. systemd `kakao-radar-api`, `kakao-radar-local-https`, `kakao-radar-analysis`, `kakao-radar-delivery`, `kakao-radar-retention` 서비스를 사용한다.

API는 `127.0.0.1:8000`, 폰 업로드 HTTPS는 `127.0.0.1:8443`이다. USB 연결에서 `adb reverse tcp:8443 tcp:8443`로 폰의 `https://localhost:8443`를 연결한다. 기존 방 선택과 DB를 보존하며 디버그 앱의 private `files/sync-setup.json`을 일회성으로 읽고 즉시 지운다. 기기/방 UUID와 고엔트로피 토큰은 대상 하나에만 허용된다. 서버는 토큰 해시만 저장하고 Android는 Keystore AES-GCM으로 암호화한다.

로컬 인증서를 신뢰하는 설정은 디버그 앱의 `localhost:8443`에만 허용된다. HTTPS 호스트명 검증을 끄지 않으며 정상 공개 서버는 기본 시스템 인증서를 사용한다. 로컬 CA 공개 인증서는 비밀이 아니다. TLS 개인 키, raw 기기 토큰 및 환경 파일은 Git에서 제외한다.

사용자 승인 OpenAI 키와 Telegram 토큰은 기존 `outputs/kakao-radar-fixed/.env.local`에 저장돼 있다. 내용은 출력하지 않는다. `tools/runtime.py`는 해당 파일에서 분석 프로세스에 OpenAI 키만, 발송 프로세스에 Telegram 값만 읽는다. API/retention에는 외부 서비스 비밀을 전달하지 않는다. 별도 OpenAI 키 사본을 만들지 않는다.

## 관찰된 결과와 한계

- 폰 350건 저장, 서버 350건 저장, 폰 전송 완료 350건/대기 0건, 처리 오류 0건을 집계 확인했다. M1 parser와 수집률 검증은 후속이다.
- OpenAI 합성 연결 검증 1건, 측정 비용 492 micro-USD. 실제 메시지 분석에서 불확실한 원문을 확실하다고 표현한 결과와 누락된 주제를 차단했다. 불확실한 batch는 schema에서 `none`을 제외하고, topic별 필수 객체 키로 빠짐없는 결과를 요구하도록 보강했다. 내부 공통 출력은 기존 topic 배열로 변환하고 근거 범위를 다시 검사한다.
- 본인 Telegram으로 실제 요약의 설정 검증 1건을 발송했고 API 수락을 확인했다. 본폰 화면 표시/사용자 열람은 확인하지 않았다. 재시도 중 응답이 소실되면 uncertain으로 보존하며 중복 발송하지 않는다.
- 최초 Telegram 입력 화면은 실행 sandbox가 네트워크를 차단하여 입력값 검증 전에 실패했다. 네트워크 접근이 가능한 실행으로 수정했고 단계별 오류 안내를 추가했다. 정상 연결 정보 저장을 확인했다.

WSL과 노트북이 실행 중이어야 한다. Windows 재부팅/ADB 재시작/USB 재연결 후 reverse를 다시 설정해야 한다. WSL 시작 시 systemd enabled 서비스가 시작하지만 Windows 로그인 자체가 WSL 시작을 보장하지 않는다. 절전·전원 종료·USB 분리 때 업로드와 발송은 지연된다. 공인 서버 uptime이나 원격 관리가 검증된 구성은 아니다.

공개 Cloudflare 터널 생성은 자동 승인 검토에서 공개 범위와 실제 대화 전송에 대한 명시 승인이 부족하다는 이유로 거절됐다. 터널을 시작하지 않았으며 우회하지 않는다. `RADAR_PUBLIC_URL`이 없는 동안 Telegram 상세 링크 버튼은 표시하지 않는다. 정기 요약 본문은 Telegram으로 전송할 수 있다. 본폰에서 웹 근거/피드백을 쓰려면 추후 승인된 외부 HTTPS 또는 private VPN을 구성해야 한다.

최신 집계는 상위 outputs의 `kakao-radar-runtime-check.json`에 저장하며 채팅 원문/닉네임/키는 포함하지 않는다. 사용자 50주제 요약 품질 평가, 본폰 실제 열람, 밤새 운영, 재부팅 뒤 방 identity와 수집률은 아직 통과한 것으로 기록하지 않는다.
