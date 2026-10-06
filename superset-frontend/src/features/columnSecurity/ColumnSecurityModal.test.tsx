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
import userEvent from '@testing-library/user-event';
import {
  render,
  screen,
  selectOption,
  waitFor,
  within,
} from 'spec/helpers/testing-library';
import ColumnSecurityModal, {
  type ColumnSecurityModalProps,
} from './ColumnSecurityModal';

const datasetsEndpoint = 'glob:*/api/v1/columnsecurity/related/datasets?q=*';
const rolesEndpoint = 'glob:*/api/v1/columnsecurity/related/roles?q=*';
const datasetRolesEndpoint = 'glob:*/api/v1/columnsecurity/related/roles/1?q=*';
const columnsEndpoint = 'glob:*/api/v1/columnsecurity/related/columns/1?q=*';
const postEndpoint = 'glob:*/api/v1/columnsecurity/';
const policyEndpoint = 'glob:*/api/v1/columnsecurity/1';
const putEndpoint = 'glob:*/api/v1/columnsecurity/1';

fetchMock.get(datasetsEndpoint, {
  count: 1,
  result: [{ value: 1, text: 'demo_dataset' }],
});
fetchMock.get(rolesEndpoint, {
  count: 1,
  result: [{ value: 1, text: 'field_test' }],
});
fetchMock.get(datasetRolesEndpoint, {
  count: 1,
  result: [{ value: 1, text: 'field_test', disabled: false }],
});
fetchMock.get(columnsEndpoint, {
  count: 2,
  result: [
    { value: 1, text: 'don_vi' },
    { value: 2, text: 'so_luong' },
  ],
});
fetchMock.post(postEndpoint, { id: 1, result: {} });
fetchMock.get(policyEndpoint, {
  result: {
    id: 1,
    name: 'existing policy',
    table_id: 1,
    table: { id: 1, table_name: 'demo_dataset' },
    roles: [{ id: 1, name: 'field_test', label: 'field_test' }],
    columns: [{ id: 1, column_name: 'don_vi', label: 'don_vi' }],
    description: 'existing',
    enabled: true,
  },
});
fetchMock.put(putEndpoint, { id: 1, result: {} });

const defaultProps: ColumnSecurityModalProps = {
  policy: null,
  addDangerToast: jest.fn(),
  addSuccessToast: jest.fn(),
  onHide: jest.fn(),
  show: true,
};

const getSelectItemContainer = (select: HTMLElement) =>
  select.parentElement?.parentElement?.getElementsByClassName(
    'ant-select-selection-item',
  );

const getSelectField = (label: string) => {
  const labelElement = screen.getByText(label, { selector: 'label' });
  const field = labelElement.parentElement;
  expect(field).not.toBeNull();
  return field as HTMLElement;
};

const getCurrentSelect = (label: string) =>
  within(getSelectField(label)).getByRole('combobox', { name: label });

const selectOptionFromField = async (label: string, option: string) => {
  const field = getSelectField(label);
  const select = within(field).getByRole('combobox', { name: label });
  await userEvent.click(select);
  const listbox = await within(field).findByRole('listbox');
  await userEvent.click(
    await within(listbox).findByRole('option', { name: option }),
  );
};

test('renders the create policy form with dataset-dependent columns disabled', () => {
  render(<ColumnSecurityModal {...defaultProps} />, { useRedux: true });

  expect(screen.getByText('Add Policy')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add/i })).toBeDisabled();
});

test('loads columns after selecting a dataset and submits runtime IDs', async () => {
  const onHide = jest.fn();
  render(<ColumnSecurityModal {...defaultProps} onHide={onHide} />, {
    useRedux: true,
  });

  const policyNameField =
    screen.getByText('Policy Name').parentElement?.parentElement;
  expect(policyNameField).not.toBeNull();
  const name = within(policyNameField as HTMLElement).getByRole('textbox');
  await userEvent.type(name, 'policy');
  await waitFor(() => expect(name).toHaveValue('policy'));
  await selectOption('demo_dataset', 'Dataset');

  await waitFor(() => expect(getCurrentSelect('Roles')).toBeEnabled());
  await selectOptionFromField('Roles', 'field_test');
  await waitFor(() =>
    expect(fetchMock.callHistory.calls(datasetRolesEndpoint)).toHaveLength(1),
  );
  await waitFor(() => {
    const selectedItems = getSelectItemContainer(getCurrentSelect('Roles'));
    expect(selectedItems).toHaveLength(1);
    expect(selectedItems?.[0]).toHaveTextContent('field_test');
  });

  await waitFor(() =>
    expect(getCurrentSelect('Allowed Columns')).toBeEnabled(),
  );
  await selectOptionFromField('Allowed Columns', 'don_vi');
  await waitFor(() =>
    expect(fetchMock.callHistory.calls(columnsEndpoint)).toHaveLength(1),
  );
  await waitFor(() => {
    const selectedItems = getSelectItemContainer(
      getCurrentSelect('Allowed Columns'),
    );
    expect(selectedItems).toHaveLength(1);
    expect(selectedItems?.[0]).toHaveTextContent('don_vi');
  });
  await userEvent.click(getCurrentSelect('Allowed Columns'));

  expect(fetchMock.callHistory.calls(columnsEndpoint)).toHaveLength(1);
  const addButton = screen.getByRole('button', { name: /add/i });
  await waitFor(() => expect(addButton).toBeEnabled());
  await userEvent.click(addButton);
  await waitFor(() => expect(onHide).toHaveBeenCalled());
  await waitFor(() => {
    const calls = fetchMock.callHistory.calls(postEndpoint);
    expect(calls).toHaveLength(1);
    expect(calls[0].options?.body).toContain('"table_id":1');
    expect(calls[0].options?.body).toContain('"roles":[1]');
    expect(calls[0].options?.body).toContain('"columns":[1]');
  });
});

test('loads an existing policy and updates it', async () => {
  render(
    <ColumnSecurityModal
      {...defaultProps}
      policy={{
        id: 1,
        name: 'existing policy',
        table_id: 1,
        roles: [],
        columns: [],
        enabled: true,
      }}
    />,
    { useRedux: true },
  );

  expect(
    await screen.findByDisplayValue('existing policy'),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /save/i }));
  await waitFor(() =>
    expect(fetchMock.callHistory.calls(putEndpoint)).toHaveLength(1),
  );
});
