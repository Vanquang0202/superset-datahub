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
from flask import Response
from flask.ctx import AppContext
from flask_appbuilder.security.sqla.models import Role, User

from superset import db, security_manager
from superset.connectors.sqla.models import ColumnSecurityPolicy, SqlaTable, TableColumn
from superset.exceptions import QueryObjectValidationError
from superset.models.core import Database
from superset.utils.core import override_user
from tests.integration_tests.base_tests import SupersetTestCase
from tests.integration_tests.constants import ADMIN_USERNAME


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


class TestColumnSecurityAdminAPI(SupersetTestCase):
    """Exercise CRUD and relationship validation for the CLS admin API."""

    @pytest.fixture
    def policy_datasets(self, app_context: AppContext):
        first = SqlaTable(
            table_name=f"cls_api_{uuid4().hex}",
            database_id=1,
            columns=[
                TableColumn(column_name="visible", type="TEXT"),
                TableColumn(column_name="restricted", type="TEXT"),
            ],
        )
        second = SqlaTable(
            table_name=f"cls_other_{uuid4().hex}",
            database_id=1,
            columns=[TableColumn(column_name="foreign_column", type="TEXT")],
        )
        db.session.add_all([first, second])
        db.session.flush()
        try:
            yield first, second
        finally:
            db.session.delete(first)
            db.session.delete(second)
            db.session.commit()

    @staticmethod
    def _get_policy_datasets() -> tuple[SqlaTable, SqlaTable]:
        """Return the datasets created by the policy_datasets fixture."""
        first = (
            db.session.query(SqlaTable)
            .filter(SqlaTable.table_name.like("cls_api_%"))
            .order_by(SqlaTable.__table__.c.id.desc())
            .first()
        )
        second = (
            db.session.query(SqlaTable)
            .filter(SqlaTable.table_name.like("cls_other_%"))
            .order_by(SqlaTable.__table__.c.id.desc())
            .first()
        )
        assert first is not None
        assert second is not None
        return first, second

    @pytest.mark.usefixtures("policy_datasets")
    def test_policy_crud_and_dataset_column_validation(self) -> None:
        self.login(ADMIN_USERNAME)
        first, second = self._get_policy_datasets()
        role = security_manager.find_role("Alpha")
        assert role is not None

        payload = {
            "name": f"policy_{uuid4().hex}",
            "table_id": first.id,
            "roles": [role.id],
            "columns": [first.columns[0].id],
            "description": "API policy",
            "enabled": True,
        }
        response = self.client.post("/api/v1/columnsecurity/", json=payload)
        assert response.status_code == 201
        policy_id = response.json["id"]

        policy = db.session.get(ColumnSecurityPolicy, policy_id)
        assert policy is not None
        assert policy.table_id == first.id
        assert [item.id for item in policy.roles] == [role.id]
        assert [item.id for item in policy.columns] == [first.columns[0].id]

        response = self.client.get(f"/api/v1/columnsecurity/{policy_id}")
        assert response.status_code == 200
        assert response.json["result"]["table_id"] == first.id

        response = self.client.put(
            f"/api/v1/columnsecurity/{policy_id}",
            json={**payload, "columns": [first.columns[0].id, first.columns[1].id]},
        )
        assert response.status_code == 200
        db.session.expire_all()
        policy = db.session.get(ColumnSecurityPolicy, policy_id)
        assert policy is not None
        assert {item.id for item in policy.columns} == {
            first.columns[0].id,
            first.columns[1].id,
        }

        response = self.client.put(
            f"/api/v1/columnsecurity/{policy_id}",
            json={**payload, "columns": [second.columns[0].id]},
        )
        assert response.status_code == 400

        response = self.client.delete(f"/api/v1/columnsecurity/{policy_id}")
        assert response.status_code == 200
        assert db.session.get(ColumnSecurityPolicy, policy_id) is None

    @pytest.mark.usefixtures("policy_datasets")
    def test_policy_rejects_duplicate_role_on_same_dataset(self) -> None:
        """A role can have only one policy per dataset."""
        self.login(ADMIN_USERNAME)
        first, second = self._get_policy_datasets()
        role = security_manager.find_role("Alpha")
        assert role is not None

        def create(table: SqlaTable, name: str) -> Response:
            return self.client.post(
                "/api/v1/columnsecurity/",
                json={
                    "name": name,
                    "table_id": table.id,
                    "roles": [role.id],
                    "columns": [table.columns[0].id],
                },
            )

        first_response = create(first, f"first_{uuid4().hex}")
        assert first_response.status_code == 201
        duplicate_response = create(first, f"duplicate_{uuid4().hex}")
        assert duplicate_response.status_code == 400
        assert role.name in str(duplicate_response.json)

        different_dataset_response = create(second, f"different_{uuid4().hex}")
        assert different_dataset_response.status_code == 201

        for response in (first_response, different_dataset_response):
            self.client.delete(f"/api/v1/columnsecurity/{response.json['id']}")

    @pytest.mark.usefixtures("policy_datasets")
    def test_policy_update_allows_own_roles_and_rejects_other_policy_roles(
        self,
    ) -> None:
        """Updates exclude the policy being edited from duplicate checks."""
        self.login(ADMIN_USERNAME)
        first, _ = self._get_policy_datasets()
        own_role = security_manager.find_role("Alpha")
        other_role = security_manager.find_role("Gamma")
        assert own_role is not None
        assert other_role is not None

        def create(role_id: int, name: str) -> int:
            response = self.client.post(
                "/api/v1/columnsecurity/",
                json={
                    "name": name,
                    "table_id": first.id,
                    "roles": [role_id],
                    "columns": [first.columns[0].id],
                },
            )
            assert response.status_code == 201
            return response.json["id"]

        own_policy_id = create(own_role.id, f"own_{uuid4().hex}")
        other_policy_id = create(other_role.id, f"other_{uuid4().hex}")
        try:
            response = self.client.put(
                f"/api/v1/columnsecurity/{own_policy_id}",
                json={"roles": [own_role.id]},
            )
            assert response.status_code == 200

            response = self.client.put(
                f"/api/v1/columnsecurity/{own_policy_id}",
                json={"roles": [own_role.id, other_role.id]},
            )
            assert response.status_code == 400
        finally:
            self.client.delete(f"/api/v1/columnsecurity/{own_policy_id}")
            self.client.delete(f"/api/v1/columnsecurity/{other_policy_id}")

    @pytest.mark.usefixtures("policy_datasets")
    def test_policy_supports_multiple_roles(self) -> None:
        """One policy can continue to contain multiple roles."""
        self.login(ADMIN_USERNAME)
        first, _ = self._get_policy_datasets()
        roles = [
            security_manager.find_role("Alpha"),
            security_manager.find_role("Gamma"),
        ]
        assert all(role is not None for role in roles)
        role_ids = [role.id for role in roles if role is not None]
        response = self.client.post(
            "/api/v1/columnsecurity/",
            json={
                "name": f"multi_{uuid4().hex}",
                "table_id": first.id,
                "roles": role_ids,
                "columns": [first.columns[0].id],
            },
        )
        assert response.status_code == 201
        policy_id = response.json["id"]
        try:
            assert {role["id"] for role in response.json["result"]["roles"]} == set(
                role_ids
            )
        finally:
            self.client.delete(f"/api/v1/columnsecurity/{policy_id}")
