import streamlit as st
import pandas as pd

from db import (
    get_accounts, get_cash_total_by_date, get_balance_trend,
    get_setting, set_setting, get_latest_cash_by_account,
)
from theme import inject_base_css, build_goal_donut, EMERALD, MUTED, GREEN
from config import CASH_GOAL, GOAL_MONTHS_MIN, GOAL_MONTHS_MAX
from utils import blur_toggle_sidebar, is_blur_active, blur_amount

st.set_page_config(page_title="Financial Goals", page_icon="🌿", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()
if blur:
    st.session_state["home_goal_editing"] = False

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Overview")

accounts = get_accounts()
cash_series = get_cash_total_by_date()

if cash_series.empty:
    st.warning("No balance history yet. Run the daily sync to start populating this dashboard.")
    st.stop()

current_cash = cash_series.iloc[-1]["total_cash"]
current_date = cash_series.iloc[-1]["date"]
as_of = current_date.strftime("%B %d, %Y")

# Goal is stored in the database (settings table) so it's editable and
# stays in sync with the Savings Goal page. config.CASH_GOAL is only
# the fallback used the very first time, before anyone has edited it.
current_goal = float(get_setting("cash_goal", CASH_GOAL))

# --- Top row: combined goal + account-breakdown donut + key figures ---
cash_by_account = get_latest_cash_by_account()

col_gauge, col_stats = st.columns([1, 2])

with col_gauge:
    if not cash_by_account.empty:
        fig_donut = build_goal_donut(
            current=current_cash, goal=current_goal,
            account_labels=cash_by_account["display_name"],
            account_values=cash_by_account["current_balance"],
            blur=blur,
        )
        st.plotly_chart(fig_donut, width='stretch')
    st.markdown(
        f'<p style="text-align:center; color:{MUTED}; font-family:IBM Plex Mono, monospace; '
        f'font-size:0.85rem;">as of {as_of}</p>',
        unsafe_allow_html=True,
    )

with col_stats:
    remaining = max(current_goal - current_cash, 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("Current Cash", blur_amount(current_cash, blur))

    # Goal rendered in emerald, with a small inline edit affordance rather
    # than a separate expander -- one click reveals a compact input right
    # in place, no extra container to open.
    with c2:
        st.markdown('<div class="ledger-eyebrow">Goal</div>', unsafe_allow_html=True)

        if not st.session_state.get("home_goal_editing", False):
            gcol1, gcol2 = st.columns([5, 1])
            gcol1.markdown(
                f'<p class="ledger-number" style="font-size:1.6rem; color:{EMERALD}; margin:0;">'
                f'{blur_amount(current_goal, blur)}</p>',
                unsafe_allow_html=True,
            )
            if gcol2.button(
                "✏️", key="home_goal_edit_btn",
                help="Editing is disabled in Privacy Mode" if blur else "Edit goal",
                disabled=blur,
            ):
                st.session_state["home_goal_editing"] = True
                st.rerun()
        else:
            new_goal = st.number_input(
                "New goal ($)", min_value=0, value=int(current_goal), step=1000,
                key="home_goal_input", label_visibility="collapsed",
            )
            scol1, scol2 = st.columns(2)
            if scol1.button("Save", key="home_goal_save", width='stretch'):
                set_setting("cash_goal", new_goal)
                st.session_state["home_goal_editing"] = False
                st.cache_data.clear()
                st.rerun()
            if scol2.button("Cancel", key="home_goal_cancel", width='stretch'):
                st.session_state["home_goal_editing"] = False
                st.rerun()

    c3.metric("Remaining", blur_amount(remaining, blur))

    # Required pace to hit the goal within the stated window
    months_min_left = GOAL_MONTHS_MIN
    months_max_left = GOAL_MONTHS_MAX
    pace_fast = remaining / months_min_left if months_min_left else 0
    pace_slow = remaining / months_max_left if months_max_left else 0

    st.markdown(
        f"""
        <div class="ledger-card" style="margin-top:0.5rem;">
            <div class="ledger-eyebrow">Required monthly pace</div>
            <p class="ledger-number" style="font-size:1.4rem; margin:0;">
                {blur_amount(pace_slow, blur)} &ndash; {blur_amount(pace_fast, blur)} / month
            </p>
            <p style="color:{MUTED}; font-size:0.85rem; margin-top:0.25rem;">
                to reach {blur_amount(current_goal, blur)} within {months_min_left}&ndash;{months_max_left} months
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Recent average pace, selectable lookback window ---------------
    data_start = cash_series["date"].min()
    total_months_available = max(
        1, (current_date.year - data_start.year) * 12 + (current_date.month - data_start.month)
    )
    default_lookback = min(6, total_months_available)

    lookback_months = st.slider(
        "Compare against actual pace over the last (months):",
        min_value=1, max_value=total_months_available, value=default_lookback,
    )

    cutoff = current_date - pd.DateOffset(months=lookback_months)
    past = cash_series[cash_series["date"] <= cutoff]

    if not past.empty:
        past_value = past.iloc[-1]["total_cash"]
        past_date = past.iloc[-1]["date"]
        elapsed_months = max((current_date - past_date).days / 30.44, 0.1)
        actual_pace = (current_cash - past_value) / elapsed_months
        pace_color = GREEN if actual_pace >= pace_slow else "#B0563C"

        st.markdown(
            f'<p style="color:{MUTED}; font-size:0.85rem; margin-top:0.5rem;">'
            f'Actual average pace over the last {lookback_months} month(s): '
            f'<span class="ledger-number" style="color:{pace_color};">{blur_amount(actual_pace, blur)}/month</span>'
            f'</p>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("Not enough history yet for this lookback window.")

st.divider()

# --- Balance breakdown by account type --------------------------------
st.subheader("Balances by Type")

latest_by_account = get_balance_trend()
if not latest_by_account.empty:
    latest_date = latest_by_account["date"].max()
    latest_snapshot = latest_by_account[latest_by_account["date"] == latest_date].copy()

    # Retirement-specific subtypes; everything else under "investment"
    # (brokerage, hsa, 529, etc.) is treated as Individual for our purposes.
    RETIREMENT_SUBTYPES = {"401k", "403b", "ira", "roth"}

    def categorize(row):
        if row["type"] == "depository":
            return "Cash"
        if row["type"] == "investment":
            return "Retirement" if row["subtype"] in RETIREMENT_SUBTYPES else "Individual"
        return str(row["type"]).title() if row["type"] else "Other"

    latest_snapshot["display_type"] = latest_snapshot.apply(categorize, axis=1)
    by_type = latest_snapshot.groupby("display_type")["current_balance"].sum().reset_index()
    by_type.columns = ["Type", "Total"]

    cols = st.columns(len(by_type)) if len(by_type) > 0 else [st]
    for col, (_, row) in zip(cols, by_type.iterrows()):
        col.metric(row["Type"], blur_amount(row["Total"], blur))

st.caption(
    "Cash goal tracks checking + savings only. Investments and retirement "
    "balances are shown above for context but excluded from the goal above."
)