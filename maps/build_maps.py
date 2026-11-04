#!/usr/bin/env python3
"""Export sparse dimensional housing maps from an explicit cleaned Table A2 CSV.

Run from the repository root: python3 -m maps.build_maps --input <cleaned CSV>.
Geometry and ACS denominators come from the immutable archived reference.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd
from charts.basic_apr_charts import (
    DATA_PATH, STAGE_METADATA, UNIT_CAT_CODES_TOP_TO_BOTTOM, UNIT_CAT_LABELS,
    _load_and_derive_apr_dataframe, _derive_tenure_flags, _derive_dr_type_flags,
    income_col_names, to_numeric_safe,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(__file__).with_name('reference') / 'jurisdictions.geojson'
OUTPUT = ROOT / 'docs/data/releases/2018-2024'
YEARS = (2018, 2024)
BUCKETS = {
    'housing': [*UNIT_CAT_CODES_TOP_TO_BOTTOM, 'unknown'],
    'tenure': ['owner', 'renter', 'unknown'],
    'program': ['db', 'inc_only', 'other'],
    'year': list(range(YEARS[0], YEARS[1] + 1)),
}
MEASURES = {'net': None, 'low_dr': [('LOW', 'dr')], 'vlow_dr': [('VLOW', 'dr')],
            'mod_dr': [('MOD', 'dr')],
            'nonrestricted': [('VLOW', 'ndr'), ('LOW', 'ndr'), ('MOD', 'ndr'), ('ABOVE_MOD', None)]}
PRIMITIVES = [f"{stage['key']}_{measure}" for stage in STAGE_METADATA
              for measure in MEASURES]
NET_POLICY = 'Shared chart raw stage net, including negative corrections; no clipping.'
TIER_POLICY = 'Reported income-tier units; demolition allocation unavailable. DR excludes NDR and stage-less ELI.'
UNRESTRICTED_POLICY = 'Reported VLOW, LOW and MOD non-deed-restricted units plus above-moderate units; no demolition allocation or stage-less ELI.'
CITY_ALIASES = {
    'COMMERCE': 'CITY OF COMMERCE', 'INDUSTRY': 'CITY OF INDUSTRY',
    'CRESCENT': 'CRESCENT CITY', 'CALIFORNIA': 'CALIFORNIA CITY',
    'CATHEDRAL': 'CATHEDRAL CITY', 'AMADOR': 'AMADOR CITY',
    'NEVADA': 'NEVADA CITY', 'NATIONAL': 'NATIONAL CITY',
    'SUISUN': 'SUISUN CITY', 'TEMPLE': 'TEMPLE CITY', 'UNION': 'UNION CITY',
    'YUBA': 'YUBA CITY', 'VENTURA': 'SAN BUENAVENTURA',
    'CARMEL': 'CARMEL-BY-THE-SEA', 'PASO ROBLES': 'EL PASO DE ROBLES',
    'SAINT HELENA': 'ST HELENA', 'ANGELS CAMP': 'ANGELS',
    'LA CAAADA FLINTRIDGE': 'LA CANADA FLINTRIDGE',
    'LA CAANADA FLINTRIDGE': 'LA CANADA FLINTRIDGE',
    'LA CAAANADA FLINTRIDGE': 'LA CANADA FLINTRIDGE',
}
# Finite source/reference crosswalk. County normalization never reads this table.
CITY_ALIASES.update({
    'CULVER CITY': 'CULVER', 'DALY CITY': 'DALY', 'FOSTER CITY': 'FOSTER',
    'KING CITY': 'KING', 'REDWOOD CITY': 'REDWOOD', 'SAND CITY': 'SAND',
    'WESTLAKE VILLAGE': 'WESTLAKE',
    'PASO ROBLES': 'EL PASO DE ROBLES (PASO ROBLES)',
    'EL PASO DE ROBLES': 'EL PASO DE ROBLES (PASO ROBLES)',
    'SAN BUENAVENTURA': 'SAN BUENAVENTURA (VENTURA)',
    'VENTURA': 'SAN BUENAVENTURA (VENTURA)',
    'SAINT HELENA': 'ST. HELENA', 'ST HELENA': 'ST. HELENA',
})


def base_name(value):
    if pd.isna(value):
        return ''
    name = str(value).split(',')[0].strip()
    name = (name.replace('Ã\x83Â±', 'n').replace('ÃÂ±', 'n').replace('Ã±', 'n')
            .replace('ñ', 'n').replace('Ñ', 'N'))
    return ''.join(c for c in unicodedata.normalize('NFD', name.upper())
                   if unicodedata.category(c) != 'Mn' and ord(c) < 128)


def normalize_name(value):
    # Census-style lowercase suffixes are distinct from official uppercase names.
    name = re.sub(r'\s+(city|town|cdp|village)$', '', str(value)).strip()
    name = base_name(name)
    return CITY_ALIASES.get(name, name)


def county_name(value):
    return re.sub(r'\s+COUNTY$', '', base_name(value)).strip()


def axis_manifest():
    """The sole selector definitions; the browser reads membership and named measures."""
    def choices(keys, labels, memberships):
        return [dict(key=k, label=l, buckets=m) for k, l, m in zip(keys, labels, memberships)]

    housing = choices(['all', *UNIT_CAT_CODES_TOP_TO_BOTTOM],
                      ['All housing', *(UNIT_CAT_LABELS[k] for k in UNIT_CAT_CODES_TOP_TO_BOTTOM)],
                      [list(range(len(BUCKETS['housing']))), *[[i] for i in range(6)]])
    return [
        {'key': 'geography', 'label': 'Geography', 'default': 'cities_plus_unincorporated', 'choices': [
            {'key': 'incorporated_cities', 'label': 'Incorporated cities', 'geo_types': ['city'],
             'colorscale': [[0,'rgba(239,246,255,.25)'],[.25,'rgba(191,219,254,.5)'],[.5,'rgba(96,165,250,.7)'],[.75,'rgba(37,99,235,.88)'],[1,'#1e3a8a']]},
            {'key': 'whole_counties', 'label': 'Whole counties', 'geo_types': ['county_whole'],
             'colorscale': [[0,'rgba(255,247,237,.25)'],[.25,'rgba(254,215,170,.5)'],[.5,'rgba(251,146,60,.7)'],[.75,'rgba(234,88,12,.88)'],[1,'#9a3412']]},
            {'key': 'cities_plus_unincorporated', 'label': 'Cities + unincorporated county', 'geo_types': ['city','county_residual'],
             'colorscale': [[0,'rgba(250,245,255,.25)'],[.25,'rgba(233,213,255,.5)'],[.5,'rgba(192,132,252,.7)'],[.75,'rgba(147,51,234,.88)'],[1,'#581c87']]},
        ]},
        {'key': 'housing', 'label': 'Housing type', 'default': '5+', 'row_field': 'housing_bucket', 'choices': housing},
        {'key': 'stage', 'label': 'Development stage', 'default': 'CO', 'choices': [
            {'key': s['key'], 'label': s['label'] + ', Net of Demolitions',
             'labels': {'net': s['label'] + ', Net of Demolitions',
                        'reported': s['label']},
             'stage': s['key']}
            for s in STAGE_METADATA]},
        {'key': 'tenure', 'label': 'Tenure', 'default': 'both', 'row_field': 'tenure_bucket', 'choices': choices(
            ['owner','renter','both'], ['Owner (for sale)','Renter','Rent + Own'], [[0],[1],[0,1]])},
        {'key': 'program', 'label': 'Inclusionary Program', 'default': 'all', 'row_field': 'program_bucket', 'choices': choices(
            ['all','db','inc_only'], ['All projects','Density bonus','Non-bonus inclusionary'], [[0,1,2],[0],[1]])},
        {'key': 'affordability', 'label': 'Income Restrictions', 'default': 'all', 'choices': [
            {'key': 'all', 'label': 'All (with+without restrictions)', 'measures': ['net'], 'stage_label_variant': 'net', 'explanation': 'Net of demolitions.'},
            {'key': 'none', 'label': 'None (No Deed Restrictions)', 'measures': ['nonrestricted'], 'stage_label_variant': 'reported', 'explanation': UNRESTRICTED_POLICY},
            {'key': 'dr', 'label': 'Deed-restricted units', 'measures': ['low_dr','vlow_dr','mod_dr'], 'stage_label_variant': 'reported', 'explanation': TIER_POLICY},
            {'key': 'low', 'label': 'Low', 'measures': ['low_dr'], 'stage_label_variant': 'reported', 'explanation': TIER_POLICY},
            {'key': 'vlow', 'label': 'Very Low', 'measures': ['vlow_dr'], 'stage_label_variant': 'reported', 'explanation': TIER_POLICY},
            {'key': 'vlow_low', 'label': 'Low + Very Low', 'measures': ['low_dr','vlow_dr'], 'stage_label_variant': 'reported', 'explanation': TIER_POLICY},
            {'key': 'mod', 'label': 'Moderate-income deed-restricted units', 'measures': ['mod_dr'], 'stage_label_variant': 'reported', 'explanation': TIER_POLICY},
        ]},
        {'key': 'year', 'label': 'Year', 'default': 'all', 'row_field': 'year_bucket', 'choices': choices(
            ['all', *map(str, BUCKETS['year'])], ['All Years', *map(str, BUCKETS['year'])],
            [list(range(len(BUCKETS['year']))), *[[i] for i in range(len(BUCKETS['year']))]])},
    ]


def prepare_rows(data_path):
    """Run shared chart preparation, then create fifteen additive primitives and exclusive buckets."""
    frame, _ = _load_and_derive_apr_dataframe(data_path=data_path)
    source_rows = len(frame)
    frame = frame.loc[frame['YEAR'].between(*YEARS)].copy()
    frame = _derive_tenure_flags(frame)
    frame, _ = _derive_dr_type_flags(frame)
    values = {}
    for stage in STAGE_METADATA:
        key, prefix = stage['key'], stage['prefix']
        for measure, sources in MEASURES.items():
            values[f'{key}_{measure}'] = (frame[stage['net_column']] if sources is None else
                sum(to_numeric_safe(frame[col]) for tier, restriction in sources
                    for col in income_col_names(prefix, tier, restriction)))
    rows = pd.DataFrame(values, index=frame.index)
    # Exact chart codes: unknown/malformed codes stay outside named housing choices.
    rows['housing'] = frame['UNIT_CAT'].map({k: i for i, k in enumerate(BUCKETS['housing'][:-1])}).fillna(6).astype(int)
    rows['tenure'] = np.select([frame['is_owner'], frame['is_rental']], [0, 1], default=2)
    rows['year'] = frame['YEAR'].map({year: i for i, year in enumerate(BUCKETS['year'])}).astype(int)
    rows['program'] = np.select([frame['has_db'], frame['has_inc_only']], [0, 1], default=2)
    rows['jurisdiction'] = frame['JURIS_NAME'].map(normalize_name)
    rows['county'] = frame['CNTY_NAME'].map(county_name)
    rows['is_county'] = frame['JURIS_NAME'].map(base_name).str.endswith(' COUNTY')
    rows['source_jurisdiction'] = frame['JURIS_NAME']
    coverage = {}
    for name, mask in [('unknown_housing', rows['housing'].eq(6)), ('unclassified_tenure_excluded_from_both', rows['tenure'].eq(2))]:
        coverage[name] = {'rows': int(mask.sum()), 'primitive_units': {
            key: float(rows.loc[mask, key].sum()) for key in PRIMITIVES}}
    return rows, {'source_rows': source_rows, 'rows_in_year_range': len(rows),
                  'years': sorted(int(y) for y in frame['YEAR'].unique()), 'coverage': coverage}


def build_cube(rows, reference):
    """Map one atomic aggregation to city/whole/residual geography without changing denominators."""
    collection = deepcopy(reference)
    collection.pop('reference', None)
    # The reference contains geometry and identity/population only; no old metric columns survive.
    identity = ('feature_id','geo_type','city_name','county_name','county_fips','population')
    for feature in collection['features']:
        feature['properties'] = {k: feature['properties'][k] for k in identity}
    features = collection['features']
    counties = {county_name(f['properties']['county_name']): f['properties']['county_fips']
                for f in features if f['properties']['geo_type'] == 'county_whole'}
    cities = {(normalize_name(f['properties']['city_name']), f['properties']['county_fips']): i
              for i, f in enumerate(features) if f['properties']['geo_type'] == 'city'}
    whole = {f['properties']['county_fips']: i for i, f in enumerate(features)
             if f['properties']['geo_type'] == 'county_whole'}
    residual = {f['properties']['county_fips']: i for i, f in enumerate(features)
                if f['properties']['geo_type'] == 'county_residual'}
    active = rows[PRIMITIVES].ne(0).any(axis=1)
    missing_counties = sorted(set(rows.loc[active, 'county']) - set(counties))
    if missing_counties:
        raise ValueError(f'Counties with activity missing from reference: {missing_counties}')
    fips = rows['county'].map(counties)
    unmatched = active & ~rows['is_county'] & pd.Series(
        [(name, county) not in cities for name, county in zip(rows['jurisdiction'], fips)], index=rows.index)
    if unmatched.any():
        evidence = rows.loc[unmatched, ['source_jurisdiction','jurisdiction','county',*PRIMITIVES]]
        raise ValueError('Active source jurisdictions missing from city reference (source indices and rows):\n' + evidence.to_string())
    group_columns = ['jurisdiction','county','is_county','housing','tenure','program','year']
    grouped = rows.groupby(group_columns, dropna=False, sort=True)[PRIMITIVES].sum()
    partitions = defaultdict(lambda: np.zeros(len(PRIMITIVES)))
    # Each atomic source group feeds county_whole; city groups also feed city. Residual is subtraction.
    for (jurisdiction, county, is_county, housing, tenure, program, year), numbers in grouped.iterrows():
        values = numbers.to_numpy(dtype=float)
        if not values.any():
            continue
        county_fips = counties[county]
        bucket = (int(housing), int(tenure), int(program), int(year))
        partitions[(whole[county_fips], *bucket)] += values
        partitions[(residual[county_fips], *bucket)] += values
        if not is_county:
            partitions[(cities[(jurisdiction, county_fips)], *bucket)] += values
            partitions[(residual[county_fips], *bucket)] -= values
    data = {'schema_version': 3, 'axes': axis_manifest(), 'buckets': BUCKETS,
            'primitive_columns': PRIMITIVES,
            'row_schema': ['feature_index','housing_bucket','tenure_bucket','program_bucket','year_bucket',*PRIMITIVES],
            'feature_ids': [f['properties']['feature_id'] for f in features],
            'partitions': [[*key, *values.tolist()] for key, values in sorted(partitions.items()) if values.any()]}
    return collection, data


def compose_counts(data, selection):
    """Compose exported partitions using the manifest contract (also used by verification)."""
    selected = {axis['key']: next(c for c in axis['choices'] if c['key'] == selection.get(axis['key'], axis['default']))
                for axis in data['axes']}
    result = np.zeros(len(data['feature_ids']))
    positions = {name: index for index, name in enumerate(data['row_schema'])}
    dimensions = [(positions[axis['row_field']], selected[axis['key']]['buckets'])
                  for axis in data['axes'] if 'row_field' in axis]
    indices = [positions[f"{selected['stage']['stage']}_{measure}"]
               for measure in selected['affordability']['measures']]
    for row in data['partitions']:
        if all(row[column] in membership for column, membership in dimensions):
            result[row[positions['feature_index']]] += sum(row[index] for index in indices)
    return result


def per_1000(numerator, population):
    return float(numerator) / population * 1000 if population is not None and population > 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DATA_PATH)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    reference_bytes = REFERENCE.read_bytes()
    reference = json.loads(reference_bytes)
    rows, stats = prepare_rows(args.input)
    collection, data = build_cube(rows, reference)
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    provenance = {
        'release_id': '2018-2024', 'built_at': datetime.now(timezone.utc).isoformat(),
        'hcd_apr_range': '2018–2024', 'hcd_input': args.input.name, 'hcd_input_sha256': digest,
        'reference_sha256': hashlib.sha256(reference_bytes).hexdigest(),
        'reference': reference['reference'], 'net_policy': NET_POLICY, 'affordability_policy': TIER_POLICY,
        'unrestricted_policy': UNRESTRICTED_POLICY,
        'year_policy': 'Cleaned APR reporting YEAR, not a stage-date year.',
        'tenure_policy': 'Both is owner plus renter; unclassified tenure excluded.',
        'housing_policy': 'All housing includes unknown/malformed types; named types use exact chart codes.',
        'program_policy': 'Density bonus includes rows reporting DB; non-bonus inclusionary includes INC without DB; All projects includes other/missing programs.',
        'data_mode': 'rebuilt_from_local_cleaned_csv', **stats,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name, payload in [('maps.geojson',collection), ('map_data.json',data), ('provenance.json',provenance)]:
        (args.output / name).write_text(json.dumps(payload, separators=(',', ':'), allow_nan=False) + '\n')
    print(f'Built {len(collection["features"])} features, {len(data["partitions"])} nonzero atomic partitions, {len(PRIMITIVES)} primitives from {len(rows):,} rows')
    print(f'Input SHA-256: {digest}')
    print('Source primitive sums:', {key: float(rows[key].sum()) for key in PRIMITIVES})
    print('Coverage:', json.dumps(stats['coverage'], sort_keys=True))
    sale = compose_counts(data, {'housing':'5+', 'tenure':'owner', 'affordability':'all'})
    county_sale = [sale[i] for i,f in enumerate(collection['features']) if f['properties']['geo_type']=='county_whole']
    print(f'MF owner CO: {sum(v > 0 for v in county_sale)} positive counties, {sum(county_sale)} units')
    print('map_data.json bytes:', (args.output / 'map_data.json').stat().st_size)


if __name__ == '__main__':
    main()
