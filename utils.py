"""Small shared utilities used across pages."""

import streamlit as st
import pandas as pd


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convert a dataframe to CSV bytes for st.download_button."""
    return df.to_csv(index=False).encode("utf-8")


def reconstruct_mortgage_balance(payments_df: pd.DataFrame, current_balance: float) -> pd.DataFrame:
    """
    Reconstructs historical mortgage balance from a known current balance
    plus a log of payments (date, principal, interest). Same backward-
    walk technique used to backfill Raisin's account history: each
    payment's principal portion is added BACK as we step backward in
    time, since paying principal is what reduced the balance going
    forward. Returns a date-sorted dataframe with one row per payment
    date, each showing the balance AFTER that payment posted.
    """
    if payments_df.empty:
        return pd.DataFrame(columns=["date", "balance"])

    df = payments_df.sort_values("date", ascending=False).copy()
    running = current_balance
    rows = []
    for _, row in df.iterrows():
        rows.append({"date": row["date"], "balance": running})
        running += row["principal"]  # undo this payment's principal reduction

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------
# Blur / privacy mode
#
# One sidebar toggle, shared across every page via st.session_state
# (Streamlit persists session_state across pages of the same multi-page
# app automatically). When active: dollar figures render as masked
# placeholders, chart Y-axes hide their tick labels, chart hover
# tooltips are suppressed, and CSV export is disabled outright (masking
# the screen but still letting someone download the real numbers would
# defeat the purpose).
# ---------------------------------------------------------------------

def is_blur_active() -> bool:
    return st.session_state.get("blur_mode", False)


def blur_toggle_sidebar():
    """Renders the privacy mode toggle in the sidebar. Call once per page,
    near the top, before anything that needs to know the current state."""
    with st.sidebar:
        st.session_state["blur_mode"] = st.checkbox(
            "🙈 Privacy Mode", value=st.session_state.get("blur_mode", False),
            help="Masks dollar figures and disables CSV export -- for showing this off without exposing real numbers.",
        )


def blur_amount(value: float, active: bool = None) -> str:
    """Format a dollar amount, masking it with bullet characters when
    blur mode is active. Preserves the digit-length/comma structure so
    a masked figure still looks plausible at a glance, without revealing
    the real number."""
    if active is None:
        active = is_blur_active()
    if value is None:
        return ""
    if not active:
        return f"${value:,.0f}"
    sign = "-" if value < 0 else ""
    digits = f"{abs(value):,.0f}"
    masked = "".join("•" if c.isdigit() else c for c in digits)
    return f"{sign}${masked}"


def safe_download_button(label: str, df: pd.DataFrame, file_name: str, key: str):
    """Same interface as st.download_button, but disabled with an
    explanatory caption while blur mode is active -- masking the screen
    but still allowing a real-data CSV download would defeat the point."""
    if is_blur_active():
        st.caption("CSV export disabled in Privacy Mode.")
    else:
        st.download_button(label, to_csv_bytes(df), file_name=file_name, mime="text/csv", key=key)