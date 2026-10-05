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

from typing import Any

from flask import request, Response
from flask_appbuilder.api import expose, protect, rison, safe
from flask_appbuilder.api.schemas import get_list_schema
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import permission_name
from marshmallow import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from superset import db, security_manager
from superset.column_security.schemas import (
    ColumnSecurityPolicySchema,
    ColumnSecurityPolicyUpdateSchema,
    openapi_spec_methods_override,
)
from superset.connectors.sqla.models import (
    ColumnSecurityPolicy,
    ColumnSecurityPolicyRoles,
    SqlaTable,
    TableColumn,
)
from superset.constants import MODEL_API_RW_METHOD_PERMISSION_MAP
from superset.views.base_api import BaseSupersetModelRestApi, requires_json


class ColumnSecurityRestApi(BaseSupersetModelRestApi):
    """Admin API for the existing ColumnSecurityPolicy model."""

    datamodel = SQLAInterface(ColumnSecurityPolicy)
    resource_name = "columnsecurity"
    class_permission_name = "Column Level Security"
    method_permission_name = MODEL_API_RW_METHOD_PERMISSION_MAP
    allow_browser_login = True
    openapi_spec_tag = "Column Level Security"
    openapi_spec_methods = openapi_spec_methods_override

    @staticmethod
    def _serialize(policy: ColumnSecurityPolicy) -> dict[str, Any]:
        """Serialize a policy and its runtime relationships."""
        return {
            "id": policy.id,
            "name": policy.name,
            "table_id": policy.table_id,
            "table": {
                "id": policy.table.id,
                "table_name": policy.table.table_name,
                "schema": policy.table.schema,
            },
            "roles": [
                {"id": role.id, "name": role.name, "label": role.name}
                for role in policy.roles
            ],
            "columns": [
                {
                    "id": column.id,
                    "column_name": column.column_name,
                    "label": column.column_name,
                }
                for column in policy.columns
            ],
            "description": policy.description,
            "enabled": policy.enabled,
        }

    @staticmethod
    def _related_page() -> tuple[str, int, int]:
        """Read the common related-resource query parameters."""
        import prison

        page = 0
        page_size = 25
        values: dict[str, Any] = {}

        if query := request.args.get("q", ""):
            values = prison.loads(query)
            page = int(values.get("page", page))
            page_size = int(values.get("page_size", page_size))

        return str(values.get("filter", "")), page, page_size

    @staticmethod
    def _resolve_policy_relationships(
        table_id: int, role_ids: list[int], column_ids: list[int]
    ) -> tuple[SqlaTable, list[Any], list[TableColumn]]:
        """Resolve and validate all policy relationships before saving."""
        table = db.session.get(SqlaTable, table_id)
        if table is None:
            raise ValueError("Dataset not found")

        role_model = security_manager.role_model
        roles = db.session.query(role_model).filter(role_model.id.in_(role_ids)).all()
        if len(roles) != len(set(role_ids)):
            raise ValueError("One or more roles were not found")

        columns = (
            db.session.query(TableColumn)
            .filter(
                TableColumn.id.in_(column_ids),
                TableColumn.table_id == table_id,
            )
            .all()
        )
        if len(columns) != len(set(column_ids)):
            raise ValueError(
                "One or more columns do not belong to the selected dataset"
            )
        return table, roles, columns

    @staticmethod
    def _validate_unique_roles(
        table_id: int, role_ids: list[int], exclude_policy_id: int | None = None
    ) -> None:
        """Ensure each role is assigned to at most one policy for a dataset."""
        if not role_ids:
            return

        role_model = security_manager.role_model
        query = (
            db.session.query(role_model.name)
            .join(
                ColumnSecurityPolicyRoles,
                ColumnSecurityPolicyRoles.c.role_id == role_model.id,
            )
            .join(
                ColumnSecurityPolicy,
                ColumnSecurityPolicy.id == ColumnSecurityPolicyRoles.c.policy_id,
            )
            .filter(
                ColumnSecurityPolicy.table_id == table_id,
                ColumnSecurityPolicyRoles.c.role_id.in_(role_ids),
            )
        )
        if exclude_policy_id is not None:
            query = query.filter(ColumnSecurityPolicy.id != exclude_policy_id)

        if duplicate_roles := sorted({name for (name,) in query.all()}):
            raise ValueError(
                "The following roles already have a Column Level Security policy "
                "for this dataset: "
                + ", ".join(duplicate_roles)
            )

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @rison(get_list_schema)
    def get_list(self, **kwargs: Any) -> Response:
        """Return policies for the admin list view."""
        query = db.session.query(ColumnSecurityPolicy).order_by(
            ColumnSecurityPolicy.name
        )
        values = kwargs.get("rison", {})
        page = int(values.get("page", 0))
        page_size = int(values.get("page_size", 25))
        policies = query.offset(page * page_size).limit(page_size).all()
        return self.response(
            200,
            result=[self._serialize(policy) for policy in policies],
            count=query.count(),
        )

    @expose("/<int:pk>", methods=("GET",))
    @protect()
    @safe
    def get(self, pk: int) -> Response:
        """Return one policy."""
        policy = db.session.get(ColumnSecurityPolicy, pk)
        if policy is None:
            return self.response_404()
        return self.response(200, result=self._serialize(policy))

    @expose("/", methods=("POST",))
    @protect()
    @safe
    @requires_json
    def post(self) -> Response:
        """Create a policy and its role/column mappings."""
        try:
            data = ColumnSecurityPolicySchema().load(request.json)
            self._validate_unique_roles(data["table_id"], data["roles"])
            table, roles, columns = self._resolve_policy_relationships(
                data["table_id"], data["roles"], data["columns"]
            )
            policy = ColumnSecurityPolicy(
                name=data["name"],
                table=table,
                roles=roles,
                columns=columns,
                description=data.get("description"),
                enabled=data.get("enabled", True),
            )
            db.session.add(policy)
            db.session.commit()
        except (ValidationError, ValueError) as ex:
            db.session.rollback()
            message = ex.messages if isinstance(ex, ValidationError) else str(ex)
            return self.response_400(message=message)
        except SQLAlchemyError as ex:
            db.session.rollback()
            return self.response_422(message=str(ex))
        return self.response(201, id=policy.id, result=self._serialize(policy))

    @expose("/<int:pk>", methods=("PUT",))
    @protect()
    @safe
    @requires_json
    def put(self, pk: int) -> Response:
        """Update a policy and replace supplied mappings."""
        policy = db.session.get(ColumnSecurityPolicy, pk)
        if policy is None:
            return self.response_404()
        try:
            data = ColumnSecurityPolicyUpdateSchema().load(request.json)
            table_id = data.get("table_id", policy.table_id)
            role_ids = data.get("roles", [role.id for role in policy.roles])
            column_ids = data.get("columns", [column.id for column in policy.columns])
            self._validate_unique_roles(table_id, role_ids, exclude_policy_id=policy.id)
            table, roles, columns = self._resolve_policy_relationships(
                table_id, role_ids, column_ids
            )
            for field in ("name", "description", "enabled"):
                if field in data:
                    setattr(policy, field, data[field])
            policy.table = table
            policy.roles = roles
            policy.columns = columns
            db.session.commit()
        except (ValidationError, ValueError) as ex:
            db.session.rollback()
            message = ex.messages if isinstance(ex, ValidationError) else str(ex)
            return self.response_400(message=message)
        except SQLAlchemyError as ex:
            db.session.rollback()
            return self.response_422(message=str(ex))
        return self.response(200, id=policy.id, result=self._serialize(policy))

    @expose("/<int:pk>", methods=("DELETE",))
    @protect()
    @safe
    def delete(self, pk: int) -> Response:
        """Delete a policy and its relationship rows."""
        policy = db.session.get(ColumnSecurityPolicy, pk)
        if policy is None:
            return self.response_404()
        db.session.delete(policy)
        db.session.commit()
        return self.response(200, message="Policy deleted")

    @expose("/related/datasets", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def related_datasets(self) -> Response:
        """Return datasets available to the policy editor."""
        filter_text, page, page_size = self._related_page()
        query = db.session.query(SqlaTable).order_by(SqlaTable.table_name)
        if filter_text:
            query = query.filter(SqlaTable.table_name.ilike(f"%{filter_text}%"))
        datasets = query.offset(page * page_size).limit(page_size).all()
        return self.response(
            200,
            result=[
                {
                    "value": table.id,
                    "text": (
                        f"{table.schema}.{table.table_name}"
                        if table.schema
                        else table.table_name
                    ),
                }
                for table in datasets
            ],
            count=query.count(),
        )

    @expose("/related/roles", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def related_roles(self) -> Response:
        """Return Superset roles available to the policy editor."""
        filter_text, page, page_size = self._related_page()
        role_model = security_manager.role_model
        query = db.session.query(role_model).order_by(role_model.name)
        if filter_text:
            query = query.filter(role_model.name.ilike(f"%{filter_text}%"))
        roles = query.offset(page * page_size).limit(page_size).all()
        return self.response(
            200,
            result=[{"value": role.id, "text": role.name} for role in roles],
            count=query.count(),
        )

    @expose("/related/roles/<int:table_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def related_roles_for_dataset(self, table_id: int) -> Response:
        """Return roles with duplicate assignments disabled for a dataset."""
        filter_text, page, page_size = self._related_page()
        policy_id = request.args.get("policy_id", type=int)
        assigned_roles_query = (
            db.session.query(ColumnSecurityPolicyRoles.c.role_id)
            .join(
                ColumnSecurityPolicy,
                ColumnSecurityPolicy.id == ColumnSecurityPolicyRoles.c.policy_id,
            )
            .filter(ColumnSecurityPolicy.table_id == table_id)
        )
        if policy_id is not None:
            assigned_roles_query = assigned_roles_query.filter(
                ColumnSecurityPolicy.id != policy_id
            )
        assigned_role_ids = {
            role_id for (role_id,) in assigned_roles_query.distinct().all()
        }

        role_model = security_manager.role_model
        query = db.session.query(role_model).order_by(role_model.name)
        if filter_text:
            query = query.filter(role_model.name.ilike(f"%{filter_text}%"))
        roles = query.offset(page * page_size).limit(page_size).all()
        return self.response(
            200,
            result=[
                {
                    "value": role.id,
                    "text": role.name,
                    "disabled": role.id in assigned_role_ids,
                }
                for role in roles
            ],
            count=query.count(),
        )

    @expose("/related/columns/<int:table_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def related_columns(self, table_id: int) -> Response:
        """Return columns belonging to the selected dataset."""
        filter_text, page, page_size = self._related_page()
        query = db.session.query(TableColumn).filter(TableColumn.table_id == table_id)
        if filter_text:
            query = query.filter(TableColumn.column_name.ilike(f"%{filter_text}%"))
        columns = (
            query.order_by(TableColumn.column_name)
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return self.response(
            200,
            result=[
                {"value": column.id, "text": column.column_name}
                for column in columns
            ],
            count=query.count(),
        )
