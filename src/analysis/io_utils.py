from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go


def add_figure_note(fig: go.Figure, text: str) -> None:
    """Add a small source/description note below the chart area."""
    fig.add_annotation(
        text=text,
        xref="paper", yref="paper",
        x=0.0, y=-0.13,
        showarrow=False,
        font=dict(size=10, color="#666666"),
        align="left",
        xanchor="left",
    )
    current_b = fig.layout.margin.b
    fig.update_layout(margin=dict(b=max(current_b if current_b else 60, 80)))


def _apply_static_legend(fig: go.Figure) -> go.Figure:
    """Return a copy of fig with the legend repositioned to the bottom (horizontal)."""
    import copy
    fig2 = copy.deepcopy(fig)
    current_b = fig2.layout.margin.b or 60
    fig2.update_layout(
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
        ),
        margin=dict(b=max(current_b, 110)),
    )
    for ann in fig2.layout.annotations:
        if ann.yref == "paper" and ann.y < 0:
            ann.visible = False
    return fig2


def write_outputs(fig: go.Figure, out_html: Path, also_static: bool, also_png: bool = False) -> None:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    fig.update_layout(hoverlabel=dict(namelength=-1))
    fig.write_html(out_html)
    print(f"Wrote: {out_html}")

    if also_static:
        pdf_path = out_html.with_suffix(".pdf")
        try:
            _apply_static_legend(fig).write_image(pdf_path)
            print(f"Wrote: {pdf_path}")
        except Exception as e:
            print(f"Skipping static export ({pdf_path.name}): {e}")

    if also_png:
        png_path = out_html.with_suffix(".png")
        try:
            fig.write_image(png_path, scale=2)
            print(f"Wrote: {png_path}")
        except Exception as e:
            print(f"Skipping PNG export ({png_path.name}): {e}")


def iter_run_dirs(benchmarks_root: Path) -> list[Path]:
    """
    Return run directories under benchmarks_root.
    Your structure: benchmarks/run_0/is, benchmarks/run_1/is, benchmarks/run-default/is, ...
    """
    runs = [p for p in benchmarks_root.iterdir() if p.is_dir()]
    runs = sorted(runs, key=lambda p: p.name)
    return runs
