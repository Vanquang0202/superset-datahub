# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
from flask import Flask, jsonify
from flask_cors import CORS


class ConfigurationError(RuntimeError):
    """Raised when a required demo environment variable is missing."""


class SupersetUpstreamError(RuntimeError):
    """Raised when Superset rejects an authentication or token request."""


@dataclass(frozen=True)
class Settings:
    """Configuration required by the demo backend."""

    superset_url: str
    superset_username: str
    superset_password: str
    dashboard_uuid: str
    frontend_origin: str

    @classmethod
    def from_environment(cls) -> Settings:
        values = {
            "superset_url": os.environ.get("SUPERSET_URL", "").rstrip("/"),
            "superset_username": os.environ.get("SUPERSET_USERNAME", ""),
            "superset_password": os.environ.get("SUPERSET_PASSWORD", ""),
            "dashboard_uuid": os.environ.get("SUPERSET_DASHBOARD_UUID", ""),
            "frontend_origin": os.environ.get(
                "FRONTEND_ORIGIN", "http://localhost:5173"
            ),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigurationError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        return cls(**values)


def _raise_for_upstream(response: requests.Response, operation: str) -> None:
    """Raise a safe error without copying upstream response data to the client."""
    if response.ok:
        return
    raise SupersetUpstreamError(
        f"Superset {operation} failed with HTTP {response.status_code}"
    )


def create_app(settings: Settings | None = None) -> Flask:
    """Create the external DataHub demo backend."""
    app = Flask(__name__)
    configured_settings = settings or Settings.from_environment()

    CORS(
        app,
        resources={r"/api/*": {"origins": [configured_settings.frontend_origin]}},
        supports_credentials=False,
    )

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.get("/api/guest-token")
    def guest_token() -> tuple[Any, int]:
        """Authenticate server-side and return only a short-lived guest token."""
        try:
            session = requests.Session()

            login_response = session.post(
                f"{configured_settings.superset_url}/api/v1/security/login",
                json={
                    "username": configured_settings.superset_username,
                    "password": configured_settings.superset_password,
                    "provider": "db",
                },
                timeout=15,
            )
            _raise_for_upstream(login_response, "login")

            access_token = login_response.json().get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise SupersetUpstreamError("Superset login returned no access token")

            csrf_response = session.get(
                f"{configured_settings.superset_url}/api/v1/security/csrf_token/",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            _raise_for_upstream(csrf_response, "CSRF token")

            csrf_token = csrf_response.json().get("result")
            if not isinstance(csrf_token, str) or not csrf_token:
                raise SupersetUpstreamError("Superset CSRF endpoint returned no token")

            guest_response = session.post(
                f"{configured_settings.superset_url}/api/v1/security/guest_token/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-CSRFToken": csrf_token,
                },
                json={
                    "user": {
                        "username": "embedded_guest",
                        "first_name": "Embedded",
                        "last_name": "Guest",
                    },
                    "resources": [
                        {
                            "type": "dashboard",
                            "id": configured_settings.dashboard_uuid,
                        }
                    ],
                    "rls": [],
                },
                timeout=15,
            )

            if not guest_response.ok:
                app.logger.warning(
                    "Guest token upstream response: %s",
                    guest_response.text,
                )

            _raise_for_upstream(guest_response, "guest token creation")
            token = guest_response.json().get("token")
            if not isinstance(token, str) or not token:
                raise SupersetUpstreamError(
                    "Superset guest token response contained no token"
                )
            return jsonify(token=token), 200
        except (requests.RequestException, SupersetUpstreamError) as error:
            app.logger.warning("Guest token request failed: %s", error)
            return jsonify(error="Unable to obtain a guest token"), 502

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5001, debug=False)
