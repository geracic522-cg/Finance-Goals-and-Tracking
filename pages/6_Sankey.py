import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import datetime

from db import get_income_sources, get_spending_by_category, get_available_transaction_years
from theme import inject_base_css, EMERALD, TEAL, GREEN, SURFACE, TEXT, HOT_PALETTE
from utils import blur_toggle_sidebar, is_blur_active, blur_amount, safe_download_button

st.set_page_config(page_title="Sankey", page_icon="🌊", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Money Flow")

years = get_available_transaction_years()
if not years:
    st.warning("No transaction history yet.")
    st.stop()

# Default to the most recent FULL calendar year, not the current
# (likely partial) year -- a half-finished year makes for a lopsided
# diagram next to prior full years.
current_year = datetime.date.today().year
default_years = [y for y in years if y != current_year][:1] or years[:1]

with st.sidebar:
    st.subheader("Years")
    selected_years = st.multiselect(
        "Select one or more years to compare", years, default=default_years,
    )

    st.subheader("Display")
    show_pct = st.checkbox(
        "Show as % of income", value=False,
        help="Percentages are ratios, not dollar amounts, so they stay visible even in Privacy Mode.",
    )
    node_pad = st.slider(
        "Node spacing", min_value=5, max_value=60, value=30,
        help="Vertical gap between nodes in the same column.",
    )

if not selected_years:
    st.info("Select at least one year in the sidebar.")
    st.stop()

TOP_N = 8  # cap nodes per side so the diagram stays readable; rest lumped into "Other"


def format_value(amount, total_income, show_pct, blur):
    """Percentages are ratios, not absolute dollar figures -- they don't
    reveal real magnitude, so they stay visible even under Privacy Mode
    (unlike every dollar figure elsewhere in the app)."""
    if show_pct:
        pct = (amount / total_income * 100) if total_income else 0
        return f"{pct:.1f}%"
    return blur_amount(amount, blur)


def build_year_sankey(year, blur, show_pct, node_pad):
    start, end = f"{year}-01-01", f"{year}-12-31"

    income_df = get_income_sources(start_date=start, end_date=end, limit=100)
    spend_df = get_spending_by_category(start_date=start, end_date=end, level="pfc_primary")

    if income_df.empty and spend_df.empty:
        return None, 0, 0, [], [], 0

    # Cap to top N per side, lump the remainder into "Other"
    if len(income_df) > TOP_N:
        top_income = income_df.iloc[:TOP_N]
        other_income = income_df.iloc[TOP_N:]["total"].sum()
        income_rows = list(zip(top_income["source"], top_income["total"]))
        if other_income > 0:
            income_rows.append(("Other Income", other_income))
    else:
        income_rows = list(zip(income_df["source"], income_df["total"]))

    spend_df = spend_df.copy()
    spend_df["category_label"] = spend_df["category"].fillna("Uncategorized").str.replace("_", " ").str.title()
    if len(spend_df) > TOP_N:
        top_spend = spend_df.iloc[:TOP_N]
        other_spend = spend_df.iloc[TOP_N:]["total"].sum()
        spend_rows = list(zip(top_spend["category_label"], top_spend["total"]))
        if other_spend > 0:
            spend_rows.append(("Other Spending", other_spend))
    else:
        spend_rows = list(zip(spend_df["category_label"], spend_df["total"]))

    total_income = sum(v for _, v in income_rows)
    total_spending = sum(v for _, v in spend_rows)
    savings = total_income - total_spending

    # --- Build node list -------------------------------------------------
    income_labels = [name for name, _ in income_rows]
    spend_labels = [name for name, _ in spend_rows]
    node_labels = income_labels + ["Income"] + spend_labels
    if savings > 0:
        node_labels.append("Savings")

    income_idx = {name: i for i, name in enumerate(income_labels)}
    income_node_idx = len(income_labels)
    spend_idx = {name: income_node_idx + 1 + i for i, name in enumerate(spend_labels)}
    savings_idx = len(node_labels) - 1 if savings > 0 else None

    # Cool (emerald/teal) for inflows, hot (red/orange/yellow) for
    # outflows -- spending is money leaving, so it reads as "warm."
    node_colors = (
        [EMERALD] * len(income_labels)
        + [TEAL]
        + [HOT_PALETTE[i % len(HOT_PALETTE)] for i in range(len(spend_labels))]
    )
    if savings > 0:
        node_colors.append(GREEN)

    # --- Build links -------------------------------------------------------
    # Note: link VALUES (which control visual band width) stay as real
    # dollar amounts regardless of show_pct -- scaling everything by the
    # same factor wouldn't change the proportions at all. Only the
    # displayed TEXT (label/hover) changes between $ and %.
    sources, targets, values, link_labels = [], [], [], []

    for name, amount in income_rows:
        sources.append(income_idx[name])
        targets.append(income_node_idx)
        values.append(amount)
        link_labels.append(format_value(amount, total_income, show_pct, blur))

    for name, amount in spend_rows:
        sources.append(income_node_idx)
        targets.append(spend_idx[name])
        values.append(amount)
        link_labels.append(format_value(amount, total_income, show_pct, blur))

    if savings > 0:
        sources.append(income_node_idx)
        targets.append(savings_idx)
        values.append(savings)
        link_labels.append(format_value(savings, total_income, show_pct, blur))

    node_display_labels = node_labels if not blur else ["" for _ in node_labels]

    fig = go.Figure(go.Sankey(
        node=dict(
            label=node_display_labels,
            color=node_colors,
            pad=node_pad, thickness=18,
            line=dict(color=SURFACE, width=0.5),
            customdata=node_labels,
            hovertemplate="%{customdata}<extra></extra>" if not blur else "<extra></extra>",
        ),
        link=dict(
            source=sources, target=targets, value=values,
            customdata=link_labels,
            hovertemplate="%{customdata}<extra></extra>",
            color="rgba(139, 150, 168, 0.25)",
        ),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color=TEXT, size=12),
        margin=dict(t=10, b=10, l=10, r=10),
        height=480,
    )
    return fig, total_income, total_spending, income_rows, spend_rows, savings


for year in sorted(selected_years, reverse=True):
    st.subheader(str(year))
    fig, total_income, total_spending, income_rows, spend_rows, savings = build_year_sankey(
        year, blur, show_pct, node_pad
    )

    if fig is None:
        st.caption("No income or spending data for this year.")
        continue

    scol1, scol2, scol3 = st.columns(3)
    scol1.metric("Income", format_value(total_income, total_income, show_pct, blur))
    scol2.metric("Spending", format_value(total_spending, total_income, show_pct, blur))
    scol3.metric(
        "Savings" if savings >= 0 else "Shortfall",
        format_value(abs(savings), total_income, show_pct, blur),
    )
    if savings < 0:
        st.caption(
            "Spending exceeded recognized income this year -- no Savings flow shown "
            "(a Sankey can't render a negative flow)."
        )

    st.plotly_chart(fig, width='stretch')

    flow_rows = (
        [{"Flow": "Income", "Node": name, "Amount": amt} for name, amt in income_rows]
        + [{"Flow": "Spending", "Node": name, "Amount": amt} for name, amt in spend_rows]
    )
    if savings > 0:
        flow_rows.append({"Flow": "Savings", "Node": "Savings", "Amount": savings})
    flow_df = pd.DataFrame(flow_rows)
    if blur:
        flow_df = flow_df.copy()
        flow_df["Amount"] = flow_df["Amount"].apply(lambda v: blur_amount(v, True))
    safe_download_button("Download CSV", flow_df, file_name=f"money_flow_{year}.csv", key=f"dl_sankey_{year}")

    st.divider()

st.caption(
    "Excludes internal transfers between your own accounts, same as the Spending page. "
    "The largest income sources and spending categories are shown individually; smaller "
    "ones are grouped into \"Other Income\" / \"Other Spending\" to keep the diagram readable."
)