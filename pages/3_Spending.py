import streamlit as st
import plotly.graph_objects as go
import calendar
from datetime import date, timedelta

from db import (
    get_spending_by_category, get_category_merchant_breakdown,
    get_top_merchants, get_merchant_transactions, get_recurring_streams,
)
from theme import inject_base_css, EMERALD, TEAL, MUTED, GREEN, RUST, SURFACE_LINE, TEXT
from utils import blur_toggle_sidebar, is_blur_active, blur_amount, safe_download_button

st.set_page_config(page_title="Spending", page_icon="🧾", layout="wide")
inject_base_css()
blur_toggle_sidebar()
blur = is_blur_active()

st.markdown('<div class="ledger-eyebrow">Financial Goals</div>', unsafe_allow_html=True)
st.title("Spending")


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
    level = st.radio("Detail", ["Broad category", "Detailed category"])

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
    prev_df = get_spending_by_category(start_date=prev_start, end_date=prev_end, level="pfc_primary")
    compare_total = prev_df["total"].sum() if not prev_df.empty else 0
    compare_label = f"{calendar.month_name[prev_month]} {prev_year}"

else:  # Year-over-year
    with st.sidebar:
        month_name = st.selectbox("Month", list(calendar.month_name)[1:], index=today.month - 1)
    sel_month = list(calendar.month_name).index(month_name)
    start, end = month_bounds(today.year, sel_month)

    prev_start, prev_end = month_bounds(today.year - 1, sel_month)
    prev_df = get_spending_by_category(start_date=prev_start, end_date=prev_end, level="pfc_primary")
    compare_total = prev_df["total"].sum() if not prev_df.empty else 0
    compare_label = f"{month_name} {today.year - 1}"

pfc_level = "pfc_primary" if level == "Broad category" else "pfc_detailed"
df = get_spending_by_category(start_date=start, end_date=end, level=pfc_level)

if df.empty:
    st.info("No spending transactions found for this range.")
    st.stop()

# --- Comparison banner (calendar month / year-over-year modes only) ----
if compare_total is not None:
    current_total = df["total"].sum()
    delta = current_total - compare_total
    pct = (delta / compare_total * 100) if compare_total else 0
    delta_color = RUST if delta > 0 else GREEN  # more spending = rust, less = green
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

# Keep the raw category value for querying; category_label is just for display.
df["category_raw"] = df["category"]
df["category_label"] = df["category"].fillna("UNCATEGORIZED").str.replace("_", " ").str.title()

col1, col2 = st.columns([2, 1])

with col1:
    st.caption("Click a bar to see the merchants behind that category.")

    fig = go.Figure(go.Bar(
        x=df["total"], y=df["category_label"], orientation="h",
        marker=dict(
            color=df["total"], colorscale=[[0, EMERALD], [1, TEAL]],
            line=dict(width=0),
        ),
        customdata=df["total"].apply(lambda v: blur_amount(v, blur)),
        hovertemplate="%{y}: %{customdata}<extra></extra>",
    ))
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color=TEXT),
        xaxis=dict(gridcolor=SURFACE_LINE, tickprefix="$", separatethousands=True, showticklabels=not blur),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=10, b=10, l=10, r=10),
        height=max(400, len(df) * 28),
        hoverlabel=dict(bgcolor=SURFACE_LINE, font_color=TEXT, bordercolor=TEAL),
        clickmode="event+select",
    )

    event = st.plotly_chart(
        fig, width='stretch',
        on_select="rerun", selection_mode="points",
        key="spending_bar_chart",
    )

with col2:
    st.metric("Total Spending", blur_amount(df["total"].sum(), blur))
    category_display = df[["category_label", "total"]].rename(
        columns={"category_label": "Category", "total": "Total"}
    )
    if blur:
        category_display = category_display.copy()
        category_display["Total"] = category_display["Total"].apply(lambda v: blur_amount(v, True))
    st.dataframe(category_display, hide_index=True, width='stretch')
    safe_download_button(
        "Download CSV", category_display, file_name="spending_by_category.csv", key="dl_category",
    )

# --- Drill-down: merchants behind the selected category ---------------
selected_category = None
if event and event.get("selection") and event["selection"].get("points"):
    point = event["selection"]["points"][0]
    idx = point.get("point_index")
    if idx is not None:
        selected_category = df.iloc[idx]["category_raw"]

if selected_category:
    st.divider()
    label = df[df["category_raw"] == selected_category].iloc[0]["category_label"]
    st.subheader(f"{label} — Line Items")

    merchants = get_category_merchant_breakdown(
        selected_category, level=pfc_level, start_date=start, end_date=end
    )

    if merchants.empty:
        st.info("No line items found for this category in the selected range.")
    else:
        by_merchant = merchants.groupby("merchant")["amount"].sum().sort_values(ascending=False).reset_index()

        drill_fig = go.Figure(go.Bar(
            x=by_merchant["amount"], y=by_merchant["merchant"], orientation="h",
            marker=dict(color=MUTED, line=dict(width=0)),
            customdata=by_merchant["amount"].apply(lambda v: blur_amount(v, blur)),
            hovertemplate="%{y}: %{customdata}<extra></extra>",
        ))
        drill_fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="IBM Plex Sans", color=TEXT),
            xaxis=dict(gridcolor=SURFACE_LINE, tickprefix="$", separatethousands=True, showticklabels=not blur),
            yaxis=dict(autorange="reversed"),
            margin=dict(t=10, b=10, l=10, r=10),
            height=max(300, len(by_merchant) * 32),
            hoverlabel=dict(bgcolor=SURFACE_LINE, font_color=TEXT, bordercolor=MUTED),
        )
        st.plotly_chart(drill_fig, width='stretch')

        st.caption(f"{len(merchants)} transaction(s)")
        line_items_display = merchants.rename(columns={"merchant": "Merchant", "date": "Date", "amount": "Amount"})
        if blur:
            line_items_display = line_items_display.copy()
            line_items_display["Amount"] = line_items_display["Amount"].apply(lambda v: blur_amount(v, True))
        st.dataframe(line_items_display, hide_index=True, width='stretch', height=350)
        safe_download_button(
            "Download CSV", line_items_display,
            file_name=f"{label.replace(' ', '_').lower()}_line_items.csv", key="dl_category_lineitems",
        )

st.divider()
st.subheader("Top Merchants")
st.caption("Biggest merchants by total spend, regardless of category -- often more concrete than category buckets.")

top_merchants = get_top_merchants(start_date=start, end_date=end, limit=15)
if top_merchants.empty:
    st.caption("No merchant data for this range.")
else:
    merch_customdata = list(zip(
        top_merchants["total"].apply(lambda v: blur_amount(v, blur)),
        top_merchants["transactions"],
    ))
    merch_fig = go.Figure(go.Bar(
        x=top_merchants["total"], y=top_merchants["merchant"], orientation="h",
        marker=dict(
            color=top_merchants["total"], colorscale=[[0, EMERALD], [1, TEAL]],
            line=dict(width=0),
        ),
        customdata=merch_customdata,
        hovertemplate="%{y}: %{customdata[0]} (%{customdata[1]} txn)<extra></extra>",
    ))
    merch_fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans", color=TEXT),
        xaxis=dict(gridcolor=SURFACE_LINE, tickprefix="$", separatethousands=True, showticklabels=not blur),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=10, b=10, l=10, r=10),
        height=max(350, len(top_merchants) * 28),
        hoverlabel=dict(bgcolor=SURFACE_LINE, font_color=TEXT, bordercolor=TEAL),
        clickmode="event+select",
    )

    st.caption("Click a bar to see every transaction with that merchant.")
    merch_event = st.plotly_chart(
        merch_fig, width='stretch',
        on_select="rerun", selection_mode="points",
        key="top_merchants_chart",
    )
    top_merchants_display = top_merchants.rename(
        columns={"merchant": "Merchant", "total": "Total", "transactions": "Transactions"}
    )
    if blur:
        top_merchants_display = top_merchants_display.copy()
        top_merchants_display["Total"] = top_merchants_display["Total"].apply(lambda v: blur_amount(v, True))
    safe_download_button(
        "Download CSV", top_merchants_display, file_name="top_merchants.csv", key="dl_top_merchants",
    )

    selected_merchant = None
    if merch_event and merch_event.get("selection") and merch_event["selection"].get("points"):
        point = merch_event["selection"]["points"][0]
        idx = point.get("point_index")
        if idx is not None:
            selected_merchant = top_merchants.iloc[idx]["merchant"]

    if selected_merchant:
        st.subheader(f"{selected_merchant} — All Transactions")
        merchant_txns = get_merchant_transactions(selected_merchant, start_date=start, end_date=end)
        if merchant_txns.empty:
            st.info("No transactions found.")
        else:
            display = merchant_txns.rename(columns={
                "date": "Date", "amount": "Amount",
                "pfc_primary": "Category", "pfc_detailed": "Detail",
            })
            if blur:
                display = display.copy()
                display["Amount"] = display["Amount"].apply(lambda v: blur_amount(v, True))
            st.dataframe(display, hide_index=True, width='stretch', height=350)
            safe_download_button(
                "Download CSV", display,
                file_name=f"{selected_merchant.replace(' ', '_').lower()}_transactions.csv",
                key="dl_merchant_txns",
            )

st.divider()
st.subheader("Recurring")

recurring = get_recurring_streams()
if not recurring.empty:
    display = recurring[["direction", "merchant_name", "description", "average_amount", "frequency"]].copy()
    display.columns = ["Direction", "Merchant", "Description", "Avg Amount", "Frequency"]
    if blur:
        display["Avg Amount"] = display["Avg Amount"].apply(lambda v: blur_amount(v, True))
    st.dataframe(display, hide_index=True, width='stretch')
    safe_download_button(
        "Download CSV", display, file_name="recurring_streams.csv", key="dl_recurring",
    )
else:
    st.caption("No recurring streams synced yet -- run get_recurring_streams() to populate this section.")