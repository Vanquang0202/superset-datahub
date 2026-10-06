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

from sqlglot import exp

from superset.sql.parse import SQLGLOT_DIALECTS, SQLStatement


def get_column_security_columns(expression: str, engine: str) -> set[str]:
    """Resolve a source-free SQL expression, rejecting ambiguous column scopes."""
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or engine not in SQLGLOT_DIALECTS
        or any(marker in expression for marker in ("{{", "{%", "{#"))
    ):
        raise ValueError("SQL expression cannot be safely resolved for column security")
    statement = SQLStatement(f"SELECT {expression}", engine=engine)
    parsed = statement._parsed  # pylint: disable=protected-access
    # A fragment must not introduce FROM, WHERE, UNION, another projection,
    # or a nested query whose column scope differs from this dataset.
    if (
        not isinstance(parsed, exp.Select)
        or len(parsed.expressions) != 1
        or any(value for key, value in parsed.args.items() if key != "expressions")
    ):
        raise ValueError("SQL expression cannot be safely resolved for column security")
    for node in parsed.walk():
        if node is not parsed and isinstance(
            node,
            (
                exp.Query,
                exp.Table,
                exp.Command,
                exp.Anonymous,
                exp.Parameter,
                exp.Placeholder,
                exp.Lambda,
                exp.Columns,
            ),
        ):
            raise ValueError(
                "SQL expression cannot be safely resolved for column security"
            )
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            raise ValueError(
                "SQL expression cannot be safely resolved for column security"
            )
        if isinstance(node, exp.Column) and (
            node.table
            or node.db
            or node.catalog
            or not isinstance(node.this, exp.Identifier)
        ):
            raise ValueError(
                "SQL expression cannot be safely resolved for column security"
            )
    return {column.name for column in parsed.find_all(exp.Column)}
