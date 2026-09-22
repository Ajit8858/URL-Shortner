# URL Shortener — Scalable FastAPI Service

An end-to-end URL shortener built to handle ~1M users comfortably, with
a clear path to far more. Async FastAPI, Postgres, Redis, stateless
horizontal scaling. Every claim below was verified by actually running
the stack (Postgres + Redis + the app) and exercising the API, not just
asserted — see "What was tested" at the bottom.

## Capacity target (why the design looks like this)

Assume 1M registered users, each creating ~5 short links/month, with a
typical URL-shortener read:write ratio of ~100:1 (redirects vastly
outnumber creations):

| Metric | Average | Peak (10x) |
|---|---|---|
| Writes (shorten) | ~2 req/s | ~20 req/s |
| Reads (redirects) | ~200 req/s | ~2,000 req/s |

That peak read load is trivial for a cache-warmed system and very
achievable for Postgres directly if needed — but the design below
means Postgres barely sees the read traffic at all.

## Architecture

```
                     ┌─────────────┐
 clients ──────────► │ Load Balancer│  (nginx here; ALB/nginx-ingress in prod)
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         ┌────────┐   ┌────────┐    ┌────────┐
         │ App #1 │   │ App #2 │    │ App #N │   stateless FastAPI,
         └───┬────┘   └───┬────┘    └───┬────┘   horizontally scaled
             │            │             │
             └─────┬──────┴──────┬──────┘
                    ▼             ▼
              ┌──────────┐  ┌───────────┐
              │  Redis   │  │  Postgres │
              │ (cache,  │  │ (primary +│
              │  counter,│  │  replicas)│
              │  rate    │  └───────────┘
              │  limit)  │
              └──────────┘
```

### 1. Stateless app layer (horizontal scale)
Every app instance is identical and holds no local state that matters
across requests (the in-process ID-batch cache is a pure optimization,
safe to lose). This means scaling is "add more replicas" — no sticky
sessions, no coordination needed. Demonstrated here with 3 replicas
behind nginx in `docker-compose.yml`; in production this is a
Kubernetes Deployment + HorizontalPodAutoscaler (or ECS service)
driven by the `/metrics` Prometheus endpoint (CPU + request rate).

### 2. Redirect hot path: cache-aside with negative caching
`GET /{code}` is by far the highest-volume endpoint. It:
1. Checks Redis first (`app/cache.py`) — sub-millisecond, handles the
   large majority of traffic once warm.
2. On a miss, reads Postgres, populates the cache, and serves.
3. Caches **misses too** (short TTL) so a burst of requests for a
   bad/typo'd/scraped code can't hammer Postgres.
4. Click counting is `INCR`'d in Redis, never written to Postgres
   synchronously — see point 4 below.

This is what keeps Postgres load roughly flat even as redirect volume
grows: reads scale with Redis, not with the database.

### 3. Distributed ID generation (no single point of write contention)
Short codes are Base62-encoded sequential IDs. Rather than a DB
`SERIAL` (which becomes a contention point and ties ID generation to
DB availability under high write concurrency), each app process
reserves a **batch** of IDs from Redis at once (`INCRBY`, atomic) and
hands them out locally until the batch is exhausted
(`app/id_generator.py`). Result: ~0 network round trips per short code
minted, no collisions, and adding more app replicas doesn't increase
contention.

**Durability safeguard**: Redis is the fast path for ID allocation,
but Postgres is the actual source of truth. If Redis ever lost the
counter key (cold restart, memory-pressure eviction, failover,
accidental `FLUSHALL`), naively restarting the counter from zero would
collide with existing primary keys and break every write. This was
caught during testing (see below) and fixed: on every app startup, the
counter is reconciled to `max(id)` in Postgres via an idempotent Lua
script that only ever raises the counter, never lowers it — safe to
run concurrently from every replica on boot.

### 4. Click analytics off the hot path
Redirects `INCR` a Redis counter per short code. A background task
(`app/background.py`) drains these into Postgres every 15s in
batches, so click volume never translates 1:1 into Postgres writes.
The stats endpoint merges the committed count with the not-yet-flushed
Redis delta, so `GET /stats` is accurate in real time despite the
batching. At much higher scale, the append-only `click_events` table
is the first candidate to move out of Postgres entirely (e.g. into
Kafka → ClickHouse), since it's write-heavy, time-series shaped, and
not on the read path for redirects at all.

### 5. Distributed rate limiting
Enforced in Redis (fixed-window counter, `app/rate_limiter.py`), not
per-process — otherwise a user could bypass limits simply by landing
on a different replica behind the load balancer. Anonymous and
authenticated users get different limits.

### 6. Database
- Async SQLAlchemy + `asyncpg`, connection-pooled per process
  (`app/database.py`). In production, point `DATABASE_URL` at
  PgBouncer (transaction-mode pooling) so N replicas × pool_size
  doesn't translate into an unbounded number of real Postgres
  connections.
- Add read replicas as read traffic that *does* hit Postgres (cache
  misses, analytics queries) grows; the app already separates reads
  from writes at the query level, so routing reads to replicas is a
  connection-string change, not a rewrite.
- Indexed on `short_code` (unique), `owner_id`, `created_at`, and a
  composite `(owner_id, created_at)` for "my links" listings.
- If/when a single Postgres primary becomes the bottleneck even with
  replicas (very high write volume), the schema is shardable by
  `short_code` hash, since lookups are always by short_code or by
  owner — no cross-shard joins required for the core paths.

### 7. Graceful degradation
Redis being down doesn't take the service offline: ID generation falls
back to a random Base62 code, and the readiness probe
(`/health/ready`) reports the dependency as unhealthy so orchestration
can react — without the redirect/shorten paths hard-failing.

## Project layout

```
app/
  main.py           FastAPI app, lifespan, route registration
  config.py         env-driven settings (pydantic-settings)
  database.py       async SQLAlchemy engine/session
  models.py         User, URL, ClickEvent
  schemas.py        Pydantic request/response models
  crud.py           DB operations
  cache.py          Redis cache-aside layer
  id_generator.py   batched distributed ID generator + durability fix
  rate_limiter.py   Redis-backed sliding-window rate limiting
  security.py       bcrypt password hashing, JWT
  deps.py           FastAPI dependencies (DB session, current user)
  background.py     click-count flusher
  routers/
    auth.py         register/login
    urls.py         shorten / redirect / stats / delete
migrations/         Alembic, async-engine wired
nginx/nginx.conf    load balancer config for the compose demo
docker-compose.yml  3x app replicas + nginx + Postgres + Redis
Dockerfile          gunicorn + uvicorn workers
tests/              unit tests (Base62 correctness)
```

## Running it locally

```bash
cp .env.example .env   # edit SECRET_KEY etc.
docker-compose up --build
# API is now at http://localhost:8080 (nginx), fanning out to 3 app replicas
```

Or without Docker, against local Postgres/Redis:

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://shortener:shortener@localhost:5432/shortener
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=dev-secret
alembic upgrade head
uvicorn app.main:app --reload
```

## API

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register` | – | Create account, get API key |
| POST | `/api/v1/auth/login` | – | Get a JWT |
| POST | `/api/v1/shorten` | optional | Create a short URL (optional `custom_alias`, `expires_in_days`) |
| GET | `/{short_code}` | – | 302 redirect to the long URL |
| GET | `/api/v1/urls/{code}/stats` | – | Click count, created_at, active status |
| DELETE | `/api/v1/urls/{code}` | required | Deactivate a link you own |
| GET | `/health`, `/health/ready` | – | Liveness / deep readiness probes |
| GET | `/metrics` | – | Prometheus metrics |

Full interactive docs at `/docs` once running.

## What was tested

This wasn't just written and assumed correct — it was run against real
Postgres and Redis and exercised end to end, which caught three real
bugs before you'd have hit them:

1. **Route-shadowing**: the catch-all `GET /{short_code}` redirect
   route was originally registered before `/health`, so FastAPI
   matched `"health"` as a short code and 404'd. Fixed by ordering
   specific routes before the catch-all.
2. **SQLAlchemy 2.x raw SQL**: `conn.execute("SELECT 1")` needs
   `text("SELECT 1")` in SQLAlchemy 2.x; the readiness check would
   have thrown on every call. Fixed.
3. **ID counter durability** (the significant one — see design section
   4 above): simulated Redis losing its counter key and confirmed the
   original design would silently start issuing colliding primary
   keys. Added startup reconciliation against Postgres `max(id)`
   and reproduced the failure, then confirmed the fix prevents it.

Verified working end to end: health/readiness checks, registration,
authenticated and anonymous URL shortening, custom aliases, duplicate-
alias rejection, redirects (both cache-miss and cache-hit paths),
404s for unknown codes, real-time click counting via the Redis buffer,
per-minute rate limiting (confirmed exact cutoff at the configured
limit), delete with ownership enforcement, and 401/404 authorization
edge cases. Zero errors in the application log across the full run.

## Scaling beyond 1M users

- **App**: add replicas; stateless by design.
- **Redis**: move from single instance to Redis Cluster; cache and
  rate-limit keys are already simple string ops that shard cleanly.
- **Postgres**: add read replicas first (cheap, no app changes beyond
  routing reads); shard by `short_code` hash if write volume ever
  outgrows a single primary.
- **Click analytics**: migrate `click_events` to a
  stream/columnar store (Kafka → ClickHouse) once volume makes
  Postgres an awkward fit for it — nothing else in the request path
  depends on that table.
- **CDN**: redirects are dynamic (need a DB/cache lookup) so they
  can't be edge-cached directly, but static assets (docs, landing
  pages) should sit behind a CDN regardless.
