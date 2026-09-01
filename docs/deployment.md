# RevivePay Phase 4 deployment

## Safety model
- All payments remain synthetic; the only executor is the deterministic simulator.
- Deploy migrations explicitly before serving traffic. Do not use `create_all()` in production.
- Production requires `ENVIRONMENT=production`, `AUTH_MODE=api_key`, a non-empty `API_KEY`, explicit CORS origins, and `EXECUTION_MODE=enqueue`.
- The API process accepts durable work at `POST /api/jobs/recovery/{case_id}` with `Authorization: Bearer <API_KEY>` and a unique `Idempotency-Key`; workers claim it from PostgreSQL. The direct recovery endpoint remains for deterministic local/demo tests.

## Local development (PowerShell)
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\migrate.py
.\.venv\Scripts\python.exe scripts\seed.py
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```
In another terminal:
```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```
Use `GET /health` for liveness and `GET /readyz` for database readiness.

## Legacy SQLite adoption
For an existing database created before Alembic, first back it up, validate that it is a RevivePay seven-domain-table schema, then stamp it once:
```powershell
.\.venv\Scripts\python.exe scripts\stamp_existing_schema.py
.\.venv\Scripts\python.exe scripts\migrate.py
```
`stamp_existing_schema.py` refuses incomplete schemas. New databases require only `scripts\migrate.py`.

## Production-like Compose
Set secrets outside source control, then run:
```powershell
$env:POSTGRES_PASSWORD = "use-a-long-random-password"
$env:API_KEY = "use-a-32-byte-or-longer-random-secret"
$env:BACKEND_CORS_ORIGINS = "https://app.example.com"
docker compose up --build
```
The compose stack provides PostgreSQL, a FastAPI service, a database worker, and Nginx-served static frontend. It creates no cloud resources.

## AWS-oriented plan (no automatic deployment)
1. Build/push the backend image to ECR and deploy separate API and worker task definitions on ECS Fargate (or equivalent container service).
2. Use RDS PostgreSQL with TLS, private subnets, backups, and credentials in Secrets Manager. Set `DATABASE_URL=postgresql+psycopg://...` from the injected secret.
3. Run `python scripts/migrate.py` as a one-off ECS task before rolling API/worker deployments.
4. Host `frontend/dist` in S3 behind CloudFront; set `VITE_API_BASE_URL` to the API origin at build time and permit that CloudFront domain in `BACKEND_CORS_ORIGINS`.
5. Place the API behind an ALB with HTTPS termination, forward only trusted traffic, and configure health checks for `/readyz`.
6. Keep the worker replica count conservative until PostgreSQL load testing validates lease contention. No Redis/Celery is required; the outbox/jobs tables form the initial durable boundary.

## Production smoke checks
```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend run typecheck
npm --prefix frontend run build
$env:DATABASE_URL = "sqlite:///./smoke.db"; .\.venv\Scripts\python.exe scripts\migrate.py
```
For PostgreSQL, run the same migration command with a non-production disposable `postgresql+psycopg://` URL, then query `/readyz` and submit a protected idempotent job.
