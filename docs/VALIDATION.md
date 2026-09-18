# 검증 결과

## 서버 0.6.0 / WSL 실제 통합 — 2026-09-18 (최신)

- Ubuntu 24.04 native PostgreSQL 16, 전용 disposable `radar_integration_test` DB: **최종 pytest 172 passed / 0 skipped / 0 failed**, 24.67초. 기존 Starlette/FastAPI deprecation 경고 2개. 운영 DB/실제 대화는 이 테스트에 사용하지 않았다.
- 후속 다량 테스트: 10분 시간표 144슬롯/상한 144회, 최대 3개 주제, 자정에 23:00/하루 1회/최대 5개 주제 복귀를 검증했다. 실제 인용의 원문 수집 시각을 한국 시간으로 표시하는 시험을 포함한다. 사용자 보고로 Telegram 실제 수신을 확인했으며 정확한 단말 표시 latency는 미측정이다.
- OpenAI strict Responses, 실제 비용·예약 상한·sanitized 실패, 주제별 필수 출력과 evidence scope, 불확실성 표시, Telegram 정확한 개인 chat ID/응답 소실/정정 표시/원문 인용 회귀를 검증했다.
- 30분 시간표 48슬롯/테스트 상한 48회, 자정 자동 복귀·기존 큐 취소, 첫 열람 멱등성·HMAC/기기 범위, urgent threshold/age/cooldown·공통 quota와 수동 정기 슬롯 보존을 검증했다.
- 인용은 같은 device/room의 live 원문과 정확히 일치한다. 다른 방 원문을 읽지 않고 outbox에 원문 quote를 영구 저장하지 않는 시험을 포함한다.
- Android 최종 build / **43 unit tests** / lint / debug instrumentation APK build 통과. 마지막 빌드 2분 8초. DB schema 3 유지, 기존 개인 debug 서명으로 Redmi 업데이트했다. 진단 1건 OK, 진단이 끊은 listener를 복구하고 최종 앱 시작 requestRebind 뒤 Bound=true·sync enabled·error 없음 확인.
- 실제 운영: 메시지 354건 저장, 분석 작업 45건 완료, 요약 351개/관심 후보 272개. 원문·닉네임·비밀을 보고서에 넣지 않았다. 요약은 문맥 중첩이 있어 message 수와 분모가 다르다.
- 실제 인용 포함 검증 발송: 주제 5개/원문 인용 5개, Telegram API accepted. 정기 next_due는 2026-09-18 08:00으로 유지됐다. API 수락은 본폰 표시나 사용자 열람을 뜻하지 않는다.

초기 적체/노트북 중단 구간 때문에 전체 capture→upload p95 약 3908초, upload→analysis p95 약 28993초였다. steady-state 5분 목표를 통과한 것으로 기록하지 않는다. 실제 단말 알림 표시·사용자 50주제 품질 평가·재부팅 뒤 수집률/장기 운영·외부 웹 근거 접근은 미검증이다. 공개 터널은 자동 승인 검토 거절로 시작하지 않았고 로컬 USB HTTPS로 운영한다.

## 서버 0.5.0 / M4 — 2026-09-17 (최신)

기준 M3는 `0a750c0`이며 새 Thread의 사용자 M4 구현 요청으로 `feat/m4-delivery`에서 개발했다. Android 코드/APK와 실제 collector 설정은 변경하지 않았다. 테스트는 전용 localhost:55330/radar_m4_test와 모의 ntfy를 사용했다.

| 검증 | 결과 |
|---|---|
| M4 코어/채널 | 38개 통과: 설정 엄격성, 기본 비활성/잘못된 공급자 차단, 시간표/자정/서머타임, 조용한 시간, 정정과 방을 보존하는 내용 중복, UTF-8 길이, HMAC 링크 범위/회전/비ASCII 거절, ntfy JSON/인증/일반 우선순위, 429·인증/서버 오류·응답 유실·과대/잘못된 응답 처리 |
| M4 실제 PostgreSQL/API | 32개 통과: 전 구간 합성 처리/피드백, 설정 버전/경쟁, Worker/계획 경쟁, 조용한 시간/일일 상한/다음 날짜/시간대 변경, 후보/프로필 제외, 확정 실패 재시도/상한, uncertain 수동 복구, lease/이전 소유권 차단, 진행 중 설정 변경, 방 삭제 전/중/후 사본·링크·피드백 제거와 시도 보존, 요약 만료 뒤 삭제, 보관·반복 마이그레이션 |
| 기존 M2/M3 회귀 | 66개 전부 통과; 마이그레이션 기대 버전만 새 스키마 3으로 갱신 |
| 실제 Browser UI | 요약/근거 펼치기, 유용함↔관심 없음 저장, 새로고침 후 유지, 좁은 화면 가로 넘침 없음, 합성 img/onerror 문자열이 텍스트로 표시되고 이미지/JS dialog가 생성되지 않음 |

최종 서버 pytest는 **136개 / skip 0 / failure 0 / error 0**, 105.74초다. 기존 FastAPI/Starlette 테스트 의존성의 deprecation 경고 2개는 유지됐다. 테스트 실행 중 운영 DB나 실제 카톡 데이터를 사용하지 않았다. 보관 정리는 요약/항목 삭제를 커밋한 뒤 발송 큐 잠금을 잡도록 분리해 발송의 잠금 순서와 충돌하지 않게 했다.

합성 `demo_m4.py`: 메시지 3건 → 관심 주제 2개 → 모의 ntfy 수락 1회, 원문 근거 조회와 유용함 피드백 저장, 동일 요약 재발송 0회. 외부 API 네트워크 호출 0회. 기존 M3 demo도 완료했다. 페이지는 localhost:8004에서 실제 브라우저로 확인했고 CSS 화면 폭 375px에서 가로 넘침이 없었다. 검증 후 임시 기기/데이터를 제거하고 페이지 서버와 테스트 클러스터를 정상 종료했다.

보고서: `server/.state/m4-tests.xml`, `m4-demo.json`, `m4-demo.md`, `m4-browser.json`, `m4-phone.png`. `.state`는 Git에서 제외한다. 재현 도구와 채널 연결 계약은 [M4_DELIVERY.md](M4_DELIVERY.md)를 따른다.

**미검증:** 실제 본폰/운영 ntfy 수신, 공개 HTTPS/reverse proxy·Compose 실행, 실제 방→본폰 전 구간, 사용자 알림량·유용성 평가. M1 실제 방 수집률과 M3 외부 LLM·50개 주제 평가는 계속 대기다. ntfy API 수락을 본폰 수신으로 기록하지 않는다.

## 서버 0.4.0 / M3 — 2026-09-17 (최신)

기준 M2는 GitHub `fix/kakao-notification-format`의 `672092c`다. M3를 미리 구현하라는 사용자 요청에 따라 별도 브랜치에서 선행 개발했다. Android 소스/APK/실제 collector 설정은 변경하지 않았다.

| 검증 | 결과 |
|---|---|
| M3 코어 | 21개 통과: URL 의미 보존, 잡담/정정/정상 반복, 엄격한 출력, 주제별 근거, 프로필/입력 한도 |
| M3 실제 PostgreSQL | 28개 통과: 프로필 버전/경쟁, 개수/시간/배치 잔여 처리, 늦은 업로드, 배치 사이 정정 문맥, 기기/방 인증, 예산 경쟁/보류/다음 날짜, 3회 실패, lease 복구/이전 소유권 차단, 원자적 요약 저장, 진행 중 삭제/프로필 변경/권한 회수, 원문 만료, 실제 사용량 초과, 가격 없는 외부 공급자 차단 |
| 평가 도구 | 6개 통과: 50개 기준, 관심 재현율/후보 정밀도, 누락/미라벨/근거 미검토/불명확 분모 처리 |
| 기존 M2 PostgreSQL 회귀 | 11개 전부 통과 |
| 기존 수집 비교 도구 | 5개 전부 통과 |

서버 `pytest` 합계 66개/skip 0/failure 0, 마지막 실행 50.59초. 별도 native PostgreSQL 클러스터 localhost:55329/radar_m3_test만 사용했고 종료 후 정상 중지했다. 기존 M2 테스트 DB나 실제 카톡 데이터는 사용하지 않았다. 기존 고정된 FastAPI/Starlette 테스트 의존성의 deprecation 경고 2개가 있었고 실패는 없다. tzdata는 기존 lock의 2026.4를 직접 의존성으로 선언했다.

합성 실행 도구 `tools/demo_m3.py`도 완료했다. 5개 합성 메시지에서 정정/취소를 보존한 관심 후보 1개, 비관심 주제 1개, 광고 제외 주제 1개를 만들고 잡담을 제외했다. 문장별 근거 조회와 completed 상태를 확인했다. 외부 API 호출은 0회, 토큰은 기준선의 추정값, 비용 0이다. 실행 뒤 임시 기기/방/원문/요약을 제거하고 서버 .state에 합성 보고서만 남겼다.

이번 결과는 실제 LLM의 요약 품질이나 사용자의 관심 평가를 뜻하지 않는다. **외부 공급자/키/가격 연결, 실제 사용자 50개 주제 라벨, M1 실제 방 저장·수집률, M4 본폰 발송은 대기다.** Compose analysis 프로필은 제공했으나 Docker 실행은 미검증이다.

재현: server에서 `pip install -r requirements-dev.txt` 후 `python tools/run_local_tests.py --postgres-bin /path/to/pgsql/bin`. 클러스터·보고서는 Git 제외된 server/.state에 생성된다. 일반 `pytest -q`는 RADAR_TEST_DATABASE_URL이 없으면 DB 검사를 skip하므로 이를 전체 검증 성공으로 기록하지 않는다. [M3 실행/평가 계약](M3_ANALYSIS.md).

아래는 이전 Android/M2 검증 이력이다.

## v0.3.0 / M2 — 2026-09-17 (최신)

사용자 지시로 M1 실측을 대기하며 M2를 합성 데이터로 구현했다. 아래는 실제 카톡 수집률이 아닌 저장·동기화 검증 결과다.

| 검증 | 결과 |
|---|---|
| Android JVM/Robolectric | 43개 통과: capture→outbox, DB 1→2→3, 표시 제목 변경, 재전송 ID, 잘못된 ack, 120건 backlog, 과대 항목 |
| 실제 PostgreSQL API | 11개 통과: 인증, 허용 방, 동시 중복, 트랜잭션 롤백, 만료, 삭제/차단 |
| Python 비교 도구 | 5개 통과 |
| Redmi instrumentation | 4개 통과: 본체 스키마/집계, 저장소, Keystore 토큰, 합성 HTTPS 응답 유실/재전송 |
| lintDebug | 오류 0 / 경고 15 |
| assembleDebug / assembleDebugAndroidTest | 통과 |

- 최종 versionCode=3/versionName=0.3.0을 기존 데이터 유지 방식으로 Redmi에 설치하고 MainActivity `Status: ok` 확인.
- 합성 메시지 2건은 HTTPS 서버 커밋 후 응답 유실을 재현하고 단말 DB 재열기 후 duplicate로 모두 완료. 다른 방 합성 항목 1건은 미전송 pending으로 보존. 서버 원문은 2건만 유지.
- 전용 테스트 PostgreSQL의 갑작스러운 종료/재시작 후에도 커밋한 합성 2건 보존.
- 실제 collector는 schema 3, 대상 미선택, capture/sync=false, 원문 저장 0건. 이전 진단 44회 유지.
- 실제 collector 설정에 테스트 토큰/방을 쓰지 않았고 테스트 CA는 테스트 transport만 신뢰했다. DB 원문을 PC로 복사하지 않고 단말 내부에서 집계했다.
- 경고 15개는 SharedPreferences commit, 고정 라이브러리/KAPT, deprecated insets, 번역 리소스 관련이다. 설정 저장 시점을 보장하는 commit과 기존 의존성 버전을 유지했다.
- APK SHA-256: `511dd93189b2d3186e0b46ab802aa744fa6a90939863540b1d52d97fa72923fe`. 0.3.0에는 INTERNET/ACCESS_NETWORK_STATE 권한이 있고 서버 설정 전에는 전송하지 않는다.
- 미검증: 실제 대상 방 신규 저장/500건 수집률, 재부팅/화면 꺼짐 WorkManager, WAN/TLS 운영, Compose 실행, 배터리, M3/M4.

[실행·삭제·재검증 안내](M2_SYNC.md). 아래는 이전 버전의 검증 이력이다.

검증일: 2026-09-16

- APK: debug 서명, 버전 0.1.0, applicationId `dev.kakaoradar.collector`, min SDK 28 / target SDK 35.
- `assembleDebug`: 통과.
- `testDebugUnitTest`: 21개 통과. 메시지 창 비교, Robolectric Android 15 그룹/개인/타 앱 필터, Room 재시작·트랜잭션 롤백, 수집 시작·중지·방 구분·내보내기, Activity 시작을 검증했다.
- Python 표본 비교 도구: 5개 테스트 통과.
- `lintDebug`: 오류 0개, 경고 11개. 세부 보고서는 Android 빌드 reports 폴더에 생성된다.
- APK 서명 검증 통과, INTERNET 권한 없음 확인.
- Gradle 8.9 wrapper 생성, 배포 ZIP SHA-256 검증값 고정.

후속 설치 검증: 사용자가 USB로 연결한 Redmi Note 14 5G(ADB 모델 24094RAD4G)에 APK 설치 성공. `am start -W`로 MainActivity를 실행해 `Status: ok`를 확인했고 앱 프로세스가 실행 중임을 확인했다. 알림 접근 권한 부여·대상 방 선택·실제 카카오톡 파싱·야간 수집·배터리·수집률·실기기 instrumentation 테스트는 아직 수행하지 않았다. 설치·자동 검사 통과는 실측 수집률을 보장하지 않는다.

서버 동기화, AI 요약, 본폰 알림은 M2 이후 범위로 아직 구현하지 않았다. [실기기 검증 안내](DEVICE_TEST.md)에 따라 M1을 검증한 뒤 진행한다.

APK SHA-256: `43646499049119e0974e2ddc1fa9bd492ad5b8ac7c7b2104484c9a2bd15341b8`


## 실기기 첫 사용 결과 — 2026-09-16

사용자 export에서 `unsupported_kakao_callbacks`가 반복 증가했고 `selected_callbacks` 및 message record는 관찰되지 않았다. Kakao package callback 자체가 CollectorService까지 도달했으므로 알림 접근/Listener 전체 실패로 보지 않는다. 현재 parser가 `MessagingStyle + conversationTitle + isGroupConversation`을 모두 요구하는 부분이 실제 KakaoTalk notification representation과 맞지 않는 것이 최우선 원인 후보다.

이 결과로 기존 자동 테스트의 범위도 명확해졌다. 21개 unit test 통과는 앱이 생성한 MessagingStyle fixture와 저장 로직을 검증했을 뿐, 실제 KakaoTalk notification 형식 호환성을 검증한 것이 아니다. M1 완료 조건은 parser failure reason 분리, standard-extras fallback, privacy-safe structure diagnostic, room identity 안정성 확인 후 다시 평가한다.

## v0.2.0 — 2026-09-17

assembleDebug, testDebugUnitTest(33개), lintDebug(오류 0/경고 11), assembleDebugAndroidTest 통과. Python 5개 통과. Redmi 실제 단말 instrumentation 2개 통과. 기존 데이터 유지 업데이트와 schema 1→2 전환을 확인했다. 실제 기존 알림 4개 중 방 알림 3개 해석/방 3개 발견, summary 1개 제외, 처리 오류 0회. 대상 방 미선택 상태라 저장은 0건이고 신규 원문 저장·수집률·야간 지속성은 미검증이다. 상세 수치와 남은 작업은 DEBUG_NOTES의 2026-09-17 기록을 따른다.

원문 복사 없는 단말 진단: 테스트 APK 설치 후 `adb shell am instrument -w -e class dev.kakaoradar.collector.DeviceDiagnosticsTest dev.kakaoradar.collector.test/androidx.test.runner.AndroidJUnitRunner`. 실제 DB를 삭제하지 않으며 집계와 HMAC 식별자만 출력한다.

최종 APK 서명 검증 통과, INTERNET 권한 없음. 설치된 versionCode=2 / versionName=0.2.0, MainActivity `Status: ok`. APK SHA-256: `5ab0620e1d83c8a0b7cf09bbbfd29df8bf71e2e2c5f497c812eba770dc133626`.
