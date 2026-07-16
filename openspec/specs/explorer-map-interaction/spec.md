# explorer-map-interaction Specification

## Purpose
Live APR Explorer Maps choropleth interaction and visual contrast.

## Requirements

### Requirement: Stronger choropleth opacity

The explorer Maps choropleth SHALL render polygon fills at opacity **0.92** (or higher). Soft white borders MAY remain but SHALL NOT reduce fill opacity below 0.92.

#### Scenario: Sequential metric readability

- **WHEN** user views a sequential per-1000 map metric on carto-positron
- **THEN** filled jurisdictions are clearly distinguishable from the basemap (not washed to near-white)

### Requirement: Map scroll and pan zoom

The explorer Maps panel SHALL enable Plotly scroll zoom and drag zoom on the mapbox choropleth. Hover SHALL continue to show feature name and metric value after zoom.

#### Scenario: Zoom preserves hover

- **WHEN** user zooms into the Bay Area
- **THEN** hovering a city feature still shows its name and metric value
