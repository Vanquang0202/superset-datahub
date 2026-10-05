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
import { useMemo, useState } from 'react';
import { ConfirmStatusChange } from '@superset-ui/core/components';
import { ListView, type ListViewProps } from 'src/components';
import withToasts from 'src/components/MessageToasts/withToasts';
import SubMenu from 'src/features/home/SubMenu';
import { Icons } from '@superset-ui/core/components/Icons';
import { useListViewResource } from 'src/views/CRUD/hooks';
import { createErrorHandler } from 'src/views/CRUD/utils';
import ColumnSecurityModal from 'src/features/columnSecurity/ColumnSecurityModal';
import type { ColumnSecurityPolicy } from 'src/features/columnSecurity/types';

interface ColumnSecurityListProps {
  addDangerToast: (message: string) => void;
  addSuccessToast: (message: string) => void;
}

export function ColumnSecurityList({
  addDangerToast,
  addSuccessToast,
}: ColumnSecurityListProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [currentPolicy, setCurrentPolicy] =
    useState<ColumnSecurityPolicy | null>(null);
  const {
    state: { loading, resourceCount, resourceCollection, bulkSelectEnabled },
    hasPerm,
    fetchData,
    refreshData,
    toggleBulkSelect,
  } = useListViewResource<ColumnSecurityPolicy>(
    'columnsecurity',
    t('Column Level Security'),
    addDangerToast,
    true,
    undefined,
    undefined,
    true,
  );

  const openPolicy = (policy: ColumnSecurityPolicy | null) => {
    setCurrentPolicy(policy);
    setModalOpen(true);
  };

  const deletePolicy = (policy: ColumnSecurityPolicy) =>
    SupersetClient.delete({
      endpoint: `/api/v1/columnsecurity/${policy.id}`,
    }).then(
      () => {
        refreshData();
        addSuccessToast(t('Deleted %s', policy.name));
      },
      createErrorHandler(message =>
        addDangerToast(
          t('There was an issue deleting %s: %s', policy.name, message),
        ),
      ),
    );

  const columns = useMemo(
    () => [
      { accessor: 'name', Header: t('Policy Name'), id: 'name', size: 'xl' },
      {
        accessor: 'table.table_name',
        Header: t('Dataset'),
        id: 'table.table_name',
        Cell: ({
          row: { original },
        }: {
          row: { original: ColumnSecurityPolicy };
        }) =>
          original.table?.schema
            ? `${original.table.schema}.${original.table.table_name}`
            : original.table?.table_name,
      },
      {
        accessor: 'roles',
        Header: t('Roles'),
        id: 'roles',
        Cell: ({
          row: { original },
        }: {
          row: { original: ColumnSecurityPolicy };
        }) => original.roles.map(role => role.label).join(', '),
      },
      {
        accessor: 'columns',
        Header: t('Allowed Columns'),
        id: 'columns',
        Cell: ({
          row: { original },
        }: {
          row: { original: ColumnSecurityPolicy };
        }) => original.columns.map(column => column.label).join(', '),
      },
      {
        accessor: 'enabled',
        Header: t('Enabled'),
        id: 'enabled',
        Cell: ({
          row: { original },
        }: {
          row: { original: ColumnSecurityPolicy };
        }) => (original.enabled ? t('Yes') : t('No')),
      },
      {
        accessor: 'actions',
        Header: t('Actions'),
        id: 'actions',
        disableSortBy: true,
        Cell: ({
          row: { original },
        }: {
          row: { original: ColumnSecurityPolicy };
        }) => (
          <div className="actions">
            {hasPerm('can_write') && (
              <button type="button" onClick={() => openPolicy(original)}>
                <Icons.EditOutlined iconSize="m" />
              </button>
            )}
            {hasPerm('can_write') && (
              <ConfirmStatusChange
                title={t('Please confirm')}
                description={t(
                  'Are you sure you want to delete %s?',
                  original.name,
                )}
                onConfirm={() => deletePolicy(original)}
              >
                {confirmDelete => (
                  <button type="button" onClick={confirmDelete}>
                    <Icons.DeleteOutlined iconSize="m" />
                  </button>
                )}
              </ConfirmStatusChange>
            )}
          </div>
        ),
      },
    ],
    [hasPerm, refreshData, addDangerToast, addSuccessToast],
  );

  const canWrite = hasPerm('can_write');
  const subMenuButtons = canWrite
    ? [
        {
          name: t('Policy'),
          icon: <Icons.PlusOutlined iconSize="m" />,
          buttonStyle: 'primary' as const,
          onClick: () => openPolicy(null),
        },
      ]
    : [];
  const bulkActions: ListViewProps['bulkActions'] = [];

  return (
    <>
      <SubMenu name={t('Column Level Security')} buttons={subMenuButtons} />
      <ColumnSecurityModal
        policy={currentPolicy}
        addDangerToast={addDangerToast}
        addSuccessToast={addSuccessToast}
        show={modalOpen}
        onHide={() => {
          setModalOpen(false);
          setCurrentPolicy(null);
          refreshData();
        }}
      />
      <ListView<ColumnSecurityPolicy>
        className="column-security-list-view"
        columns={columns}
        initialSort={[{ id: 'name', desc: false }]}
        count={resourceCount}
        data={resourceCollection}
        loading={loading}
        fetchData={fetchData}
        refreshData={() => {}}
        pageSize={25}
        addDangerToast={addDangerToast}
        addSuccessToast={addSuccessToast}
        bulkActions={bulkActions}
        bulkSelectEnabled={bulkSelectEnabled}
        disableBulkSelect={toggleBulkSelect}
        emptyState={{
          title: t('No Column Level Security policies yet'),
          buttonText: canWrite ? t('Policy') : null,
          buttonAction: canWrite ? () => openPolicy(null) : undefined,
        }}
      />
    </>
  );
}

export default withToasts(ColumnSecurityList);
