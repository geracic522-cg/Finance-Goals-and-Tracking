"""
Visual identity for the dashboard: ink-navy ledger with an emerald-to-teal
accent family, serif display + tabular mono numerals. Kept in one place so
every page looks consistent.
"""

import streamlit as st
import plotly.graph_objects as go

# --- Token system -----------------------------------------------------
INK = "#0F1B2D"          # background
SURFACE = "#16243A"      # card background
SURFACE_LINE = "#26364F"  # hairline rule / border
TEXT = "#E8ECF2"          # primary text
MUTED = "#8B96A8"         # secondary text

EMERALD = "#0B6E4F"      # primary accent -- start of the gradient family
TEAL = "#12877F"         # primary accent -- end of the gradient family
GREEN = "#4C9F70"        # positive movement / "on pace" indicator
RUST = "#B0563C"         # negative / flagged / over-budget

# Discrete shades within the emerald-teal family, for things that need
# distinct-but-related colors (multiple account slices/lines) rather than
# a true continuous gradient.
DONUT_PALETTE = [
    EMERALD, TEAL, "#3FA796", "#0A4F3B",
    "#5FBFB3", "#1F5C57", "#7FD1C4", "#083D2E",
]

# Warm palette for outflow/spending nodes -- visually distinct from the
# cool emerald/teal inflow family, signaling "money leaving" the way a
# heat gradient reads as intensifying rather than neutral.
HOT_PALETTE = [
    "#B0563C", "#C2571C", "#D9822B", "#E8974E",
    "#E0B03E", "#F2C14E", "#A8381F", "#C2432B",
]


def _interp_color(c1, c2, t):
    """Linear interpolation between two hex colors, t in [0, 1]."""
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def inject_base_css():
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

        html, body, [class*="css"] {{
            font-family: 'IBM Plex Sans', sans-serif;
        }}

        .stApp {{
            background-color: {INK};
            color: {TEXT};
        }}

        section[data-testid="stSidebar"] {{
            background-color: {SURFACE};
            border-right: 1px solid {SURFACE_LINE};
        }}

        h1, h2, h3 {{
            font-family: 'Fraunces', serif;
            font-weight: 600;
            color: {TEXT};
            letter-spacing: -0.01em;
        }}

        .ledger-eyebrow {{
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.72rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: {MUTED};
            margin-bottom: 0.25rem;
        }}

        .ledger-card {{
            background-color: {SURFACE};
            border: 1px solid {SURFACE_LINE};
            border-radius: 6px;
            padding: 1.25rem 1.5rem;
        }}

        .ledger-number {{
            font-family: 'IBM Plex Mono', monospace;
            font-variant-numeric: tabular-nums;
        }}

        hr {{
            border-color: {SURFACE_LINE};
        }}

        [data-testid="stMetricValue"] {{
            font-family: 'IBM Plex Mono', monospace;
            font-variant-numeric: tabular-nums;
            color: {TEXT};
        }}

        [data-testid="stMetricLabel"] {{
            font-family: 'IBM Plex Mono', monospace;
            color: {MUTED};
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.1em;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_goal_donut(current, goal, account_labels, account_values, height=420, blur=False):
    """
    Combined visual: a thin outer ring showing % progress toward the cash
    goal, nested around a thick inner ring sliced by individual account
    balances. The progress ring is a genuine emerald-to-teal gradient,
    built from many thin interpolated slices rather than a flat fill.
    """
    pct = max(0, min(current / goal, 1)) if goal else 0

    fig = go.Figure()

    # Outer thin progress ring: true emerald->teal gradient across the
    # filled portion, built from many small interpolated slices (Plotly
    # pie slices are flat-colored, so a smooth gradient arc means slicing
    # the filled portion finely enough that the color steps are invisible).
    SEGMENTS = 60
    filled_segments = max(1, round(SEGMENTS * pct)) if pct > 0 else 0
    remaining_value = 1 - pct

    values = []
    colors = []
    for i in range(filled_segments):
        t = i / max(filled_segments - 1, 1)
        values.append(pct / filled_segments if filled_segments else 0)
        colors.append(_interp_color(EMERALD, TEAL, t))
    if remaining_value > 0:
        values.append(remaining_value)
        colors.append(SURFACE_LINE)

    fig.add_trace(go.Pie(
        values=values,
        hole=0.82,
        domain=dict(x=[0, 1], y=[0, 1]),
        marker=dict(colors=colors, line=dict(width=0)),
        textinfo="none",
        sort=False,
        direction="clockwise",
        hoverinfo="skip",
        showlegend=False,
    ))

    # Inner thick ring: per-account slices, nested inside the outer ring's hole
    fig.add_trace(go.Pie(
        labels=account_labels,
        values=account_values,
        hole=0.45,
        domain=dict(x=[0.15, 0.85], y=[0.15, 0.85]),
        marker=dict(colors=DONUT_PALETTE[: len(account_labels)], line=dict(color=INK, width=2)),
        textinfo="none",
        sort=False,
        hovertemplate="%{label}<extra></extra>" if blur else "%{label}: $%{value:,.0f} (%{percent})<extra></extra>",
        hoverinfo="skip" if blur else None,
        showlegend=True,
    ))

    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="top", y=-0.05,
            font=dict(color=MUTED, family="IBM Plex Sans", size=11),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=10, b=10, l=10, r=10),
        height=height,
        annotations=[
            dict(text=f"{pct * 100:.1f}%", x=0.5, y=0.56, showarrow=False,
                 font=dict(size=26, family="IBM Plex Mono, monospace", color=TEXT)),
            dict(text="TO GOAL", x=0.5, y=0.465, showarrow=False,
                 font=dict(size=11, family="IBM Plex Mono, monospace", color=MUTED)),
        ],
    )
    return fig