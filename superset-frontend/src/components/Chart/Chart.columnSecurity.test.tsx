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
import { render, screen } from 'spec/helpers/testing-library';
import { ErrorTypeEnum, type SupersetError } from '@superset-ui/core';
import { ChartSource } from 'src/types/ChartSource';
import Chart, { type ChartProps } from './Chart';
import { ChartErrorMessage } from './ChartErrorMessage';

jest.mock('src/hooks/apiResources', () => ({
  useChartOwnerNames: () => ({ result: [] }),
}));
jest.mock('./ChartRenderer', () => () => <div>Rendered chart</div>);

const forbidden: SupersetError = {
  error_type: ErrorTypeEnum.COLUMN_SECURITY_ACCESS_ERROR,
  message: 'Column ngay is not accessible',
  level: 'error',
  extra: {},
};
const props: ChartProps = {
  chartId: 1,
  dashboardId: 7,
  width: 400,
  height: 300,
  formData: { datasource: '1__table', viz_type: 'table' },
  vizType: 'table',
  chartStatus: 'success',
  queriesResponse: [{ data: [{ don_vi: 'A' }] }],
  setControlValue: jest.fn(),
  actions: {
    chartRenderingSucceeded: jest.fn(),
    chartRenderingFailed: jest.fn(),
    logEvent: jest.fn(),
    postChartFormData: jest.fn(),
  },
};

test('a forbidden dashboard chart shows authorization while an allowed chart renders', () => {
  render(
    <>
      <Chart {...props} />
      <Chart
        {...props}
        chartId={2}
        chartStatus="failed"
        chartAlert={forbidden.message}
        queriesResponse={[{ errors: [forbidden], message: forbidden.message }]}
      />
    </>,
  );
  expect(screen.getByText('Rendered chart')).toBeInTheDocument();
  expect(
    screen.getByText('You do not have permission to view this chart.'),
  ).toBeInTheDocument();
  expect(screen.queryByText('Data error')).not.toBeInTheDocument();
  expect(screen.queryByText(forbidden.message)).not.toBeInTheDocument();
});

test('unrestricted successful dashboard charts render normally', () => {
  render(
    <Chart
      {...props}
      queriesResponse={[
        { data: [{ don_vi: 'A', ngay: '2026-01-01', muc_tieu: 5 }] },
      ]}
    />,
  );
  expect(screen.getByText('Rendered chart')).toBeInTheDocument();
  expect(
    screen.queryByText('You do not have permission to view this chart.'),
  ).not.toBeInTheDocument();
});

test.each([
  {
    ...forbidden,
    error_type: ErrorTypeEnum.GENERIC_DB_ENGINE_ERROR,
    message: 'SQL syntax error',
  },
  { ...forbidden, error_type: ErrorTypeEnum.GENERIC_BACKEND_ERROR },
])(
  'unrelated errors retain the normal chart error display: $message',
  error => {
    render(
      <ChartErrorMessage
        chartId={1}
        source={ChartSource.Dashboard}
        error={error}
        subtitle={error.message}
      />,
    );
    expect(screen.getByText('Data error')).toBeInTheDocument();
    expect(screen.getByText(error.message)).toBeInTheDocument();
    expect(
      screen.queryByText('You do not have permission to view this chart.'),
    ).not.toBeInTheDocument();
  },
);

test('Explore CLS error display remains unchanged', () => {
  render(
    <ChartErrorMessage
      chartId={1}
      source={ChartSource.Explore}
      error={forbidden}
      subtitle={forbidden.message}
    />,
  );
  expect(screen.getByText('Data error')).toBeInTheDocument();
  expect(screen.getByText(forbidden.message)).toBeInTheDocument();
});
