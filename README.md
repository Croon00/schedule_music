# schedule_music

## Current Usage: X 분류, Discord 라우팅, Google Calendar

이 섹션이 현재 구현 기준의 사용법입니다. 아래쪽의 오래된 MVP 설명보다 이 섹션을 우선해서 보면 됩니다.

현재 흐름:

```text
Discord에서 아티스트/X 계정 등록
-> agent가 X 새 게시글 수집
-> source_items로 중복 제거
-> LangGraph workflow에서 글 타입 분류
-> live_event/ticket이면 일정 정보 추출
-> 개인 Google Calendar에 일정 생성
-> Discord route 설정에 맞는 서버 채널로 알림 전송
```

### 글 타입

```text
notice      일반 공지, 방송, 안내
release     음원, 앨범, MV 공개
live_event  라이브, 공연, 페스, 출연
ticket      티켓, 선행, 일반판매, 추첨, 응모, 마감
merch       굿즈, 상품, 예약판매, 특전
irrelevant  알림이 필요 없는 글
```

### Discord 알림 route

Discord 채널 알림은 서버별로 저장됩니다.

```text
guild_id + source_id + item_type -> discord_channel_id
```

즉 같은 RKMusic X 계정이라도 서버마다 다른 채널로 보낼 수 있습니다.

```text
A 서버: RKMusic notice -> #rk공지
B 서버: RKMusic notice -> #jpop-news
```

### Google Calendar 연동

Google Calendar는 서버 공용이 아니라 Discord 사용자별 개인 OAuth 연결입니다.

현재 동작은 다음 기준입니다.

```text
사용자 A가 /google_connect 완료
사용자 A가 /artist_add로 X 계정 등록
agent가 해당 X 계정에서 live_event/ticket 감지
-> 사용자 A의 Google Calendar에 일정 생성
```

서버 채널 알림은 여러 서버 route로 보낼 수 있지만, 캘린더는 각 사용자가 자기 Google 계정을 직접 연결해야 합니다.

여러 사람이 같은 소스를 구독해서 각자 캘린더에 넣는 구조는 아직 별도 구독 테이블이 필요합니다.

### Discord 명령어

아티스트/X 계정 등록:

```text
/artist_add name:RKMusic x_username:RKMusic_inc
/artist_add name:KAMITSUBAKI x_username:kamitsubaki_jp
```

등록 목록:

```text
/artist_list
```

라우팅에 사용할 source id 확인:

```text
/source_list
```

Discord 채널 route 설정:

```text
/route_add source_id:3 item_type:notice channel:#공지
/route_add source_id:3 item_type:release channel:#릴리즈
/route_add source_id:3 item_type:live_event channel:#라이브
/route_add source_id:3 item_type:ticket channel:#티켓
/route_add source_id:3 item_type:merch channel:#굿즈
```

`source_id`를 비우면 해당 서버의 전체 기본 route로 저장됩니다.

```text
/route_add item_type:notice channel:#전체공지
```

route 확인/삭제/테스트:

```text
/route_list
/route_list source_id:3
/route_delete route_id:5
/route_test route_id:5
```

개인 Google Calendar 연결:

```text
/google_connect
```

### 환경변수

필수/주요 설정:

```text
DATABASE_URL=postgresql://...
DATABASE_AUTO_INIT=true

DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=

X_BEARER_TOKEN=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini

AGENT_ENABLED=true
AGENT_RUN_ON_START=true
AGENT_INTERVAL_SECONDS=600

PUBLIC_BASE_URL=https://your-app.example.com
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://your-app.example.com/auth/google/callback
GOOGLE_CALENDAR_ID=primary
```

### 실행

API만 실행:

```powershell
uvicorn app.api.main:app --reload
```

API, Discord 봇, agent loop 함께 실행:

```powershell
python -m app.runtime
```

### LangGraph 사용 위치

LangGraph는 X 수집 자체가 아니라, 수집된 게시글 하나를 어떻게 처리할지 결정하는 workflow에 사용합니다.

```text
START
-> classify_item
-> live_event/ticket이면 extract_event
-> END
```

구현 위치:

```text
app/agents/music_graph.py
```

`langgraph`가 설치되어 있으면 실제 LangGraph workflow로 실행하고, 설치되어 있지 않아도 같은 node 순서로 fallback 실행합니다.

### 주의사항

- X 게시글 수집은 실시간 push가 아니라 agent 주기 실행입니다.
- `AGENT_INTERVAL_SECONDS`가 짧을수록 더 자주 확인하지만 X API 제한을 더 빨리 씁니다.
- route가 없으면 Discord 알림은 보내지 않습니다.
- 봇이 Discord에 로그인되어 있지 않으면 agent가 알림 전송을 건너뜁니다.
- Google Calendar는 사용자별 연결입니다.
- 자동 구매, 자동 응모, CAPTCHA 우회, 결제 자동화는 구현하지 않습니다.

JPOP 아티스트의 공연, 티켓, 이벤트 일정을 수집하고 관리하기 위한 MVP 백엔드입니다.

현재 버전은 아티스트, X 계정, 공식 사이트, 티켓 사이트 같은 출처를 저장하고,
나중에 Google Calendar 또는 Naver Calendar로 동기화할 수 있는 일정 후보를 관리합니다.

## 현재 목표

처음부터 큰 웹 서비스를 만드는 것이 아니라, 아래 흐름을 작게 검증하는 것이 목표입니다.

1. 관심 있는 아티스트를 등록합니다.
2. 아티스트별 X 계정 또는 공식 출처를 저장합니다.
3. 수집된 일정 후보를 저장합니다.
4. 사람이 후보를 확인한 뒤 캘린더 동기화 대상으로 사용할 수 있게 만듭니다.

## 웹 화면이 꼭 필요한가?

필수는 아닙니다.

현재 백엔드는 FastAPI로 만들어져 있어서 `/docs` 화면만으로도 아티스트와 출처를 등록할 수 있습니다.
나중에 사용성이 필요해지면 웹 관리자 화면을 추가할 수 있습니다.

대신 Discord 봇을 붙이면 웹 화면 없이도 `!` 명령어로 관리할 수 있습니다.

예시:

```text
!artist add YOASOBI @YOASOBI_staff
!artist list
!source add 1 official_site https://example.com/news
!events
```

## AI가 필요한가?

첫 MVP에는 꼭 필요하지 않습니다.

- 먼저 AI 없이 아티스트 출처를 저장합니다.
- 날짜, 장소, 티켓 오픈 시간처럼 명확한 텍스트는 규칙 기반으로 파싱합니다.
- 일본어 공지 문장이 복잡하거나 이미지 공지가 많아지면 AI 또는 OCR을 추가합니다.
- 캘린더 동기화 자체는 AI가 아니라 Google/Naver API 인증 정보가 필요합니다.

## DB는 무엇을 쓰나?

현재는 SQLite를 사용합니다.

SQLite는 별도 DB 서버가 필요 없고, `.db` 파일 하나로 동작하므로 MVP와 개인용 봇에 적합합니다.
나중에 여러 서버, 여러 유저, 상시 운영 규모가 커지면 PostgreSQL로 옮기는 것을 고려합니다.

MongoDB는 X 원문, OCR 결과, 크롤링 로그처럼 비정형 데이터를 많이 저장해야 할 때 검토하면 됩니다.
지금처럼 아티스트, 출처, 일정 후보처럼 관계가 명확한 데이터는 SQLite/PostgreSQL 쪽이 더 잘 맞습니다.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

실행 후 아래 주소를 엽니다.

- API 문서: http://127.0.0.1:8000/docs
- 헬스 체크: http://127.0.0.1:8000/health

## X 계정이 있는 아티스트 추가

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/artists `
  -ContentType "application/json" `
  -Body '{"name":"YOASOBI","x_username":"@YOASOBI_staff"}'
```

`x_username`은 `@YOASOBI_staff`와 `YOASOBI_staff` 둘 다 허용합니다.
저장할 때는 앞의 `@`를 제거해서 보관합니다.

## 추가 출처 등록

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/artists/1/sources `
  -ContentType "application/json" `
  -Body '{"source_type":"official_site","label":"공식 뉴스","value":"https://example.com/news"}'
```

사용 가능한 `source_type` 값:

- `x`
- `official_site`
- `ticket_site`
- `rss`
- `other`

## 현재 API

- `POST /artists`: 아티스트 등록
- `GET /artists`: 아티스트 목록 조회
- `GET /artists/{artist_id}`: 아티스트 상세 조회
- `PATCH /artists/{artist_id}`: 아티스트 수정
- `DELETE /artists/{artist_id}`: 아티스트 삭제
- `POST /artists/{artist_id}/sources`: 아티스트 출처 추가
- `GET /artists/{artist_id}/sources`: 아티스트 출처 목록 조회
- `DELETE /artists/{artist_id}/sources/{source_id}`: 아티스트 출처 삭제
- `POST /event-candidates`: 일정 후보 등록
- `GET /event-candidates`: 일정 후보 목록 조회

## 다음 작업

1. Discord 봇 명령어 추가
2. Discord 서버별 또는 유저별 데이터 저장 구조 추가
3. 등록된 X 출처를 주기적으로 확인하는 agent 추가
4. 일본어 날짜/티켓 문구 파서 추가
5. Google Calendar OAuth와 일정 생성 기능 추가
6. 필요하면 Naver Calendar 동기화 추가
7. 규칙 기반 파싱이 어려운 공지에만 AI 추출 기능 추가
