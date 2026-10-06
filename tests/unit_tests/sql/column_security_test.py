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

import pytest

from superset.exceptions import SupersetParseError
from superset.sql.column_security import get_column_security_columns


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("visible", {"visible"}),
        ("SUM(visible)", {"visible"}),
        ("COUNT(*)", set()),
        ("1", set()),
        ("visible + other", {"visible", "other"}),
    ],
)
def test_column_security_expression(expression: str, expected: set[str]) -> None:
    """Return only identifiers bound to the current dataset."""
    assert get_column_security_columns(expression, "sqlite") == expected


@pytest.mark.parametrize(
    "expression, engine",
    [
        ("", "sqlite"),
        ("visible", "unsupported"),
        ("{{ visible }}", "sqlite"),
        ("visible, other", "sqlite"),
        ("visible FROM other", "sqlite"),
        ("(SELECT visible FROM other)", "sqlite"),
        ("custom_function(visible)", "sqlite"),
        ("*", "sqlite"),
        ("other.visible", "sqlite"),
        ("?", "sqlite"),
        ("visible; SELECT other", "sqlite"),
        ("SUM(", "sqlite"),
    ],
)
def test_column_security_expression_rejected(expression: str, engine: str) -> None:
    """Reject unknown scopes, templates, parameters, and invalid syntax."""
    with pytest.raises((SupersetParseError, ValueError)):
        get_column_security_columns(expression, engine)
