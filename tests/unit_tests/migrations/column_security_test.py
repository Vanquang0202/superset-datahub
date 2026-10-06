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

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from superset.connectors.sqla.models import ColumnSecurityPolicy


def test_column_security_migration() -> None:
    """The migration matches ORM metadata, enforces constraints, and round-trips."""
    migration = importlib.import_module(
        "superset.migrations.versions."
        "2026_09_22_0000_c7e2a9b41d06_add_column_security_policy"
    )
    engine = sa.create_engine("sqlite://")
    names = (
        "column_security_policy",
        "column_security_policy_roles",
        "column_security_policy_columns",
    )
    with engine.connect() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        for name in ("tables", "ab_role", "table_columns"):
            parent = sa.Table(
                name, sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True)
            )
            parent.create(connection)
            connection.execute(parent.insert().values(id=1))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            inspector = sa.inspect(connection)
            for name in names:
                model = ColumnSecurityPolicy.metadata.tables[name]
                actual = inspector.get_columns(name)
                assert [col["name"] for col in actual] == list(model.columns.keys())
                for col in actual:
                    expected = model.c[col["name"]]
                    assert col["nullable"] == expected.nullable
                    assert str(col["type"]) == str(expected.type)
                assert inspector.get_pk_constraint(name)["constrained_columns"] == [
                    "id"
                ]
                assert {
                    tuple(c["column_names"])
                    for c in inspector.get_unique_constraints(name)
                } == {
                    tuple(c.columns.keys())
                    for c in model.constraints
                    if isinstance(c, sa.UniqueConstraint)
                }
                assert {
                    (
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                    )
                    for fk in inspector.get_foreign_keys(name)
                } == {
                    (
                        tuple(fk.column_keys),
                        fk.referred_table.name,
                        tuple(element.column.name for element in fk.elements),
                    )
                    for fk in model.foreign_key_constraints
                }
                assert inspector.get_indexes(name) == []
            connection.execute(
                sa.text(
                    "INSERT INTO column_security_policy (id, name, table_id) "
                    "VALUES (1, 'policy', 1)"
                )
            )
            assert (
                connection.execute(
                    sa.text("SELECT enabled FROM column_security_policy")
                ).scalar()
                == 1
            )
            for table, key in ((names[1], "role_id"), (names[2], "column_id")):
                association = sa.Table(table, sa.MetaData(), autoload_with=connection)
                statement = association.insert().values(
                    policy_id=sa.bindparam("policy"), **{key: 1}
                )
                connection.execute(statement, {"policy": 1})
                with pytest.raises(IntegrityError):
                    connection.execute(statement, {"policy": 1})
                with pytest.raises(IntegrityError):
                    connection.execute(statement, {"policy": 999})
            migration.downgrade()
            assert not set(names) & set(sa.inspect(connection).get_table_names())
            migration.upgrade()
            assert set(names) <= set(sa.inspect(connection).get_table_names())
    engine.dispose()
