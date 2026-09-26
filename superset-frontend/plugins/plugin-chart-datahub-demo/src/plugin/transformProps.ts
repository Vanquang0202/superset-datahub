/**
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

import { ChartProps } from '@superset-ui/core';

type RawRow = Record<string, unknown>;

export default function transformProps(chartProps: ChartProps) {
  const { width, height, formData, queriesData } = chartProps;

  const data = (queriesData?.[0]?.data ?? []) as RawRow[];
  const firstRow = data[0] ?? {};
  const keys = Object.keys(firstRow);

  const configuredSeries =
    typeof formData.series === 'string' ? formData.series : undefined;

  const categoryKey =
    configuredSeries && keys.includes(configuredSeries)
      ? configuredSeries
      : (keys[0] ?? '');

  const metricKey = keys.find(key => key !== categoryKey) ?? '';

  const normalized = data
    .map(row => ({
      label: String(row[categoryKey] ?? 'Unknown'),
      value: Number(row[metricKey] ?? 0),
    }))
    .filter(item => Number.isFinite(item.value))
    .sort((a, b) => b.value - a.value);

  const total = normalized.reduce((sum, item) => sum + item.value, 0);

  const items = normalized.map(item => ({
    ...item,
    percentage: total > 0 ? (item.value / total) * 100 : 0,
  }));

  return {
    width,
    height,
    items,
    categoryLabel: categoryKey,
    metricLabel: metricKey,
  };
}
