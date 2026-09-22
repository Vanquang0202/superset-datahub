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

from uuid import uuid4

import pytest
from flask.ctx import AppContext
from flask_appbuilder.security.sqla.models import Role, User

from superset import db, security_manager
from superset.connectors.sqla.models import ColumnSecurityPolicy, SqlaTable, TableColumn
from superset.exceptions import QueryObjectValidationError
from superset.models.core import Database
from superset.utils.core import override_user


def test_column_security_on_migrated_database(app_context: AppContext) -> None:
    """Resolve real policy relationships on the migration-created metadata schema."""
    suffix = uuid4().hex
    role = Role(name=f"cls_{suffix}")
    user = User(
        username=f"cls_{suffix}",
        first_name="Column",
        last_name="Security",
        email=f"cls_{suffix}@example.com",
        roles=[role],
        active=True,
    )
    table = SqlaTable(
        table_name=f"cls_{suffix}",
        database=Database(database_name=f"cls_{suffix}", sqlalchemy_uri="sqlite://"),
        columns=[
            TableColumn(column_name="visible", type="TEXT"),
            TableColumn(column_name="restricted", type="TEXT"),
        ],
    )
    try:
        db.session.add_all([user, table])
        db.session.flush()
        with override_user(user, force=True):
            assert security_manager.get_allowed_columns(table) is None
            policy = ColumnSecurityPolicy(
                name=f"cls_{suffix}", table=table, roles=[role]
            )
            db.session.add(policy)
            db.session.flush()
            assert security_manager.get_allowed_columns(table) == set()
            with pytest.raises(QueryObjectValidationError):
                table._validate_column_security(["visible"])
            policy.columns = [table.columns[0]]
            db.session.flush()
            assert security_manager.get_allowed_columns(table) == {"visible"}
            table._validate_column_security(["visible"])
            with pytest.raises(QueryObjectValidationError):
                table._validate_column_security(["restricted"])
            policy.enabled = False
            db.session.flush()
            assert security_manager.get_allowed_columns(table) is None
    finally:
        db.session.rollback()
