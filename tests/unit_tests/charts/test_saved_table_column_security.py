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
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from superset.charts.data.api import ChartDataRestApi
from superset.connectors.sqla.models import SqlaTable, TableColumn
from superset.exceptions import QueryObjectValidationError
from superset.models.core import Database

COLUMNS = ["don_vi", "khu_vuc", "trang_thai", "so_luong", "muc_tieu"]
ALLOWED = set(COLUMNS[:3])


@pytest.fixture
def table() -> SqlaTable:
    """Create metadata without modifying a persisted datasource."""
    return SqlaTable(
        table_name="cls_demo",
        database=Database(database_name="test", sqlalchemy_uri="sqlite://"),
        columns=[TableColumn(column_name=name) for name in COLUMNS],
    )


@pytest.fixture
def payload() -> dict[str, Any]:
    """Represent the table plugin's saved raw-records request."""
    return {
        "datasource": {"id": 1, "type": "table"},
        "form_data": {
            "slice_id": 42,
            "viz_type": "table",
            "query_mode": "raw",
            "all_columns": list(COLUMNS),
        },
        "queries": [{"columns": list(COLUMNS), "metrics": []}],
    }


def sanitize(
    payload: dict[str, Any], table: SqlaTable, allowed: set[str] | None = ALLOWED
) -> dict[str, Any]:
    """Run the helper with a real datasource and a mocked policy lookup."""
    with (
        patch("superset.charts.data.api.get_datasource_by_id", return_value=table),
        patch(
            "superset.charts.data.api.security_manager", new_callable=MagicMock
        ) as manager,
    ):
        manager.get_allowed_columns.return_value = allowed
        return ChartDataRestApi()._sanitize_saved_table_columns_for_column_security(
            payload
        )


@pytest.mark.parametrize(
    "allowed, expected", [(ALLOWED, COLUMNS[:3]), (None, COLUMNS), (set(), [])]
)
def test_saved_raw_columns(
    payload: dict[str, Any],
    table: SqlaTable,
    allowed: set[str] | None,
    expected: list[str],
) -> None:
    """Only forbidden physical display columns are removed, without mutation."""
    original = deepcopy(payload)
    result = sanitize(payload, table, allowed)
    assert result["queries"][0]["columns"] == expected
    assert result["form_data"]["all_columns"] == expected
    assert payload == original
    assert [column.column_name for column in table.columns] == COLUMNS
    if allowed is None:
        assert result is payload


@pytest.mark.parametrize(
    "change",
    [
        {"slice_id": None},
        {"viz_type": "pie"},
        {"query_mode": "aggregate"},
    ],
)
def test_ineligible_chart(
    payload: dict[str, Any], table: SqlaTable, change: dict[str, Any]
) -> None:
    """Unsaved, non-table, and aggregate requests preserve all references."""
    payload["form_data"].update(change)
    assert sanitize(payload, table) is payload


def test_legacy_raw_mode(payload: dict[str, Any], table: SqlaTable) -> None:
    """Legacy all_columns selections imply raw mode as in the table plugin."""
    del payload["form_data"]["query_mode"]
    assert sanitize(payload, table)["queries"][0]["columns"] == COLUMNS[:3]


@pytest.mark.parametrize(
    "key, value, validation_key, references",
    [
        (
            "metrics",
            [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "SUM",
                    "column": {"column_name": "muc_tieu"},
                }
            ],
            "metric_references",
            [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "SUM",
                    "column": {"column_name": "muc_tieu"},
                }
            ],
        ),
        (
            "metrics",
            [{"expressionType": "SQL", "sqlExpression": "SUM(muc_tieu)"}],
            "metric_references",
            [{"expressionType": "SQL", "sqlExpression": "SUM(muc_tieu)"}],
        ),
        ("extras", {"where": "muc_tieu > 0"}, "sql_expressions", ["muc_tieu > 0"]),
        (
            "filters",
            [{"col": "muc_tieu", "op": ">", "val": 0}],
            "filter_references",
            ["muc_tieu"],
        ),
        ("orderby", [["muc_tieu", False]], "orderby_references", ["muc_tieu"]),
    ],
)
def test_forbidden_references_still_rejected(
    app_context: None,
    payload: dict[str, Any],
    table: SqlaTable,
    key: str,
    value: Any,
    validation_key: str,
    references: list[Any],
) -> None:
    """Retained references still fail the existing, unmodified CLS validator."""
    payload["queries"][0][key] = value
    result = sanitize(payload, table)
    assert result["queries"][0][key] == value
    with (
        patch("superset.security_manager.get_allowed_columns", return_value=ALLOWED),
        pytest.raises(QueryObjectValidationError),
    ):
        table._validate_column_security(
            result["queries"][0]["columns"],
            metric_references=references
            if validation_key == "metric_references"
            else None,
            filter_references=references
            if validation_key == "filter_references"
            else None,
            orderby_references=references
            if validation_key == "orderby_references"
            else None,
            sql_expressions=references if validation_key == "sql_expressions" else None,
        )


def test_expressions_and_calculated_columns_retained(
    payload: dict[str, Any],
    table: SqlaTable,
) -> None:
    """SQL objects, unknown strings, and calculated columns are never pruned."""
    table.columns.append(
        TableColumn(column_name="calculated", expression="muc_tieu + 1")
    )
    expressions = [
        "calculated",
        "SUM(muc_tieu)",
        {"label": "muc_tieu", "sqlExpression": "muc_tieu", "expressionType": "SQL"},
        {"label": "alias", "sqlExpression": "muc_tieu", "isColumnReference": True},
    ]
    payload["queries"][0]["columns"].extend(expressions)
    assert (
        sanitize(payload, table)["queries"][0]["columns"] == COLUMNS[:3] + expressions
    )


def test_allowed_chart(
    app_context: None, payload: dict[str, Any], table: SqlaTable
) -> None:
    """An allowed raw chart passes normal column validation."""
    payload["queries"][0]["columns"] = COLUMNS[:3]
    payload["form_data"]["all_columns"] = COLUMNS[:3]
    result = sanitize(payload, table)
    assert result == payload
    with patch("superset.security_manager.get_allowed_columns", return_value=ALLOWED):
        table._validate_column_security(result["queries"][0]["columns"])


@pytest.mark.parametrize("form_data", [None, [], "invalid", {}])
def test_invalid_form_data(
    payload: dict[str, Any], table: SqlaTable, form_data: Any
) -> None:
    """Malformed form data is left to schema validation."""
    payload["form_data"] = form_data
    assert sanitize(payload, table) is payload


def test_other_datasource(payload: dict[str, Any], table: SqlaTable) -> None:
    """SQL Lab datasources do not participate in table column policies."""
    payload["datasource"]["type"] = "query"
    assert sanitize(payload, table) is payload


def test_missing_slice_id(payload: dict[str, Any], table: SqlaTable) -> None:
    """Direct requests without a saved chart ID retain forbidden columns."""
    del payload["form_data"]["slice_id"]
    assert sanitize(payload, table) is payload


def test_multiple_queries_preserve_other_fields(
    payload: dict[str, Any],
    table: SqlaTable,
) -> None:
    """Only columns and all_columns change across all query objects."""
    payload["queries"][0].update(
        {
            "groupby": ["muc_tieu"],
            "granularity": "muc_tieu",
            "extras": {"having": "SUM(muc_tieu) > 0"},
            "orderby": [["muc_tieu", False]],
        }
    )
    payload["queries"].append({"columns": ["so_luong", "don_vi"]})
    payload["form_data"]["groupby"] = ["muc_tieu"]
    expected = deepcopy(payload)
    expected["queries"][0]["columns"] = COLUMNS[:3]
    expected["queries"][1]["columns"] = ["don_vi"]
    expected["form_data"]["all_columns"] = COLUMNS[:3]
    assert sanitize(payload, table) == expected


@pytest.fixture
def temporal_payload(payload: dict[str, Any], table: SqlaTable) -> dict[str, Any]:
    """Add both representations of the mandatory no-op temporal filter."""
    table.columns.append(TableColumn(column_name="ngay", type="DATE", is_dttm=True))
    payload["queries"][0]["filters"] = [
        {"col": "ngay", "op": "TEMPORAL_RANGE", "val": "No filter"}
    ]
    payload["form_data"]["adhoc_filters"] = [
        {
            "subject": "ngay",
            "operator": "TEMPORAL_RANGE",
            "comparator": "No filter",
            "expressionType": "SIMPLE",
            "clause": "WHERE",
        }
    ]
    return payload


def test_forbidden_noop_temporal_filter_removed(
    temporal_payload: dict[str, Any],
    table: SqlaTable,
) -> None:
    """Drop both no-op filter representations without mutating the request."""
    original = deepcopy(temporal_payload)
    result = sanitize(temporal_payload, table)
    assert result["queries"][0]["filters"] == []
    assert result["form_data"]["adhoc_filters"] == []
    assert result["queries"][0]["columns"] == COLUMNS[:3]
    assert temporal_payload == original
    assert table.columns[-1].column_name == "ngay"


@pytest.mark.parametrize(
    "value", ["2026-01-01 : 2026-02-01", "Last week", "", None, [], "No filter "]
)
def test_active_or_invalid_temporal_filter_retained(
    app_context: None,
    temporal_payload: dict[str, Any],
    table: SqlaTable,
    value: Any,
) -> None:
    """Only the explicit no-range sentinel is removed; other values fail CLS."""
    temporal_payload["queries"][0]["filters"][0]["val"] = value
    temporal_payload["form_data"]["adhoc_filters"][0]["comparator"] = value
    result = sanitize(temporal_payload, table)
    assert result["queries"][0]["filters"] == temporal_payload["queries"][0]["filters"]
    assert (
        result["form_data"]["adhoc_filters"]
        == temporal_payload["form_data"]["adhoc_filters"]
    )
    with (
        patch("superset.security_manager.get_allowed_columns", return_value=ALLOWED),
        pytest.raises(QueryObjectValidationError, match="ngay"),
    ):
        table._validate_column_security(
            result["queries"][0]["columns"],
            filter_references=[
                clause["col"] for clause in result["queries"][0]["filters"]
            ],
        )


@pytest.mark.parametrize("allowed", [ALLOWED | {"ngay"}, None])
def test_allowed_or_unrestricted_temporal_filter_retained(
    temporal_payload: dict[str, Any],
    table: SqlaTable,
    allowed: set[str] | None,
) -> None:
    """Allowed time columns and unrestricted users keep their no-op filters."""
    result = sanitize(temporal_payload, table, allowed)
    assert result["queries"][0]["filters"] == temporal_payload["queries"][0]["filters"]
    assert (
        result["form_data"]["adhoc_filters"]
        == temporal_payload["form_data"]["adhoc_filters"]
    )


@pytest.mark.parametrize("change", ["unsaved", "non_table", "aggregate"])
def test_ineligible_temporal_filter_retained(
    app_context: None,
    temporal_payload: dict[str, Any],
    table: SqlaTable,
    change: str,
) -> None:
    """Direct and other ineligible requests retain the forbidden filter for CLS."""
    if change == "unsaved":
        del temporal_payload["form_data"]["slice_id"]
    elif change == "non_table":
        temporal_payload["form_data"]["viz_type"] = "line"
    else:
        temporal_payload["form_data"]["query_mode"] = "aggregate"
    result = sanitize(temporal_payload, table)
    assert result is temporal_payload
    with (
        patch("superset.security_manager.get_allowed_columns", return_value=ALLOWED),
        pytest.raises(QueryObjectValidationError, match="ngay"),
    ):
        table._validate_column_security(
            [], filter_references=[result["queries"][0]["filters"][0]["col"]]
        )


def test_unrelated_filters_retained(
    temporal_payload: dict[str, Any],
    table: SqlaTable,
) -> None:
    """Removing a no-op time filter preserves unrelated query and adhoc filters."""
    query_filter = {"col": "muc_tieu", "op": "==", "val": "No filter"}
    adhoc_filter = {
        "subject": "muc_tieu",
        "operator": "==",
        "comparator": "No filter",
        "expressionType": "SIMPLE",
        "clause": "WHERE",
    }
    temporal_payload["queries"][0]["filters"].append(query_filter)
    temporal_payload["form_data"]["adhoc_filters"].append(adhoc_filter)
    result = sanitize(temporal_payload, table)
    assert result["queries"][0]["filters"] == [query_filter]
    assert result["form_data"]["adhoc_filters"] == [adhoc_filter]


@pytest.mark.parametrize(
    "change",
    [{"expressionType": "SQL", "sqlExpression": "ngay > 0"}, {"clause": "HAVING"}],
)
def test_non_simple_where_temporal_filter_retained(
    temporal_payload: dict[str, Any],
    table: SqlaTable,
    change: dict[str, Any],
) -> None:
    """Temporal-looking SQL and HAVING expressions must not be pruned."""
    temporal_payload["form_data"]["adhoc_filters"][0].update(change)
    result = sanitize(temporal_payload, table)
    assert (
        result["form_data"]["adhoc_filters"]
        == temporal_payload["form_data"]["adhoc_filters"]
    )


def test_calculated_temporal_filter_retained(
    temporal_payload: dict[str, Any],
    table: SqlaTable,
) -> None:
    """Calculated time-column references remain subject to CLS validation."""
    table.columns[-1].expression = "DATE(muc_tieu)"
    result = sanitize(temporal_payload, table)
    assert result["queries"][0]["filters"] == temporal_payload["queries"][0]["filters"]
    assert (
        result["form_data"]["adhoc_filters"]
        == temporal_payload["form_data"]["adhoc_filters"]
    )


def test_localized_noop_temporal_filter_removed(
    temporal_payload: dict[str, Any],
    table: SqlaTable,
) -> None:
    """Match the date parser's localized no-range sentinel as well."""
    temporal_payload["queries"][0]["filters"][0]["val"] = "Không lọc"
    temporal_payload["form_data"]["adhoc_filters"][0]["comparator"] = "Không lọc"
    with patch("superset.charts.data.api._", return_value="Không lọc"):
        result = sanitize(temporal_payload, table)
    assert result["queries"][0]["filters"] == []
    assert result["form_data"]["adhoc_filters"] == []
