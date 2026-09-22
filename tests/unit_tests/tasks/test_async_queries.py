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
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from flask import g
from flask_babel import lazy_gettext as _
from pytest_mock import MockerFixture

from superset.commands.chart.exceptions import ChartDataQueryFailedError
from superset.errors import ErrorLevel, SupersetError, SupersetErrorType
from superset.exceptions import (
    QueryObjectValidationError,
    SupersetErrorException,
    SupersetErrorsException,
    SupersetException,
)


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("existing_user", [False, True])
def test_async_job_user_restored(
    mocker: MockerFixture, fail: bool, existing_user: bool
) -> None:
    """The job user wins over ambient identity and is cleaned up on errors."""
    from superset.tasks.async_queries import _override_job_user

    origin = SimpleNamespace(id=11, is_active=True, is_authenticated=True)
    previous = SimpleNamespace(id=1)
    mocker.patch(
        "superset.tasks.async_queries.security_manager.get_user_by_id",
        return_value=origin,
    )
    if existing_user:
        g.user = previous
    else:
        g.pop("user", None)
    try:
        with _override_job_user({"user_id": 11}):
            assert g.user is origin
            if fail:
                raise RuntimeError("query failed")
    except RuntimeError:
        assert fail
    assert (g.user is previous) if existing_user else not hasattr(g, "user")


@pytest.mark.parametrize(
    "metadata, user",
    [
        ({"user_id": 11}, None),
        ({"user_id": 11}, SimpleNamespace(is_active=False, is_authenticated=True)),
        ({}, None),
        ({"user_id": None, "guest_token": {"exp": 1}}, None),
    ],
)
def test_async_invalid_identity_marks_job_failed(
    mocker: MockerFixture, metadata: dict[str, Any], user: Any
) -> None:
    """Identity failures never fall back to a broader anonymous execution."""
    from superset.tasks.async_queries import load_chart_data_into_cache

    mocker.patch(
        "superset.tasks.async_queries.security_manager.get_user_by_id",
        return_value=user,
    )
    events = mocker.patch("superset.tasks.async_queries.async_query_manager")
    build = mocker.patch("superset.tasks.async_queries._create_query_context_from_form")
    with pytest.raises(SupersetException):
        load_chart_data_into_cache.run(metadata, {})
    build.assert_not_called()
    assert events.update_job.call_args.args[1] == events.STATUS_ERROR
    assert "guest_token" not in metadata


@pytest.mark.parametrize(
    "user_id, reference, rejected",
    [
        (11, "don_vi", False),
        (11, "muc_tieu", True),
        (11, {"expressionType": "SQL", "sqlExpression": "SUM(muc_tieu)"}, True),
        (11, {"expressionType": "SQL", "sqlExpression": "COUNT(don_vi)"}, False),
        (1, "muc_tieu", False),
    ],
)
def test_async_chart_column_security_context(
    mocker: MockerFixture, user_id: int, reference: Any, rejected: bool
) -> None:
    """Worker validation and fingerprinting use the same identity as sync calls."""
    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.models.core import Database
    from superset.tasks.async_queries import load_chart_data_into_cache

    users = {
        uid: SimpleNamespace(id=uid, is_active=True, is_authenticated=True)
        for uid in (1, 11)
    }
    table = SqlaTable(
        id=3,
        database=Database(database_name="test", sqlalchemy_uri="sqlite://"),
        columns=[TableColumn(column_name=name) for name in ("don_vi", "muc_tieu")],
    )
    mocker.patch(
        "superset.tasks.async_queries.security_manager.get_user_by_id",
        side_effect=users.get,
    )
    resolver = mocker.patch(
        "superset.security_manager.get_allowed_columns",
        side_effect=lambda dataset: {"don_vi"} if g.user.id == 11 else None,
    )
    context = mocker.Mock()
    context.raise_for_access.side_effect = lambda: (
        g.user is users[user_id] or pytest.fail("wrong access-check identity")
    )
    mocker.patch(
        "superset.tasks.async_queries._create_query_context_from_form",
        return_value=context,
    )
    events = mocker.patch("superset.tasks.async_queries.async_query_manager")
    g.user = users[user_id]
    expected_key = table.get_column_security_cache_key()
    if rejected:
        with pytest.raises(QueryObjectValidationError):
            table._validate_column_security([reference])
    else:
        table._validate_column_security([reference])

    def execute(**kwargs: Any) -> dict[str, Any]:
        assert g.user is users[user_id]
        context.raise_for_access.assert_called_once()
        assert table.get_column_security_cache_key() == expected_key
        table._validate_column_security([reference])
        return {"cache_key": "query-context-key"}

    mocker.patch(
        "superset.commands.chart.data.get_data_command.ChartDataCommand.run",
        side_effect=execute,
    )
    # Simulate a broader identity left on the worker's Flask context. Client form
    # data must not replace the server-submitted job principal either.
    g.user = users[1]
    if rejected:
        with pytest.raises(QueryObjectValidationError):
            load_chart_data_into_cache.run({"user_id": user_id}, {"user_id": 1})
        assert events.update_job.call_args.args[1] == events.STATUS_ERROR
    else:
        load_chart_data_into_cache.run({"user_id": user_id}, {"user_id": 1})
        assert events.update_job.call_args.args[1] == events.STATUS_DONE
    assert g.user is users[1]
    assert resolver.called


def test_async_cache_policy_reduction(mocker: MockerFixture) -> None:
    """Retrieval recomputes current access instead of reusing the producer's key."""
    from superset.common.query_context_processor import QueryContextProcessor
    from superset.common.query_object import QueryObject
    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.tasks.async_queries import _override_job_user

    users = {
        uid: SimpleNamespace(id=uid, is_active=True, is_authenticated=True)
        for uid in (1, 11)
    }
    policies: dict[int, set[str] | None] = {1: None, 11: {"don_vi", "khu_vuc"}}
    mocker.patch(
        "superset.tasks.async_queries.security_manager.get_user_by_id",
        side_effect=users.get,
    )
    mocker.patch(
        "superset.security_manager.get_allowed_columns",
        side_effect=lambda dataset: policies[g.user.id],
    )
    table = SqlaTable(
        id=3, columns=[TableColumn(column_name=name) for name in ("don_vi", "khu_vuc")]
    )
    mocker.patch.object(table, "has_extra_cache_key_calls", return_value=False)
    mocker.patch("superset.security_manager.get_rls_cache_key", return_value=[])
    processor = QueryContextProcessor(mocker.Mock(datasource=table))
    query = QueryObject(columns=["khu_vuc"], is_timeseries=False)
    with _override_job_user({"user_id": 1}):
        unrestricted_key = processor.query_cache_key(query)
    with _override_job_user({"user_id": 11}):
        producer_key = processor.query_cache_key(query)
    cache = {unrestricted_key: "broad result", producer_key: "older restricted result"}
    policies[11] = {"don_vi"}
    g.user = users[11]
    assert processor.query_cache_key(query) not in cache
    with pytest.raises(QueryObjectValidationError, match="khu_vuc.*not accessible"):
        table._validate_column_security(["khu_vuc"])


@pytest.mark.parametrize("legacy", [False, True])
def test_async_rechecks_access(mocker: MockerFixture, legacy: bool) -> None:
    """Both workers check current access as the originating user before querying."""
    from superset.tasks.async_queries import (
        load_chart_data_into_cache,
        load_explore_json_into_cache,
    )

    origin = SimpleNamespace(id=11, is_active=True, is_authenticated=True)
    mocker.patch(
        "superset.tasks.async_queries.security_manager.get_user_by_id",
        return_value=origin,
    )
    mocker.patch("superset.tasks.async_queries.async_query_manager")
    mocker.patch(
        "superset.tasks.async_queries.get_datasource_info", return_value=(3, "table")
    )
    viz = mocker.Mock()

    def deny_access() -> None:
        assert g.user is origin
        raise SupersetException("access revoked")

    viz.raise_for_access.side_effect = deny_access
    mocker.patch("superset.tasks.async_queries.get_viz", return_value=viz)
    mocker.patch(
        "superset.tasks.async_queries._create_query_context_from_form", return_value=viz
    )
    run = mocker.patch(
        "superset.commands.chart.data.get_data_command.ChartDataCommand.run"
    )
    with pytest.raises(SupersetException, match="access revoked"):
        task = load_explore_json_into_cache if legacy else load_chart_data_into_cache
        task.run({"user_id": 11}, {})
    viz.get_payload.assert_not_called()
    run.assert_not_called()


def test_async_public_and_guest_identity(mocker: MockerFixture) -> None:
    """Explicit public requests and unexpired authenticated guest claims still work."""
    from superset.tasks.async_queries import _override_job_user

    anonymous = SimpleNamespace(is_authenticated=False)
    guest = SimpleNamespace(is_authenticated=True)
    mocker.patch(
        "superset.tasks.async_queries.security_manager.get_anonymous_user",
        return_value=anonymous,
    )
    guest_loader = mocker.patch(
        "superset.tasks.async_queries.security_manager.get_guest_user_from_token",
        return_value=guest,
    )
    mocker.patch("superset.tasks.async_queries.time.time", return_value=100)
    with _override_job_user({"user_id": None}):
        assert g.user is anonymous
    metadata = {"user_id": None, "guest_token": {"exp": 200}}
    with _override_job_user(metadata):
        assert g.user is guest
    guest_loader.assert_called_once_with({"exp": 200})
    assert "guest_token" not in metadata


@mock.patch("superset.tasks.async_queries.security_manager")
@mock.patch("superset.tasks.async_queries.async_query_manager")
@mock.patch("superset.tasks.async_queries.ChartDataQueryContextSchema")
def test_load_chart_data_into_cache_with_error(
    mock_query_context_schema_cls, mock_async_query_manager, mock_security_manager
):
    """Test that the task is gracefully marked failed in event of error"""
    from superset.tasks.async_queries import load_chart_data_into_cache

    job_metadata = {"user_id": 1}
    form_data = {}
    err_message = "Something went wrong"
    err = ChartDataQueryFailedError(_(err_message))

    mock_user = mock.MagicMock()
    mock_query_context_schema = mock.MagicMock()

    mock_security_manager.get_user_by_id.return_value = mock_user
    mock_async_query_manager.STATUS_ERROR = "error"
    mock_query_context_schema_cls.return_value = mock_query_context_schema

    mock_query_context_schema.load.side_effect = err

    with pytest.raises(ChartDataQueryFailedError):
        load_chart_data_into_cache(job_metadata, form_data)

    expected_errors = [{"message": err_message}]

    mock_async_query_manager.update_job.assert_called_once_with(
        job_metadata, "error", errors=expected_errors
    )


@mock.patch("superset.tasks.async_queries.security_manager")
@mock.patch("superset.tasks.async_queries.async_query_manager")
@mock.patch("superset.tasks.async_queries.ChartDataQueryContextSchema")
def test_load_chart_data_into_cache_with_superset_error_exception(
    mock_query_context_schema_cls, mock_async_query_manager, mock_security_manager
):
    """Test that SupersetErrorException extracts SIP-40 style errors"""
    from superset.tasks.async_queries import load_chart_data_into_cache

    job_metadata = {"user_id": 1}
    form_data = {}

    superset_error = SupersetError(
        message="Access denied to datasource",
        error_type=SupersetErrorType.DATASOURCE_SECURITY_ACCESS_ERROR,
        level=ErrorLevel.ERROR,
        extra={"datasource": "my_table"},
    )
    err = SupersetErrorException(superset_error)

    mock_user = mock.MagicMock()
    mock_query_context_schema = mock.MagicMock()

    mock_security_manager.get_user_by_id.return_value = mock_user
    mock_async_query_manager.STATUS_ERROR = "error"
    mock_query_context_schema_cls.return_value = mock_query_context_schema

    mock_query_context_schema.load.side_effect = err

    with pytest.raises(SupersetErrorException):
        load_chart_data_into_cache(job_metadata, form_data)

    # Verify the full SIP-40 error structure is preserved
    call_args = mock_async_query_manager.update_job.call_args
    assert call_args[0] == (job_metadata, "error")
    errors = call_args[1]["errors"]
    assert len(errors) == 1
    assert errors[0]["message"] == "Access denied to datasource"
    assert errors[0]["error_type"] == SupersetErrorType.DATASOURCE_SECURITY_ACCESS_ERROR
    assert errors[0]["level"] == ErrorLevel.ERROR
    assert errors[0]["extra"]["datasource"] == "my_table"


@mock.patch("superset.tasks.async_queries.security_manager")
@mock.patch("superset.tasks.async_queries.async_query_manager")
@mock.patch("superset.tasks.async_queries.ChartDataQueryContextSchema")
def test_load_chart_data_into_cache_with_superset_errors_exception(
    mock_query_context_schema_cls, mock_async_query_manager, mock_security_manager
):
    """Test that SupersetErrorsException extracts multiple SIP-40 style errors"""
    from superset.tasks.async_queries import load_chart_data_into_cache

    job_metadata = {"user_id": 1}
    form_data = {}

    superset_errors = [
        SupersetError(
            message="Column not found",
            error_type=SupersetErrorType.COLUMN_DOES_NOT_EXIST_ERROR,
            level=ErrorLevel.ERROR,
        ),
        SupersetError(
            message="Table not found",
            error_type=SupersetErrorType.TABLE_DOES_NOT_EXIST_ERROR,
            level=ErrorLevel.WARNING,
        ),
    ]
    err = SupersetErrorsException(superset_errors)

    mock_user = mock.MagicMock()
    mock_query_context_schema = mock.MagicMock()

    mock_security_manager.get_user_by_id.return_value = mock_user
    mock_async_query_manager.STATUS_ERROR = "error"
    mock_query_context_schema_cls.return_value = mock_query_context_schema

    mock_query_context_schema.load.side_effect = err

    with pytest.raises(SupersetErrorsException):
        load_chart_data_into_cache(job_metadata, form_data)

    # Verify all SIP-40 errors are preserved
    call_args = mock_async_query_manager.update_job.call_args
    assert call_args[0] == (job_metadata, "error")
    errors = call_args[1]["errors"]
    assert len(errors) == 2
    assert errors[0]["message"] == "Column not found"
    assert errors[0]["error_type"] == SupersetErrorType.COLUMN_DOES_NOT_EXIST_ERROR
    assert errors[0]["level"] == ErrorLevel.ERROR
    assert errors[1]["message"] == "Table not found"
    assert errors[1]["error_type"] == SupersetErrorType.TABLE_DOES_NOT_EXIST_ERROR
    assert errors[1]["level"] == ErrorLevel.WARNING
