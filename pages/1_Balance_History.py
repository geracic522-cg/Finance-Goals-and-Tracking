import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from db import get_accounts, get_balance_trend
from theme import inject_base_css, EMERALD, TEAL, MUTED, SURFACE_LINE, TEXT
from utils import blur_toggle_sidebar, is_blur_active, blur_amount, safe_download_button

st.set_page_config(page_title="Balance History", page_icon="📈", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Balance History")

accounts = get_accounts()

with st.sidebar:
    st.subheader("Filters")
    institutions = sorted(accounts["item_name"].dropna().unique().tolist())
    # Default to institutions that actually hold cash accounts (Chase, Raisin) --
    # Empower/Fidelity/Acorns are investment-only and clutter the default view
    cash_institutions = sorted(
        accounts[accounts["type"] == "depository"]["item_name"].dropna().unique().tolist()
    )
    selected_institutions = st.multiselect("Institution", institutions, default=cash_institutions)

    types = sorted(accounts["type"].dropna().unique().tolist())
    # Default to depository only -- investment/retirement excluded unless manually added
    selected_types = st.multiselect("Account Type", types, default=["depository"])

    filtered_accounts = accounts[
        accounts["item_name"].isin(selected_institutions) & accounts["type"].isin(selected_types)
    ]
    nickname_options = filtered_accounts["display_name"].dropna().tolist()
    selected_nicknames = st.multiselect("Account", nickname_options, default=nickname_options)

account_ids = filtered_accounts[filtered_accounts["display_name"].isin(selected_nicknames)][
    "account_id"
].tolist()

df = get_balance_trend(account_ids=account_ids if account_ids else None)

if df.empty:
    st.info("No data for the selected filters.")
    st.stop()

# --- Date range + Y-axis controls --------------------------------------
data_start = df["date"].min()
data_end = df["date"].max()
total_months_available = max(
    1, (data_end.year - data_start.year) * 12 + (data_end.month - data_start.month)
)
default_months = min(23, total_months_available)

with st.sidebar:
    st.subheader("Range")
    months_back = st.slider(
        "Months of history",
        min_value=1, max_value=total_months_available, value=default_months,
    )

cutoff = data_end - pd.DateOffset(months=months_back)
df = df[df["date"] >= cutoff]

palette = [EMERALD, TEAL, "#3FA796", "#0A4F3B", "#5FBFB3", "#7FD1C4"]

# --- Combined total (stacked on top) ------------------------------------
st.subheader("Combined Total")

with st.sidebar:
    st.subheader("Combined Total scale")
    if blur:
        combined_auto = True
        st.caption("Y-axis scale controls hidden in Privacy Mode (auto-scale forced on).")
    else:
        combined_auto = st.checkbox("Auto-scale", value=True, key="combined_auto")
        combined_y_max = st.slider(
            "Y-axis max ($)", min_value=10_000, max_value=1_000_000,
            value=120_000, step=10_000, disabled=combined_auto, key="combined_y_max",
        )

combined = df.groupby("date")["current_balance"].sum().reset_index()
combined_hovertext = combined.apply(
    lambda row: f"{row['date'].strftime('%b %d, %Y')}: {blur_amount(row['current_balance'], blur)}", axis=1
)
fig_combined = go.Figure(go.Scatter(
    x=combined["date"], y=combined["current_balance"],
    mode="lines", name="Combined", fill="tozeroy",
    line=dict(color=EMERALD, width=2),
    fillcolor="rgba(11, 110, 79, 0.10)",
    text=combined_hovertext,
    hovertemplate="%{text}<extra></extra>",
))
fig_combined.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Sans", color=TEXT),
    xaxis=dict(gridcolor=SURFACE_LINE, showgrid=True),
    yaxis=dict(
        gridcolor=SURFACE_LINE, showgrid=True,
        tickprefix="$", separatethousands=True,
        range=None if combined_auto else [0, combined_y_max],
        showticklabels=not blur,
    ),
    margin=dict(t=10, b=10, l=10, r=10),
    height=320,
    showlegend=False,
)
st.plotly_chart(fig_combined, width='stretch')
safe_download_button(
    "Download CSV", combined.rename(columns={"date": "Date", "current_balance": "Total"}),
    file_name="combined_balance_history.csv", key="dl_combined",
)

# --- By account (stacked below) -----------------------------------------
st.subheader("By Account")

with st.sidebar:
    st.subheader("By Account scale")
    if blur:
        by_account_auto = True
        st.caption("Y-axis scale controls hidden in Privacy Mode (auto-scale forced on).")
    else:
        by_account_auto = st.checkbox("Auto-scale", value=True, key="by_account_auto")
        by_account_y_max = st.slider(
            "Y-axis max ($)", min_value=5_000, max_value=500_000,
            value=60_000, step=5_000, disabled=by_account_auto, key="by_account_y_max",
        )

fig_by_account = go.Figure()
for i, nickname in enumerate(df["display_name"].dropna().unique()):
    sub = df[df["display_name"] == nickname]
    sub_hovertext = sub.apply(
        lambda row: f"{nickname} · {row['date'].strftime('%b %d, %Y')}: {blur_amount(row['current_balance'], blur)}",
        axis=1,
    )
    fig_by_account.add_trace(go.Scatter(
        x=sub["date"], y=sub["current_balance"],
        mode="lines", name=nickname,
        line=dict(color=palette[i % len(palette)], width=2),
        text=sub_hovertext,
        hovertemplate="%{text}<extra></extra>",
    ))
fig_by_account.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Sans", color=TEXT),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis=dict(gridcolor=SURFACE_LINE, showgrid=True),
    yaxis=dict(
        gridcolor=SURFACE_LINE, showgrid=True,
        tickprefix="$", separatethousands=True,
        range=None if by_account_auto else [0, by_account_y_max],
        showticklabels=not blur,
    ),
    margin=dict(t=20, b=10, l=10, r=10),
    height=500,
)
st.plotly_chart(fig_by_account, width='stretch')
by_account_display = df[["date", "display_name", "current_balance"]].rename(
    columns={"date": "Date", "display_name": "Account", "current_balance": "Balance"}
)
safe_download_button(
    "Download CSV", by_account_display,
    file_name="balance_history_by_account.csv", key="dl_by_account",
)