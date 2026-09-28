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

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

from authlib.integrations.flask_client import OAuth
from flask import current_app, flash, g, redirect, request, session, url_for
from flask_appbuilder import expose
from flask_appbuilder.security.decorators import no_cache
from flask_appbuilder.security.forms import LoginForm_db
from flask_appbuilder.security.views import (
    AuthOAuthView,
    get_safe_redirect,
    WerkzeugResponse,
)
from flask_babel import lazy_gettext
from flask_login import login_user, logout_user

from superset.security.manager import SupersetSecurityManager
from superset.utils import json
from superset.utils.json import JSONDecodeError

logger = logging.getLogger(__name__)


class DataHubAuthView(AuthOAuthView):
    """Combined native Superset and Keycloak login view."""

    route_base = ""
    invalid_login_message = lazy_gettext("Invalid login. Please try again.")

    @expose("/login/", methods=["GET", "POST"])
    @expose("/login/<provider>")
    @no_cache
    def login(self, provider: str | None = None) -> WerkzeugResponse:
        """Keep DB login and expose the existing FAB OAuth redirect."""
        if provider is not None:
            return super().login(provider)

        if g.user is not None and g.user.is_authenticated:
            return redirect(self.appbuilder.get_url_for_index)

        form = LoginForm_db()
        if form.validate_on_submit():
            next_url = self._safe_next_url()
            user = self.appbuilder.sm.auth_user_db(
                form.username.data, form.password.data
            )
            if not user:
                flash(str(self.invalid_login_message), "warning")
                return redirect(self.appbuilder.get_url_for_login_with(next_url))
            session.pop("keycloak_sso", None)
            session.pop("keycloak_id_token", None)
            login_user(user, remember=False)
            return redirect(next_url)

        providers = [
            {
                "name": provider_config["name"],
                "url": url_for(
                    "DataHubAuthView.login",
                    provider=provider_config["name"],
                    next=request.args.get("next", ""),
                ),
            }
            for provider_config in self.appbuilder.sm.oauth_providers
        ]
        return self.render_template(
            "keycloak_login.html",
            title=self.title,
            form=form,
            providers=providers,
            appbuilder=self.appbuilder,
        )

    @expose("/logout/")
    def logout(self) -> WerkzeugResponse:
        """Log out locally and end the Keycloak session for SSO users."""
        keycloak_sso = session.pop("keycloak_sso", False)
        id_token = session.pop("keycloak_id_token", None)
        logout_user()
        session.clear()

        if not keycloak_sso:
            return redirect(
                current_app.config.get(
                    "LOGOUT_REDIRECT_URL", self.appbuilder.get_url_for_index
                )
            )

        logout_url = (
            f"{current_app.config['KEYCLOAK_BROWSER_BASE_URL']}"
            f"/realms/{current_app.config['KEYCLOAK_REALM']}"
            "/protocol/openid-connect/logout"
        )
        logout_params = {
            "post_logout_redirect_uri": current_app.config[
                "KEYCLOAK_POST_LOGOUT_REDIRECT_URI"
            ],
            "client_id": current_app.config["KEYCLOAK_CLIENT_ID"],
        }
        if isinstance(id_token, str) and id_token:
            logout_params["id_token_hint"] = id_token

        logger.debug("Redirecting Keycloak SSO session to RP-initiated logout")
        return redirect(f"{logout_url}?{urlencode(logout_params)}")

    @staticmethod
    def _safe_next_url() -> str:
        """Return the validated post-login destination."""
        return get_safe_redirect(request.args.get("next", ""))


class DataHubSecurityManager(SupersetSecurityManager):
    """Security manager for the Keycloak SSO demonstration.

    Keycloak authenticates the user.  This class receives the resulting OIDC
    claims and performs the demo's authorization decision by mapping external
    role/group names to existing Superset roles.
    """

    EXTERNAL_ROLE_MAPPING = {
        "BI_ADMIN": "Admin",
        "BI_ANALYST": "Gamma",
    }

    def __init__(self, appbuilder: Any) -> None:
        """Initialize DB authentication and the configured OAuth remotes."""
        super().__init__(appbuilder)

        # Superset's standard manager initializes OAuth only for AUTH_OAUTH.
        # The demo keeps AUTH_DB so the native login remains available, then
        # initializes the same FAB OAuth clients for the additional SSO route.
        self.oauth = OAuth(current_app)
        self.oauth_remotes = {}
        for provider in self.oauth_providers:
            provider_name = provider["name"]
            remote = self.oauth.register(provider_name, **provider["remote_app"])
            remote._tokengetter = self.oauth_tokengetter
            if "whitelist" in provider:
                self.oauth_whitelists[provider_name] = provider["whitelist"]
            self.oauth_remotes[provider_name] = remote

    def register_views(self) -> None:
        """Add the combined login view before Superset's native auth views."""
        self.auth_view = self.appbuilder.add_view_no_menu(DataHubAuthView)
        super().register_views()

    def oauth_user_info(
        self, provider: str, response: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Convert Keycloak OIDC claims into Superset's user-info shape."""
        if provider != "keycloak":
            return self.get_oauth_user_info(provider, dict(response or {}))

        userinfo_response = self.oauth_remotes[provider].get("userinfo")
        userinfo = userinfo_response.json()
        if not isinstance(userinfo, Mapping):
            raise ValueError("Keycloak userinfo response must be a JSON object")

        claims = [userinfo, *(self._claims_from_response(response or {}))]
        external_roles = sorted(self._extract_external_roles(claims))

        username = str(
            userinfo.get("preferred_username")
            or userinfo.get("email")
            or userinfo.get("sub")
            or ""
        )
        user_info = {
            "username": username,
            "email": str(userinfo.get("email") or ""),
            "first_name": str(userinfo.get("given_name") or ""),
            "last_name": str(userinfo.get("family_name") or ""),
            # Flask-AppBuilder consumes role_keys when calculating OAuth roles.
            "role_keys": external_roles,
        }

        session["keycloak_sso"] = True
        id_token = (response or {}).get("id_token")
        if isinstance(id_token, str) and id_token:
            session["keycloak_id_token"] = id_token
        else:
            session.pop("keycloak_id_token", None)

        logger.debug(
            "Extracted Keycloak external roles: provider=%s username=%s "
            "roles=%s claim_sources=%s",
            provider,
            username,
            external_roles,
            [self._claim_source(claim) for claim in claims],
        )

        logger.info(
            "Keycloak identity received: provider=%s username=%s email=%s "
            "external_roles=%s",
            provider,
            username,
            user_info["email"],
            external_roles,
        )
        return user_info

    def _oauth_calculate_user_roles(self, userinfo: Mapping[str, Any]) -> list[Any]:
        """Map external Keycloak roles/groups to Superset role objects.

        This intentionally keeps the authorization decision in Python so it is
        easy to review in a demo.  Unknown identities receive the configured
        registration role (Public) and do not inherit Admin or Gamma.
        """
        external_roles = {str(role) for role in userinfo.get("role_keys", []) if role}
        role_names = {
            self.EXTERNAL_ROLE_MAPPING[role]
            for role in external_roles
            if role in self.EXTERNAL_ROLE_MAPPING
        }

        if not role_names:
            role_names.add(self.auth_role_public)

        roles = []
        for role_name in sorted(role_names):
            role = self.find_role(role_name)
            if role:
                roles.append(role)
            else:
                logger.warning("Superset role does not exist: %s", role_name)
        return roles

    def auth_user_oauth(self, userinfo: Mapping[str, Any]) -> Any:
        """Create or synchronize an SSO user without FAB self-registration."""
        username = str(userinfo.get("username") or "")
        if not username:
            logger.warning("Keycloak identity did not contain a username")
            return None

        roles = self._oauth_calculate_user_roles(userinfo)
        user = self.find_user(username=username)
        if user is None:
            return self.add_user(
                username=username,
                first_name=str(userinfo.get("first_name") or ""),
                last_name=str(userinfo.get("last_name") or ""),
                email=str(userinfo.get("email") or ""),
                role=roles,
            )

        changed = False
        if self.auth_roles_sync_at_login:
            user.roles = roles
            changed = True

        for field in ("first_name", "last_name", "email"):
            value = str(userinfo.get(field) or "")
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                changed = True

        if changed:
            self.update_user(user)
        return user

    @classmethod
    def _extract_external_roles(
        cls, claims_list: Iterable[Mapping[str, Any]]
    ) -> set[str]:
        """Extract Keycloak realm roles, client roles, and groups.

        The demo's documented source is ``realm_access.roles``.  The other
        common Keycloak shapes are accepted as a small convenience for client
        scope/protocol-mapper variations.
        """
        roles: set[str] = set()
        for claims in claims_list:
            roles.update(cls._string_values(claims.get("roles")))
            roles.update(cls._nested_roles(claims.get("realm_access")))

            resource_access = claims.get("resource_access")
            if isinstance(resource_access, Mapping):
                for client_claims in resource_access.values():
                    roles.update(cls._nested_roles(client_claims))

            roles.update(cls._string_values(claims.get("groups")))

        return {role.rsplit("/", 1)[-1] for role in roles}

    @classmethod
    def _nested_roles(cls, value: Any) -> set[str]:
        if isinstance(value, Mapping):
            return cls._string_values(value.get("roles"))
        return set()

    @staticmethod
    def _string_values(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
            return {str(item) for item in value if item}
        return set()

    @staticmethod
    def _claims_from_response(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        """Read JWT claims from the OAuth response without logging tokens."""
        claims: list[Mapping[str, Any]] = []
        for key in ("userinfo", "id_token", "access_token"):
            value = response.get(key)
            if isinstance(value, Mapping):
                claims.append(value)
            elif key in ("id_token", "access_token") and isinstance(value, str):
                decoded = DataHubSecurityManager._decode_jwt_payload(value)
                if decoded:
                    claims.append(decoded)
        return claims

    @staticmethod
    def _claim_source(claims: Mapping[str, Any]) -> str:
        """Describe extracted claim content without exposing token values."""
        sources = []
        if "realm_access" in claims:
            sources.append("realm_access")
        if "resource_access" in claims:
            sources.append("resource_access")
        if "groups" in claims:
            sources.append("groups")
        if "roles" in claims:
            sources.append("roles")
        return ",".join(sources) or "userinfo"

    @staticmethod
    def _decode_jwt_payload(token: str) -> Mapping[str, Any] | None:
        """Decode a verified OIDC JWT payload for claim extraction only."""
        try:
            payload = token.split(".")[1]
            padding = "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload + padding))
        except (
            IndexError,
            ValueError,
            TypeError,
            binascii.Error,
            JSONDecodeError,
        ):
            return None
        return decoded if isinstance(decoded, Mapping) else None
