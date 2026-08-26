# Backend architecture

The canonical HTTP namespace is `/api`. Unprefixed routes are temporarily kept
for the existing Vue client and existing Discord links.

```text
router -> service -> repository -> SQLAlchemy ORM / explicit SQL -> PostgreSQL
                         |
                         +-> integrations (Spotify, YouTube, OpenAI, Google)
```

- `app/api/routers/`: domain-specific HTTP endpoints and response status codes
- `app/schemas/`: Pydantic request/response contracts
- `app/services/`: use cases, orchestration, and external integrations
- `app/repositories/`: database queries only
- `app/db/models.py`: SQLAlchemy entity mappings
- `app/db/session.py`: SQLAlchemy engine and request-scoped sessions
- `app/core/config.py`: `pydantic-settings` configuration (the Python analogue
  to `application.yml`); values are loaded from `.env`
- `app/core/security.py`: optional `API_KEY` authentication dependency

`app/core/db.py` remains responsible for the existing incremental schema
bootstrap during migration. It must not be replaced by `Base.metadata.create_all`
until all current schema changes are represented by migrations.

## Security

Set `API_KEY` in `.env` to require an `X-API-Key` header on newly migrated
routers. It is intentionally optional for now, so deploying this refactor does
not break the current unauthenticated web client. Enable it only after the
frontend/client header is configured.
