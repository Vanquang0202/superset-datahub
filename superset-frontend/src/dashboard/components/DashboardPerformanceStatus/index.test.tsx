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
import {
  formatDashboardLoadDuration,
  getDashboardPerformanceSnapshot,
} from './index';
import type { ChartState } from 'src/explore/types';
import type { ChartsState } from 'src/dashboard/types';

const chart = (overrides: Record<string, unknown> = {}) =>
  ({
    chartStatus: 'success',
    chartUpdateStartTime: 1_000,
    chartUpdateEndTime: 2_250,
    queriesResponse: [{ is_cached: false }],
    ...overrides,
  }) as unknown as ChartState;

const charts = (value: ChartState): ChartsState => ({ 1: value });

test('reports processing while a chart is loading', () => {
  expect(
    getDashboardPerformanceSnapshot(
      charts(chart({ chartStatus: 'loading', chartUpdateEndTime: null })),
      [1],
    ).status,
  ).toBe('processing');
});

test('reports fresh completion and measures the dashboard cycle', () => {
  expect(getDashboardPerformanceSnapshot(charts(chart()), [1])).toEqual({
    status: 'fresh',
    durationMs: 1250,
    completedAt: 2250,
  });
});

test('reports cached only when response metadata proves it', () => {
  expect(
    getDashboardPerformanceSnapshot(
      charts(chart({ queriesResponse: [{ is_cached: true }] })),
      [1],
    ).status,
  ).toBe('cached');
  expect(
    getDashboardPerformanceSnapshot(
      charts(chart({ queriesResponse: [{}] })),
      [1],
    ).status,
  ).toBe('ready');
});

test('formats measured load duration for users', () => {
  expect(formatDashboardLoadDuration(420)).toBe('Load: 420 ms');
  expect(formatDashboardLoadDuration(1240)).toBe('Load: 1.24 s');
});
