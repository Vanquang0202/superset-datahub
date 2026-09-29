/*
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

import { SupersetTheme } from '@apache-superset/core/ui';
import { FeatureCollection, Point } from 'geojson';

// Synthetic locations, with no bundled Mapbox credentials.
export const generateData = (theme: SupersetTheme) => ({
  bounds: [
    [-122.43, 37.77],
    [-122.41, 37.79],
  ],
  geoJSON: {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-122.42, 37.78] },
        properties: { metric: 12, radius: 10, color: theme.colorPrimary },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-122.41, 37.79] },
        properties: { metric: 8, radius: 10, color: theme.colorPrimary },
      },
    ],
  } satisfies FeatureCollection<Point>,
  hasCustomMetric: true,
  mapboxApiKey: '',
});
