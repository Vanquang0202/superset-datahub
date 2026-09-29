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
#
# This file is included in the final Docker image and SHOULD be overridden when
# deploying the image to prod. Settings configured here are intended for use in local
# development environments. Also note that superset_config_docker.py is imported
# as a final step as a means to override "defaults" configured here
#
import logging
import os
import sys

from celery.schedules import crontab
from flask_caching.backends.filesystemcache import FileSystemCache
from superset.utils.core import parse_boolean_string

logger = logging.getLogger()

DATABASE_DIALECT = os.getenv("DATABASE_DIALECT")
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_DB = os.getenv("DATABASE_DB")

EXAMPLES_USER = os.getenv("EXAMPLES_USER")
EXAMPLES_PASSWORD = os.getenv("EXAMPLES_PASSWORD")
EXAMPLES_HOST = os.getenv("EXAMPLES_HOST")
EXAMPLES_PORT = os.getenv("EXAMPLES_PORT")
EXAMPLES_DB = os.getenv("EXAMPLES_DB")

# The SQLAlchemy connection string.
SQLALCHEMY_DATABASE_URI = (
    f"{DATABASE_DIALECT}://"
    f"{DATABASE_USER}:{DATABASE_PASSWORD}@"
    f"{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_DB}"
)

# Use environment variable if set, otherwise construct from components
# This MUST take precedence over any other configuration
SQLALCHEMY_EXAMPLES_URI = os.getenv(
    "SUPERSET__SQLALCHEMY_EXAMPLES_URI",
    (
        f"{DATABASE_DIALECT}://"
        f"{EXAMPLES_USER}:{EXAMPLES_PASSWORD}@"
        f"{EXAMPLES_HOST}:{EXAMPLES_PORT}/{EXAMPLES_DB}"
    ),
)


REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_CELERY_DB = os.getenv("REDIS_CELERY_DB", "0")
REDIS_RESULTS_DB = os.getenv("REDIS_RESULTS_DB", "1")
REDIS_CACHE_DB = os.getenv("REDIS_CACHE_DB", REDIS_RESULTS_DB)

CACHE_DEFAULT_TIMEOUT = int(os.getenv("SUPERSET_CACHE_DEFAULT_TIMEOUT", "300"))
CACHE_KEY_PREFIX = os.getenv("SUPERSET_CACHE_KEY_PREFIX", "superset_")
CACHE_WARMUP_ENABLED = parse_boolean_string(os.getenv("SUPERSET_CACHE_WARMUP_ENABLED"))
CACHE_WARMUP_SCHEDULE_MINUTE = os.getenv("SUPERSET_CACHE_WARMUP_SCHEDULE_MINUTE", "0")
CACHE_WARMUP_TOP_N = int(os.getenv("SUPERSET_CACHE_WARMUP_TOP_N", "10"))
CACHE_WARMUP_SINCE = os.getenv("SUPERSET_CACHE_WARMUP_SINCE", "7 days ago")

RESULTS_BACKEND = FileSystemCache("/app/superset_home/sqllab")

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": CACHE_DEFAULT_TIMEOUT,
    "CACHE_KEY_PREFIX": CACHE_KEY_PREFIX,
    "CACHE_REDIS_HOST": REDIS_HOST,
    "CACHE_REDIS_PORT": REDIS_PORT,
    "CACHE_REDIS_DB": REDIS_CACHE_DB,
}
DATA_CACHE_CONFIG = CACHE_CONFIG
THUMBNAIL_CACHE_CONFIG = CACHE_CONFIG

# Global async queries use the existing Redis-backed cache for coordination.
GLOBAL_ASYNC_QUERIES_CACHE_BACKEND = CACHE_CONFIG
GLOBAL_ASYNC_QUERIES_JWT_SECRET = os.environ["SUPERSET_SECRET_KEY"]


class CeleryConfig:
    broker_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_CELERY_DB}"
    imports = (
        "superset.sql_lab",
        "superset.tasks.scheduler",
        "superset.tasks.thumbnails",
        "superset.tasks.cache",
    )
    result_backend = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_RESULTS_DB}"
    worker_prefetch_multiplier = 1
    task_acks_late = False
    beat_schedule = {
        "reports.scheduler": {
            "task": "reports.scheduler",
            "schedule": crontab(minute="*", hour="*"),
        },
        "reports.prune_log": {
            "task": "reports.prune_log",
            "schedule": crontab(minute=10, hour=0),
        },
    }
    if CACHE_WARMUP_ENABLED:
        beat_schedule["cache-warmup-hourly"] = {
            "task": "cache-warmup",
            "schedule": crontab(minute=CACHE_WARMUP_SCHEDULE_MINUTE, hour="*"),
            "kwargs": {
                "strategy_name": "top_n_dashboards",
                "top_n": CACHE_WARMUP_TOP_N,
                "since": CACHE_WARMUP_SINCE,
            },
        }


CELERY_CONFIG = CeleryConfig

FEATURE_FLAGS = {
    "ALERT_REPORTS": True,
    "DATASET_FOLDERS": True,
    "GLOBAL_ASYNC_QUERIES": True,
}
_LOCAL_FEATURE_FLAGS = FEATURE_FLAGS.copy()
ALERT_REPORTS_NOTIFICATION_DRY_RUN = True
SUPERSET_APP_ROOT = os.environ.get("SUPERSET_APP_ROOT", "/")
WEBDRIVER_BASEURL = os.getenv(
    "SUPERSET_WEBDRIVER_BASEURL",
    f"http://superset:8088{SUPERSET_APP_ROOT.rstrip('/')}/",
)
# The base URL for the email report hyperlinks.
WEBDRIVER_BASEURL_USER_FRIENDLY = f"http://localhost:8888/{SUPERSET_APP_ROOT}/"
SQLLAB_CTAS_NO_LIMIT = True

log_level_text = os.getenv("SUPERSET_LOG_LEVEL", "INFO")
LOG_LEVEL = getattr(logging, log_level_text.upper(), logging.INFO)

if os.getenv("CYPRESS_CONFIG") == "true":
    # When running the service as a cypress backend, we need to import the config
    # located @ tests/integration_tests/superset_test_config.py
    base_dir = os.path.dirname(__file__)
    module_folder = os.path.abspath(
        os.path.join(base_dir, "../../tests/integration_tests/")
    )
    sys.path.insert(0, module_folder)
    from superset_test_config import *  # noqa

    sys.path.pop(0)

#
# Optionally import superset_config_docker.py (which will have been included on
# the PYTHONPATH) in order to allow for local settings to be overridden
#
try:
    import superset_config_docker
    from superset_config_docker import *  # noqa: F403

    logger.info(
        "Loaded your Docker configuration at [%s]", superset_config_docker.__file__
    )
except ImportError:
    logger.info("Using default Docker config...")

# Preserve local feature flags after the optional Docker override's wildcard import.
FEATURE_FLAGS.update(_LOCAL_FEATURE_FLAGS)
