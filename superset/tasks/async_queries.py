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
from __future__ import annotations

import copy
import dataclasses
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast, TYPE_CHECKING

from celery.exceptions import SoftTimeLimitExceeded
from flask import current_app, g
from flask_appbuilder.security.sqla.models import User
from marshmallow import ValidationError

from superset.charts.schemas import ChartDataQueryContextSchema
from superset.errors import SupersetErrorType
from superset.exceptions import (
    SupersetErrorException,
    SupersetErrorsException,
    SupersetException,
    SupersetVizException,
)
from superset.extensions import (
    async_query_manager,
    cache_manager,
    celery_app,
    security_manager,
)
from superset.utils.cache import generate_cache_key, set_and_log_cache
from superset.utils.core import override_user
from superset.views.utils import get_datasource_info, get_viz

if TYPE_CHECKING:
    from superset.common.query_context import QueryContext

logger = logging.getLogger(__name__)
query_timeout = current_app.config[
    "SQLLAB_ASYNC_TIME_LIMIT_SEC"
]  # TODO: new config key


def set_form_data(form_data: dict[str, Any]) -> None:
    g.form_data = form_data


def _create_query_context_from_form(form_data: dict[str, Any]) -> QueryContext:
    """
    Create the query context from the form data.

    :param form_data: The task form data
    :returns: The query context
    :raises ValidationError: If the request is incorrect
    """

    try:
        return ChartDataQueryContextSchema().load(form_data)
    except KeyError as ex:
        raise ValidationError("Request is incorrect") from ex


def _load_user_from_job_metadata(job_metadata: dict[str, Any]) -> User:
    """Resolve the server-submitted principal using current metadata."""
    if (user_id := job_metadata.get("user_id")) is not None:
        # logged in user
        user = security_manager.get_user_by_id(user_id)
        if user is None or not user.is_active or not user.is_authenticated:
            raise SupersetException("Async query user is missing or inactive")
    elif "guest_token" in job_metadata:
        guest_token = job_metadata.pop("guest_token")
        # embedded guest user
        # These claims were authenticated at submission. Do not execute a queued
        # job after their authorization has expired, or expose them in job events.
        if (
            not isinstance(guest_token, dict)
            or guest_token.get("exp", 0) <= time.time()
        ):
            raise SupersetException("Async query guest authorization has expired")
        user = security_manager.get_guest_user_from_token(guest_token)
    else:
        if "user_id" not in job_metadata:
            raise SupersetException("Async query identity is missing")
        # An explicit null ID without guest claims represents a public request.
        user = security_manager.get_anonymous_user()
    return user


@contextmanager
def _override_job_user(job_metadata: dict[str, Any]) -> Iterator[None]:
    """Use the job principal even in an existing context, restoring it on errors."""
    had_user = hasattr(g, "user")
    previous_user = getattr(g, "user", None)
    try:
        with override_user(_load_user_from_job_metadata(job_metadata), force=True):
            yield
    finally:
        # override_user does not restore g.user when its body raises.
        if had_user:
            g.user = previous_user
        else:
            g.pop("user", None)


@celery_app.task(name="load_chart_data_into_cache", soft_time_limit=query_timeout)
def load_chart_data_into_cache(
    job_metadata: dict[str, Any],
    form_data: dict[str, Any],
) -> None:
    # pylint: disable=import-outside-toplevel
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    try:
        with _override_job_user(job_metadata):
            set_form_data(form_data)
            query_context = _create_query_context_from_form(form_data)
            command = ChartDataCommand(query_context)
            command.validate()
            result = command.run(cache=True)
            cache_key = result["cache_key"]
            result_url = f"/api/v1/chart/data/{cache_key}"
            async_query_manager.update_job(
                job_metadata,
                async_query_manager.STATUS_DONE,
                result_url=result_url,
            )
    except SoftTimeLimitExceeded as ex:
        logger.warning("A timeout occurred while loading chart data, error: %s", ex)
        raise
    except Exception as ex:
        # Extract SIP-40 style errors when available
        if isinstance(ex, SupersetErrorException):
            errors = [dataclasses.asdict(ex.error)]
        elif isinstance(ex, SupersetErrorsException):
            errors = [dataclasses.asdict(error) for error in ex.errors]
        elif (
            isinstance(ex, SupersetException)
            and ex.error_type == SupersetErrorType.COLUMN_SECURITY_ACCESS_ERROR
        ):
            errors = [{**ex.to_dict(), "level": "error", "extra": {}}]
        else:
            # Fallback for non-Superset exceptions
            error = str(ex.message if hasattr(ex, "message") else ex)
            errors = [{"message": error}]
        async_query_manager.update_job(
            job_metadata, async_query_manager.STATUS_ERROR, errors=errors
        )
        raise


@celery_app.task(name="load_explore_json_into_cache", soft_time_limit=query_timeout)
def load_explore_json_into_cache(  # pylint: disable=too-many-locals
    job_metadata: dict[str, Any],
    form_data: dict[str, Any],
    response_type: str | None = None,
    force: bool = False,
) -> None:
    cache_key_prefix = "ejr-"  # ejr: explore_json request

    try:
        with _override_job_user(job_metadata):
            set_form_data(form_data)
            datasource_id, datasource_type = get_datasource_info(None, None, form_data)

            # Perform a deep copy here so that below we can cache the original
            # value of the form_data object. This is necessary since the viz
            # objects modify the form_data object. If the modified version were
            # to be cached here, it will lead to a cache miss when clients
            # attempt to retrieve the value of the completed async query.
            original_form_data = copy.deepcopy(form_data)

            viz_obj = get_viz(
                datasource_type=cast(str, datasource_type),
                datasource_id=datasource_id,
                form_data=form_data,
                force=force,
            )
            # run query & cache results
            viz_obj.raise_for_access()
            payload = viz_obj.get_payload()
            if viz_obj.has_error(payload):
                raise SupersetVizException(errors=payload["errors"])

            # Cache the original form_data value for async retrieval
            cache_value = {
                "form_data": original_form_data,
                "response_type": response_type,
            }
            cache_key = generate_cache_key(cache_value, cache_key_prefix)
            cache_instance = cache_manager.cache
            cache_timeout = (
                cache_instance.cache.default_timeout if cache_instance.cache else None
            )
            set_and_log_cache(
                cache_instance, cache_key, cache_value, cache_timeout=cache_timeout
            )
            result_url = f"/superset/explore_json/data/{cache_key}"
            async_query_manager.update_job(
                job_metadata,
                async_query_manager.STATUS_DONE,
                result_url=result_url,
            )
    except SoftTimeLimitExceeded as ex:
        logger.warning(
            "A timeout occurred while loading explore json, error: %s", ex
        )
        raise
    except Exception as ex:
        if isinstance(ex, SupersetVizException):
            errors = ex.errors
        else:
            error = ex.message if hasattr(ex, "message") else str(ex)
            errors = [error]  # type: ignore

        async_query_manager.update_job(
            job_metadata, async_query_manager.STATUS_ERROR, errors=errors
        )
        raise
