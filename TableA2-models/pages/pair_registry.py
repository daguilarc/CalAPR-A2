"""Enumerate outcome × predictor × geography × robustness pairs for Pages catalog."""

from __future__ import annotations

PAIR_REGISTRY_VERSION = "1"

from dataclasses import dataclass
from typing import Iterator

from acs_apr_models import (
    PREDICTOR_META,
    UNIT_CATEGORIES,
    _predictor_requires_msa,
)

CITY_STREAM_PREFIXES = (
    "DB",
    "INC",
    "PROJ_DB",
    "PROJ_INC",
    "total_owner",
    "mf_owner",
    "TOTAL",
    "TOTAL_MF",
    "VLOW_LOW",
    "MOD",
)

ZIP_STREAM_PREFIXES = (
    ("net", "TOTAL"),
    ("net_MF", "TOTAL_MF"),
    ("dr_db", "DB"),
    ("total_db", "PROJ_DB"),
    ("total_inc", "PROJ_INC"),
    ("total_owner", "total_owner"),
    ("mf_owner", "mf_owner"),
    ("vlow_low", "VLOW_LOW"),
    ("mod", "MOD"),
)

ROBUSTNESS_SUFFIX_TO_KEY = {
    "": "none",
    "_xsf": "xsf",
    "_city_hash": "randhash",
    "_xsf_city_hash": "xsf_randhash",
    "_zip_hash": "randhash",
    "_xsf_zip_hash": "xsf_randhash",
}

CITY_MIN_JURIS = 10
ZIP_MIN_JURIS = 20


@dataclass(frozen=True)
class PairRecord:
    geography: str
    y_col: str
    x_col: str
    robustness: str
    var_suffix: str
    exclude_set: frozenset | None
    requires_msa: bool
    x_axis_filter_note: str | None
    min_jurisdictions: int
    dr_type: str
    cat_suffix: str
    y_is_rate: bool


def robustness_key_from_suffix(var_suffix: str) -> str:
    return ROBUSTNESS_SUFFIX_TO_KEY.get(var_suffix or "", "none")


def city_y_cols(df) -> list[str]:
    cols: list[str] = []
    for prefix in CITY_STREAM_PREFIXES:
        for phase in UNIT_CATEGORIES:
            if phase != "CO":
                continue
            col = f"{prefix}_{phase}_total"
            if col in df.columns:
                cols.append(col)
    return sorted(set(cols))


def zip_y_cols(df) -> list[str]:
    cols: list[str] = []
    for prefix, _ in ZIP_STREAM_PREFIXES:
        for phase in UNIT_CATEGORIES:
            if phase != "CO":
                continue
            col = f"{prefix}_{phase}"
            if col in df.columns:
                cols.append(col)
    return sorted(set(cols))


def parse_city_outcome(y_col: str) -> tuple[str, str]:
    if not y_col.endswith("_total"):
        raise ValueError(f"Not a city outcome column: {y_col}")
    stem = y_col[: -len("_total")]
    for phase in UNIT_CATEGORIES:
        suffix = f"_{phase}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)], phase
    raise ValueError(f"Cannot parse city outcome: {y_col}")


def parse_zip_outcome(y_col: str) -> tuple[str, str]:
    for phase in UNIT_CATEGORIES:
        suffix = f"_{phase}"
        if y_col.endswith(suffix):
            prefix = y_col[: -len(suffix)]
            for zip_prefix, dr_type in ZIP_STREAM_PREFIXES:
                if prefix == zip_prefix:
                    return dr_type, phase
            raise ValueError(f"Unknown ZIP outcome prefix: {y_col}")
    raise ValueError(f"Cannot parse ZIP outcome: {y_col}")


def predictors_for_geography(geography: str) -> list[str]:
    want = "zip" if geography == "zip" else "city"
    return sorted(
        x_col
        for x_col, meta in PREDICTOR_META.items()
        if meta["geo_applicability"] in (want, "both")
    )


def variables_for_geography(df_final, df_zip, geography: str) -> list[str]:
    frame = df_zip if geography == "zip" else df_final
    y_cols = zip_y_cols(frame) if geography == "zip" else city_y_cols(frame)
    x_cols = [c for c in predictors_for_geography(geography) if c in frame.columns]
    seen: set[str] = set()
    out: list[str] = []
    for key in [*y_cols, *x_cols]:
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _construction_y_cols(geography: str, frame) -> frozenset[str]:
    return frozenset(zip_y_cols(frame) if geography == "zip" else city_y_cols(frame))


def _pair_dr_type_cat_suffix(geography: str, y_col: str, construction_cols: frozenset[str]) -> tuple[str, str]:
    if y_col in construction_cols:
        if geography == "zip":
            return parse_zip_outcome(y_col)
        return parse_city_outcome(y_col)
    return y_col, "CO"


def _x_col_requires_msa(x_col: str) -> bool:
    if x_col not in PREDICTOR_META:
        return False
    return _predictor_requires_msa(x_col)


def _emit_directed_pairs(
    geography: str,
    frame,
    variables: list[str],
    min_jurisdictions: int,
) -> Iterator[PairRecord]:
    construction_cols = _construction_y_cols(geography, frame)
    for y_col in variables:
        y_is_rate = geography == "zip" and y_col in construction_cols
        dr_type, cat_suffix = _pair_dr_type_cat_suffix(geography, y_col, construction_cols)
        for x_col in variables:
            if x_col == y_col:
                continue
            requires_msa = _x_col_requires_msa(x_col)
            yield PairRecord(
                geography=geography,
                y_col=y_col,
                x_col=x_col,
                robustness="none",
                var_suffix="",
                exclude_set=None,
                requires_msa=requires_msa,
                x_axis_filter_note="Metro Regions only" if requires_msa else None,
                min_jurisdictions=min_jurisdictions,
                dr_type=dr_type,
                cat_suffix=cat_suffix,
                y_is_rate=y_is_rate,
            )


def iter_pairs(
    df_final,
    df_zip,
    *,
    sf_zips_for_xsf: frozenset | None = None,
) -> Iterator[PairRecord]:
    """Yield directed non-identity variable pairs at robustness none only."""
    del sf_zips_for_xsf
    city_vars = variables_for_geography(df_final, df_zip, "city")
    zip_vars = variables_for_geography(df_final, df_zip, "zip")
    yield from _emit_directed_pairs("city", df_final, city_vars, CITY_MIN_JURIS)
    yield from _emit_directed_pairs("zip", df_zip, zip_vars, ZIP_MIN_JURIS)
