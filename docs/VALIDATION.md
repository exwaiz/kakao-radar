# M1 검증 결과

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
