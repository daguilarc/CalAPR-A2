## ADDED Requirements

### Requirement: Ocean water clip for Pages builds

Map boundary preparation SHALL subtract ocean water geometries from city and county polygons whenever an ocean boundary shapefile is available under the maps boundary cache, including when `PAGES_BUILD=1`. Tiger mode SHALL control place/county boundary source selection and SHALL NOT disable water clipping.

#### Scenario: Pages build clips ocean

- **WHEN** `PAGES_BUILD=1` and an `*ocean*.shp` exists in the boundary cache
- **THEN** exported city and county geometries used for `maps.geojson` are land-only relative to that ocean mask (no full county fill over Pacific ocean extents that the mask covers)

### Requirement: Residual county city punch-out

`county_residual` feature geometries SHALL equal the county polygon minus the union of incorporated city polygons in that county (same county FIPS), not a full county footprint. Numeric residual rates remain as already computed.

#### Scenario: Residual smaller than whole county

- **WHEN** a coastal county has both `county_whole` and `county_residual` features in `maps.geojson`
- **THEN** the residual geometry area is strictly less than the whole-county geometry area when the county contains mapped cities
- **AND** residual geometry does not cover those city interiors
