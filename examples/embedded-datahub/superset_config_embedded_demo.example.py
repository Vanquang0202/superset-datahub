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

from copy import deepcopy
from typing import Any

from superset.config import FEATURE_FLAGS as BASE_FEATURE_FLAGS
from superset.config import TALISMAN_CONFIG as BASE_TALISMAN_CONFIG
from superset.config import TALISMAN_DEV_CONFIG as BASE_TALISMAN_DEV_CONFIG

FEATURE_FLAGS = deepcopy(BASE_FEATURE_FLAGS)
FEATURE_FLAGS["EMBEDDED_SUPERSET"] = True


def _allow_demo_frame_ancestor(config: dict[str, Any]) -> dict[str, Any]:
    """Allow only the local demo app to frame Superset pages."""
    result = deepcopy(config)
    csp = deepcopy(result.get("content_security_policy", {}))
    csp["frame-ancestors"] = ["'self'", "http://localhost:5173"]
    result["content_security_policy"] = csp
    return result


TALISMAN_CONFIG = _allow_demo_frame_ancestor(BASE_TALISMAN_CONFIG)
TALISMAN_DEV_CONFIG = _allow_demo_frame_ancestor(BASE_TALISMAN_DEV_CONFIG)
