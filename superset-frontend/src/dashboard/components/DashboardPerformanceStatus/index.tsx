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
import { useEffect, useMemo, useState } from 'react';
import { t } from '@apache-superset/core';
import { Tooltip } from '@superset-ui/core/components';
import { extendedDayjs } from '@superset-ui/core/utils/dates';
import { styled } from '@apache-superset/core/ui';
import type { JsonObject } from '@superset-ui/core';

import type { ChartsState } from 'src/dashboard/types';

type PerformanceStatus = 'processing' | 'fresh' | 'cached' | 'ready';

export interface DashboardPerformanceSnapshot {
  status: PerformanceStatus;
  durationMs: number | null;
  completedAt: number | null;
}

const StatusContainer = styled.div`
  align-items: center;
  display: flex;
  gap: ${({ theme }) => theme.sizeUnit}px;
  white-space: nowrap;
`;

const StatusLabel = styled.span`
  color: ${({ theme }) => theme.colorText};
  font-size: ${({ theme }) => theme.fontSizeSM}px;
`;

const Detail = styled.span`
  color: ${({ theme }) => theme.colorTextSecondary};
  font-size: ${({ theme }) => theme.fontSizeSM}px;
  white-space: nowrap;
`;

const getChartResponses = (charts: ChartsState, chartIds: number[]) =>
  chartIds.flatMap(chartId => charts[chartId]?.queriesResponse || []);

export function getDashboardPerformanceSnapshot(
  charts: ChartsState,
  chartIds: number[],
): DashboardPerformanceSnapshot {
  const dashboardCharts = chartIds
    .map(chartId => charts[chartId])
    .filter(Boolean);

  if (
    dashboardCharts.length === 0 ||
    dashboardCharts.some(
      chart =>
        chart.chartStatus === 'loading' ||
        chart.chartUpdateStartTime > (chart.chartUpdateEndTime ?? 0),
    )
  ) {
    return { status: 'processing', durationMs: null, completedAt: null };
  }

  const completedCharts = dashboardCharts.filter(
    chart =>
      (chart.chartStatus === 'success' || chart.chartStatus === 'rendered') &&
      chart.chartUpdateStartTime > 0 &&
      chart.chartUpdateEndTime != null,
  );

  if (completedCharts.length !== dashboardCharts.length) {
    return { status: 'processing', durationMs: null, completedAt: null };
  }

  const start = Math.min(
    ...completedCharts.map(chart => chart.chartUpdateStartTime),
  );
  const completedAt = Math.max(
    ...completedCharts.map(chart => chart.chartUpdateEndTime as number),
  );
  const responses = getChartResponses(charts, chartIds);
  const cacheValues = responses.map(
    response => (response as JsonObject).is_cached,
  );
  const allCached =
    cacheValues.length > 0 && cacheValues.every(value => value === true);
  const allFresh =
    cacheValues.length > 0 && cacheValues.every(value => value === false);

  return {
    // A cache label is shown only when every response explicitly identifies
    // its provenance. Warmup cannot be distinguished from another cache hit.
    status: allCached ? 'cached' : allFresh ? 'fresh' : 'ready',
    durationMs: Math.max(0, completedAt - start),
    completedAt,
  };
}

export function formatDashboardLoadDuration(durationMs: number): string {
  return durationMs < 1000
    ? t('Load: %s ms', Math.round(durationMs))
    : t('Load: %s s', (durationMs / 1000).toFixed(2));
}

export interface DashboardPerformanceStatusProps {
  charts: ChartsState;
  chartIds: number[];
}

export default function DashboardPerformanceStatus({
  charts,
  chartIds,
}: DashboardPerformanceStatusProps) {
  const snapshot = useMemo(
    () => getDashboardPerformanceSnapshot(charts, chartIds),
    [charts, chartIds],
  );
  const [, setRelativeTimeTick] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRelativeTimeTick(value => value + 1);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const statusText = {
    processing: t('Processing data'),
    fresh: t('Fresh'),
    cached: t('Cached'),
    ready: t('Ready'),
  }[snapshot.status];
  const updatedText = snapshot.completedAt
    ? t('Updated %s', extendedDayjs(snapshot.completedAt).fromNow())
    : null;

  return (
    <Tooltip
      title={t('This status shows how the current Dashboard data was loaded.')}
    >
      <StatusContainer data-test="dashboard-performance-status">
        <StatusLabel>
          {t('Performance')}: {statusText}
        </StatusLabel>
        {snapshot.durationMs != null && (
          <Detail>{formatDashboardLoadDuration(snapshot.durationMs)}</Detail>
        )}
        {updatedText && <Detail>{updatedText}</Detail>}
      </StatusContainer>
    </Tooltip>
  );
}
