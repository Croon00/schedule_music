# schedule_music web

Vue 3 + TypeScript + Vite 기반 관리자 프론트엔드가 위치할 디렉터리다.

기본 프론트엔드 구성:

- Vue 3 + TypeScript + Vite
- Vue Router
- Pinia
- TanStack Query for Vue
- Nuxt UI for Vue/Vite
- Inspira UI 일부 장식 컴포넌트

예정 화면:

- 대시보드
- 아티스트 및 수집 소스 관리
- Discord 알림 라우트 관리
- 수집 게시글과 분류 결과 확인
- 라이브·티켓 일정 확인
- 수동 수집 및 재전송 실행 이력

프론트는 `app/api/`의 FastAPI와 통신하며 Discord, X, OpenAI, PostgreSQL에 직접 접근하지 않는다.

예정된 개발·빌드 명령:

```text
npm install
npm run dev
npm run typecheck
npm run test
npm run build
npm run preview
```

`npm run build` 결과는 기본적으로 `web/dist/`에 생성한다. `npm run preview`는 빌드 결과의 로컬 확인용이며 production server로 사용하지 않는다.
