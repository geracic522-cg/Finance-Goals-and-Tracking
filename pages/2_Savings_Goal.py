import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta

from db import (
    get_cash_total_by_date, get_setting, set_setting,
    get_latest_cash_by_account, get_account_transactions,
    get_large_transactions, get_all_flagged_events, get_active_events, save_event,
)
from theme import inject_base_css, build_goal_donut, EMERALD, TEAL, MUTED, GREEN, RUST, SURFACE, SURFACE_LINE, TEXT
from config import CASH_GOAL
from utils import blur_toggle_sidebar, is_blur_active, blur_amount, safe_download_button

st.set_page_config(page_title="Savings Goal", page_icon="🎯", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()
if blur:
    st.session_state["savings_goal_editing"] = False

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Cash Savings Goal")

df = get_cash_total_by_date()

if df.empty:
    st.warning("No balance history yet.")
    st.stop()

current_cash = df.iloc[-1]["total_cash"]
current_date = df.iloc[-1]["date"]

# Same DB-backed setting Home.py reads/writes -- editing the goal on
# either page keeps both in sync.
current_goal = float(get_setting("cash_goal", CASH_GOAL))

st.sidebar.subheader("Timeline")
target_months = st.sidebar.slider("Target: months from today", 12, 30, 20)
target_date = current_date + timedelta(days=target_months * 30.44)

cash_by_account = get_latest_cash_by_account()

col1, col2 = st.columns([1, 2])

with col1:
    if not cash_by_account.empty:
        fig_donut = build_goal_donut(
            current=current_cash, goal=current_goal,
            account_labels=cash_by_account["display_name"],
            account_values=cash_by_account["current_balance"],
            height=380, blur=blur,
        )
        st.plotly_chart(fig_donut, width='stretch')

with col2:
    remaining = max(current_goal - current_cash, 0)
    months_left = max(target_months, 0.1)
    required_monthly = remaining / months_left

    # Goal figure lives outside the card now, as its own inline
    # click-to-edit control -- one click reveals a compact input right
    # in place, no separate expander to open.
    st.markdown('<div class="ledger-eyebrow">Target</div>', unsafe_allow_html=True)

    if not st.session_state.get("savings_goal_editing", False):
        gcol1, gcol2 = st.columns([5, 1])
        gcol1.markdown(
            f'<p class="ledger-number" style="font-size:1.6rem; color:{EMERALD}; margin:0.15rem 0;">'
            f'{blur_amount(current_goal, blur)} by {target_date.strftime("%B %Y")}</p>',
            unsafe_allow_html=True,
        )
        if gcol2.button(
            "✏️", key="savings_goal_edit_btn",
            help="Editing is disabled in Privacy Mode" if blur else "Edit goal",
            disabled=blur,
        ):
            st.session_state["savings_goal_editing"] = True
            st.rerun()
    else:
        new_goal = st.number_input(
            "New goal ($)", min_value=0, value=int(current_goal), step=1000,
            key="savings_goal_input", label_visibility="collapsed",
        )
        scol1, scol2 = st.columns(2)
        if scol1.button("Save", key="savings_goal_save", width='stretch'):
            set_setting("cash_goal", new_goal)
            st.session_state["savings_goal_editing"] = False
            st.cache_data.clear()
            st.rerun()
        if scol2.button("Cancel", key="savings_goal_cancel", width='stretch'):
            st.session_state["savings_goal_editing"] = False
            st.rerun()

    st.markdown(
        f"""
        <div class="ledger-card">
            <p style="color:{MUTED}; margin:0;">
                {blur_amount(current_cash, blur)} saved &middot; {blur_amount(remaining, blur)} remaining
            </p>
            <hr style="margin:1rem 0;">
            <div class="ledger-eyebrow">Required pace</div>
            <p class="ledger-number" style="font-size:1.4rem; margin:0;">
                {blur_amount(required_monthly, blur)} / month
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()

# --- Drill-down: recent transactions for a selected account ------------
# NOTE: Plotly pie/donut charts don't reliably support click-to-select in
# Streamlit's on_select feature (a known library limitation, not specific
# to this chart) -- so this uses a dropdown instead, which always works.
if not cash_by_account.empty:
    account_options = ["Select an account..."] + cash_by_account["display_name"].tolist()
    chosen = st.selectbox("View recent transactions for:", account_options, key="savings_drilldown_select")

    if chosen != "Select an account...":
        selected_account = cash_by_account[cash_by_account["display_name"] == chosen].iloc[0]

        st.subheader(f"{selected_account['display_name']} — Recent Transactions")

        txns = get_account_transactions(selected_account["account_id"])
        if txns.empty:
            st.info("No transactions found for this account.")
        else:
            display = txns.rename(columns={
                "date": "Date", "description": "Description", "amount": "Amount",
                "pfc_primary": "Category", "pfc_detailed": "Detail",
            })
            if blur:
                display = display.copy()
                display["Amount"] = display["Amount"].apply(lambda v: blur_amount(v, True))
            st.dataframe(display, hide_index=True, width='stretch', height=400)
            safe_download_button(
                "Download CSV", display,
                file_name=f"{selected_account['display_name'].replace(' ', '_').lower()}_transactions.csv",
                key="dl_account_txns",
            )

st.divider()

# --- Fit window (drives both the expense candidate list and the trend fit)
df = df.sort_values("date")
df["ordinal"] = df["date"].map(pd.Timestamp.toordinal)

data_start_date = df["date"].min().date()
data_end_date = df["date"].max().date()

fit_start, fit_end = st.slider(
    "Fit window (controls which history is used below -- both for flagging "
    "one-time expenses and calculating the trend line)",
    min_value=data_start_date, max_value=data_end_date,
    value=(data_start_date, data_end_date),
)

window_df = df[
    (df["date"] >= pd.Timestamp(fit_start)) & (df["date"] <= pd.Timestamp(fit_end))
]

st.divider()

# --- Large one-time expense flagging ------------------------------------
st.subheader("Large One-Time Expenses")
st.caption(
    "Flag big one-time purchases within the fit window above (car, remodel, "
    "roof, etc.) and they'll be backed out of the trend calculation below -- "
    "showing what your pace looks like without that one-time hit."
)

if blur:
    level_choice = st.select_slider(
        "Flag transactions over:", options=["Small", "Medium", "Large", "Very Large"], value="Medium",
    )
    threshold = {"Small": 300, "Medium": 1000, "Large": 3000, "Very Large": 7000}[level_choice]
else:
    threshold = st.slider(
        "Flag transactions over ($)", min_value=200, max_value=10_000,
        value=1000, step=100, key="event_threshold",
    )

candidates = get_large_transactions(threshold=threshold)
if not candidates.empty:
    candidates = candidates.copy()
    candidates["date_ts"] = pd.to_datetime(candidates["date"])
    candidates = candidates[
        (candidates["date_ts"] >= pd.Timestamp(fit_start)) & (candidates["date_ts"] <= pd.Timestamp(fit_end))
    ]

existing = get_all_flagged_events()
existing_by_id = existing.set_index("transaction_id") if not existing.empty else existing

with st.expander(
    f"Review {len(candidates)} transaction(s) over {blur_amount(threshold, blur)} within the fit window",
    key="large_expense_expander",
):
    if candidates.empty:
        st.caption("No transactions above this threshold within the current fit window.")
    else:
        pending_rows = []
        for _, row in candidates.iterrows():
            tx_id = row["transaction_id"]
            prior = (
                existing_by_id.loc[tx_id]
                if not existing_by_id.empty and tx_id in existing_by_id.index
                else None
            )
            default_checked = bool(prior["is_active"]) if prior is not None else False
            default_label = prior["label"] if prior is not None else row["description"]

            c1, c2, c3 = st.columns([0.4, 2, 1])
            checked = c1.checkbox("Flag", value=default_checked, key=f"event_check_{tx_id}", label_visibility="collapsed")
            label = c2.text_input(
                "Label", value=default_label, key=f"event_label_{tx_id}", label_visibility="collapsed",
            )
            c3.markdown(
                f"<span class='ledger-number' style='color:{MUTED};'>"
                f"{row['date']} &middot; {blur_amount(abs(row['amount']), blur)}</span>",
                unsafe_allow_html=True,
            )
            pending_rows.append((tx_id, row["date"], row["amount"], label, checked))

        if st.button("Save flagged expenses"):
            for tx_id, tx_date, tx_amount, tx_label, tx_checked in pending_rows:
                save_event(tx_id, tx_date, tx_amount, tx_label, tx_checked)
            st.session_state["large_expense_expander"] = False
            st.cache_data.clear()
            st.rerun()

st.divider()

# --- Trend + projection -------------------------------------------
st.subheader("Trend & Projection")

if len(window_df) >= 2:
    # Back out flagged one-time expenses before fitting: for each active
    # event within the window, add its amount back to every day on/after
    # its date. This removes the step-down it caused, so the fit reflects
    # "what if that one-time hit hadn't happened" rather than being dragged
    # down by a single anomalous purchase.
    active_events = get_active_events()
    window_events = pd.DataFrame()
    smoothed = window_df.copy()

    if not active_events.empty:
        active_events = active_events.copy()
        active_events["date"] = pd.to_datetime(active_events["date"])
        window_events = active_events[
            (active_events["date"] >= pd.Timestamp(fit_start)) & (active_events["date"] <= pd.Timestamp(fit_end))
        ]
        for _, ev in window_events.iterrows():
            mask = smoothed["date"] >= ev["date"]
            smoothed.loc[mask, "total_cash"] = smoothed.loc[mask, "total_cash"] + abs(ev["amount"])

    slope, _ = np.polyfit(smoothed["ordinal"], smoothed["total_cash"], 1)
    monthly_trend_rate = slope * 30.44

    # Project forward from TODAY'S actual balance using the smoothed slope,
    # so the projected line always connects cleanly to the real current
    # point even if the fit window doesn't include the most recent data.
    current_ordinal = pd.Timestamp(current_date).toordinal()
    future_dates = pd.date_range(current_date, target_date, freq="7D")
    future_ordinals = future_dates.map(pd.Timestamp.toordinal)
    projected = current_cash + slope * (future_ordinals - current_ordinal)

    fig = go.Figure()
    actual_hovertext = df.apply(
        lambda row: f"{row['date'].strftime('%b %d, %Y')}: {blur_amount(row['total_cash'], blur)}", axis=1
    )
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total_cash"], mode="lines", name="Actual",
        line=dict(color=EMERALD, width=2.5),
        text=actual_hovertext,
        hovertemplate="%{text}<extra></extra>",
    ))
    projected_hovertext = [
        f"{d.strftime('%b %d, %Y')}: {blur_amount(v, blur)}" for d, v in zip(future_dates, projected)
    ]
    fig.add_trace(go.Scatter(
        x=future_dates, y=projected, mode="lines",
        name="Projected (excl. flagged expenses)" if not window_events.empty else "Projected (fit window pace)",
        line=dict(color=MUTED, width=1.5, dash="dot"),
        text=projected_hovertext,
        hovertemplate="%{text}<extra></extra>",
    ))
    fig.add_hline(y=current_goal, line_dash="dash", line_color=TEAL,
                   annotation_text="Goal", annotation_font_color=TEAL)
    fig.add_vrect(
        x0=fit_start, x1=fit_end,
        fillcolor=SURFACE_LINE, opacity=0.25, line_width=0,
        annotation_text="Fit window", annotation_position="top left",
        annotation_font_color=MUTED,
    )

    # Flagged large one-time expenses, annotated directly on the chart
    # (amount hidden from the annotation label while blurred)
    if not window_events.empty:
        for _, ev in window_events.iterrows():
            fig.add_vline(x=ev["date"], line_dash="dot", line_color=RUST, opacity=0.6)
            amount_text = blur_amount(abs(ev["amount"]), blur)
            fig.add_annotation(
                x=ev["date"], y=df["total_cash"].max(),
                text=f"{ev['label']}<br>{amount_text}",
                showarrow=True, arrowhead=1, ax=0, ay=-40,
                font=dict(color=RUST, size=10, family="IBM Plex Sans"),
                bgcolor=SURFACE, bordercolor=RUST, borderwidth=1,
            )

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
    )
    st.plotly_chart(fig, width='stretch')

    if monthly_trend_rate > 0:
        months_to_goal_at_trend = max(current_goal - current_cash, 0) / monthly_trend_rate
        color = GREEN if monthly_trend_rate * target_months >= remaining else RUST
        excl_note = (
            f" (excluding {len(window_events)} flagged one-time expense(s))"
            if not window_events.empty else ""
        )
        st.markdown(
            f"""<p style="color:{MUTED};">
            At the pace observed within the fit window{excl_note}
            (<span class="ledger-number" style="color:{color};">{blur_amount(monthly_trend_rate, blur)}/month</span>),
            the goal would be reached in roughly
            <span class="ledger-number" style="color:{color};">{months_to_goal_at_trend:,.1f} months</span>
            &mdash; versus the {target_months}-month target above.
            </p>""",
            unsafe_allow_html=True,
        )
    else:
        st.warning("Cash balance was flat or declining within the selected fit window -- "
                    "no positive trend to project forward from.")
else:
    st.info("Select a fit window with at least two days of balance history.")