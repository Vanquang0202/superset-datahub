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
from contextlib import nullcontext
from inspect import unwrap
from unittest.mock import Mock, patch

import pytest
from flask import current_app

from superset.charts.data.api import ChartDataRestApi
from superset.commands.chart.data.get_data_command import ChartDataCommand
from superset.commands.chart.exceptions import ChartDataQueryFailedError
from superset.common.chart_data import ChartDataResultType
from superset.common.query_context_processor import QueryContextProcessor
from superset.common.query_object import QueryObject
from superset.common.utils.query_cache_manager import QueryCacheManager
from superset.connectors.sqla.models import SqlaTable, TableColumn
from superset.errors import SupersetErrorType
from superset.exceptions import QueryObjectValidationError


@pytest.mark.parametrize("allowed", [None, {"don_vi", "ngay"}])
def test_allowed_columns_still_validate(
    app_context: None, allowed: set[str] | None
) -> None:
    """Allowed and unrestricted users retain successful validation."""
    table = SqlaTable(columns=[TableColumn(column_name="ngay")])
    with patch("superset.security_manager.get_allowed_columns", return_value=allowed):
        table._validate_column_security(["ngay"])


def test_forbidden_column_is_identified(app_context: None) -> None:
    """The forbidden-column path rejects with the same message and status."""
    table = SqlaTable(columns=[TableColumn(column_name="ngay")])
    with (
        patch("superset.security_manager.get_allowed_columns", return_value={"don_vi"}),
        pytest.raises(
            QueryObjectValidationError, match="Column ngay is not accessible"
        ) as caught,
    ):
        table._validate_column_security(["ngay"])
    assert caught.value.error_type == SupersetErrorType.COLUMN_SECURITY_ACCESS_ERROR
    assert caught.value.status == 400


@pytest.mark.parametrize(
    "error_type", [None, SupersetErrorType.COLUMN_SECURITY_ACCESS_ERROR]
)
def test_chart_error_identity_reaches_response(
    app_context: None,
    error_type: SupersetErrorType | None,
) -> None:
    """Carry CLS identity through payload/command/API without tagging other errors."""
    error = QueryObjectValidationError("query failed", error_type=error_type)
    datasource = Mock(column_names=["don_vi"])
    context = Mock(
        datasource=datasource, force=False, result_type=ChartDataResultType.FULL
    )
    processor = QueryContextProcessor(context)
    with (
        patch.object(processor, "query_cache_key", return_value="cls-test"),
        patch.object(processor, "get_cache_timeout", return_value=60),
        patch.object(processor, "get_query_result", side_effect=error),
        patch(
            "superset.common.query_context_processor.QueryCacheManager.get",
            return_value=QueryCacheManager(),
        ),
    ):
        payload = processor.get_df_payload(QueryObject(columns=["don_vi"], metrics=[]))
    assert payload.get("error_type") == error_type
    context.get_payload.return_value = {"queries": [payload]}
    with pytest.raises(ChartDataQueryFailedError) as caught:
        ChartDataCommand(context).run()
    response = ChartDataRestApi()._query_error_response(caught.value)
    assert response.status_code == 400
    body = response.get_json()
    assert body["message"] == "Error: query failed"
    if error_type:
        assert body == {
            "message": "Error: query failed",
            "errors": [
                {
                    "message": "Error: query failed",
                    "error_type": "COLUMN_SECURITY_ACCESS_ERROR",
                    "level": "error",
                    "extra": {},
                }
            ],
        }
    else:
        assert body == {"message": "Error: query failed"}


@pytest.mark.parametrize("path", ["sync", "cached", "async"])
@pytest.mark.parametrize(
    "error_class", [QueryObjectValidationError, ChartDataQueryFailedError]
)
@pytest.mark.parametrize("restricted", [False, True])
def test_chart_data_error_http_payload(
    app_context: None,
    path: str,
    error_class: type[QueryObjectValidationError] | type[ChartDataQueryFailedError],
    restricted: bool,
) -> None:
    """Use real FAB response methods for sync, cached, and async-cache failures."""
    message = "Column ngay is not accessible" if restricted else "Invalid query"
    error = error_class(
        message,
        error_type=SupersetErrorType.COLUMN_SECURITY_ACCESS_ERROR
        if restricted
        else None,
    )
    command = Mock(spec=ChartDataCommand)
    command.run.side_effect = error
    api = ChartDataRestApi()
    with current_app.test_request_context("/api/v1/chart/data", method="POST"):
        if path == "async":
            response = api._run_async({}, command)
        else:
            # Bypass only event logging; exercise the real error handler and FAB.
            response = unwrap(ChartDataRestApi._get_data_response)(
                api, command, force_cached=path == "cached"
            )
    command.run.assert_called_once_with(force_cached=path != "sync")
    assert response.status_code == 400
    assert response.mimetype == "application/json"
    if restricted:
        assert response.get_json() == {
            "message": message,
            "errors": [
                {
                    "message": message,
                    "error_type": "COLUMN_SECURITY_ACCESS_ERROR",
                    "level": "error",
                    "extra": {},
                }
            ],
        }
    else:
        assert response.get_json() == {"message": message}


def test_async_worker_preserves_cls_error(app_context: None) -> None:
    """Async events use the same machine-readable CLS identity."""
    from superset.tasks.async_queries import load_chart_data_into_cache

    error = ChartDataQueryFailedError(
        "Error: Column ngay is not accessible",
        error_type=SupersetErrorType.COLUMN_SECURITY_ACCESS_ERROR,
    )
    with (
        patch(
            "superset.tasks.async_queries._override_job_user",
            return_value=nullcontext(),
        ),
        patch("superset.tasks.async_queries.set_form_data"),
        patch("superset.tasks.async_queries._create_query_context_from_form"),
        patch(
            "superset.commands.chart.data.get_data_command.ChartDataCommand.run",
            side_effect=error,
        ),
        patch("superset.tasks.async_queries.async_query_manager") as events,
        pytest.raises(ChartDataQueryFailedError),
    ):
        load_chart_data_into_cache.run({"user_id": 1}, {})
    assert (
        events.update_job.call_args.kwargs["errors"][0]["error_type"]
        == SupersetErrorType.COLUMN_SECURITY_ACCESS_ERROR
    )
