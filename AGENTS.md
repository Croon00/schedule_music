# schedule_music Agent Guide

이 문서는 `schedule_music` 프로젝트를 LangGraph 기반 알림/일정 자동화 봇으로 확장하기 위한 작업 지침이다.
목표는 J-POP, RKMusic, KAMITSUBAKI, 버추얼 아티스트 관련 공식 소스의 새 글을 수집하고, 글 종류별로 분류한 뒤, Discord 채널과 캘린더에 안전하게 라우팅하는 것이다.

## 목표

최종 흐름은 다음과 같다.

```text
X 계정 / 공식 사이트 / RSS / 티켓 페이지 수집
-> 이미 본 글 제거
-> 글 타입 분류
-> 타입별 정보 추출
-> 필요 시 번역/요약
-> DB 저장
-> Google Calendar 등록
-> Discord 설정 채널로 알림
-> 티켓/구매/응모는 사람 승인으로 마무리
```

구매, 응모, 결제는 완전 자동화하지 않는다. 티켓/굿즈 사이트는 자동 구매, 매크로, CAPTCHA 우회, 대량 접속을 금지하는 경우가 많다. 이 프로젝트는 구매 직전 안내와 승인 버튼까지만 자동화하고, 최종 결제/응모 버튼은 사람이 누르는 구조로 설계한다.

## 현재 기반

이미 존재하는 주요 파일과 역할:

- `app/core/db.py`: PostgreSQL 스키마 초기화
- `app/agents/scheduler.py`: 등록된 X 소스를 주기적으로 읽고 이벤트 후보를 만드는 기존 agent
- `app/integrations/x_client.py`: X API 호출
- `app/integrations/web_pages.py`: 링크된 공개 웹페이지 텍스트 수집
- `app/integrations/ai_extractor.py`: OpenAI 기반 공연/티켓 정보 추출
- `app/bots/discord_bot.py`: Discord slash command와 봇 실행
- `app/integrations/google_calendar.py`: Google Calendar 연동

현재 DB에는 다음 테이블이 이미 있다.

- `artists`: 아티스트
- `artist_sources`: X 계정, 공식 사이트 등 수집 소스
- `source_items`: 이미 본 원문 글
- `event_candidates`: 공연/티켓 후보
- `calendar_syncs`: 캘린더 동기화 기록

## 추천 구조

LangGraph는 "판단과 분기"에 사용하고, 수집/저장/전송은 일반 Python 함수로 유지한다.

```text
START
  -> collect_sources
  -> detect_new_items
  -> prepare_item
  -> classify_item
  -> route_by_item_type
      notice      -> summarize_translate -> notify
      live_event  -> extract_schedule -> create_calendar -> notify
      ticket      -> extract_ticket_info -> create_deadline_calendar -> notify_with_approval
      merch       -> extract_product_info -> notify_purchase_candidate
      irrelevant  -> mark_ignored
  -> END
```

처음부터 모든 코드를 LangGraph로 갈아엎지 않는다. 현재 `scheduler.py`의 정상 동작을 유지하면서, 분류/라우팅 부분부터 점진적으로 옮긴다.

## State 초안

```python
from typing import Literal, TypedDict


ItemType = Literal["notice", "release", "live_event", "ticket", "merch", "irrelevant"]


class MusicAgentState(TypedDict, total=False):
    source: dict
    raw_items: list[dict]
    new_items: list[dict]
    current_item: dict

    item_type: ItemType
    original_text: str
    page_context: str
    translated_text: str
    summary: str

    event_title: str
    event_start: str
    event_end: str
    venue: str
    ticket_open_at: str
    application_deadline: str
    ticket_url: str
    price_text: str

    event_candidate_id: int
    calendar_event_ids: dict[str, str]
    notification_route: dict
    notification_message: str

    needs_human_approval: bool
    error: str
```

## 글 타입

기본 타입은 다음 다섯 가지로 둔다.

- `notice`: 일반 공지, 방송, 업데이트, 안내
- `release`: 음원, 앨범, MV 공개, 디지털 배포
- `live_event`: 라이브, 콘서트, 페스, 출연 일정
- `ticket`: 선행, 일반 판매, 추첨, 응모, 티켓 마감
- `merch`: 굿즈, 음반, 판매, 예약, 특전
- `irrelevant`: 봇이 알릴 필요 없는 글

먼저 키워드 기반 필터로 후보를 줄이고, 애매한 글만 LLM에 보낸다.

예시 키워드:

```text
LIVE, ライブ, 公演, 出演, 開催, 会場, チケット, 先行, 一般販売,
抽選, 受付, 応募, 締切, グッズ, 販売, 予約, 特典, お知らせ
```

## 비용 관리 원칙

모든 새 글을 저장하되, 모든 글을 LLM에 보내지 않는다.

권장 순서:

```text
1. X/API/웹페이지에서 새 글 목록 수집
2. source_items로 중복 제거
3. rule filter로 명백히 관련 없는 글 제외
4. 후보 글만 classify_item LLM 호출
5. live_event/ticket/merch만 상세 추출
6. 필요할 때만 번역/요약
```

`fetch_recent_posts()`는 현재 `max_results`가 작게 잡혀 있다. 실전 감시에서는 실행 주기와 X API 제한을 보고 `max_results`와 `agent_interval_seconds`를 조정한다. 하루 한 번만 실행하면 게시글이 많은 계정에서 누락될 수 있다.

## 추가할 DB 테이블

Discord 채널 라우팅을 위해 다음 테이블을 추가한다.

```sql
CREATE TABLE IF NOT EXISTS notification_routes (
    id SERIAL PRIMARY KEY,
    discord_user_id TEXT,
    guild_id TEXT NOT NULL,
    source_id INTEGER,
    item_type TEXT NOT NULL,
    discord_channel_id TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES artist_sources(id) ON DELETE CASCADE,
    UNIQUE (guild_id, source_id, item_type, discord_channel_id)
);
```

필요하면 나중에 전체 기본 라우팅을 위해 `source_id`를 nullable로 둔다.

예시:

```text
source_id=3, item_type=ticket, channel=#ticket-alerts
source_id=3, item_type=merch, channel=#goods-alerts
source_id=7, item_type=live_event, channel=#hachi-live
```

## Discord 명령어

초기 구현에 필요한 slash command:

```text
/route_add source_id item_type channel
/route_list
/route_delete route_id
/route_test route_id
```

권장 추가 명령어:

```text
/source_add artist_id source_type value label
/source_list artist_id
/source_delete source_id
```

서버 공용 설정 명령어는 권한 체크를 넣는다.

```python
if not interaction.user.guild_permissions.manage_guild:
    await interaction.response.send_message(
        "서버 관리 권한이 있는 사용자만 설정할 수 있어요.",
        ephemeral=True,
    )
    return
```

## 알림 전송 방식

라우팅은 다음 순서로 처리한다.

```text
1. current_item의 source_id 확인
2. item_type 확인
3. notification_routes에서 guild_id + source_id + item_type에 맞는 route 조회
4. Discord channel_id로 채널 가져오기
5. 메시지 전송
6. 전송 결과를 notification log로 저장하는 것은 추후 추가
```

메시지는 가능한 짧고, 원문 링크를 반드시 포함한다.

```text
[티켓] HACHI 2nd LIVE 선행 접수 시작
일정: 2026-08-12 18:00 JST
마감: 2026-07-20 23:59 JST
장소: ...
링크: ...
```

티켓/굿즈는 버튼을 붙일 수 있다.

```text
[페이지 열기] [관심 있음] [무시]
```

단, 결제/응모 제출은 자동으로 하지 않는다.

## 구현 순서

1. `notification_routes` 테이블을 `app/core/db.py`에 추가한다.
2. 라우팅 CRUD helper를 별도 모듈로 만든다.
   - 추천 위치: `app/integrations/notifications.py` 또는 `app/core/routes.py`
3. `discord_bot.py`에 `/route_add`, `/route_list`, `/route_delete`, `/route_test`를 추가한다.
4. `ai_extractor.py`에 글 타입 분류 모델을 추가한다.
5. `scheduler.py`에서 새 글 저장 후 분류를 호출한다.
6. 분류 결과에 따라 route를 조회하고 Discord 채널에 알림을 보낸다.
7. 그 다음 LangGraph 모듈을 추가해서 orchestration만 옮긴다.
   - 추천 위치: `app/agents/music_graph.py`

초기에는 LangGraph 없이도 라우팅을 붙일 수 있다. 라우팅이 안정된 뒤 LangGraph로 분기 구조를 옮기는 편이 안전하다.

## LangGraph 도입 기준

다음 조건 중 2개 이상이 생기면 LangGraph로 옮긴다.

- 글 타입별 처리 단계가 3개 이상으로 갈라진다.
- 티켓/굿즈/라이브/일반공지의 추출 스키마가 달라진다.
- 사람 승인 단계가 필요하다.
- 실패한 node만 재시도하고 싶다.
- 테스트에서 각 node를 독립적으로 검증하고 싶다.

## 테스트 기준

최소 테스트:

- 같은 `source_items`가 두 번 저장되지 않는지
- 글 타입 분류가 허용된 값만 반환하는지
- `notification_routes`가 source/type별로 정확히 조회되는지
- route가 없으면 Discord 전송을 건너뛰는지
- 티켓/구매 타입이 자동 구매를 시도하지 않는지

가능하면 LLM 호출은 테스트에서 mock 처리한다.

## 운영 주의

- X API 호출 제한을 고려한다.
- 공식 사이트는 robots.txt와 약관을 존중한다.
- CAPTCHA 우회, 자동 결제, 자동 응모 제출은 구현하지 않는다.
- Discord 알림 폭주 방지를 위해 같은 글은 반드시 `source_items`로 중복 차단한다.
- 길고 복잡한 웹페이지 전체를 매번 LLM에 넣지 말고, 필요한 본문만 추출한다.
- LLM 비용 로그를 남길 수 있으면 좋다. 최소한 글 수, 분류 호출 수, 상세 추출 호출 수는 agent 결과에 포함한다.

## 좋은 기본값

개인/소규모 운영 기준:

```text
agent_interval_seconds: 600~1800
X max_results: 10~50
LLM classify: 후보 글만
LLM extract: live_event/ticket/merch만
Discord route 없음: 알림 생략
Calendar: live_event/ticket deadline만
```

이 프로젝트의 방향은 "모든 일을 AI에게 맡기는 봇"이 아니라, "수집과 저장은 deterministic code로 하고, 애매한 판단과 요약만 AI에게 맡기는 자동화 파이프라인"이다.
