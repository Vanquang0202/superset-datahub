<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Performance / Cache / Async Query

## Dashboard Performance Optimization

_Tối ưu tốc độ tải Dashboard bằng Async Query và Cache_

This use case explains how Superset can make dashboards more responsive when
they contain many charts or expensive queries. It is written for PMs, analysts,
administrators, business stakeholders, and technical teams.

## The user problem

A dashboard may contain many charts. Each chart can query Trino, and the
queries may take different amounts of time. When a user opens the dashboard,
waiting for every query can make the experience feel slow. Opening the same
dashboard repeatedly may also repeat expensive work.

Frequently used dashboards should ideally have their data prepared before users
arrive, while long-running queries should not make the browser wait for all
processing synchronously.

## User-facing goal

This use case aims to:

- reduce the time users wait for dashboard data;
- make repeated dashboard loads faster when data is still valid in cache;
- keep the interface responsive while expensive work runs in the background;
- prepare frequently used dashboards before users open them.

No exact performance improvement is promised by configuration alone. The
included verifier measures cold and warm requests when a chart ID and
credentials are supplied.

## Dashboard Performance Status

The dashboard header includes a compact **Dashboard Performance Status**
(`Trạng thái hiệu năng Dashboard`). It makes the current browser session
understandable without requiring users to open worker logs or Redis:

- **Processing data** appears while one or more dashboard chart queries are
  still running.
- **Fresh** appears after the charts complete when their responses explicitly
  report that they were not cached.
- **Cached** appears only when every completed chart response explicitly
  reports `is_cached=true`.
- **Ready** is used when the charts completed but the response metadata is
  mixed or does not identify cache provenance.
- **Load** is measured in the browser from the dashboard chart request start
  timestamps through the last chart completion.
- **Updated** is the time the displayed result completed in this browser
  session. It is not a source-system ingestion timestamp.

The UI does not show **Pre-warmed** because Superset exposes a cache hit but
does not expose whether that hit was created by scheduled warmup or by another
request. It therefore avoids presenting an unsupported conclusion.

The status is intentionally a user-facing summary. Redis, Celery, polling,
cache keys, and task names remain part of the technical validation below.

## End-user demonstration

1. Open a dashboard.
2. Observe **Processing data** while charts are loading.
3. Wait for completion and note the final status, load duration, and updated
   time in the dashboard header.
4. Refresh the dashboard and compare the measured load duration.
5. If the response metadata proves a cache hit, observe **Cached**. Otherwise,
   the UI deliberately leaves cache provenance unlabeled.
6. Use the technical verifier and logs afterward as supporting evidence.

## Before and after

### Before

```text
User opens dashboard
        |
        v
Superset waits for query
        |
        v
Trino executes
        |
        v
Browser waits for response
        |
        v
Repeated open may execute the query again
```

### After

```text
User opens dashboard
        |
        v
Cache checked first
        |
        +---- cached result --> return result sooner
        |
        +---- cache miss --> process asynchronously
                              |
                              v
                         save result in cache
                              |
                              v
                         return when ready
```

## User scenarios

### Scenario 1: First dashboard load

1. A user opens a dashboard.
2. The requested data is not cached yet.
3. Superset processes the query.
4. The result is stored temporarily.
5. This first load may take longer.

### Scenario 2: Repeated dashboard load

1. The user opens the same dashboard again while the cache is valid.
2. Superset checks Redis before repeating the query.
3. A cached result can be returned faster.
4. Trino is not unnecessarily queried again where the cache applies.

### Scenario 3: Frequently used dashboard

1. Before users arrive, scheduled warmup identifies frequently used dashboards.
2. Superset requests their chart data through the built-in warmup task.
3. The results are placed in Redis.
4. A user opening the dashboard can benefit from data already prepared.

### Scenario 4: Long-running query

1. A user requests a chart.
2. The request is submitted for background processing.
3. The browser is not responsible for doing all processing synchronously.
4. A Celery worker runs the task.
5. Superset returns the result when it is ready.

## Component explanations

| Component | Easy explanation | User benefit |
| --- | --- | --- |
| Redis Cache | Temporary storage for previously calculated results | Repeated dashboard loads can avoid recomputing the same result |
| Celery Worker | Background worker that handles query work | Long-running work does not need to block the main web request |
| Async Query | Query processing that continues in the background | Better responsiveness during expensive queries |
| Cache Warmup | Preparing dashboard data before users open it | Frequently used dashboards can load faster on first access |
| Celery Beat | Scheduler for recurring background work | Warmup can run automatically on a schedule |

## Architecture: business view

```text
User
  |
  v
Dashboard
  |
  +-- data ready ------> display quickly
  |
  +-- data not ready --> process in background
                              |
                              v
                         save result
                              |
                              v
                           display
```

## Architecture: technical view

```text
Browser
  |
Superset Web
  |
  +-- cache hit --> Redis
  |
  +-- cache miss --> Celery
                     |
                     v
                   Trino
                     |
                     v
                   Redis
                     |
                     v
                   Browser
```

Scheduled warmup:

```text
Celery Beat
   |
   v
cache-warmup
   |
   v
Top dashboards
   |
   v
Redis populated before user access
```

Global async queries use polling by default in this checkout. The Compose file
also contains an optional `superset-websocket` service and nginx `/ws` route for
deployments that explicitly select websocket transport.

## How to demonstrate this use case

This demo is intended to be understandable without reading logs:

1. Open a dashboard and note the initial load behavior.
2. Run the warmup task or enable its scheduled configuration.
3. Re-open the same dashboard.
4. Compare the first and repeated loads.
5. Show that Redis contains cache entries with a remaining TTL.
6. Explain that the worker processed the background work.

Logs are supporting evidence. The primary demo is the dashboard behavior and
the measured cold-versus-warm summary.

## Configuration and warmup

The implementation is in `docker/pythonpath_dev/superset_config.py`.

Safe defaults are preserved:

- Redis cache DB falls back to `REDIS_RESULTS_DB` (DB 1 locally).
- Cache timeout remains 300 seconds.
- Cache prefix remains `superset_`.
- Cache warmup is disabled unless explicitly enabled.
- Warmup defaults to the top 10 dashboards from the previous 7 days.

Warmup uses Superset's existing `cache-warmup` task and the built-in
`top_n_dashboards` strategy. No custom cache engine or strategy was added.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUPERSET_CACHE_WARMUP_ENABLED` | `false` | Enable the hourly warmup beat entry |
| `SUPERSET_CACHE_WARMUP_SCHEDULE_MINUTE` | `0` | Minute within each hour |
| `SUPERSET_CACHE_WARMUP_TOP_N` | `10` | Number of frequently used dashboards |
| `SUPERSET_CACHE_WARMUP_SINCE` | `7 days ago` | Activity window for `top_n_dashboards` |
| `SUPERSET_CACHE_DEFAULT_TIMEOUT` | `300` | Default Redis cache TTL in seconds |
| `REDIS_CACHE_DB` | `REDIS_RESULTS_DB` | Redis DB for Superset cache and GAQ |
| `SUPERSET_CACHE_KEY_PREFIX` | `superset_` | Cache key prefix |
| `SUPERSET_WEBDRIVER_BASEURL` | `http://superset:8088/` | Internal web URL used by workers for warmup/report requests |

## Technical validation

From the repository root:

```bash
python examples/performance-cache-async/verify_performance.py
```

The verifier checks:

- Redis reachability, DB, key count, and representative TTL;
- effective cache timeout, prefix, and Redis backend;
- `GLOBAL_ASYNC_QUERIES` and polling transport;
- whether the JWT secret is configured, without printing it;
- Celery worker reachability and async task registration when detectable.

It never prints secrets, passwords, tokens, or cookies.

To dispatch the built-in warmup task explicitly:

```bash
python examples/performance-cache-async/verify_performance.py --warmup
```

Confirm `cache-warmup`, `fetch_url`, and successful HTTP 200 warmup requests
in the worker logs. A warmup can produce no new keys when there are no
qualifying dashboards or charts.

## Benchmarking

Benchmarking is optional and is separate from runtime validation. It requires a
saved chart ID and either an access token or session cookie supplied through the
environment:

```powershell
$env:SUPERSET_ACCESS_TOKEN = "<short-lived-token>"
python examples/performance-cache-async/verify_performance.py `
  --benchmark --chart-id <chart-id> --runs 3
```

Alternatively set `SUPERSET_SESSION_COOKIE`. The script requests
`/api/v1/chart/{chart_id}/data/`, measures the first request as cold and the
remaining requests as warm samples, then reports:

```text
=== Performance Summary ===
cold load: ...
warm load: ...
difference: ...
improvement percentage: ...
cache hit/miss evidence: ...
cache keys before: ...
cache keys after: ...
async task status: ...
```

Values are printed only when measured. If credentials or chart ID are missing,
the summary says `SKIPPED`; no performance improvement is fabricated.

## Recommended captures

Business-facing captures:

- dashboard before and after a repeated load;
- the `Performance Summary` benchmark output;
- a warm-load result with a simple timing comparison;
- the business architecture diagram above.

Technical evidence:

- `docker compose ps` showing Superset, worker, beat, and Redis healthy;
- Celery async task success;
- `cache-warmup` and `fetch_url` success logs;
- Redis cache key and TTL evidence;
- verifier output;
- effective feature flag and polling transport configuration.

## Known limitation

SQL Lab Async was not changed because the shared Trino database connection is
not editable in this environment. Its **Asynchronous Query Execution** setting
must be enabled manually on an appropriate database before SQL Lab async
execution can be demonstrated.
