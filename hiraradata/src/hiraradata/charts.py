"""chart_render: numbers in, a chart image out.

Agents produce numbers all the time and then describe them in prose. This
renders them as a real chart (line, bar, horizontal bar, scatter, area, pie,
histogram, box) to PNG or SVG with matplotlib's headless backend, and returns
a short text description of what is plotted so the result can be checked
without looking at the image.
"""

from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .errors import DataError  # noqa: E402

KINDS = ("line", "bar", "barh", "scatter", "area", "pie", "histogram", "box")
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860", "#DA8BC3",
           "#8C8C8C", "#CCB974", "#64B5CD"]


def _numbers(values, name: str) -> list[float | None]:
    out = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise DataError(f"series {name!r} has a non-number: {v!r}") from None
        out.append(f if math.isfinite(f) else None)
    return out


def normalise_series(*, x=None, series=None, records=None, x_field=None, y_fields=None,
                     max_points: int = 200_000) -> tuple[list, list[dict]]:
    """Accept either x + series, or records + x_field / y_fields."""
    if records is not None:
        if not isinstance(records, list) or not records or not isinstance(records[0], dict):
            raise DataError("records must be a non-empty list of objects")
        fields = list(records[0].keys())
        x_field = x_field or fields[0]
        y_fields = y_fields or [f for f in fields if f != x_field]
        x = [r.get(x_field) for r in records]
        series = [{"name": f, "values": [r.get(f) for r in records]} for f in y_fields]
    if not series or not isinstance(series, list):
        raise DataError("provide series (a list of {name, values}) or records")
    out = []
    for i, s in enumerate(series):
        if not isinstance(s, dict) or not isinstance(s.get("values"), list):
            raise DataError(f"series[{i}] must be an object with a values list")
        name = str(s.get("name") or f"series {i + 1}")
        out.append({"name": name, "values": _numbers(s["values"], name)})
    longest = max(len(s["values"]) for s in out)
    if sum(len(s["values"]) for s in out) > max_points:
        raise DataError(f"more than {max_points} points (HD_MAX_POINTS)")
    if x is None:
        x = list(range(1, longest + 1))
    if not isinstance(x, list):
        raise DataError("x must be a list")
    return x, out


def render(kind: str, x: list, series: list[dict], *, title: str | None = None,
           x_label: str | None = None, y_label: str | None = None, width: int = 900,
           height: int = 500, fmt: str = "png", stacked: bool = False, log_y: bool = False,
           legend: bool | None = None, bins: int = 20) -> tuple[bytes, str]:
    if kind not in KINDS:
        raise DataError(f"type must be one of {', '.join(KINDS)}")
    if fmt not in ("png", "svg"):
        raise DataError("format must be png or svg")
    width = max(200, min(int(width), 4000))
    height = max(150, min(int(height), 4000))
    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    try:
        positions = list(range(len(x)))
        numeric_x = all(isinstance(v, (int, float)) for v in x)
        xs = x if numeric_x else positions
        if kind in ("line", "area", "scatter"):
            base = [0.0] * len(x)
            for i, s in enumerate(series):
                vals = s["values"] + [None] * (len(x) - len(s["values"]))
                ys = [math.nan if v is None else v for v in vals[: len(x)]]
                color = PALETTE[i % len(PALETTE)]
                if kind == "line":
                    ax.plot(xs, ys, label=s["name"], color=color, linewidth=2, marker="o" if len(x) <= 30 else None)
                elif kind == "scatter":
                    ax.scatter(xs, ys, label=s["name"], color=color, s=18)
                else:
                    top = [b + (0 if math.isnan(y) else y) for b, y in zip(base, ys)] if stacked else ys
                    ax.fill_between(xs, base if stacked else 0, top, alpha=0.35, color=color,
                                    label=s["name"])
                    ax.plot(xs, top, color=color, linewidth=1.5)
                    if stacked:
                        base = top
        elif kind in ("bar", "barh"):
            n = len(series)
            group = 0.8
            w = group if stacked else group / n
            base = [0.0] * len(x)
            for i, s in enumerate(series):
                vals = [0 if v is None else v for v in (s["values"] + [None] * len(x))[: len(x)]]
                offs = positions if stacked else [p - group / 2 + w * (i + 0.5) for p in positions]
                color = PALETTE[i % len(PALETTE)]
                if kind == "bar":
                    ax.bar(offs, vals, w, bottom=base if stacked else None, label=s["name"], color=color)
                else:
                    ax.barh(offs, vals, w, left=base if stacked else None, label=s["name"], color=color)
                if stacked:
                    base = [b + v for b, v in zip(base, vals)]
            ticks = [str(v) for v in x]
            if kind == "bar":
                ax.set_xticks(positions, ticks, rotation=45 if max(map(len, ticks), default=0) > 6 else 0,
                              ha="right" if max(map(len, ticks), default=0) > 6 else "center")
            else:
                ax.set_yticks(positions, ticks)
        elif kind == "pie":
            vals = [0 if v is None else v for v in series[0]["values"]]
            if any(v < 0 for v in vals):
                raise DataError("pie values must be >= 0")
            ax.pie(vals, labels=[str(v) for v in x[: len(vals)]], autopct="%1.1f%%",
                   colors=PALETTE * (len(vals) // len(PALETTE) + 1), startangle=90,
                   counterclock=False)
            ax.axis("equal")
        elif kind == "histogram":
            for i, s in enumerate(series):
                ax.hist([v for v in s["values"] if v is not None], bins=max(1, min(int(bins), 200)),
                        alpha=0.6 if len(series) > 1 else 0.9, label=s["name"],
                        color=PALETTE[i % len(PALETTE)])
        elif kind == "box":
            data = [[v for v in s["values"] if v is not None] for s in series]
            ax.boxplot(data, tick_labels=[s["name"] for s in series])
        if log_y and kind not in ("pie", "barh"):
            ax.set_yscale("log")
        if title:
            ax.set_title(title)
        if x_label and kind != "pie":
            ax.set_xlabel(x_label)
        if y_label and kind != "pie":
            ax.set_ylabel(y_label)
        show_legend = legend if legend is not None else (len(series) > 1 and kind not in ("pie", "box"))
        if show_legend:
            ax.legend(frameon=False)
        if kind not in ("pie",):
            ax.grid(True, alpha=0.3)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=dpi, metadata={"Software": None} if fmt == "png" else None)
    finally:
        plt.close(fig)
    return buf.getvalue(), describe(kind, x, series)


def describe(kind: str, x: list, series: list[dict]) -> str:
    lines = [f"{kind} chart, {len(x)} x value(s), {len(series)} series"]
    for s in series[:10]:
        vals = [v for v in s["values"] if v is not None]
        if not vals:
            lines.append(f"- {s['name']}: no values")
            continue
        hi = max(vals)
        lo = min(vals)
        hi_at = x[s["values"].index(hi)] if s["values"].index(hi) < len(x) else "?"
        lo_at = x[s["values"].index(lo)] if s["values"].index(lo) < len(x) else "?"
        lines.append(f"- {s['name']}: {len(vals)} points, min {lo:g} at {lo_at}, "
                     f"max {hi:g} at {hi_at}, first {vals[0]:g}, last {vals[-1]:g}")
    return "\n".join(lines)


__all__ = ["KINDS", "normalise_series", "render"]
