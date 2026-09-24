/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import { embedDashboard } from '@superset-ui/embedded-sdk';
import './style.css';

const statusElement = document.querySelector<HTMLParagraphElement>('#status');
const mountPoint = document.querySelector<HTMLElement>('#superset-dashboard');

function configuredValue(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(`Missing frontend configuration: ${name}`);
  }
  return value.replace(/\/$/, '');
}

function setStatus(message: string, isError = false): void {
  if (statusElement) {
    statusElement.textContent = message;
    statusElement.classList.toggle('error', isError);
  }
}

async function fetchGuestToken(backendUrl: string): Promise<string> {
  const response = await fetch(`${backendUrl}/api/guest-token`, {
    headers: { Accept: 'application/json' },
  });
  const payload: unknown = await response.json();
  if (!response.ok || typeof payload !== 'object' || payload === null) {
    throw new Error('The demo backend could not provide a guest token.');
  }
  const token = (payload as { token?: unknown }).token;
  if (typeof token !== 'string' || token.length === 0) {
    throw new Error('The demo backend returned an invalid guest token response.');
  }
  return token;
}

async function start(): Promise<void> {
  if (!mountPoint) {
    throw new Error('The dashboard mount element is missing.');
  }

  const supersetUrl = configuredValue(
    import.meta.env.VITE_SUPERSET_URL,
    'VITE_SUPERSET_URL',
  );
  const dashboardUuid = configuredValue(
    import.meta.env.VITE_SUPERSET_DASHBOARD_UUID,
    'VITE_SUPERSET_DASHBOARD_UUID',
  );
  const backendUrl = configuredValue(
    import.meta.env.VITE_DEMO_BACKEND_URL,
    'VITE_DEMO_BACKEND_URL',
  );

  await embedDashboard({
    id: dashboardUuid,
    supersetDomain: supersetUrl,
    mountPoint,
    fetchGuestToken: () => fetchGuestToken(backendUrl),
    dashboardUiConfig: {
      hideTitle: false,
      hideTab: false,
      hideChartControls: false,
    },
    iframeTitle: 'DataHub Superset dashboard',
    referrerPolicy: 'strict-origin-when-cross-origin',
  });
  setStatus('Dashboard embedded successfully.');
}

start().catch(error => {
  console.error('Embedded dashboard failed to load:', error);
  setStatus(
    error instanceof Error ? error.message : 'Dashboard failed to load.',
    true,
  );
});
