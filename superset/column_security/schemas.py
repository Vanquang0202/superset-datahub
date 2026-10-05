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

from marshmallow import fields, Schema
from marshmallow.validate import Length


openapi_spec_methods_override = {
    "get": {"get": {"summary": "Get a column security policy"}},
    "get_list": {
        "get": {
            "summary": "Get a list of column security policies",
            "description": "Gets a list of column security policies, use Rison or "
            "JSON query parameters for pagination and metadata.",
        }
    },
    "post": {"post": {"summary": "Create a column security policy"}},
    "put": {"put": {"summary": "Update a column security policy"}},
    "delete": {"delete": {"summary": "Delete a column security policy"}},
    "info": {"get": {"summary": "Get metadata information about this API resource"}},
}


class ColumnSecurityPolicySchema(Schema):
    """Payload for creating or updating a column security policy."""

    name = fields.String(required=True, allow_none=False, validate=Length(1, 255))
    table_id = fields.Integer(required=True, allow_none=False)
    roles = fields.List(fields.Integer(), required=True, allow_none=False)
    columns = fields.List(fields.Integer(), required=True, allow_none=False)
    description = fields.String(required=False, allow_none=True)
    enabled = fields.Boolean(required=False, allow_none=False, load_default=True)


class ColumnSecurityPolicyUpdateSchema(Schema):
    """Payload for updating a column security policy."""

    name = fields.String(required=False, allow_none=False, validate=Length(1, 255))
    table_id = fields.Integer(required=False, allow_none=False)
    roles = fields.List(fields.Integer(), required=False, allow_none=False)
    columns = fields.List(fields.Integer(), required=False, allow_none=False)
    description = fields.String(required=False, allow_none=True)
    enabled = fields.Boolean(required=False, allow_none=False)
