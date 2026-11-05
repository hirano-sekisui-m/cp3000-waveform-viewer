"""Plotly figures for the viewer: stacked overlay panels and a one-waveform detail view."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# wave type -> (panel title, y-axis label)
WAVE_TYPES: Dict[str, Tuple[str, str]] = {
    "raw": ("生波形", "吸光度(生値)"),
    "scaled": ("凝固波形(最大=100%)", "%"),
    "endpoint_scaled": ("凝固波形(終点=100%)", "%"),
    "slope": ("速度波形(1次微分)", "%/s"),
    "acceleration": ("加速度波形(2次微分)", "%/s²"),
    "base_aligned": ("タイムコース(0点補正)", "吸光度(生値差分)"),
    "abs_slope": ("速度波形", "mAbs/min."),
}

# Categorical slots in fixed order (validated reference palette), light / dark surface.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MAX_SERIES = len(SERIES_LIGHT)


@dataclass
class Theme:
    dark: bool

    @property
    def series(self) -> List[str]:
        return SERIES_DARK if self.dark else SERIES_LIGHT

    @property
    def surface(self) -> str:
        return "#1a1a19" if self.dark else "#fcfcfb"

    @property
    def text(self) -> str:
        return "#f0efec" if self.dark else "#0b0b0b"

    @property
    def text2(self) -> str:
        return "#c3c2b7" if self.dark else "#52514e"

    @property
    def grid(self) -> str:
        return "rgba(240,239,236,0.10)" if self.dark else "rgba(11,11,11,0.08)"

    @property
    def axis(self) -> str:
        return "rgba(240,239,236,0.35)" if self.dark else "rgba(11,11,11,0.30)"

    @property
    def other(self) -> str:  # folded "その他" / one-color mode
        return "#8a8983" if self.dark else "#9a9993"


@dataclass
class Series:
    """One waveform to draw: its label, color, time axis (already shifted) and values per type."""

    label: str
    color: str
    time: np.ndarray
    values: Dict[str, np.ndarray]
    tc2: float = np.nan
    group: Optional[str] = None
    hover: str = ""
    extra: Dict[str, float] = field(default_factory=dict)


def _thin(t: np.ndarray, v: np.ndarray, max_points: Optional[int]) -> Tuple[np.ndarray, np.ndarray]:
    if max_points is None or len(t) <= max_points:
        return t, v
    step = int(np.ceil(len(t) / max_points))
    return t[::step], v[::step]


def _style_axes(fig: go.Figure, theme: Theme) -> None:
    fig.update_xaxes(showgrid=True, gridcolor=theme.grid, zeroline=False, linecolor=theme.axis,
                     ticks="outside", tickcolor=theme.axis, color=theme.text2,
                     showspikes=True, spikemode="across", spikethickness=1, spikedash="dot",
                     spikecolor=theme.axis)
    fig.update_yaxes(showgrid=True, gridcolor=theme.grid, zeroline=False, linecolor=theme.axis,
                     ticks="outside", tickcolor=theme.axis, color=theme.text2)
    fig.update_annotations(font=dict(color=theme.text, size=13))


def overlay_figure(
    series: Sequence[Series],
    types: Sequence[str],
    theme: Theme,
    *,
    x_range: Optional[Tuple[float, float]] = None,
    x_title: str = "時間 (秒)",
    show_tc2: bool = True,
    ref_time: Optional[float] = None,
    max_points: Optional[int] = 1500,
    panel_height: int = 260,
    legend_groups: bool = False,
) -> go.Figure:
    """Stacked panels (one per wave type) on one shared time axis, every waveform overlaid."""
    types = list(types)
    fig = make_subplots(rows=len(types), cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=[WAVE_TYPES[k][0] for k in types])
    many = len(series) > MAX_SERIES
    width = 1.2 if many else 2.0
    opacity = 0.55 if many else 0.95
    use_gl = len(series) > 40
    Line = go.Scattergl if use_gl else go.Scatter
    seen_groups: set = set()

    for s in series:
        name = s.group if legend_groups and s.group is not None else s.label
        show_legend = True
        if legend_groups:
            show_legend = name not in seen_groups
            seen_groups.add(name)
        for row, key in enumerate(types, start=1):
            v = s.values.get(key)
            if v is None:
                continue
            t, y = _thin(s.time, v, max_points)
            fig.add_trace(Line(
                x=t, y=y, mode="lines", name=name,
                legendgroup=name, showlegend=show_legend and row == 1,
                line=dict(color=s.color, width=width), opacity=opacity,
                customdata=np.full(len(t), s.label, dtype=object),
                hovertemplate="%{customdata}<br>%{x:.1f} 秒: %{y:.4g}<extra></extra>",
            ), row=row, col=1)
            if show_tc2 and key in ("scaled", "endpoint_scaled") and np.isfinite(s.tc2):
                y_tc = float(np.interp(s.tc2, s.time, np.nan_to_num(v, nan=0.0)))
                fig.add_trace(go.Scatter(
                    x=[s.tc2], y=[y_tc], mode="markers", legendgroup=name, showlegend=False,
                    marker=dict(size=9, color=s.color, line=dict(color=theme.surface, width=2)),
                    hovertemplate=f"{s.label}<br>Tc2 = {s.tc2:.1f} 秒<extra></extra>",
                ), row=row, col=1)

    for row, key in enumerate(types, start=1):
        fig.update_yaxes(title_text=WAVE_TYPES[key][1], row=row, col=1)
        if key == "base_aligned":
            fig.add_hline(y=0, line=dict(color=theme.axis, width=1, dash="dash"), row=row, col=1)
            if ref_time is not None and np.isfinite(ref_time):
                fig.add_vline(x=ref_time, line=dict(color=theme.text2, width=1.5, dash="dot"), row=row, col=1)
                fig.add_annotation(x=ref_time, y=0.92, yref=f"y{row} domain", xref=f"x{row}",
                                   text=f"基準点 {ref_time:.1f}s", showarrow=False, xanchor="left", xshift=4,
                                   bgcolor=theme.surface, font=dict(size=11, color=theme.text2))
    fig.update_xaxes(title_text=x_title, row=len(types), col=1)
    if x_range is not None:
        fig.update_xaxes(range=list(x_range))

    fig.update_layout(
        height=max(320, panel_height * len(types) + 90),
        margin=dict(l=60, r=10, t=30, b=50),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=theme.surface,
        font=dict(color=theme.text, family="Meiryo, 'Yu Gothic UI', 'Noto Sans JP', sans-serif"),
        hovermode="x unified" if len(series) <= MAX_SERIES else "closest",
        hoverlabel=dict(bgcolor=theme.surface, font=dict(color=theme.text)),
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=1.01,
                    font=dict(color=theme.text2, size=12), itemclick="toggle", itemdoubleclick="toggleothers",
                    tracegroupgap=2),
    )
    _style_axes(fig, theme)
    return fig


DETAIL_PANELS = ["raw", "scaled", "slope", "acceleration"]


def detail_figure(time: np.ndarray, values: Dict[str, np.ndarray], tetc: Dict[str, float], theme: Theme,
                  *, color: str, x_range: Optional[Tuple[float, float]] = None,
                  device_value: Optional[float] = None) -> go.Figure:
    """2 x 2 panels for one waveform with Te/Tc markers (full resolution)."""
    fig = make_subplots(rows=2, cols=2, shared_xaxes=True, vertical_spacing=0.12, horizontal_spacing=0.08,
                        subplot_titles=[WAVE_TYPES[k][0] for k in DETAIL_PANELS])
    for i, key in enumerate(DETAIL_PANELS):
        r, c = divmod(i, 2)
        v = values[key]
        fig.add_trace(go.Scatter(x=time, y=v, mode="lines", line=dict(color=color, width=2),
                                 name=WAVE_TYPES[key][0], showlegend=False,
                                 hovertemplate="%{x:.1f} 秒: %{y:.4g}<extra></extra>"), row=r + 1, col=c + 1)
        fig.update_yaxes(title_text=WAVE_TYPES[key][1], row=r + 1, col=c + 1)

    # Te/Tc lines on every panel; one label per distinct time (Tc1 often equals Tc2), stacked
    # inside the 0-100 % panel so they never collide with the panel titles.
    marks = [("Tc1", "dot"), ("Tc2", "dash"), ("Te1", "dot"), ("Te2", "dash")]
    by_time: Dict[float, List[str]] = {}
    for name, dash in marks:
        x = tetc.get(name, np.nan)
        if x is None or not np.isfinite(x):
            continue
        x = round(float(x), 1)
        if x not in by_time:
            for i in range(4):
                r, c = divmod(i, 2)
                fig.add_vline(x=x, line=dict(color=theme.text2, width=1, dash=dash), row=r + 1, col=c + 1)
        by_time.setdefault(x, []).append(name)
    labels = [(x, "=".join(names) + f" {x:.1f}s") for x, names in sorted(by_time.items())]
    if device_value is not None and np.isfinite(device_value):
        fig.add_vline(x=device_value, line=dict(color=theme.series[1], width=1.5), row=1, col=2)
        labels.append((float(device_value), f"装置値 {device_value:.1f}s"))
    for k, (x, text) in enumerate(labels):
        fig.add_annotation(x=x, y=0.62 - 0.12 * k, yref="y2 domain", xref="x2", text=text,
                           showarrow=False, xanchor="left", xshift=4, bgcolor=theme.surface,
                           font=dict(size=11, color=theme.text2))
    fig.add_hline(y=50, line=dict(color=theme.axis, width=1, dash="dot"), row=1, col=2)
    fig.update_xaxes(title_text="時間 (秒)", row=2, col=1)
    fig.update_xaxes(title_text="時間 (秒)", row=2, col=2)
    if x_range is not None:
        fig.update_xaxes(range=list(x_range))
    fig.update_layout(
        height=620, margin=dict(l=60, r=20, t=50, b=50),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=theme.surface,
        font=dict(color=theme.text, family="Meiryo, 'Yu Gothic UI', 'Noto Sans JP', sans-serif"),
        hovermode="x unified", hoverlabel=dict(bgcolor=theme.surface, font=dict(color=theme.text)),
    )
    _style_axes(fig, theme)
    return fig


CHROMOGENIC_PANELS = ["raw", "base_aligned", "abs_slope"]


def detail_chromogenic_figure(
    time: np.ndarray,
    values: Dict[str, np.ndarray],
    theme: Theme,
    *,
    color: str,
    ref_time: Optional[float] = None,
    x_range: Optional[Tuple[float, float]] = None,
    device_value: Optional[float] = None,
    proc_value: Optional[float] = None,
) -> go.Figure:
    """Stacked 3 panels for one chromogenic waveform: Raw, Base-aligned, Velocity (mAbs/min.)."""
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        subplot_titles=[WAVE_TYPES[k][0] for k in CHROMOGENIC_PANELS],
    )
    for row, key in enumerate(CHROMOGENIC_PANELS, start=1):
        v = values.get(key)
        if v is None:
            continue
        fig.add_trace(go.Scatter(
            x=time, y=v, mode="lines+markers" if len(time) <= 30 else "lines",
            line=dict(color=color, width=2), marker=dict(size=5, color=color),
            name=WAVE_TYPES[key][0], showlegend=False,
            hovertemplate="%{x:.1f} 秒: %{y:.4g}<extra></extra>",
        ), row=row, col=1)
        fig.update_yaxes(title_text=WAVE_TYPES[key][1], row=row, col=1)

    # Base-aligned panel: zero line and ref_time vertical line
    fig.add_hline(y=0, line=dict(color=theme.axis, width=1, dash="dash"), row=2, col=1)
    if ref_time is not None and np.isfinite(ref_time):
        for r in range(1, 4):
            fig.add_vline(x=ref_time, line=dict(color=theme.text2, width=1.5, dash="dot"), row=r, col=1)
        fig.add_annotation(
            x=ref_time, y=0.92, yref="y2 domain", xref="x2",
            text=f"基準点 {ref_time:.1f}s", showarrow=False, xanchor="left", xshift=4,
            bgcolor=theme.surface, font=dict(size=11, color=theme.text2),
        )

    # Velocity panel: peak annotation
    v_slope = values.get("abs_slope")
    if v_slope is not None and np.isfinite(v_slope).any():
        idx_max = int(np.nanargmax(v_slope))
        t_max = float(time[idx_max])
        val_max = float(v_slope[idx_max])
        fig.add_trace(go.Scatter(
            x=[t_max], y=[val_max], mode="markers", showlegend=False,
            marker=dict(size=8, color=theme.series[1], line=dict(color=theme.surface, width=2)),
            hovertemplate=f"最大速度: {val_max:.2f} mAbs/min. ({t_max:.1f}s)<extra></extra>",
        ), row=3, col=1)

    fig.update_xaxes(title_text="時間 (秒)", row=3, col=1)
    if x_range is not None:
        fig.update_xaxes(range=list(x_range))
    fig.update_layout(
        height=620, margin=dict(l=60, r=20, t=50, b=50),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=theme.surface,
        font=dict(color=theme.text, family="Meiryo, 'Yu Gothic UI', 'Noto Sans JP', sans-serif"),
        hovermode="x unified", hoverlabel=dict(bgcolor=theme.surface, font=dict(color=theme.text)),
    )
    _style_axes(fig, theme)
    return fig
