/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import fetchMock from 'fetch-mock';
import { QueryParamProvider } from 'use-query-params';
import { ReactRouter5Adapter } from 'use-query-params/adapters/react-router-5';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from 'spec/helpers/testing-library';
import { ColumnSecurityList } from '.';

const listEndpoint = 'glob:*/api/v1/columnsecurity/?*';
const infoEndpoint = 'glob:*/api/v1/columnsecurity/_info*';

fetchMock.get(listEndpoint, {
  count: 1,
  result: [
    {
      id: 1,
      name: 'field_test policy',
      table: { id: 1, table_name: 'demo_dataset' },
      roles: [{ id: 1, label: 'field_test' }],
      columns: [{ id: 1, label: 'don_vi' }],
      enabled: true,
    },
  ],
});
fetchMock.get(infoEndpoint, {
  permissions: ['can_read', 'can_write'],
});

test('renders the Column Level Security policy list and create action', async () => {
  render(
    <MemoryRouter>
      <QueryParamProvider adapter={ReactRouter5Adapter}>
        <ColumnSecurityList
          addDangerToast={jest.fn()}
          addSuccessToast={jest.fn()}
        />
      </QueryParamProvider>
    </MemoryRouter>,
    { useRedux: true },
  );

  expect(await screen.findByText('Column Level Security')).toBeInTheDocument();
  expect(await screen.findByText('field_test policy')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /policy/i })).toBeInTheDocument();
});
