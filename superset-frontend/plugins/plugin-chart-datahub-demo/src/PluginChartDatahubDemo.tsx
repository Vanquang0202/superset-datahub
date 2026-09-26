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

import { styled } from '@apache-superset/core/ui';
import { PluginChartDatahubDemoProps } from './types';

const Container = styled.div<{ height: number; width: number }>`
  box-sizing: border-box;
  height: ${({ height }) => height}px;
  width: ${({ width }) => width}px;
  padding: ${({ theme }) => theme.sizeUnit * 4}px;
  overflow: auto;
`;

const Header = styled.div`
  margin-bottom: ${({ theme }) => theme.sizeUnit * 4}px;
`;

const Title = styled.h3`
  margin: 0;
  font-weight: 600;
`;

const Subtitle = styled.div`
  margin-top: ${({ theme }) => theme.sizeUnit}px;
  opacity: 0.65;
`;

const Row = styled.div`
  display: grid;
  grid-template-columns: minmax(110px, 180px) minmax(140px, 1fr) 90px 64px;
  align-items: center;
  gap: ${({ theme }) => theme.sizeUnit * 3}px;
  min-height: 38px;
`;

const Label = styled.div`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
`;

const Track = styled.div`
  position: relative;
  height: 18px;
`;

const Stem = styled.div`
  position: absolute;
  left: 0;
  top: 8px;
  height: 2px;
  min-width: 2px;
  background: ${({ theme }) => theme.colorPrimary};
`;

const Dot = styled.div`
  position: absolute;
  right: -6px;
  top: -5px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: ${({ theme }) => theme.colorPrimary};
`;

const Value = styled.div`
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
`;

const Percentage = styled.div`
  text-align: right;
  opacity: 0.65;
  font-variant-numeric: tabular-nums;
`;

const EmptyState = styled.div`
  padding: ${({ theme }) => theme.sizeUnit * 6}px;
  text-align: center;
  opacity: 0.65;
`;

export default function PluginChartDatahubDemo(
  props: PluginChartDatahubDemoProps,
) {
  const { items, height, width, categoryLabel, metricLabel } = props;

  const maxValue = Math.max(...items.map(item => item.value), 0);
  const formatter = new Intl.NumberFormat();

  return (
    <Container height={height} width={width}>
      <Header>
        <Title>DataHub Lollipop Ranking</Title>
        <Subtitle>
          {categoryLabel || 'Category'} ranked by {metricLabel || 'Metric'}
        </Subtitle>
      </Header>

      {items.length === 0 ? (
        <EmptyState>
          Select a category and metric, then run the query.
        </EmptyState>
      ) : (
        items.map(item => {
          const position =
            maxValue > 0 ? Math.max((item.value / maxValue) * 100, 1) : 1;

          return (
            <Row key={item.label}>
              <Label title={item.label}>{item.label}</Label>

              <Track>
                <Stem style={{ width: `${position}%` }}>
                  <Dot />
                </Stem>
              </Track>

              <Value>{formatter.format(item.value)}</Value>
              <Percentage>{item.percentage.toFixed(1)}%</Percentage>
            </Row>
          );
        })
      )}
    </Container>
  );
}
