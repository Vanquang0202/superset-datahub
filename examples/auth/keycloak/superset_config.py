"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import importlib.util
import os
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Protocol

from flask import Flask
from flask_appbuilder.security.manager import AUTH_DB
from jinja2 import ChoiceLoader, FileSystemLoader
from security_manager import DataHubSecurityManager

from superset.config import *  # noqa: F403,F401

BASE_CONFIG_PATH = os.environ.get(
    "SUPERSET_BASE_CONFIG_PATH",
    "/app/docker/pythonpath_dev/superset_config.py",
)


def _load_base_config(config_path: str) -> None:
    """Load uppercase settings from the existing Superset Docker config."""
    spec = importlib.util.spec_from_file_location(
        "superset_docker_base_config", config_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Superset base config: {config_path}")

    base_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base_config)
    globals().update(
        {
            name: getattr(base_config, name)
            for name in dir(base_config)
            if name.isupper()
        }
    )


_load_base_config(BASE_CONFIG_PATH)

KEYCLOAK_TEMPLATE_DIR = str(Path(__file__).resolve().parent / "templates")
_base_flask_app_mutator: Callable[[Flask], None] | None = globals().get(
    "FLASK_APP_MUTATOR"
)


def _configure_keycloak_templates(app: Flask) -> None:
    """Add the demo templates without replacing Superset's template loader."""
    if _base_flask_app_mutator:
        _base_flask_app_mutator(app)

    demo_loader = FileSystemLoader(KEYCLOAK_TEMPLATE_DIR)
    existing_loader = app.jinja_loader
    if isinstance(existing_loader, ChoiceLoader):
        app.jinja_loader = ChoiceLoader(
            [demo_loader, *existing_loader.loaders]
        )
    elif existing_loader:
        app.jinja_loader = ChoiceLoader([demo_loader, existing_loader])
    else:
        app.jinja_loader = demo_loader


FLASK_APP_MUTATOR = _configure_keycloak_templates

KEYCLOAK_BROWSER_BASE_URL = os.environ.get(
    "KEYCLOAK_BROWSER_BASE_URL", "http://localhost:8081"
).rstrip("/")
KEYCLOAK_INTERNAL_BASE_URL = os.environ.get(
    "KEYCLOAK_INTERNAL_BASE_URL", "http://host.docker.internal:8081"
).rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "superset-demo")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "superset")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_POST_LOGOUT_REDIRECT_URI = os.environ.get(
    "KEYCLOAK_POST_LOGOUT_REDIRECT_URI", "http://127.0.0.1:8089/login/"
)

KEYCLOAK_BROWSER_REALM_URL = (
    f"{KEYCLOAK_BROWSER_BASE_URL}/realms/{KEYCLOAK_REALM}"
)
KEYCLOAK_INTERNAL_REALM_URL = (
    f"{KEYCLOAK_INTERNAL_BASE_URL}/realms/{KEYCLOAK_REALM}"
)


class _AuthlibOAuthClient(Protocol):
    metadata: MutableMapping[str, object]


def _configure_keycloak_issuer(client: _AuthlibOAuthClient) -> None:
    """Validate Keycloak tokens against the issuer exposed to the browser."""
    client.metadata["issuer"] = KEYCLOAK_BROWSER_REALM_URL

# Keycloak authenticates the user; DataHubSecurityManager maps its claims to
# Superset roles after the OAuth callback returns to this application.
CUSTOM_SECURITY_MANAGER = DataHubSecurityManager
AUTH_TYPE = AUTH_DB
# FAB self-registration is disabled; the custom security manager provisions
# Keycloak users directly during the OAuth callback.
AUTH_USER_REGISTRATION = False
AUTH_ROLES_SYNC_AT_LOGIN = True

OAUTH_PROVIDERS = [
    {
        "name": "keycloak",
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": KEYCLOAK_CLIENT_SECRET,
            "api_base_url": f"{KEYCLOAK_INTERNAL_REALM_URL}/protocol/openid-connect/",
            "access_token_url": (
                f"{KEYCLOAK_INTERNAL_REALM_URL}/protocol/openid-connect/token"
            ),
            "server_metadata_url": (
                f"{KEYCLOAK_INTERNAL_REALM_URL}/.well-known/openid-configuration"
            ),
            "compliance_fix": _configure_keycloak_issuer,
            # The browser must be able to reach this URL, so localhost is
            # intentionally distinct from the container-facing URLs above.
            "authorize_url": (
                f"{KEYCLOAK_BROWSER_REALM_URL}/protocol/openid-connect/auth"
            ),
            "request_token_url": None,
            "client_kwargs": {"scope": "openid profile email"},
        },
    }
]
