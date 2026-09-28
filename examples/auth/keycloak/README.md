<!--
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
-->

# Keycloak + OIDC authentication demo

This example demonstrates native Superset login plus external company SSO with
Keycloak and custom authorization inside Superset. The Keycloak users are
neutral test identities that simulate company employee accounts.

## Flow

```text
User
  -> Superset username/password OR "Login with Company Account"
  -> Keycloak authenticates the company identity
  -> OIDC callback returns to Superset
  -> DataHubSecurityManager reads identity and role/group claims
  -> BI_ADMIN / BI_ANALYST maps to Admin / Gamma
  -> DataHubSecurityManager creates or synchronizes the Superset user
```

Native users continue through Superset's existing DB authentication. Keycloak
performs authentication for the company-account option. Superset's
`DataHubSecurityManager` performs the demo authorization decision and directly
creates or synchronizes the Superset user during the OAuth callback. FAB
self-registration remains disabled.

## Files

- `superset_config.py` configures OIDC and selects the custom security manager.
- `security_manager.py` extracts Keycloak claims and maps external roles/groups.
- `templates/keycloak_login.html` preserves the native login form and adds the
  generic company-account button.
- `docker-compose.keycloak.yml` starts an isolated Keycloak instance on port
  `8081`; it does not modify the Superset Docker stack.

## Start Keycloak

From this directory:

```bash
docker compose -f docker-compose.keycloak.yml up -d
```

Open `http://localhost:8081`, sign in to the temporary Keycloak admin console
with the bootstrap credentials, and create the `superset-demo` realm.

Create an OpenID Connect client:

- Client ID: `superset`
- Client authentication: enabled
- Valid redirect URI: `http://127.0.0.1:8089/oauth-authorized/keycloak`
- Web origin: `http://127.0.0.1:8089`
- Client scopes: `openid`, `profile`, and `email`

Copy the generated client secret. Supply it through
`KEYCLOAK_CLIENT_SECRET`; do not put it in this repository.

Create realm roles `BI_ADMIN` and `BI_ANALYST`, then create these test users
to simulate company employee identities:

| User | Email | Keycloak role | Superset role |
| --- | --- | --- | --- |
| `admin_user` | `admin.user@datahub.local` | `BI_ADMIN` | `Admin` |
| `analyst_user` | `analyst.user@datahub.local` | `BI_ANALYST` | `Gamma` |

Assign each realm role to its corresponding user. To include roles in the
claims Superset reads, configure a Keycloak client-scope protocol mapper:

1. Open the client scope used by `superset` (or create a dedicated scope such
   as `superset-roles`).
2. Add a mapper for realm roles using the built-in ** realm roles** mapper.
3. Set **Add to userinfo** to on. Add to ID token and access token as desired.
4. Attach the scope to the `superset` client as a default client scope.

This demo's documented role source is `realm_access.roles` in the OIDC
userinfo response. The Python extractor also accepts `roles`,
`resource_access.<client>.roles`, and `groups` to make the example tolerant of
common Keycloak mapper layouts. Group names are normalized by removing a
leading path such as `/BI_ANALYST`.

## Configure Superset

The example assumes Superset is available at `http://127.0.0.1:8089` and is
running in Docker. Mount this directory at the same path used by
`SUPERSET_CONFIG_PATH`, including its `templates` directory:

```bash
docker run ... \
  -v "$PWD/examples/auth/keycloak:/app/examples/auth/keycloak" \
  -e SUPERSET_CONFIG_PATH=/app/examples/auth/keycloak/superset_config.py
```

The demo config imports uppercase settings from
`/app/docker/pythonpath_dev/superset_config.py` by default, so the existing
Postgres and Docker development configuration remains active. Set
`SUPERSET_BASE_CONFIG_PATH` only when that base config is mounted elsewhere.
During Flask app initialization, `FLASK_APP_MUTATOR` prepends the template
directory derived from `superset_config.py` to Jinja's existing loader. This
keeps the demo template at `/app/examples/auth/keycloak/templates` without
replacing or copying Superset's core templates.

Required environment variables:

```bash
export KEYCLOAK_BROWSER_BASE_URL=http://localhost:8081
export KEYCLOAK_INTERNAL_BASE_URL=http://host.docker.internal:8081
export KEYCLOAK_REALM=superset-demo
export KEYCLOAK_CLIENT_ID=superset
export KEYCLOAK_CLIENT_SECRET='<client-secret-from-keycloak>'
```

`authorize_url` uses `localhost:8081` because the browser follows it.
`access_token_url`, `api_base_url`, and the userinfo request use
`host.docker.internal:8081` because Superset makes those requests from its
container. If Superset runs directly on the host, set
`KEYCLOAK_INTERNAL_BASE_URL=http://localhost:8081` instead.

Restart Superset after mounting the configuration. The combined login page
keeps the native username/password form and displays **Login with Company
Account** for the Keycloak provider.

The callback URL is generated by Flask from the incoming Superset request. If
the browser opens Superset at `http://127.0.0.1:8089`, the generated callback
is exactly `http://127.0.0.1:8089/oauth-authorized/keycloak`. Configure that
exact URI in Keycloak; do not substitute `localhost` unless the browser also
uses `localhost`.

## Authorization implementation

`DataHubSecurityManager.oauth_user_info` converts Keycloak identity claims to
the fields expected by Flask-AppBuilder: username, email, first name, last
name, and `role_keys`. Its explicit Python mapping is:

```text
BI_ADMIN   -> Admin
BI_ANALYST -> Gamma
```

`AUTH_ROLES_SYNC_AT_LOGIN = True` causes an existing user's mapped roles to be
recalculated at every login. `AUTH_USER_REGISTRATION = False` disables
Flask-AppBuilder's self-registration views and forms. Instead,
`DataHubSecurityManager.auth_user_oauth` creates missing Keycloak users
directly during the OAuth callback and refreshes their profile fields on later
logins. Identities without a recognized external role receive the configured
fallback role `Public` and never receive Admin or Gamma. Native database login
continues to use the same username/password flow.

## Verification

Test A with `admin.user@datahub.local`:

1. Open `http://127.0.0.1:8089/login/`.
2. Confirm the native username/password form is present and select **Login
   with Company Account** for SSO.
3. Authenticate in Keycloak as the `admin_user` test identity.
4. Confirm the callback returns to Superset and the user is created or updated.
5. Confirm the user has the Superset `Admin` role.

Test B with `analyst.user@datahub.local` follows the same steps and should
produce the Superset `Gamma` role.

## About `/ws` 404 responses

The `/ws` request is not part of the login or OIDC callback flow. In this
development setup it is the webpack-dev-server hot-module-reload client
endpoint configured in `superset-frontend/webpack.config.js`; it is not the
Global Async Queries transport. `GLOBAL_ASYNC_QUERIES` remains disabled by
default, so this SSO demo does not require a WebSocket service.

To stop the requests, serve a production frontend build instead of loading a
webpack-dev-server development bundle. No Keycloak or Superset backend
authentication setting should be changed for this. If Global Async Queries is
enabled later with `GLOBAL_ASYNC_QUERIES_TRANSPORT = "ws"`, deploy the
`superset-websocket` service, configure `GLOBAL_ASYNC_QUERIES_WEBSOCKET_URL`
to its browser-reachable URL, and keep its Redis/cache and JWT settings in
sync with Superset. Polling remains the compatible alternative when that
service is not deployed.

For a visible demo trace, set Superset logging to DEBUG for the module. The
security manager logs the provider, username, email, and extracted role names;
it never logs access tokens, refresh tokens, client secrets, or passwords.
