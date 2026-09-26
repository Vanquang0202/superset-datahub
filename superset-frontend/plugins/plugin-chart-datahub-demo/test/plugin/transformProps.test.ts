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

import { supersetTheme } from '@apache-superset/core/ui';
import { ChartProps } from '@superset-ui/core';
import transformProps from '../../src/plugin/transformProps';

describe('PluginChartDatahubDemo transformProps', () => {
  const chartProps = new ChartProps({
    width: 800,
    height: 600,
    formData: {
      datasource: '1__table',
      viz_type: 'datahub_demo',
      series: 'name',
      metric: 'sum__num',
    },
    queriesData: [
      {
        data: [
          { name: 'Hulk', sum__num: 10 },
          { name: 'Thor', sum__num: 5 },
        ],
      },
    ],
    theme: supersetTheme,
  });

  test('should transform chart props for lollipop visualization', () => {
    expect(transformProps(chartProps)).toEqual({
      width: 800,
      height: 600,
      categoryLabel: 'name',
      metricLabel: 'sum__num',
      items: [
        {
          label: 'Hulk',
          value: 10,
          percentage: 66.66666666666666,
        },
        {
          label: 'Thor',
          value: 5,
          percentage: 33.33333333333333,
        },
      ],
    });
  });
});
