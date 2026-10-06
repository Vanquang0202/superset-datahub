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

import { t } from '@apache-superset/core';
import { SupersetClient } from '@superset-ui/core';
import { css, styled } from '@apache-superset/core/ui';
import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent } from 'react';
import { ModalTitleWithIcon } from 'src/components/ModalTitleWithIcon';
import {
  AsyncSelect,
  Input,
  LabeledErrorBoundInput,
  Modal,
  Switch,
} from '@superset-ui/core/components';
import rison from 'rison';
import { useSingleViewResource } from 'src/views/CRUD/hooks';
import type { ColumnSecurityPolicy, PolicyOption, SelectValue } from './types';

const StyledSection = styled.div`
  ${({ theme }) => css`
    display: flex;
    flex-direction: column;
    padding: ${theme.sizeUnit * 3}px ${theme.sizeUnit * 4}px;
  `}
`;

const Field = styled.div`
  ${({ theme }) => css`
    display: flex;
    flex-direction: column;
    gap: ${theme.sizeUnit}px;
    margin-bottom: ${theme.sizeUnit * 3}px;
  `}
`;

const Label = styled.label`
  ${({ theme }) => css`
    color: ${theme.colorTextLabel};
    font-size: ${theme.fontSizeSM}px;
  `}
`;

const DEFAULT_POLICY: ColumnSecurityPolicy = {
  name: '',
  table_id: 0,
  roles: [],
  columns: [],
  description: '',
  enabled: true,
};

export interface ColumnSecurityModalProps {
  policy: ColumnSecurityPolicy | null;
  addSuccessToast: (message: string) => void;
  addDangerToast: (message: string) => void;
  onHide: () => void;
  show: boolean;
}

function queryOptions(input: string, page: number, pageSize: number) {
  return rison.encode({ filter: input, page, page_size: pageSize });
}

function ColumnSecurityModal({
  policy,
  addSuccessToast,
  addDangerToast,
  onHide,
  show,
}: ColumnSecurityModalProps) {
  const [currentPolicy, setCurrentPolicy] =
    useState<ColumnSecurityPolicy>(DEFAULT_POLICY);
  const [dataset, setDataset] = useState<SelectValue | null>(null);
  const [roles, setRoles] = useState<SelectValue[]>([]);
  const [columns, setColumns] = useState<SelectValue[]>([]);
  const [saving, setSaving] = useState(false);
  const isEditMode = policy !== null;

  const {
    state: { resource },
    fetchResource,
  } = useSingleViewResource<ColumnSecurityPolicy>(
    'columnsecurity',
    t('Column Level Security policy'),
    addDangerToast,
  );

  useEffect(() => {
    if (policy?.id) fetchResource(policy.id);
    if (!policy) {
      setCurrentPolicy(DEFAULT_POLICY);
      setDataset(null);
      setRoles([]);
      setColumns([]);
    }
  }, [fetchResource, policy]);

  useEffect(() => {
    if (!policy || !resource) return;
    setCurrentPolicy(resource);
    setDataset(
      resource.table
        ? {
            value: resource.table.id,
            label: resource.table.schema
              ? `${resource.table.schema}.${resource.table.table_name}`
              : resource.table.table_name,
          }
        : null,
    );
    setRoles(
      resource.roles.map(role => ({
        value: role.value ?? role.id ?? 0,
        label: role.label ?? role.name ?? '',
      })),
    );
    setColumns(
      resource.columns.map(column => ({
        value: column.value ?? column.id ?? 0,
        label: column.label ?? column.column_name ?? '',
      })),
    );
  }, [policy, resource]);

  const loadDatasets = useMemo(
    () =>
      (input = '', page: number, pageSize: number) =>
        SupersetClient.get({
          endpoint: `/api/v1/columnsecurity/related/datasets?q=${queryOptions(input, page, pageSize)}`,
        }).then(response => ({
          data: response.json.result.map(
            (item: { value: number; text: string }) => ({
              value: item.value,
              label: item.text,
            }),
          ),
          totalCount: response.json.count,
        })),
    [],
  );

  const loadRoles = useMemo(
    () =>
      (input = '', page: number, pageSize: number) =>
        SupersetClient.get({
          endpoint: dataset
            ? `/api/v1/columnsecurity/related/roles/${dataset.value}?q=${queryOptions(input, page, pageSize)}${policy?.id ? `&policy_id=${policy.id}` : ''}`
            : `/api/v1/columnsecurity/related/roles?q=${queryOptions(input, page, pageSize)}`,
        }).then(response => ({
          data: response.json.result.map(
            (item: { value: number; text: string; disabled?: boolean }) => ({
              value: item.value,
              label: item.text,
              disabled: item.disabled,
            }),
          ),
          totalCount: response.json.count,
        })),
    [dataset, policy?.id],
  );

  const loadColumns = useMemo(
    () =>
      (input = '', page: number, pageSize: number) => {
        if (!dataset) return Promise.resolve({ data: [], totalCount: 0 });
        return SupersetClient.get({
          endpoint: `/api/v1/columnsecurity/related/columns/${dataset.value}?q=${queryOptions(input, page, pageSize)}`,
        }).then(response => ({
          data: response.json.result.map(
            (item: { value: number; text: string }) => ({
              value: item.value,
              label: item.text,
            }),
          ),
          totalCount: response.json.count,
        }));
      },
    [dataset],
  );

  const onDatasetChange = (value: SelectValue | null) => {
    setDataset(value);
    setColumns([]);
    setCurrentPolicy(current => ({
      ...current,
      table_id: value?.value ?? 0,
      columns: [],
    }));
  };

  const onSave = async () => {
    setSaving(true);
    const payload = {
      name: currentPolicy.name,
      table_id: dataset?.value ?? 0,
      roles: roles.map(role => role.value),
      columns: columns.map(column => column.value),
      description: currentPolicy.description || null,
      enabled: currentPolicy.enabled,
    };
    try {
      if (isEditMode && policy?.id) {
        await SupersetClient.put({
          endpoint: `/api/v1/columnsecurity/${policy.id}`,
          jsonPayload: payload,
        });
        addSuccessToast(t('Policy updated'));
      } else {
        await SupersetClient.post({
          endpoint: '/api/v1/columnsecurity/',
          jsonPayload: payload,
        });
        addSuccessToast(t('Policy added'));
      }
      onHide();
    } catch (error) {
      addDangerToast(
        error instanceof Error ? error.message : t('Unable to save policy'),
      );
    } finally {
      setSaving(false);
    }
  };

  const canSave = Boolean(
    currentPolicy.name.trim() && dataset && roles.length && columns.length,
  );

  return (
    <Modal
      responsive
      show={show}
      onHide={onHide}
      primaryButtonName={isEditMode ? t('Save') : t('Add')}
      disablePrimaryButton={!canSave || saving}
      onHandledPrimaryAction={onSave}
      title={
        <ModalTitleWithIcon
          isEditMode={isEditMode}
          title={isEditMode ? t('Edit Policy') : t('Add Policy')}
          data-test="column-security-modal-title"
        />
      }
    >
      <StyledSection>
        <Field>
          <LabeledErrorBoundInput
            id="column-security-policy-name"
            name="name"
            value={currentPolicy.name}
            required
            label={t('Policy Name')}
            validationMethods={{
              onChange: (event: ChangeEvent<HTMLInputElement>) =>
                setCurrentPolicy(current => ({
                  ...current,
                  name: event.target.value,
                })),
            }}
          />
        </Field>
        <Field>
          <Label>{t('Dataset')}</Label>
          <AsyncSelect
            ariaLabel={t('Dataset')}
            value={dataset}
            options={loadDatasets}
            onChange={value => onDatasetChange(value as SelectValue | null)}
          />
        </Field>
        <Field>
          <Label>{t('Roles')}</Label>
          <AsyncSelect
            ariaLabel={t('Roles')}
            mode="multiple"
            value={roles}
            options={loadRoles}
            onChange={value => setRoles(value as PolicyOption[])}
          />
        </Field>
        <Field>
          <Label>{t('Allowed Columns')}</Label>
          <AsyncSelect
            ariaLabel={t('Allowed Columns')}
            mode="multiple"
            value={columns}
            options={loadColumns}
            onChange={value => setColumns(value as PolicyOption[])}
            disabled={!dataset}
          />
        </Field>
        <Field>
          <Label htmlFor="column-security-policy-description">
            {t('Description')}
          </Label>
          <Input.TextArea
            id="column-security-policy-description"
            rows={4}
            value={currentPolicy.description || ''}
            onChange={event =>
              setCurrentPolicy(current => ({
                ...current,
                description: event.target.value,
              }))
            }
          />
        </Field>
        <Field>
          <Label htmlFor="column-security-policy-enabled">{t('Enabled')}</Label>
          <Switch
            id="column-security-policy-enabled"
            checked={currentPolicy.enabled}
            onChange={checked =>
              setCurrentPolicy(current => ({ ...current, enabled: checked }))
            }
          />
        </Field>
      </StyledSection>
    </Modal>
  );
}

export default ColumnSecurityModal;
