# FastAPI 영역 작업 지침

이 문서는 `app/api/` 아래에서 작업할 때 루트 `AGENTS.md`에 추가로 적용된다.
이 디렉터리는 웹·외부 클라이언트가 사용하는 HTTP API 경계만 담당한다.

## 책임

- FastAPI 애플리케이션과 lifespan 구성
- 요청·응답 스키마 연결
- HTTP 상태 코드와 오류 응답 정의
- Discord OAuth 기반 웹 인증 진입점
- 아티스트, 소스, 라우트, 수집 글, 이벤트 조회·관리 API

## 경계

- 수집, 분류, Discord 전송 로직을 endpoint 안에 직접 구현하지 않는다.
- DB SQL이 여러 호출부에서 재사용되면 `app/core/` 또는 `app/integrations/` helper로 옮긴다.
- 장시간 실행되는 수집 작업을 HTTP 요청이 끝날 때까지 붙잡아 두지 않는다. 작업 실행 요청과 실제 worker 실행을 분리한다.
- Discord 봇 객체를 API에서 직접 import하지 않는다.
- API는 Discord 채널 전송을 직접 수행하지 않고 명시적인 service/helper 또는 작업 큐 경계를 사용한다.

## 인증과 권한

- 공개 endpoint는 `/health`, OAuth callback 등 필요한 최소 범위로 제한한다.
- 관리 API는 인증된 Discord 사용자만 호출할 수 있어야 한다.
- `guild_id`는 클라이언트가 보낸 값을 신뢰하지 말고 인증된 사용자가 접근 가능한 서버인지 검증한다.
- 라우트 변경은 해당 guild의 `manage_guild` 권한을 확인한다.
- 토큰, OAuth secret, DB URL을 응답이나 로그에 노출하지 않는다.

## API 규칙

- 웹용 endpoint는 `/api/` prefix 아래에 둔다.
- 입력과 출력은 Pydantic 모델로 명시한다.
- 목록 API는 데이터가 커질 수 있으면 pagination과 필터를 제공한다.
- 사용자 입력 오류는 400, 미인증은 401, 권한 없음은 403, 리소스 없음은 404, 중복은 409를 기본으로 한다.
- 삭제·재전송·수동 수집처럼 상태를 바꾸는 동작은 GET으로 만들지 않는다.
- 프론트가 내부 DB 컬럼 구조에 직접 의존하지 않도록 응답 모델을 별도로 유지한다.

## 테스트

- endpoint 성공 응답뿐 아니라 401, 403, 404, 409를 테스트한다.
- 외부 X, OpenAI, Google, Discord 호출은 mock 처리한다.
- 다른 guild의 artist/source/route에 접근할 수 없는지 테스트한다.
- 스키마 변경 시 기존 API 응답 호환성을 확인한다.
