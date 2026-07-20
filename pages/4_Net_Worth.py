import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from db import (
    get_net_worth_components, get_earliest_full_coverage_date, get_setting, set_setting,
    get_mortgage_payments, get_estimated_investment_trend, get_balance_trend,
)
from theme import inject_base_css, EMERALD, GREEN, RUST, SURFACE_LINE, TEXT
from utils import blur_toggle_sidebar, is_blur_active, blur_amount, safe_download_button, reconstruct_mortgage_balance

st.set_page_config(page_title="Net Worth", page_icon="📈", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()
if blur:
    st.session_state["house_value_editing"] = False
    st.session_state["mortgage_balance_editing"] = False

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Net Worth")

components = get_net_worth_components()
if components.empty:
    st.warning("No balance history yet.")
    st.stop()

house_value = float(get_setting("house_value", 0))
mortgage_balance = float(get_setting("mortgage_balance", 0))

# --- Editable house value + current mortgage balance --------------------
st.subheader("Home & Mortgage")
st.caption(
    "Zillow's public Zestimate API has been retired since 2021, so home "
    "value is entered manually here -- check Zillow yourself whenever "
    "you want a fresh number."
)

hcol1, hcol2 = st.columns(2)

with hcol1:
    st.markdown('<div class="ledger-eyebrow">Home Value</div>', unsafe_allow_html=True)
    if not st.session_state.get("house_value_editing", False):
        gcol1, gcol2 = st.columns([5, 1])
        gcol1.markdown(
            f'<p class="ledger-number" style="font-size:1.4rem; color:{EMERALD}; margin:0;">'
            f'{blur_amount(house_value, blur)}</p>', unsafe_allow_html=True,
        )
        if gcol2.button("✏️", key="house_value_edit_btn",
                         help="Editing is disabled in Privacy Mode" if blur else "Edit home value", disabled=blur):
            st.session_state["house_value_editing"] = True
            st.rerun()
    else:
        new_val = st.number_input("New home value ($)", min_value=0, value=int(house_value),
                                   step=1000, key="house_value_input", label_visibility="collapsed")
        scol1, scol2 = st.columns(2)
        if scol1.button("Save", key="house_value_save", width='stretch'):
            set_setting("house_value", new_val)
            st.session_state["house_value_editing"] = False
            st.cache_data.clear()
            st.rerun()
        if scol2.button("Cancel", key="house_value_cancel", width='stretch'):
            st.session_state["house_value_editing"] = False
            st.rerun()

with hcol2:
    st.markdown('<div class="ledger-eyebrow">Current Mortgage Balance</div>', unsafe_allow_html=True)
    if not st.session_state.get("mortgage_balance_editing", False):
        gcol1, gcol2 = st.columns([5, 1])
        gcol1.markdown(
            f'<p class="ledger-number" style="font-size:1.4rem; color:{RUST}; margin:0;">'
            f'{blur_amount(mortgage_balance, blur)}</p>', unsafe_allow_html=True,
        )
        if gcol2.button("✏️", key="mortgage_balance_edit_btn",
                         help="Editing is disabled in Privacy Mode" if blur else "Edit mortgage balance", disabled=blur):
            st.session_state["mortgage_balance_editing"] = True
            st.rerun()
    else:
        new_val = st.number_input("New mortgage balance ($)", min_value=0, value=int(mortgage_balance),
                                   step=1000, key="mortgage_balance_input", label_visibility="collapsed")
        scol1, scol2 = st.columns(2)
        if scol1.button("Save", key="mortgage_balance_save", width='stretch'):
            set_setting("mortgage_balance", new_val)
            st.session_state["mortgage_balance_editing"] = False
            st.cache_data.clear()
            st.rerun()
        if scol2.button("Cancel", key="mortgage_balance_cancel", width='stretch'):
            st.session_state["mortgage_balance_editing"] = False
            st.rerun()

st.divider()

# --- Net worth trend ------------------------------------------------------
st.subheader("Net Worth Over Time")
st.caption(
    "Assets (checking, savings, investments, retirement) minus credit card "
    "balances owed, plus home equity. Home value is held flat at today's "
    "manually-entered figure across all history (no historical data available); "
    "mortgage balance is reconstructed from actual payment history where available."
)

payments = get_mortgage_payments()
components = components.sort_values("date")
estimated = get_estimated_investment_trend()

# --- History slider ------------------------------------------------------
# Bounded by REAL data only, same as every other page (~2 years) --
# estimated data does NOT widen this. Defaults to the first date every
# account type has real coverage, not the absolute earliest row:
# investment/retirement accounts can't be backfilled the way depository
# ones can, so before that date the total is missing whole account
# types entirely -- showing that range by default would make a real
# coverage gap look like a net worth spike the moment those accounts'
# history begins.
data_start_date = components["date"].min().date()
data_end_date = components["date"].max().date()
coverage_start = get_earliest_full_coverage_date()
coverage_start_ts = pd.Timestamp(coverage_start) if coverage_start else None
default_start = (
    coverage_start_ts.date()
    if coverage_start_ts is not None and coverage_start_ts.date() >= data_start_date
    else data_start_date
)

range_start, range_end = st.slider(
    "History range",
    min_value=data_start_date, max_value=data_end_date,
    value=(default_start, data_end_date),
)
if default_start > data_start_date:
    st.caption(
        f"Defaulting to {default_start.strftime('%B %d, %Y')} onward -- earlier dates are missing "
        "some account types (investment/retirement history can't be backfilled the way cash "
        "accounts can), which would otherwise show up as a misleading jump. Drag the slider left "
        "to see the full real history anyway."
    )

show_estimate = False
if not estimated.empty and coverage_start_ts is not None:
    show_estimate = st.checkbox(
        "Smooth pre-coverage investment gap using estimated growth",
        value=False,
        help=(
            "Fabricated, not real data. For dates before investment accounts had real coverage, "
            "this fills the gap in the Assets total with a backward-compounded estimate (flat "
            "assumed 7%/year from each account's earliest real balance) instead of leaving that "
            "account type out entirely -- which is what causes the sharp jump when checked OFF. "
            "The result is blended into the SAME line below (dashed for the estimated portion, "
            "solid for real), not a separate line. Stored in its own database table, never mixed "
            "into real synced balances."
        ),
    )

components = components[
    (components["date"] >= pd.Timestamp(range_start)) & (components["date"] <= pd.Timestamp(range_end))
]

if show_estimate and coverage_start_ts is not None:
    # Fill the gap: for dates before real investment coverage began,
    # add the estimated investment total to the real (depository/credit
    # -only) assets figure for that date -- replacing the missing
    # account type with a smooth estimate instead of leaving it at zero.
    est_sorted = estimated.sort_values("date").rename(columns={"estimated_assets": "_estimated_fill"})
    components = pd.merge_asof(
        components.sort_values("date"), est_sorted, on="date", direction="backward"
    )
    components["_estimated_fill"] = components["_estimated_fill"].fillna(0)
    pre_mask = components["date"] < coverage_start_ts
    components.loc[pre_mask, "assets"] = components.loc[pre_mask, "assets"] + components.loc[pre_mask, "_estimated_fill"]
    components = components.drop(columns=["_estimated_fill"])

if not payments.empty and mortgage_balance > 0:
    mortgage_series = reconstruct_mortgage_balance(payments, mortgage_balance)
    mortgage_series["date"] = pd.to_datetime(mortgage_series["date"])
    # Forward-fill: mortgage balance only changes on payment dates, so
    # every day between payments carries the most recent known balance.
    merged = pd.merge_asof(
        components, mortgage_series.rename(columns={"balance": "mortgage_balance_on_date"}),
        on="date", direction="backward",
    )
    # Before the earliest recorded payment, fall back to the earliest
    # known balance rather than leaving it blank.
    merged["mortgage_balance_on_date"] = merged["mortgage_balance_on_date"].fillna(
        mortgage_series["balance"].iloc[0] if not mortgage_series.empty else mortgage_balance
    )
else:
    merged = components.copy()
    merged["mortgage_balance_on_date"] = mortgage_balance

merged["net_worth"] = merged["assets"] - merged["credit_owed"] + house_value - merged["mortgage_balance_on_date"]

current_net_worth = merged.iloc[-1]["net_worth"]
current_assets = merged.iloc[-1]["assets"]
current_credit_owed = merged.iloc[-1]["credit_owed"]
current_mortgage = merged.iloc[-1]["mortgage_balance_on_date"]

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown('<div class="ledger-eyebrow">Net Worth</div>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="ledger-number" style="font-size:1.75rem; color:{GREEN}; margin:0;">'
        f'{blur_amount(current_net_worth, blur)}</p>',
        unsafe_allow_html=True,
    )

c2.metric("Assets", blur_amount(current_assets, blur))
c3.metric("Credit Owed", blur_amount(current_credit_owed, blur))
c4.metric("Mortgage", blur_amount(current_mortgage, blur))

with st.expander("▾ What makes up Net Worth?"):
    latest_date_used = merged.iloc[-1]["date"]
    latest_accounts = get_balance_trend()
    latest_accounts = latest_accounts[latest_accounts["date"] == latest_date_used]

    breakdown_rows = []
    for _, row in latest_accounts.iterrows():
        signed_balance = -row["current_balance"] if row["type"] == "credit" else row["current_balance"]
        kind = "Liability" if row["type"] == "credit" else "Asset"
        breakdown_rows.append({
            "Account": row["display_name"], "Type": kind, "Balance": signed_balance,
        })
    breakdown_rows.append({"Account": "Home Value", "Type": "Asset", "Balance": house_value})
    breakdown_rows.append({"Account": "Mortgage", "Type": "Liability", "Balance": -current_mortgage})

    breakdown_df = pd.DataFrame(breakdown_rows).sort_values(["Type", "Balance"], ascending=[True, False])
    if blur:
        breakdown_df = breakdown_df.copy()
        breakdown_df["Balance"] = breakdown_df["Balance"].apply(lambda v: blur_amount(v, True))
    st.dataframe(breakdown_df, hide_index=True, width='stretch')
    st.caption(
        f"As of {latest_date_used.strftime('%B %d, %Y')} -- sums to {blur_amount(current_net_worth, blur)}, "
        "matching the Net Worth figure above exactly (assets positive, liabilities negative)."
    )

hovertext = merged.apply(
    lambda row: f"{row['date'].strftime('%b %d, %Y')}: {blur_amount(row['net_worth'], blur)}"
    + (" (estimated)" if show_estimate and coverage_start_ts is not None and row["date"] < coverage_start_ts else ""),
    axis=1,
)

fig = go.Figure()

if show_estimate and coverage_start_ts is not None and merged["date"].min() < coverage_start_ts:
    # Split at the coverage boundary so the dashed (estimated-blended)
    # portion and the solid (real) portion visually connect as one
    # continuous line rather than two unrelated traces.
    pre = merged[merged["date"] <= coverage_start_ts]
    post = merged[merged["date"] >= coverage_start_ts]

    fig.add_trace(go.Scatter(
        x=pre["date"], y=pre["net_worth"], mode="lines",
        name="Net Worth (estimated pre-coverage)",
        line=dict(color=EMERALD, width=2.5, dash="dash"),
        text=hovertext.loc[pre.index],
        hovertemplate="%{text}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=post["date"], y=post["net_worth"], mode="lines", fill="tozeroy",
        name="Net Worth (real data)",
        line=dict(color=EMERALD, width=2.5),
        fillcolor="rgba(11, 110, 79, 0.10)",
        text=hovertext.loc[post.index],
        hovertemplate="%{text}<extra></extra>",
    ))
    show_legend = True
else:
    fig.add_trace(go.Scatter(
        x=merged["date"], y=merged["net_worth"], mode="lines", fill="tozeroy",
        name="Net Worth (real data)",
        line=dict(color=EMERALD, width=2.5),
        fillcolor="rgba(11, 110, 79, 0.10)",
        text=hovertext,
        hovertemplate="%{text}<extra></extra>",
    ))
    show_legend = False

fig.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Sans", color=TEXT),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis=dict(gridcolor=SURFACE_LINE, showgrid=True),
    yaxis=dict(
        gridcolor=SURFACE_LINE, showgrid=True, tickprefix="$", separatethousands=True,
        showticklabels=not blur,
    ),
    margin=dict(t=20, b=20, l=10, r=10),
    height=450,
    showlegend=show_legend,
)
st.plotly_chart(fig, width='stretch')

net_worth_display = merged[["date", "assets", "credit_owed", "mortgage_balance_on_date", "net_worth"]].rename(
    columns={
        "date": "Date", "assets": "Assets", "credit_owed": "Credit Owed",
        "mortgage_balance_on_date": "Mortgage Balance", "net_worth": "Net Worth",
    }
)
if blur:
    net_worth_display = net_worth_display.copy()
    for col in ["Assets", "Credit Owed", "Mortgage Balance", "Net Worth"]:
        net_worth_display[col] = net_worth_display[col].apply(lambda v: blur_amount(v, True))
safe_download_button("Download CSV", net_worth_display, file_name="net_worth_history.csv", key="dl_networth")