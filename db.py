"""
Shared database helpers for the finance dashboard.
All pages import from here so query logic lives in exactly one place.
"""

import sqlite3
import pandas as pd
import streamlit as st

import os

DATABASE_PATH = os.environ.get("FINANCE_DB_PATH", "demo_finances.db")


def get_connection():
    return sqlite3.connect(DATABASE_PATH, check_same_thread=False)


@st.cache_data(ttl=3600)
def get_available_transaction_years():
    """Which calendar years actually have transaction data -- used to
    populate the Sankey page's year selector."""
    con = get_connection()
    row = con.execute("SELECT MIN(date), MAX(date) FROM transactions WHERE pending = 0").fetchone()
    con.close()
    if not row or not row[0]:
        return []
    min_year = int(row[0][:4])
    max_year = int(row[1][:4])
    return list(range(max_year, min_year - 1, -1))


@st.cache_data(ttl=3600)
def get_accounts():
    """All accounts with their nickname/type/institution metadata.
    display_name falls back to account_name/official_name for accounts
    that were never manually nicknamed, so nothing silently disappears
    from filters/charts."""
    con = get_connection()
    df = pd.read_sql_query(
        "SELECT *, COALESCE(nickname, account_name, official_name) AS display_name FROM accounts",
        con,
    )
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_cash_total_by_date():
    """
    Daily total across all depository (checking/savings) accounts only.
    This is the series the savings goal is measured against --
    investments and retirement are deliberately excluded.
    """
    con = get_connection()
    df = pd.read_sql_query(
        """
        SELECT bh.snapshot_date AS date, SUM(bh.current_balance) AS total_cash
        FROM balance_history bh
        JOIN accounts a ON bh.account_id = a.account_id
        WHERE a.type = 'depository'
        GROUP BY bh.snapshot_date
        ORDER BY bh.snapshot_date
        """,
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=3600)
def get_balance_trend(account_ids=None, item_names=None, types=None):
    """Balance history filtered by account, institution, or type -- any combination."""
    con = get_connection()
    query = """
        SELECT bh.snapshot_date AS date,
               COALESCE(a.nickname, a.account_name, a.official_name) AS display_name,
               a.institution_name, a.type, a.subtype, bh.current_balance
        FROM balance_history bh
        JOIN accounts a ON bh.account_id = a.account_id
        WHERE 1=1
    """
    params = []

    if account_ids:
        query += f" AND bh.account_id IN ({','.join('?' * len(account_ids))})"
        params += account_ids
    if item_names:
        query += f" AND a.item_name IN ({','.join('?' * len(item_names))})"
        params += item_names
    if types:
        query += f" AND a.type IN ({','.join('?' * len(types))})"
        params += types

    query += " ORDER BY bh.snapshot_date"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=3600)
def get_spending_by_category(start_date=None, end_date=None, level="pfc_primary"):
    """Spending totals grouped by category, excluding transfers and pending."""
    con = get_connection()
    query = f"SELECT {level} AS category, SUM(amount) AS total FROM spending_transactions WHERE amount > 0"
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += f" GROUP BY {level} ORDER BY total DESC"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


# ---------------------------------------------------------------------
# Income classification. If any income comes via direct account to account
# transfers, it needs to be dealt with here. Otherwise it's silently excluded
# as a TRANSFER_IN, same as any real internal transfer. The threshold
# was used to separate actual pay from these internal transfers.
# Defined once here and reused by every income query below.
# ---------------------------------------------------------------------
TRANSFER_PATTERN = "Online Transfer from CHK %7749%"
INCOME_THRESHOLD = -300  # amount <= this (negative = inflow) counts as pay, not excluded as an internal transfer

INCOME_WHERE_CLAUSE = f"""(
    (pfc_primary = 'INCOME')
    OR (pfc_primary = 'TRANSFER_IN' AND name LIKE '{TRANSFER_PATTERN}' AND amount <= {INCOME_THRESHOLD})
)"""

PERSON_CASE = f"""CASE
    WHEN pfc_primary = 'INCOME' AND pfc_detailed IN ('INCOME_SALARY', 'INCOME_WAGES', 'INCOME_CONTRACTOR') THEN 'Person_X'
    WHEN pfc_primary = 'TRANSFER_IN' AND name LIKE '{TRANSFER_PATTERN}' AND amount <= {INCOME_THRESHOLD} THEN 'Person_Y'
    ELSE 'Other/Interest'
END"""


@st.cache_data(ttl=3600)
def get_income_by_person(start_date=None, end_date=None):
    """Income totals grouped by who earned it -- Person X (Plaid-categorized
    salary/wages/contractor income), Person Y (recognized via transfer
    pattern, see above), or Other/Interest (passive income not
    attributable to either)."""
    con = get_connection()
    query = f"""
        SELECT {PERSON_CASE} AS person, SUM(-amount) AS total
        FROM transactions
        WHERE pending = 0 AND amount < 0 AND {INCOME_WHERE_CLAUSE}
    """
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " GROUP BY person ORDER BY total DESC"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_person_income_transactions(person, start_date=None, end_date=None):
    """Every transaction attributed to one person's income bucket."""
    con = get_connection()
    query = f"""
        SELECT date, COALESCE(merchant_name, name) AS description, -amount AS amount, pfc_primary, pfc_detailed
        FROM transactions
        WHERE pending = 0 AND amount < 0 AND {INCOME_WHERE_CLAUSE}
          AND {PERSON_CASE} = ?
    """
    params = [person]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date DESC"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_income_sources(start_date=None, end_date=None, limit=15):
    """Top income sources by payer. Person_X's transfers carry a unique
    transaction number every time, so grouping by literal description
    text would show her pay as dozens of one-off "sources" -- normalized
    to a single 'Person_X (transfer)' label instead."""
    con = get_connection()
    query = f"""
        SELECT
            CASE
                WHEN pfc_primary = 'TRANSFER_IN' AND name LIKE '{TRANSFER_PATTERN}' AND amount <= {INCOME_THRESHOLD}
                THEN 'Person_X (transfer)'
                ELSE COALESCE(merchant_name, name)
            END AS source,
            SUM(-amount) AS total, COUNT(*) AS transactions
        FROM transactions
        WHERE pending = 0 AND amount < 0 AND {INCOME_WHERE_CLAUSE}
    """
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " GROUP BY source ORDER BY total DESC LIMIT ?"
    params.append(limit)
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_income_source_transactions(source, start_date=None, end_date=None):
    con = get_connection()
    if source == "Person_X (transfer)":
        query = f"""
            SELECT date, -amount AS amount, pfc_primary, pfc_detailed
            FROM transactions
            WHERE pending = 0 AND pfc_primary = 'TRANSFER_IN'
              AND name LIKE '{TRANSFER_PATTERN}' AND amount <= {INCOME_THRESHOLD}
        """
        params = []
    else:
        query = """
            SELECT date, -amount AS amount, pfc_primary, pfc_detailed
            FROM transactions
            WHERE pending = 0 AND pfc_primary = 'INCOME' AND amount < 0
              AND COALESCE(merchant_name, name) = ?
        """
        params = [source]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date DESC"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_monthly_income_vs_spending(start_date=None, end_date=None):
    """One row per calendar month with total income, total spending, and
    the net (income - spending) -- the net cash flow chart's data source."""
    con = get_connection()
    inc_query = f"""
        SELECT strftime('%Y-%m', date) AS month, SUM(-amount) AS income
        FROM transactions
        WHERE pending = 0 AND amount < 0 AND {INCOME_WHERE_CLAUSE}
    """
    spend_query = """
        SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS spending
        FROM spending_transactions
        WHERE amount > 0
    """
    params_i, params_s = [], []
    if start_date:
        inc_query += " AND date >= ?"
        params_i.append(start_date)
        spend_query += " AND date >= ?"
        params_s.append(start_date)
    if end_date:
        inc_query += " AND date <= ?"
        params_i.append(end_date)
        spend_query += " AND date <= ?"
        params_s.append(end_date)
    inc_query += " GROUP BY month"
    spend_query += " GROUP BY month"

    inc_df = pd.read_sql_query(inc_query, con, params=params_i)
    spend_df = pd.read_sql_query(spend_query, con, params=params_s)
    con.close()

    merged = pd.merge(inc_df, spend_df, on="month", how="outer").fillna(0).sort_values("month")
    merged["net"] = merged["income"] - merged["spending"]
    return merged


@st.cache_data(ttl=3600)
def get_merchant_transactions(merchant, start_date=None, end_date=None):
    """All line items for a single merchant -- powers click-to-drill-down
    from the Top Merchants leaderboard."""
    con = get_connection()
    query = """
        SELECT date, amount, pfc_primary, pfc_detailed
        FROM spending_transactions
        WHERE COALESCE(merchant_name, name) = ? AND amount > 0
    """
    params = [merchant]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date DESC"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_top_merchants(start_date=None, end_date=None, limit=15):
    """Top merchants by total spend, independent of category -- often more
    concrete than category buckets for spotting where money actually goes."""
    con = get_connection()
    query = """
        SELECT COALESCE(merchant_name, name) AS merchant, SUM(amount) AS total, COUNT(*) AS transactions
        FROM spending_transactions
        WHERE amount > 0
    """
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " GROUP BY merchant ORDER BY total DESC LIMIT ?"
    params.append(limit)
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_category_merchant_breakdown(category, level="pfc_primary", start_date=None, end_date=None):
    """Line-item breakdown by merchant for a single category -- powers click-to-drill-down."""
    con = get_connection()
    query = f"""
        SELECT COALESCE(merchant_name, name) AS merchant, date, amount
        FROM spending_transactions
        WHERE {level} = ? AND amount > 0
    """
    params = [category]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date DESC"
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


def _ensure_settings_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")


def get_setting(key, default=None):
    """Reads a dashboard setting (e.g. the editable cash goal). Not cached --
    these are cheap single-row lookups and we want edits to show up immediately."""
    con = get_connection()
    _ensure_settings_table(con)
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    con.close()
    return row[0] if row else default


def set_setting(key, value):
    con = get_connection()
    _ensure_settings_table(con)
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    con.commit()
    con.close()


@st.cache_data(ttl=3600)
def get_latest_cash_by_account():
    """Most recent balance for each depository (checking/savings) account --
    powers the per-account donut slices."""
    con = get_connection()
    df = pd.read_sql_query(
        """
        SELECT a.account_id, COALESCE(a.nickname, a.account_name, a.official_name) AS display_name,
               bh.current_balance
        FROM balance_history bh
        JOIN accounts a ON bh.account_id = a.account_id
        WHERE a.type = 'depository'
          AND bh.snapshot_date = (SELECT MAX(snapshot_date) FROM balance_history)
        ORDER BY bh.current_balance DESC
        """,
        con,
    )
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_account_transactions(account_id, limit=50):
    """Recent transactions for a single account -- powers click-to-drill-down
    from the account slices in the goal donut."""
    con = get_connection()
    df = pd.read_sql_query(
        """
        SELECT date, COALESCE(merchant_name, name) AS description, amount, pfc_primary, pfc_detailed
        FROM transactions
        WHERE account_id = ? AND pending = 0
        ORDER BY date DESC
        LIMIT ?
        """,
        con, params=(account_id, limit),
    )
    con.close()
    return df


def _ensure_events_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            transaction_id TEXT PRIMARY KEY,
            date TEXT,
            amount REAL,
            label TEXT,
            is_active INTEGER DEFAULT 0
        )
    """)


@st.cache_data(ttl=3600)
def get_large_transactions(threshold=1000, limit=60):
    """Candidate large one-time expenses for the event-flagging feature --
    scans cash-account transactions above a $ threshold. Only genuine
    outflows are included (positive amount, per Plaid's convention where
    positive = money leaving the account); deposits, interest, paychecks,
    and inter-account transfers are excluded. Mortgage payments are
    explicitly excluded, and any transaction whose merchant matches a
    known recurring outflow stream is excluded too. Checks are a special
    case: Plaid categorizes them as TRANSFER_OUT even when they're real
    one-time payments (contractor, car, etc.), so they're allowed through
    despite that category rather than being swept up in the transfer
    exclusion."""
    con = get_connection()
    df = pd.read_sql_query(
        """
        SELECT t.transaction_id, t.date, COALESCE(t.merchant_name, t.name) AS description, t.amount
        FROM transactions t
        JOIN accounts a ON t.account_id = a.account_id
        WHERE a.type = 'depository'
          AND t.pending = 0
          AND t.amount >= ?
          AND (
              t.pfc_primary NOT IN ('TRANSFER_IN', 'TRANSFER_OUT')
              OR t.name LIKE 'CHECK #%'
          )
          AND (t.pfc_detailed IS NULL OR t.pfc_detailed != 'LOAN_PAYMENTS_MORTGAGE_PAYMENT')
          AND COALESCE(t.merchant_name, t.name) NOT IN (
              SELECT merchant_name FROM recurring_streams
              WHERE direction = 'OUTFLOW' AND is_active = 1 AND merchant_name IS NOT NULL
          )
        ORDER BY t.amount DESC
        LIMIT ?
        """,
        con, params=(threshold, limit),
    )
    con.close()
    return df


def get_all_flagged_events():
    """All events regardless of active state -- used to pre-fill the review checklist."""
    con = get_connection()
    _ensure_events_table(con)
    df = pd.read_sql_query("SELECT * FROM events", con)
    con.close()
    return df


def get_active_events():
    """Only checked/confirmed events -- used to annotate charts."""
    con = get_connection()
    _ensure_events_table(con)
    df = pd.read_sql_query("SELECT * FROM events WHERE is_active = 1 ORDER BY date", con)
    con.close()
    return df


def save_event(transaction_id, date, amount, label, is_active):
    con = get_connection()
    _ensure_events_table(con)
    con.execute(
        """INSERT INTO events (transaction_id, date, amount, label, is_active)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(transaction_id) DO UPDATE SET
               label = excluded.label, is_active = excluded.is_active""",
        (transaction_id, date, amount, label, int(is_active)),
    )
    con.commit()
    con.close()


def _ensure_mortgage_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS mortgage_payments (
            date TEXT PRIMARY KEY,
            principal REAL,
            interest REAL
        )
    """)


def save_mortgage_payment(date, principal, interest):
    con = get_connection()
    _ensure_mortgage_table(con)
    con.execute(
        "INSERT INTO mortgage_payments (date, principal, interest) VALUES (?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET principal = excluded.principal, interest = excluded.interest",
        (date, principal, interest),
    )
    con.commit()
    con.close()


@st.cache_data(ttl=3600)
def get_mortgage_payments():
    con = get_connection()
    _ensure_mortgage_table(con)
    df = pd.read_sql_query("SELECT * FROM mortgage_payments ORDER BY date", con)
    con.close()
    return df


@st.cache_data(ttl=3600)
def get_earliest_full_coverage_date():
    """The earliest date at which every account TYPE currently in the
    database has at least one balance_history row -- i.e. the first day
    coverage is genuinely complete. Before this date, some account
    types (in practice, investment/retirement accounts whose sync
    started later than depository) are simply absent from the data,
    which makes any total that includes them look artificially low and
    then jump sharply the day they first appear. Used to set a sensible
    default start for date-range sliders on pages (like Net Worth) that
    include every account type, rather than defaulting to the true
    earliest row and showing that jump by default."""
    con = get_connection()
    row = con.execute("""
        SELECT MAX(min_date) FROM (
            SELECT a.type, MIN(bh.snapshot_date) AS min_date
            FROM balance_history bh
            JOIN accounts a ON bh.account_id = a.account_id
            GROUP BY a.type
        )
    """).fetchone()
    con.close()
    return row[0] if row and row[0] else None


@st.cache_data(ttl=3600)
def get_net_worth_components():
    """Daily totals split into assets (depository + investment) and
    credit owed (a liability -- subtracted, not added). House value and
    mortgage aren't in balance_history at all (they're not Plaid
    accounts), so they're layered on separately by the page itself."""
    con = get_connection()
    df = pd.read_sql_query(
        """
        SELECT bh.snapshot_date AS date,
               SUM(CASE WHEN a.type IN ('depository', 'investment') THEN bh.current_balance ELSE 0 END) AS assets,
               SUM(CASE WHEN a.type = 'credit' THEN bh.current_balance ELSE 0 END) AS credit_owed
        FROM balance_history bh
        JOIN accounts a ON bh.account_id = a.account_id
        GROUP BY bh.snapshot_date
        ORDER BY bh.snapshot_date
        """,
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _ensure_estimated_balance_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS estimated_balance_history (
            snapshot_date TEXT,
            account_id TEXT,
            current_balance REAL,
            PRIMARY KEY (snapshot_date, account_id)
        )
    """)


def save_estimated_balances(rows):
    """rows: list of (snapshot_date, account_id, current_balance) tuples.
    Deliberately a SEPARATE table from balance_history -- these values
    are fabricated (backward-compounded from the earliest real balance,
    not synced from Plaid), and keeping them structurally apart makes it
    impossible to accidentally treat an estimate as real data."""
    con = get_connection()
    _ensure_estimated_balance_table(con)
    con.executemany(
        """INSERT OR REPLACE INTO estimated_balance_history
           (snapshot_date, account_id, current_balance) VALUES (?, ?, ?)""",
        rows,
    )
    con.commit()
    con.close()


@st.cache_data(ttl=3600)
def get_estimated_investment_trend():
    """Daily total of ESTIMATED investment-account balances only (401k,
    IRA, brokerage, HSA) -- from estimated_balance_history, not real
    Plaid data. Used to draw a separate, clearly-marked dashed reference
    line, not blended into the real net worth total."""
    con = get_connection()
    _ensure_estimated_balance_table(con)
    df = pd.read_sql_query(
        """
        SELECT ebh.snapshot_date AS date, SUM(ebh.current_balance) AS estimated_assets
        FROM estimated_balance_history ebh
        JOIN accounts a ON ebh.account_id = a.account_id
        WHERE a.type = 'investment'
        GROUP BY ebh.snapshot_date
        ORDER BY ebh.snapshot_date
        """,
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=3600)
def get_recurring_streams():
    con = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM recurring_streams WHERE is_active = 1 ORDER BY direction, average_amount DESC",
        con,
    )
    con.close()
    return df