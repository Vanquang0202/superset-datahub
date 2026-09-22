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
"""Create column-level security policy metadata.

Revision ID: c7e2a9b41d06
Revises: 4b2a8c9d3e1f
Create Date: 2026-09-22 00:00:00
"""

import sqlalchemy as sa

from superset.migrations.shared.utils import create_table, drop_table

revision = "c7e2a9b41d06"
down_revision = "4b2a8c9d3e1f"


def upgrade() -> None:
    """Create policies and their role and dataset-column associations."""
    create_table(
        "column_security_policy",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("table_id", sa.Integer, sa.ForeignKey("tables.id"), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    create_table(
        "column_security_policy_roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "policy_id",
            sa.Integer,
            sa.ForeignKey("column_security_policy.id"),
            nullable=False,
        ),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("ab_role.id"), nullable=False),
        sa.UniqueConstraint("policy_id", "role_id"),
    )
    create_table(
        "column_security_policy_columns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "policy_id",
            sa.Integer,
            sa.ForeignKey("column_security_policy.id"),
            nullable=False,
        ),
        sa.Column(
            "column_id",
            sa.Integer,
            sa.ForeignKey("table_columns.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("policy_id", "column_id"),
    )


def downgrade() -> None:
    """Remove associations before their parent policies."""
    drop_table("column_security_policy_columns")
    drop_table("column_security_policy_roles")
    drop_table("column_security_policy")
