# Kakao Radar v1.0.0 — 2026-09-18

개인용 수집·분석·Telegram 전달 구현을 master로 통합한 릴리스다. Android versionCode 5 / versionName 1.0.0, 서버 1.0.0, DB schema 5다. Android 로컬 DB schema 3과 HTTPS 업로드 계약은 유지한다.

## 포함한 구현

- M1/M2: 보수적 Kakao 알림 parser, 대상 방 선택, 원문·가명·시각·URL 저장, Room 전송 큐, HTTPS 인증 및 멱등 업로드.
- M3: 버전별 관심 프로필, 주제 묶기, 문장별 근거·URL 검사, 작업 lease·복구, 일일 토큰·비용 예약 및 OpenAI 공급자.
- M4: Telegram/ntfy 정기 요약, 조용한 시간·quota·복구 가능한 outbox, 근거 조회·피드백 계약, 실제 대사와 시각 표시.
- WSL/M5: Ubuntu/PostgreSQL 운영 도구, 로컬 TLS와 USB reverse, 긴급 후보 기본 비활성, 단계별 지연 집계.
- 9/18 개선: 방별 전달 진도와 원문 ID·내용 receipt로 새 대화 구간을 이어서 보고하고 과거 후보 회귀를 억제한다. Telegram bold entities·emoji·literal 원문 인용을 지원한다.
- 최신 운영 변경: 오늘 테스트는 매시 정각 1시간 / 최대 3개 주제, 다음 날 자정에 기존 23:00 / 하루 1회 / 최대 5개 주제로 자동 복귀한다. 오늘 기존 quota·원문 인용·중복 억제·AI $1/day를 유지한다.

GitHub 기존 main, fix/kakao-notification-format, feat/m4-delivery, feat/wsl-runtime의 커밋과 로컬 feat/m3-interest-summary의 진단 기록을 포함한다. 동일 내용의 M3 baseline 두 커밋을 통합하면서 최신 WSL 기능 코드가 보존되는지 확인했다. 기존 브랜치나 기록은 삭제하지 않는다.

## 확인한 운영과 남은 검증

실제 선택 방 업로드, OpenAI 분석, 사용자 보고를 통한 Telegram 수신을 확인했다. 최신 1시간 시간표는 운영 DB에 적용하고 24개 슬롯, 다음 시각, 자정 복귀 및 기존 quota를 확인했다. 설정 변경 확인은 신규 메시지의 성공 수신이나 화면 OFF 지연 해결 시험이 아니다.

수집률, 재부팅·야간 지속성, 사용자 50주제 품질 평가, 본폰 표시 시각 실측은 남는다. 현재 WSL/노트북과 USB reverse가 필요하고 외부 웹 근거 링크는 비활성이다. 설치된 폰 버전은 이번 릴리스 표시만으로 업데이트하지 않는다. 주기적 KakaoTalk 깨우기는 사용자 지시로 보류했다.

검증 실행 결과와 빌드 범위는 [VALIDATION.md](VALIDATION.md)에 별도로 기록한다. 운영·rollback 절차는 [WSL_RUNTIME.md](WSL_RUNTIME.md)를 따른다.
