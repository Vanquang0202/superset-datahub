# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Verify Superset cache and async-query prerequisites.

The script performs read-only checks by default. Use ``--benchmark`` or
``--warmup`` explicitly for the corresponding optional actions.
"""

from __future__ import annotations

import argparse
import json  # noqa: TID251
import os
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

ASYNC_TASKS = {
    "cache-warmup",
    "load_chart_data_into_cache",
    "load_explore_json_into_cache",
    "sql_lab.get_sql_results",
}


def boolean_env(name: str, default: bool = False) -> bool:
    """Return a conventional boolean environment value."""
    return os.getenv(name, str(default)).lower() in {
        "1",
        "true",
        "yes",
        "on",
        "y",
    }


def load_local_config(path: Path) -> dict[str, Any] | None:
    """Load a local config file when its Python dependencies are available."""
    if not path.exists():
        return None

    config_dir = str(path.parent)
    sys.path.insert(0, config_dir)
    try:
        return runpy.run_path(str(path))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"effective config: unavailable ({type(exc).__name__})")
        return None
    finally:
        sys.path.remove(config_dir)


def redis_connection(config: dict[str, Any] | None) -> tuple[Any, str, str]:
    """Create the configured Redis client without exposing credentials."""
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("redis package is unavailable") from exc

    cache_config = (config or {}).get("CACHE_CONFIG", {})
    host = str(
        cache_config.get("CACHE_REDIS_HOST", os.getenv("REDIS_HOST", "localhost"))
    )
    port = int(cache_config.get("CACHE_REDIS_PORT", os.getenv("REDIS_PORT", "6379")))
    db = str(
        cache_config.get(
            "CACHE_REDIS_DB",
            os.getenv("REDIS_CACHE_DB", os.getenv("REDIS_RESULTS_DB", "1")),
        )
    )
    return (
        redis.Redis(host=host, port=port, db=int(db), decode_responses=True),
        host,
        db,
    )


def check_redis(
    config: dict[str, Any] | None,
) -> tuple[Any | None, int, int | None]:
    """Check Redis and report key count and one representative TTL."""
    try:
        client, host, db = redis_connection(config)
        client.ping()
        prefix = (config or {}).get("CACHE_CONFIG", {}).get(
            "CACHE_KEY_PREFIX", os.getenv("SUPERSET_CACHE_KEY_PREFIX", "superset_")
        )
        keys = list(client.scan_iter(match=f"{prefix}*"))
        ttl = client.ttl(keys[0]) if keys else None
        print(f"redis: reachable host={host} db={db} key_count={len(keys)}")
        print(f"redis: sample_ttl={ttl if ttl is not None else 'n/a'} prefix={prefix}")
        return client, len(keys), ttl if isinstance(ttl, int) else None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"redis: FAILED ({type(exc).__name__}: {exc})")
        return None, 0, None


def check_effective_config(config: dict[str, Any] | None) -> None:
    """Report relevant effective settings without printing secret values."""
    if config is None:
        print(
            "effective config: unavailable; run inside the Superset environment "
            "for this check"
        )
        return

    flags = config.get("FEATURE_FLAGS", {})
    cache = config.get("CACHE_CONFIG", {})
    gaq_cache = config.get("GLOBAL_ASYNC_QUERIES_CACHE_BACKEND", {})
    secret = config.get("GLOBAL_ASYNC_QUERIES_JWT_SECRET", "")
    print(
        "effective flags: "
        f"GLOBAL_ASYNC_QUERIES={flags.get('GLOBAL_ASYNC_QUERIES')}, "
        f"ALERT_REPORTS={flags.get('ALERT_REPORTS')}, "
        f"DATASET_FOLDERS={flags.get('DATASET_FOLDERS')}"
    )
    print(
        "cache: "
        f"type={cache.get('CACHE_TYPE')} "
        f"timeout={cache.get('CACHE_DEFAULT_TIMEOUT')} "
        f"db={cache.get('CACHE_REDIS_DB')}"
    )
    print(
        "global async: "
        f"transport={config.get('GLOBAL_ASYNC_QUERIES_TRANSPORT', 'polling')} "
        f"cache_type={gaq_cache.get('CACHE_TYPE')} "
        f"jwt_configured={bool(secret)}"
    )


def check_celery() -> str:
    """Check worker reachability and task registration when Celery is available."""
    celery = shutil.which("celery")
    if not celery:
        print("celery: unavailable (command not found)")
        return "unavailable"

    try:
        result = subprocess.run(  # noqa: S603
            [celery, "-A", "superset.tasks.celery_app:app", "inspect", "registered"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"celery: unavailable ({type(exc).__name__})")
        return "unavailable"

    output = f"{result.stdout}\n{result.stderr}"
    found = sorted(task for task in ASYNC_TASKS if task in output)
    status = "reachable" if result.returncode == 0 else "unavailable"
    print(f"celery: {status} async_tasks={','.join(found) or 'none'}")
    return status


def auth_headers() -> dict[str, str] | None:
    """Build optional auth headers from environment variables."""
    token = os.getenv("SUPERSET_ACCESS_TOKEN")
    cookie = os.getenv("SUPERSET_SESSION_COOKIE")
    if not token and not cookie:
        return None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
    return headers


def request_chart(
    base_url: str, chart_id: str, timeout: float
) -> tuple[float, int, str]:
    """Request a saved chart using the source version's chart data endpoint."""
    url = f"{base_url.rstrip('/')}/api/v1/chart/{chart_id}/data/"
    req = request.Request(  # noqa: S310
        url, headers=auth_headers() or {}, method="GET"
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
            return time.perf_counter() - started, response.status, body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return time.perf_counter() - started, exc.code, body


def benchmark(
    args: argparse.Namespace,
    before_keys: int,
    before_ttl: int | None,
    config: dict[str, Any] | None,
) -> None:
    """Compare two saved-chart requests when credentials and chart ID exist."""
    chart_id = args.chart_id or os.getenv("SUPERSET_BENCHMARK_CHART_ID")
    if not chart_id or auth_headers() is None:
        print("\n=== Performance Summary ===")
        print("cold load: SKIPPED")
        print("warm load: SKIPPED")
        print("difference: n/a")
        print("improvement percentage: n/a")
        print("cache hit/miss evidence: not measured")
        print(f"cache keys before: {before_keys}")
        print("cache keys after: not measured")
        print("async task status: not measured")
        print(
            "benchmark: SKIPPED (set --chart-id and SUPERSET_ACCESS_TOKEN or "
            "SUPERSET_SESSION_COOKIE)"
        )
        return

    results = [
        request_chart(args.superset_url, chart_id, args.timeout)
        for _ in range(args.runs)
    ]
    durations = [duration for duration, _, _ in results]
    statuses = [status for _, status, _ in results]
    cold = durations[0]
    warm = sum(durations[1:]) / len(durations[1:])
    delta = cold - warm
    improvement = (delta / cold * 100) if cold > 0 else None
    client, after_keys, after_ttl = check_redis(config)

    print("\n=== Performance Summary ===")
    print(f"cold load: {cold:.3f}s")
    print(f"warm load: {warm:.3f}s")
    print(f"difference: {delta:.3f}s")
    print(
        "improvement percentage: "
        f"{improvement:.1f}%"
        if improvement is not None
        else "improvement percentage: n/a"
    )
    print(f"cache hit/miss evidence: HTTP statuses={statuses}")
    print(f"cache keys before: {before_keys}")
    print(f"cache keys after: {after_keys if client is not None else 'unavailable'}")
    print(
        "cache TTL evidence: "
        f"before={before_ttl if before_ttl is not None else 'n/a'}, "
        f"after={after_ttl if after_ttl is not None else 'n/a'}"
    )
    print(
        "async task status: inspect Celery logs; HTTP 202 indicates async acceptance"
    )

    # Keep the raw measurements available for technical validation.
    print(
        f"benchmark: chart_id={chart_id} "
        f"statuses={statuses}"
    )
    print(f"benchmark: durations={[round(duration, 3) for duration in durations]}")
    print(f"benchmark: redis_keys_before={before_keys} redis_keys_after={after_keys}")


def warmup(
    args: argparse.Namespace, before_keys: int, config: dict[str, Any] | None
) -> None:
    """Dispatch the built-in top-dashboard warmup task when explicitly requested."""
    celery = shutil.which("celery")
    if not celery:
        print("warmup: SKIPPED (celery command not found)")
        return

    kwargs = {
        "strategy_name": "top_n_dashboards",
        "top_n": args.warmup_top_n,
        "since": args.warmup_since,
    }
    result = subprocess.run(  # noqa: S603
        [
            celery,
            "-A",
            "superset.tasks.celery_app:app",
            "call",
            "cache-warmup",
            "--kwargs",
            json.dumps(kwargs),
        ],
        capture_output=True,
        text=True,
        timeout=args.timeout,
        check=False,
    )
    print(f"warmup: dispatched={result.returncode == 0} strategy=top_n_dashboards")
    if result.returncode != 0:
        print("warmup: task dispatch failed; inspect Celery logs for details")
        return
    _, after_keys, _ = check_redis(config)
    print(f"warmup: redis_keys_before={before_keys} redis_keys_after={after_keys}")


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    default_config = Path(
        os.getenv(
            "SUPERSET_CONFIG_PATH", "docker/pythonpath_dev/superset_config.py"
        )
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--superset-url", default=os.getenv("SUPERSET_URL", "http://localhost:8088"))
    parser.add_argument("--chart-id", help="Saved chart ID; no default is assumed")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument(
        "--warmup-top-n",
        type=int,
        default=int(os.getenv("SUPERSET_CACHE_WARMUP_TOP_N", "10")),
    )
    parser.add_argument(
        "--warmup-since",
        default=os.getenv("SUPERSET_CACHE_WARMUP_SINCE", "7 days ago"),
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=default_config,
    )
    return parser.parse_args()


def main() -> int:
    """Run runtime checks and optional benchmark/warmup actions."""
    args = parse_args()
    if args.runs < 2:
        print("runs: must be at least 2 for cold/warm comparison")
        return 2

    config = load_local_config(args.config_file)
    check_effective_config(config)
    client, before_keys, before_ttl = check_redis(config)
    if client is None:
        return 1
    check_celery()
    if args.benchmark:
        benchmark(args, before_keys, before_ttl, config)
    if args.warmup:
        warmup(args, before_keys, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
