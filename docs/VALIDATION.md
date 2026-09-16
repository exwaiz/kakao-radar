# M1 검증 결과

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
