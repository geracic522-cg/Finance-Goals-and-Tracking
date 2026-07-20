import streamlit as st
import plotly.graph_objects as go
import calendar
from datetime import date, timedelta

from db import (
    get_income_by_person, get_person_income_transactions,
    get_income_sources, get_income_source_transactions,
    get_monthly_income_vs_spending, get_recurring_streams,
)
from theme import inject_base_css, EMERALD, TEAL, MUTED, GREEN, RUST, SURFACE_LINE, TEXT
from utils import blur_toggle_sidebar, is_blur_active, blur_amount, safe_download_button

st.set_page_config(page_title="Income & Tax", page_icon="💰", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Income & Tax")


def month_bounds(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last_day).isoformat()


def shift_month(year, month, delta):
    m = month - 1 + delta
    y = year + m // 12
    m = m % 12 + 1
    return y, m


today = date.today()
compare_total = None
compare_label = None

with st.sidebar:
    st.subheader("Date range")
    mode = st.radio("Mode", ["Rolling window", "Calendar month", "Year-over-year"])

if mode == "Rolling window":
    with st.sidebar:
        range_choice = st.radio(
            "Period", ["Last 30 days", "Last 90 days", "Last 6 months", "Last 365 days", "All time"]
        )
    if range_choice == "Last 30 days":
        start = (today - timedelta(days=30)).isoformat()
    elif range_choice == "Last 90 days":
        start = (today - timedelta(days=90)).isoformat()
    elif range_choice == "Last 6 months":
        start = (today - timedelta(days=182)).isoformat()
    elif range_choice == "Last 365 days":
        start = (today - timedelta(days=365)).isoformat()
    else:
        start = None
    end = None

elif mode == "Calendar month":
    month_options = []
    y, m = today.year, today.month
    for i in range(24):
        label = f"{calendar.month_name[m]} {y}" + (" (current)" if i == 0 else "")
        month_options.append((label, y, m))
        y, m = shift_month(y, m, -1)

    with st.sidebar:
        choice_label = st.selectbox("Month", [opt[0] for opt in month_options])
    _, sel_year, sel_month = next(opt for opt in month_options if opt[0] == choice_label)
    start, end = month_bounds(sel_year, sel_month)

    prev_year, prev_month = shift_month(sel_year, sel_month, -1)
    prev_start, prev_end = month_bounds(prev_year, prev_month)
    prev_df = get_income_by_person(start_date=prev_start, end_date=prev_end)
    compare_total = prev_df["total"].sum() if not prev_df.empty else 0
    compare_label = f"{calendar.month_name[prev_month]} {prev_year}"

else:  # Year-over-year
    with st.sidebar:
        month_name = st.selectbox("Month", list(calendar.month_name)[1:], index=today.month - 1)
    sel_month = list(calendar.month_name).index(month_name)
    start, end = month_bounds(today.year, sel_month)

    prev_start, prev_end = month_bounds(today.year - 1, sel_month)
    prev_df = get_income_by_person(start_date=prev_start, end_date=prev_end)
    compare_total = prev_df["total"].sum() if not prev_df.empty else 0
    compare_label = f"{month_name} {today.year - 1}"

person_df = get_income_by_person(start_date=start, end_date=end)

if person_df.empty:
    st.info("No income transactions found for this range.")
    st.stop()

# --- Comparison banner (calendar month / year-over-year modes only) ----
if compare_total is not None:
    current_total = person_df["total"].sum()
    delta = current_total - compare_total
    pct = (delta / compare_total * 100) if compare_total else 0
    delta_color = GREEN if delta > 0 else RUST  # more income = green, less = rust (opposite of Spending)
    arrow = "▲" if delta > 0 else "▼"

    st.markdown(
        f"""
        <div class="ledger-card" style="margin-bottom:1rem;">
            <div class="ledger-eyebrow">Compared to {compare_label}</div>
            <p class="ledger-number" style="font-size:1.4rem; margin:0;">
                {blur_amount(current_total, blur)} <span style="color:{MUTED}; font-size:1rem;">vs</span>
                {blur_amount(compare_total, blur)}
                <span style="color:{delta_color};">{arrow} {blur_amount(abs(delta), blur)} ({abs(pct):.1f}%)</span>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- Income by Person -----------------------------------------------------
st.subheader("Income by Person")
st.caption(
    "Click a bar to see that person's transactions. Y's pay is Plaid-categorized "
    "directly; X's is recognized by transfer pattern since their employer pays "
    "via a plain inter-account transfer rather than a categorized deposit."
)

pcol1, pcol2 = st.columns([2, 1])

with pcol1:
    person_fig = go.Figure(go.Bar(
        x=person_df["total"], y=person_df["person"], orientation="h",
        marker=dict(color=[EMERALD, TEAL, MUTED][:len(person_df)], line=dict(width=0)),
        customdata=person_df["total"].apply(lambda v: blur_amount(v, blur)),
        hovertemplate="%{y}: %{customdata}<extra></extra>",
    ))
    person_fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color=TEXT),
        xaxis=dict(gridcolor=SURFACE_LINE, tickprefix="$", separatethousands=True, showticklabels=not blur),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=10, b=10, l=10, r=10),
        height=220,
        clickmode="event+select",
    )
    person_event = st.plotly_chart(
        person_fig, width='stretch',
        on_select="rerun", selection_mode="points",
        key="income_person_chart",
    )

with pcol2:
    st.metric("Total Income", blur_amount(person_df["total"].sum(), blur))
    person_display = person_df.rename(columns={"person": "Person", "total": "Total"})
    if blur:
        person_display = person_display.copy()
        person_display["Total"] = person_display["Total"].apply(lambda v: blur_amount(v, True))
    st.dataframe(person_display, hide_index=True, width='stretch')
    safe_download_button(
        "Download CSV", person_display, file_name="income_by_person.csv", key="dl_income_person",
    )

selected_person = None
if person_event and person_event.get("selection") and person_event["selection"].get("points"):
    point = person_event["selection"]["points"][0]
    idx = point.get("point_index")
    if idx is not None:
        selected_person = person_df.iloc[idx]["person"]

if selected_person:
    st.subheader(f"{selected_person} — Transactions")
    person_txns = get_person_income_transactions(selected_person, start_date=start, end_date=end)
    if person_txns.empty:
        st.info("No transactions found.")
    else:
        display = person_txns.rename(columns={
            "date": "Date", "description": "Description", "amount": "Amount",
            "pfc_primary": "Category", "pfc_detailed": "Detail",
        })
        if blur:
            display = display.copy()
            display["Amount"] = display["Amount"].apply(lambda v: blur_amount(v, True))
        st.dataframe(display, hide_index=True, width='stretch', height=300)
        safe_download_button(
            "Download CSV", display,
            file_name=f"{selected_person.lower()}_income_transactions.csv", key="dl_person_txns",
        )

st.divider()
st.subheader("Top Income Sources")
st.caption("Biggest payers, regardless of category.")

top_sources = get_income_sources(start_date=start, end_date=end, limit=15)
if top_sources.empty:
    st.caption("No source data for this range.")
else:
    src_customdata = list(zip(
        top_sources["total"].apply(lambda v: blur_amount(v, blur)), top_sources["transactions"],
    ))
    src_fig = go.Figure(go.Bar(
        x=top_sources["total"], y=top_sources["source"], orientation="h",
        marker=dict(
            color=top_sources["total"], colorscale=[[0, EMERALD], [1, TEAL]],
            line=dict(width=0),
        ),
        customdata=src_customdata,
        hovertemplate="%{y}: %{customdata[0]} (%{customdata[1]} txn)<extra></extra>",
    ))
    src_fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color=TEXT),
        xaxis=dict(gridcolor=SURFACE_LINE, tickprefix="$", separatethousands=True, showticklabels=not blur),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=10, b=10, l=10, r=10),
        height=max(300, len(top_sources) * 28),
        hoverlabel=dict(bgcolor=SURFACE_LINE, font_color=TEXT, bordercolor=TEAL),
        clickmode="event+select",
    )

    st.caption("Click a bar to see every transaction from that source.")
    src_event = st.plotly_chart(
        src_fig, width='stretch',
        on_select="rerun", selection_mode="points",
        key="top_income_sources_chart",
    )
    top_sources_display = top_sources.rename(
        columns={"source": "Source", "total": "Total", "transactions": "Transactions"}
    )
    if blur:
        top_sources_display = top_sources_display.copy()
        top_sources_display["Total"] = top_sources_display["Total"].apply(lambda v: blur_amount(v, True))
    safe_download_button(
        "Download CSV", top_sources_display, file_name="top_income_sources.csv", key="dl_top_sources",
    )

    selected_source = None
    if src_event and src_event.get("selection") and src_event["selection"].get("points"):
        point = src_event["selection"]["points"][0]
        idx = point.get("point_index")
        if idx is not None:
            selected_source = top_sources.iloc[idx]["source"]

    if selected_source:
        st.subheader(f"{selected_source} — All Transactions")
        source_txns = get_income_source_transactions(selected_source, start_date=start, end_date=end)
        if source_txns.empty:
            st.info("No transactions found.")
        else:
            display = source_txns.rename(columns={
                "date": "Date", "amount": "Amount",
                "pfc_primary": "Category", "pfc_detailed": "Detail",
            })
            if blur:
                display = display.copy()
                display["Amount"] = display["Amount"].apply(lambda v: blur_amount(v, True))
            st.dataframe(display, hide_index=True, width='stretch', height=300)
            safe_download_button(
                "Download CSV", display,
                file_name=f"{selected_source.replace(' ', '_').lower()}_transactions.csv",
                key="dl_source_txns",
            )

st.divider()
st.subheader("Net Cash Flow")
st.caption("Income vs. spending, by month. Green months saved money; rust months spent more than they earned.")

cash_flow = get_monthly_income_vs_spending(start_date=start, end_date=end)
if cash_flow.empty:
    st.caption("No data for this range.")
else:
    flow_hovertext = cash_flow.apply(
        lambda row: f"{row['month']}: income {blur_amount(row['income'], blur)}, "
                    f"spending {blur_amount(row['spending'], blur)}, net {blur_amount(row['net'], blur)}",
        axis=1,
    )
    bar_colors = [GREEN if v >= 0 else RUST for v in cash_flow["net"]]
    flow_fig = go.Figure(go.Bar(
        x=cash_flow["month"], y=cash_flow["net"],
        marker=dict(color=bar_colors, line=dict(width=0)),
        text=flow_hovertext,
        hovertemplate="%{text}<extra></extra>",
    ))
    flow_fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color=TEXT),
        xaxis=dict(gridcolor=SURFACE_LINE),
        yaxis=dict(gridcolor=SURFACE_LINE, tickprefix="$", separatethousands=True, showticklabels=not blur),
        margin=dict(t=10, b=10, l=10, r=10),
        height=350,
    )
    st.plotly_chart(flow_fig, width='stretch')

    flow_display = cash_flow.rename(columns={"month": "Month", "income": "Income", "spending": "Spending", "net": "Net"})
    if blur:
        flow_display = flow_display.copy()
        for col in ["Income", "Spending", "Net"]:
            flow_display[col] = flow_display[col].apply(lambda v: blur_amount(v, True))
    safe_download_button("Download CSV", flow_display, file_name="net_cash_flow.csv", key="dl_cash_flow")

st.divider()
st.subheader("Recurring Income")

recurring = get_recurring_streams()
recurring_income = recurring[recurring["direction"] == "INFLOW"] if not recurring.empty else recurring
if not recurring_income.empty:
    display = recurring_income[["merchant_name", "description", "average_amount", "frequency"]].copy()
    display.columns = ["Source", "Description", "Avg Amount", "Frequency"]
    if blur:
        display["Avg Amount"] = display["Avg Amount"].apply(lambda v: blur_amount(v, True))
    st.dataframe(display, hide_index=True, width='stretch')
    safe_download_button("Download CSV", display, file_name="recurring_income.csv", key="dl_recurring_income")
else:
    st.caption("No recurring income streams synced yet.")