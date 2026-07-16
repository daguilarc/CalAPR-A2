"""Plotly builders and JSON serialization for GitHub Pages static explorer."""

from __future__ import annotations

from typing import Any

import numpy as np
import plotly.graph_objects as go


def _tolist(arr: Any) -> list:
    if arr is None:
        return []
    return np.asarray(arr, dtype=np.float64).tolist()


def _labels_tolist(labels: Any) -> list[str]:
    if labels is None:
        return []
    return [str(x) for x in labels]


def build_two_part_figure(
    *,
    x_scatter: np.ndarray,
    y_scatter: np.ndarray,
    x_line: np.ndarray,
    mle_y: np.ndarray,
    labels: np.ndarray | None,
    fit_mode: str,
    mcfadden_r2: float,
    ols_r2: float | None,
    mle_beta: float | None,
    boot_ci_lo: np.ndarray | None = None,
    boot_ci_hi: np.ndarray | None = None,
    bayes_ci_lo: np.ndarray | None = None,
    bayes_ci_hi: np.ndarray | None = None,
    bayes_mean: np.ndarray | None = None,
    ppm_beta: float | None = None,
    two_part: dict | None = None,
) -> dict[str, Any]:
    """Return a Plotly figure as a JSON-serializable dict."""
    nz = y_scatter > 0
    x_nz = np.asarray(x_scatter)[nz]
    y_nz = np.asarray(y_scatter)[nz]
    label_nz = _labels_tolist(labels[nz] if labels is not None else None)

    fig = go.Figure()
    hover = []
    for i in range(len(x_nz)):
        name = label_nz[i] if i < len(label_nz) else ""
        hover.append(f"{name}<br>x={x_nz[i]:,.2f}<br>y={y_nz[i]:,.2f}")

    fig.add_trace(
        go.Scatter(
            x=x_nz.tolist(),
            y=y_nz.tolist(),
            mode="markers",
            name="Observations (y>0)",
            marker={"color": "#ED7D31", "size": 8, "opacity": 0.65},
            text=hover,
            hoverinfo="text",
        )
    )

    if fit_mode == "ols":
        pos_y = mle_y if mle_y is not None else np.zeros_like(x_line)
        fig.add_trace(
            go.Scatter(
                x=_tolist(x_line),
                y=_tolist(pos_y),
                mode="lines",
                name="MLE two-part line",
                line={"color": "#4472C4", "width": 2},
            )
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=_tolist(x_line),
                y=_tolist(mle_y),
                mode="lines",
                name="MLE two-part line",
                line={"color": "#4472C4", "width": 2},
            )
        )
        if bayes_mean is not None:
            fig.add_trace(
                go.Scatter(
                    x=_tolist(x_line),
                    y=_tolist(bayes_mean),
                    mode="lines",
                    name="Posterior predictive mean",
                    line={"color": "#C04060", "width": 2},
                )
            )
        if boot_ci_lo is not None and boot_ci_hi is not None:
            fig.add_trace(
                go.Scatter(
                    x=_tolist(x_line) + _tolist(x_line)[::-1],
                    y=_tolist(boot_ci_hi) + _tolist(boot_ci_lo)[::-1],
                    fill="toself",
                    fillcolor="rgba(0, 200, 255, 0.15)",
                    line={"width": 0},
                    name="Bootstrap CI",
                    hoverinfo="skip",
                )
            )
        if bayes_ci_lo is not None and bayes_ci_hi is not None:
            fig.add_trace(
                go.Scatter(
                    x=_tolist(x_line) + _tolist(x_line)[::-1],
                    y=_tolist(bayes_ci_hi) + _tolist(bayes_ci_lo)[::-1],
                    fill="toself",
                    fillcolor="rgba(255, 100, 150, 0.15)",
                    line={"width": 0},
                    name="Hierarchical Bayes CI",
                    hoverinfo="skip",
                )
            )

    fig.update_layout(
        title="",
        template="plotly_white",
        height=560,
        margin={"l": 60, "r": 30, "t": 30, "b": 80},
        legend={"orientation": "h", "y": -0.2},
    )
    stats = {
        "mcfadden_r2": float(mcfadden_r2) if mcfadden_r2 is not None else None,
        "ols_r2": float(ols_r2) if ols_r2 is not None and np.isfinite(ols_r2) else None,
        "mle_beta": float(mle_beta) if mle_beta is not None else None,
        "ppm_beta": float(ppm_beta) if ppm_beta is not None else None,
    }
    if two_part is not None:
        stats["two_part"] = two_part
    return {"plotly": fig.to_dict(), "stats": stats}


