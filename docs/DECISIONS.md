# Kakao Radar — Decision Log

이 문서는 프로젝트에서 이미 합의했거나 실기기 결과로 확정된 결정을 기록한다. 새 Codex 세션은 장문의 과거 대화보다 이 문서와 `AGENTS.md`를 우선한다.

## D-016 — 전달 진도·원문 중복·Telegram 서식 개선 (2026-09-18)

- 사용자 피드백: 실제 대사 인용은 유용하다. 한번 보낸 이야기 재등장과 오늘 아침 이후 어젯밤으로 돌아가는 보고는 개선한다. 변경 전 작업을 먼저 커밋한다. canonical 원격 보존 커밋 `2bf1788bc0f7c44fe758326ddd53c25afc426644`, `feat/wsl-runtime`. 로컬 보존 커밋 `b120b97`의 동일 변경을 connector로 게시했다. 기존 브랜치 생성/갱신은 자동 승인 검토에서 이력 덮어쓰기 우려로 거절되어, 읽기 전용 원격 조회로 해당 브랜치가 없음을 입증한 뒤 새 브랜치를 만들었다. force push는 사용하지 않았다.
- 서버 0.6.1/schema 5: 기기·방별 `delivery_progress.observed_through`는 원문 **알림 수집 observed_at**의 단조 증가 상한이다. 분석 생성 시각이나 Telegram 발송 시각으로 대화 진도를 추정하지 않는다. 기존 sending/accepted/uncertain 이력의 가장 최신 원문 관찰값으로 최초 이관하며 버전 5에서 한번만 seed한다.
- 각 요점의 모든 근거가 동일 기기/방의 live 원문이고 진도 이후이며, 이미 전달한 ID 또는 정확히 동일한 원문 내용 SHA-256에 해당하지 않아야 한다. 새/옛 근거가 섞인 요점은 재작성 없이 제외한다. 다른 제목의 동일 근거, 새 알림 ID의 동일 원문, 동일 묶음의 겹치는 근거도 억제한다. 다른 원문으로 반복된 모든 비슷한 주장을 판별하는 semantic dedup은 보장하지 않는다.
- 새 구간 안에서 중요도/관심도로 주제를 선정한 뒤 원문 시각순으로 표시한다. accepted/uncertain 및 중단된 미확정 발송은 해당 방의 완료된 분석 구간 상한을 함께 저장한다. 구간 내 탈락한 낮은 순위의 후보나 뒤늦게 분석된 과거 원문은 정기 보고에 이월하지 않는다. 아카이브 원문/요약은 삭제하지 않는다. 연결 실패/확정 거절/취소는 진도를 소비하지 않는다. 명시 수동 재발송은 기존 중복 위험 승인 계약을 유지한다.
- 진도는 outbox/요약 만료에도 남는다. 원문 ID/내용 해시 receipt는 90일, 방/기기 삭제 시 진도·receipt도 정리한다. 닉네임/원문 사본은 새 ledger에 저장하지 않는다. delivery 워커 중지 후 이관 도구로 legacy 미발송 큐만 취소한다.
- Telegram 제목/첫 요점은 명시 bold entity로 표시한다. UTF-16 offset/length를 계산하며 원문 HTML/Markdown은 파싱하지 않는다. 실제 인용은 재작성하지 않고 표시 가능한 정확한 prefix를 유지한다. [MessageEntity 계약](https://core.telegram.org/bots/api#messageentity). 3/5/10 주제와 emoji/surrogate 경계 및 4,000 UTF-16 단위 한도를 테스트했다.
- 오늘 10분/3개/144회, 9/19 자정 정상 23:00/1회/5개 복귀, 인용 유지, AI $1/day, urgent off는 유지한다. 서비스 변경/서식 테스트 안내 1건은 공통 일일 quota와 DB 이력 `service_update`로 기록하고 Telegram API 수락을 확인했다. 이는 새 방 요약이나 본폰 표시 latency 확인이 아니다.

## D-015 — 오늘 30분 테스트 및 실제 대사 인용 (2026-09-18)

후속 사용자 요청: 유용성 판단을 위해 오늘 더 많이 보내도록 한다. 오늘 10분마다 최대 3개 주제/상한 144회로 변경한다. 자동 복귀 때 시간표·상한과 최대 주제 수 5도 복구한다. Telegram 실제 수신은 사용자 보고로 확인됐고 정확한 단말 표시 latency는 미측정이다.

- 사용자 후속 지시: 오늘 하루 1회 제한 대신 30분마다 요약하고 실제 대사 인용을 추가한다. 9/18 매시 00·30분, 테스트 상한 48회, 9/19 자정에 23:00/하루 1회 자동 복귀. 인용은 복귀 뒤에도 유지한다. 빈 후보/동일 내용 재발송은 하지 않으며 AI 일일 $1 예산은 유지한다.
- 인용은 발송 시 scope가 맞는 live 메시지를 그대로 발췌한다. AI가 새 대사를 만들지 않는다. 최대 2개/주제, 80자/인용, 뒤 생략 표시, 닉네임 별도 복제 없음. 로컬 영구 요약/outbox에 quote 원문을 추가 저장하지 않는다.
- 실제 검증 발송의 주제 5개/인용 5개 Telegram API 수락을 확인했다. 본폰 표시/열람은 별도다.

## D-014 — 실제 WSL·OpenAI·Telegram 통합 (2026-09-17)

- **사용자 명시 승인.** 실제 수집을 M1 잠정 성공으로 인정하고 제목 parser 보완을 미룬다. M2→M5는 노트북 WSL에서 통합한다. 이전 공급자·채널 미확정 상태를 대체한다.
- 새 OpenAI 키를 기존 계정에서 생성하여 승인된 로컬 파일에 저장한다. `gpt-4.1-mini` Responses, store false, 하루 $1 예약/정산. 지정 관심사와 관찰된 웃음 문맥을 반영하며 반응 버튼 수/전체 합의는 추정하지 않는다.
- 기존 Telegram 봇의 검증된 본인 개인 채팅, Asia/Seoul 23:00, 하루 1회, urgent off. 수동 설정 검증 1건도 공통 quota·중복·quiet 정책을 거치며 다음 정기 슬롯을 유지한다. API 수락은 본폰 표시/열람을 뜻하지 않는다.
- 공개 터널은 자동 승인 검토가 공개 범위/민감 데이터 전송 명시 승인 부족으로 거절했다. 로컬 HTTPS + USB reverse로 운영하며 외부 웹 링크는 비활성이다. debug localhost CA만 명시적으로 신뢰하고 hostname 검증은 유지한다.
- native PostgreSQL 16·전용 peer 서비스 계정·별도 테스트 DB·systemd를 사용한다. 초기 디스크 부족 때 작업 생성물만 정리했다. 외부 서버 uptime·수집률·사용자 품질 평가는 미검증이다.

## D-013 — M4 선행 구현과 실제 채널 연결 분리 (2026-09-17)

- 상태: **사용자 명시 요청, 선행 구현**. 새 Thread에서 M4를 요청했으며 M3 `0a750c0`에서 별도 브랜치를 만든다. D-003/D-012의 단계 범위를 이번 M4 개발로 확장한다. M1/M3 실측 대기를 성공으로 바꾸지 않는다.
- 최신 활성 관심 프로필의 후보를 정기 시간표로 준비한다. 기기별 PostgreSQL 영속 큐, 조용한 시간과 하루 시도 상한, 동일 요약/내용 중복 억제, 유용함/관심 없음 피드백과 근거 조회 페이지를 추가한다.
- 채널 응답이 없는 개발 단계의 기본 어댑터는 ntfy다. 사용자 운영 채널·시간·본폰 OS는 미확정이며 기본 발송/시간표/상한은 비활성이다. 실제 외부 메시지는 보내지 않고 합성 모의 응답으로 검증한다.
- ntfy 수락은 실제 본폰 수신이 아니다. 연결 시작 실패/429만 제한 자동 재시도하며 응답 유실·5xx·Worker 중단은 uncertain으로 남긴다. 수동 재발송은 중복 위험 명시 승인과 기존 시도 상한을 유지한다.
- 시도 수를 기기 잠금 아래 호출 전에 예약하고 결과 불명확·방 삭제로 환불하지 않는다. 이전 소유권의 늦은 응답을 저장하지 않는다. 모든 재시도는 최신 설정/프로필·권한·시간·상한을 다시 검사한다.
- 본폰 링크는 묶음 한 개의 조회/피드백에 한정된 HMAC 키로 인증한다. 기기 토큰을 채널/링크에 넣지 않는다. 방 삭제는 저장된 발송 사본과 링크를 지우되 외부 채널 사본/진행 중 호출을 취소한다고 표현하지 않는다.
- 상세 실행·API·보관·완료 판단은 M4_DELIVERY.md를 따른다. 실제 채널·운영 HTTPS·본폰 수신·사용자 알림량/유용성 평가는 별도 대기다.

## D-012 — M3 선행 구현과 외부 AI 분리 (2026-09-17)

- 상태: **사용자 명시 요청, 선행 구현**. D-003/D-011의 순서 제한을 이번 M3 범위에서 변경한다. 사용자가 다른 세션에서 커밋한 M2 `672092c`를 GitHub에서 가져와 기준으로 사용한다.
- Android/M2 전송 계약을 유지하고 서버에 버전 프로필, 주제·근거 요약, 분석 작업, 사용량 예약, 조회와 평가를 추가한다. M4 발송은 확장하지 않는다.
- 기본 프로필과 Worker는 비활성이다. 사용자 관심사/예산/모델을 임의로 채우지 않는다. 외부 호출 없는 추출형 기준선과 공급자 인터페이스를 제공한다. 기준선 토큰은 추정값이며 유료 AI 사용량이나 개인화 평가로 표현하지 않는다.
- 대상 event_id의 처리 기록과 방 잠금·lease·owner_token으로 재시도와 이전 Worker의 늦은 저장을 막는다. 작은 작업으로 나눈 배치의 잔여 항목은 같은 cutoff를 따라 계속 처리한다. 최근 완료 원문 3개를 제한된 문맥으로 사용해 다음 배치의 짧은 정정을 보존한다.
- 일일 토큰/정수 micro-USD 비용을 호출 전 예약한다. 불명확한 과금은 예약을 유지한다. 방 삭제/프로필 변경도 진행 중 호출의 예약을 환불하지 않는다.
- 자동 검사는 참조/형식 무결성이다. 주장 의미와 개인화 품질은 사용자 라벨 평가가 필요하다. 외부 AI 자격 증명 결정·모델/가격 설정·50개 주제 평가는 아직 대기다. 자세한 계약은 M3_ANALYSIS.md에 기록한다.

## D-010 — KakaoTalk 26.8.0의 제목 누락 대응 (2026-09-17)

- 상태: **실제 필드 확인, v0.2.0 구현**. 실행 검증 수치는 DEBUG_NOTES의 최신 기록을 따른다.
- 연결된 Redmi / Android 15에서 그룹 child 알림 3개와 묶음 summary 1개를 관찰했다. child에는 MessagingStyle, messages, 명시적 group=true, shortcutId, android.title이 있으나 conversationTitle이 없었다. 기존 parser의 제목 필수 조건이 탈락 원인이다.
- conversationTitle이 없을 때는 명시적 group=true와 비어 있지 않은 shortcutId가 모두 있어야 android.title을 방 이름으로 사용한다. 알림 제목만으로 그룹이나 방을 추정하지 않는다.
- MessagingStyle → EXTRA_MESSAGES → EXTRA_TEXT 순으로 복구한다. EXTRA_MESSAGES 직접 복구 API는 Android 11 이상에서만 사용하며 9/10에서 해당 경로가 필요하면 별도 미지원 사유로 기록한다.
- EXTRA_TEXT만 있는 경우 발신자·원본 시각은 추측하지 않는다. quality=fallback_no_message_time으로 구분한다.
- shortcutId와 정확한 제목을 함께 비교하며 key 변경은 허용한다. shortcutId 없는 기존 바인딩은 key가 같아야 한다. 동일 제목 충돌 시 식별자가 없는 방의 저장은 보류한다. 재부팅 후 ID 안정성은 별도 검증 대상이다.
- 구조 진단은 원문·방 이름·닉네임 없이 알려진 필드, 개수, HMAC만 저장한다. 최근 100개/72시간 한도이며 앱 실행·알림 처리 시 정리한다.
- schema 1→2는 진단 테이블만 추가한다. 기존 메시지/진단을 지우지 않는다. 기존 알림 조회는 discovery, 새 callback은 live 카운터로 분리한다.
- 서버/AI 범위는 확장하지 않는다.

## D-001 — 실시간 수집, 배치 분석

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: 카카오톡 알림은 도착 시 로컬에 즉시 저장한다. AI 분석과 본폰 알림은 서버에서 배치 또는 조건 기반으로 수행한다.
- 이유: 수집과 분석을 분리하면 서브폰의 배터리·발열 부담을 낮추고, AI 모델·프롬프트·주기를 서버에서 교체하기 쉽다.
- 결과: Android 앱은 수집기 역할에 집중한다. 온디바이스 LLM은 MVP 범위 밖이다.

## D-002 — 공식 카카오 대화 조회 API에 의존하지 않음

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: 기존 일반 오픈채팅방의 전체 대화를 공식 API로 조회할 수 있다고 가정하지 않는다. Android `NotificationListenerService`를 M1의 주 수집 경로로 검증한다.
- 결과: 알림에 노출되지 않은 메시지의 복구는 보장하지 않는다. 전체 아카이브 제품으로 표현하지 않는다.

## D-003 — M1 실기기 검증 전 서버/AI 확장 금지

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: Redmi Note 14 5G / Android 15에서 실제 KakaoTalk notification format과 room identity가 검증되기 전에는 M2 서버·M3 AI 구현을 본격 진행하지 않는다.
- 이유: 수집 경로가 틀리면 이후 파이프라인 전체가 의미가 없다.

## D-004 — 현재 MessagingStyle-only parser는 실기기에서 실패

- 상태: **실기기 확인**
- 결정일: 2026-09-16
- 근거: 사용자 실기기 export에서 `unsupported_kakao_callbacks`만 반복 기록되고 `selected_callbacks` 및 저장 메시지가 발생하지 않았다. Listener callback 자체는 발생했다.
- 해석: Notification access·Listener 생존이 1차 병목이 아니다. 현재 `NotificationParser.parse()`의 엄격한 조건이 KakaoTalk 실제 notification representation과 맞지 않는 것이 현재 최우선 가설이다.
- 현재 parser의 필수 조건:
  1. `FLAG_GROUP_SUMMARY`가 아님
  2. `NotificationCompat.MessagingStyle` 추출 성공
  3. `conversationTitle` 존재
  4. `isGroupConversation == true`
- 후속 결정: parser는 실패 원인을 구조화해 반환하고, 실기기 notification metadata를 개인정보 원문 없이 진단할 수 있어야 한다.

## D-005 — parser는 다단계 전략으로 재설계

- 상태: **다음 구현 방향 확정**
- 결정일: 2026-09-16
- 우선순위:
  1. `MessagingStyle`
  2. `EXTRA_MESSAGES`
  3. 표준 extras (`EXTRA_TITLE`, `EXTRA_TEXT`, `EXTRA_SUB_TEXT`, `EXTRA_SUMMARY_TEXT`)
- 주의: fallback은 개인 대화나 다른 방을 대상 오픈채팅으로 오인하지 않도록 보수적으로 설계한다.
- 실제 필드 매핑은 추측으로 확정하지 않고 실기기 diagnostic 결과를 source of truth로 삼는다.

## D-006 — unsupported는 하나의 숫자로 뭉개지 않음

- 상태: **다음 구현 방향 확정**
- 결정일: 2026-09-16
- 결정: `ParsedNotification?` 형태의 성공/null API를 `ParseResult` 계열로 바꾸고 실패 원인을 구분한다.
- 최소 진단 범주 후보:
  - group summary
  - no MessagingStyle
  - no conversation title
  - not group conversation
  - no title
  - no text
  - unknown
- UI/진단은 최소 다음 단계를 별도 집계한다.
  - Kakao callbacks
  - parsed callbacks
  - unsupported callbacks by reason
  - selected-room callbacks
  - saved messages
  - suppressed duplicates

## D-007 — 진단 metadata에 채팅 원문을 넣지 않음

- 상태: **확정**
- 결정일: 2026-09-16
- 저장 가능한 구조 정보 예:
  - extras key names
  - title/text/subText/summary/messages 존재 여부
  - messages count
  - MessagingStyle 감지 여부
  - group summary 여부
  - shortcutId 존재 여부
  - tag 존재 여부
  - 필요한 경우 안정성 확인용 해시
- 실제 메시지·닉네임·방 제목은 일반 diagnostic에 복제하지 않는다.

## D-008 — room identity는 notification key 하나에 의존하지 않음

- 상태: **설계 결정, 실기기 검증 필요**
- 결정일: 2026-09-16
- 문제: 현재 `RoomCandidate.matches()`는 shortcut이 없으면 동일 title이어도 `sbn.key`가 바뀌면 다른 방으로 본다.
- 목표 우선순위:
  1. 실제 Kakao chat/channel 식별자, 존재하고 안정적일 때
  2. `shortcutId`
  3. 안정적인 tag/식별 정보
  4. 단일 대상방 MVP에서 검증된 exact room title fallback
- 동일 제목 방 충돌 가능성은 명시적으로 탐지·경고한다.

## D-009 — Codex 작업 방식

- 상태: **확정**
- 결정일: 2026-09-16
- 결정: 장기 지식은 repo Markdown에 저장하고, Codex 채팅은 기능/버그 단위로 나눈다.
- 같은 버그의 수정→빌드→로그 확인은 같은 세션에서 이어간다. 하나의 milestone이 끝나면 문서를 갱신하고 다음 milestone은 새 세션으로 시작한다.
- `AGENTS.md`는 지도 역할만 하며 상세 이력은 이 문서와 `DEBUG_NOTES.md`에 둔다.

## D-011 — M1 실측 대기 중 M2 합성 개발 (2026-09-17)

- 상태: **사용자 명시 승인, 구현·합성 검증**. D-003과 D-010의 개발 선행 제한을 이번 요청 범위에서 변경한다. 실제 수집 검증을 완료한 것으로 처리하지 않는다.
- 단일 localhost FastAPI/PostgreSQL과 Android WorkManager로 M2를 개발한다. 보관 기본값은 원문 7일, 원문 없는 receipt 30일, 로컬 미전송 50,000항목이다. 운영 서버·관심 프로필·AI 예산·본폰 채널은 미확정이다.
- 실제 관찰에서 동일 key/shortcut 해시는 유지됐으나 제목 해시가 여러 callback에 걸쳐 달랐다. shortcut이 있으면 제목은 선택용 표시값으로만 사용한다. 같은 shortcut은 제목/key 변화에도 같은 방이다. shortcut이 없으면 기존 보수적 제목+key 조건을 유지한다. 이는 D-010의 제목 필수 비교를 대체한다. 재부팅 뒤 ID 안정성은 미검증이다.
- 기존 후보 목록은 shortcut 기준으로 중복을 제거한다. 같은 제목·다른 shortcut은 서로 다른 방이다.
- 전송은 기본 꺼짐이며 HTTPS 서버·기기·대상 room_id·토큰 설정 이후 활성화한다. 기기 토큰은 Keystore AES-GCM, 서버에는 SHA-256 digest로 저장한다. 방별 허용 목록이 별도로 필요하다.
- 전송 event_id 멱등 처리와 알림 재노출 억제는 분리한다. accepted/duplicate만 sent, 항목별 rejected는 보존한다. 오류 원문은 진단에 넣지 않는다.
- 단말 시험은 별도 DB와 임시 테스트 CA를 사용한 합성 데이터만 전송한다. 실제 collector의 대상/서버 설정을 바꾸지 않는다. 상세 운영/삭제/복구 계약은 M2_SYNC.md에 둔다.
