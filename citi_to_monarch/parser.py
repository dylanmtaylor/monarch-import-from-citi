"""Parser for Citi credit card statements, raw transaction JSON, and PDF files."""

import base64
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


@dataclass
class CitiTransaction:
    """Represents a normalized Citi credit card transaction conforming to Monarch specifications."""
    date: str  # YYYY-MM-DD
    merchant: str
    category: str
    account: str
    original_statement: str
    notes: str
    amount: float  # Signed decimal: negative for purchases/fees, positive for payments/credits
    running_balance: Optional[float] = None
    transaction_id: Optional[str] = None
    raw_category: Optional[str] = None


@dataclass
class StatementPeriod:
    """Represents a Citi monthly billing statement period."""
    statement_date: str  # YYYY-MM-DD
    start_date: str      # YYYY-MM-DD
    end_date: str        # YYYY-MM-DD
    previous_balance: float
    closing_balance: float
    purchases: float = 0.0
    payments_and_credits: float = 0.0
    fees: float = 0.0
    interest: float = 0.0
    transactions: List[CitiTransaction] = field(default_factory=list)


@dataclass
class CitiAccount:
    """Represents a Citi credit card account and its historical activity."""
    card_name: str
    account_number: str
    cardholder: str = ""
    current_balance: float = 0.0
    credit_limit: float = 0.0
    available_credit: float = 0.0
    account_id: str = ""
    statements: List[StatementPeriod] = field(default_factory=list)
    recent_transactions: List[CitiTransaction] = field(default_factory=list)
    historical_transactions: List[CitiTransaction] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """User-friendly display name for Monarch account mapping."""
        clean_name = self.card_name.split("-")[0].strip()
        return f"{clean_name} ({self.account_number})"

    @property
    def slug(self) -> str:
        """Filesystem safe slug for generated filenames."""
        clean_name = re.sub(r"[^a-zA-Z0-9]+", "_", self.card_name.lower()).strip("_")
        return f"{clean_name}_{self.account_number}"

    def get_all_transactions(self) -> List[CitiTransaction]:
        """
        Return a single deduplicated, chronologically sorted list of all transactions
        across historical statement PDFs, raw transaction API records, and recent activity.
        """
        seen = set()
        all_txns: List[CitiTransaction] = []

        # 1. Statement transactions (from PDFs or parsed statement periods)
        for stmt in sorted(self.statements, key=lambda s: s.end_date):
            for t in stmt.transactions:
                key = (t.date, f"{t.amount:.2f}", t.original_statement.strip())
                if key not in seen:
                    seen.add(key)
                    all_txns.append(t)

        # 2. Historical API transactions
        for t in self.historical_transactions:
            key = (t.date, f"{t.amount:.2f}", t.original_statement.strip())
            if key not in seen:
                seen.add(key)
                all_txns.append(t)

        # 3. Recent unbilled transactions
        for t in self.recent_transactions:
            key = (t.date, f"{t.amount:.2f}", t.original_statement.strip())
            if key not in seen:
                seen.add(key)
                all_txns.append(t)

        all_txns.sort(key=lambda t: (t.date, t.original_statement))
        return all_txns

    def compute_daily_balances(self, invert_liability: bool = True) -> List[Dict[str, Any]]:
        """
        Reconstruct continuous daily balance history from account opening to today.
        
        Args:
            invert_liability: If True (default for Monarch liabilities), debt balance is
                             expressed as negative (e.g. -1250.00) so that Assets - Liabilities = Net Worth.
                             
        Returns:
            List of dicts: [{"date": "YYYY-MM-DD", "balance": float}, ...]
        """
        all_txns = self.get_all_transactions()
        sorted_stmts = sorted(self.statements, key=lambda s: s.end_date)

        if not sorted_stmts and not all_txns:
            today_str = datetime.now().strftime("%Y-%m-%d")
            bal = -self.current_balance if invert_liability else self.current_balance
            return [{"date": today_str, "balance": round(bal, 2)}]

        # Start date: earliest statement start date or earliest transaction date
        start_candidates = []
        if sorted_stmts:
            start_candidates.append(sorted_stmts[0].start_date)
        if all_txns:
            start_candidates.append(all_txns[0].date)
        start_date_str = min(start_candidates)
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")

        today_dt = datetime.now().date()
        today_dt_full = datetime(today_dt.year, today_dt.month, today_dt.day)

        # Index transactions by date for fast lookup
        txns_by_date: Dict[str, List[CitiTransaction]] = {}
        for t in all_txns:
            txns_by_date.setdefault(t.date, []).append(t)

        # Map statement closing checkpoints: date -> closing_balance
        statement_checkpoints: Dict[str, float] = {}
        statement_start_points: Dict[str, float] = {}
        for s in sorted_stmts:
            statement_checkpoints[s.end_date] = s.closing_balance
            statement_start_points[s.start_date] = s.previous_balance

        daily_points: List[Dict[str, Any]] = []
        curr_dt = start_dt
        curr_balance = sorted_stmts[0].previous_balance if sorted_stmts else 0.0

        while curr_dt <= today_dt_full:
            d_str = curr_dt.strftime("%Y-%m-%d")

            # Check if this day is a statement start date
            if d_str in statement_start_points:
                curr_balance = statement_start_points[d_str]

            # Apply any transactions on this day
            if d_str in txns_by_date:
                for tx in txns_by_date[d_str]:
                    # In Monarch, purchase is negative, payment is positive.
                    # On the card debt owed: purchase increases debt (+), payment reduces debt (-)
                    # So card_balance_owed += -tx.amount
                    curr_balance -= tx.amount

            # If today is a statement closing date checkpoint, align exactly with official statement
            if d_str in statement_checkpoints:
                curr_balance = statement_checkpoints[d_str]

            # Align with current balance on today
            if curr_dt == today_dt_full:
                curr_balance = self.current_balance

            reported_bal = -curr_balance if invert_liability else curr_balance
            if abs(reported_bal) < 0.001:
                reported_bal = 0.0

            daily_points.append({
                "date": d_str,
                "balance": round(reported_bal, 2)
            })

            curr_dt += timedelta(days=1)

        return daily_points


def parse_date(date_raw: str, default_year: Optional[int] = None) -> str:
    """Parse raw date string into ISO format (YYYY-MM-DD)."""
    s = date_raw.strip()
    if not s:
        return datetime.now().strftime("%Y-%m-%d")

    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # YYYYMMDD
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    # MM/DD/YYYY
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        parts = s.split("/")
        return f"{int(parts[2]):04d}-{int(parts[0]):02d}-{int(parts[1]):02d}"

    # MM/DD/YY
    if re.match(r"^\d{1,2}/\d{1,2}/\d{2}$", s):
        parts = s.split("/")
        yr = int(parts[2]) + 2000
        return f"{yr:04d}-{int(parts[0]):02d}-{int(parts[1]):02d}"

    # MM/DD with default year
    if re.match(r"^\d{1,2}/\d{1,2}$", s):
        yr = default_year or datetime.now().year
        parts = s.split("/")
        return f"{yr:04d}-{int(parts[0]):02d}-{int(parts[1]):02d}"

    # Month Day, Year (e.g. Oct 9, 2026 or October 09, 2026)
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return s


def clean_merchant_name(desc: str) -> str:
    """Clean and normalize Citi transaction descriptions into concise merchant names."""
    if not desc:
        return "Citi"

    desc = desc.replace("\r", " ").replace("\n", " ").strip()
    desc_upper = desc.upper()

    # Exact standard overrides
    if any(k in desc_upper for k in ["ONLINE PAYMENT, THANK YOU", "PAYMENT THANK YOU", "PAYMENT - THANK YOU"]):
        return "Payment - Thank You"
    if "DOORDASH" in desc_upper:
        return "DoorDash"
    if "STARBUCKS" in desc_upper:
        return "Starbucks"
    if any(k in desc_upper for k in ["AMAZON", "AMZN"]):
        return "Amazon"
    if "COSTCO" in desc_upper:
        return "Costco"
    if "SURETYCAM" in desc_upper:
        return "SuretyCam"
    if "LITTLE ISLAND" in desc_upper:
        return "Little Island"
    if "CONNIPTION" in desc_upper:
        return "Conniption"
    if "THE HERITAGE HOTEL" in desc_upper or "HERITAGE HOTEL" in desc_upper:
        return "The Heritage Hotel"
    if "LGA CHUKO RAMEN" in desc_upper or "CHUKO RAMEN" in desc_upper:
        return "LGA Chuko Ramen"
    if "EBAY" in desc_upper:
        return "eBay"
    if "GOOGLE" in desc_upper or "GOOGLE SERVICES" in desc_upper:
        if "PLAY STORE" in desc_upper:
            return "Google Play Store"
        return "Google"
    if "PAYPAL" in desc_upper:
        return "PayPal"
    if "BURGER KING" in desc_upper:
        return "Burger King"
    if "FIVE GUYS" in desc_upper:
        return "Five Guys"
    if "DELTA" in desc_upper:
        return "Delta Air Lines"
    if "CHWYINC" in desc_upper or "CHEWY" in desc_upper:
        return "Chewy"
    if "UDEMY" in desc_upper:
        return "Udemy"
    if "GNOME FOUNDATION" in desc_upper:
        return "Gnome Foundation"
    if "GREAT CLIPS" in desc_upper:
        return "Great Clips"
    if "THE SMILE SHOP" in desc_upper:
        return "The Smile Shop"
    if "TRATTORIA DARIO" in desc_upper:
        return "Trattoria Dario"
    if "CAFÉ 66" in desc_upper or "CAFE 66" in desc_upper:
        return "Café 66"
    if "AIRBNB" in desc_upper:
        return "Airbnb"

    # Regex cleaning
    cleaned = desc
    # Strip digital account number notation
    cleaned = re.sub(r"Digital (?:Account )?Number (?:ending in )?[X\d]+", "", cleaned, flags=re.IGNORECASE)
    # Strip PayPal prefix
    cleaned = re.sub(r"^PAYPAL\s*\*", "", cleaned, flags=re.IGNORECASE)
    # Strip DD * prefix
    cleaned = re.sub(r"^DD\s*\*", "", cleaned, flags=re.IGNORECASE)
    # Remove alphanumeric order/transaction IDs (8+ chars)
    cleaned = re.sub(r"\b[A-Z0-9]{8,}\b", "", cleaned)
    # Remove phone numbers
    cleaned = re.sub(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b", "", cleaned)
    # Remove common URL patterns
    cleaned = re.sub(r"\b(?:G\.CO|AMZN\.COM|WWW\.)\S+", "", cleaned, flags=re.IGNORECASE)
    # Remove trailing 2-letter state codes
    cleaned = re.sub(r"\s+[A-Z]{2}$", "", cleaned.strip())
    # Remove asterisks and normalize spaces
    cleaned = cleaned.replace("*", " ")
    cleaned = " ".join(cleaned.split())

    return cleaned.title() if cleaned else desc[:40].strip()


def infer_category(desc: str, amount: float, raw_category: Optional[str] = None) -> str:
    """Map Citi merchant descriptions and raw categories to standard Monarch categories."""
    desc_upper = desc.upper()
    cat_upper = (raw_category or "").upper()

    if any(k in desc_upper for k in ["ONLINE PAYMENT, THANK YOU", "PAYMENT THANK YOU", "PAYMENT - THANK YOU"]):
        return "Credit Card Payment"

    if any(k in desc_upper or k in cat_upper for k in ["EATING PLACE", "RESTAURANT", "DINING", "DOORDASH", "BURGER KING", "FIVE GUYS"]):
        return "Restaurants"

    if any(k in desc_upper or k in cat_upper for k in ["HOTEL", "HERITAGE HOTEL", "AIRBNB", "DELTA", "TRAVEL"]):
        return "Travel"

    if any(k in desc_upper or k in cat_upper for k in ["UDEMY", "SUBSCRIPTION", "PATREON", "NETFLIX", "SPOTIFY"]):
        return "Subscriptions"

    if any(k in desc_upper or k in cat_upper for k in ["STARBUCKS", "COFFEE"]):
        return "Coffee Shops"

    if any(k in desc_upper or k in cat_upper for k in ["COSTCO", "GROCERY", "SUPERMARKET"]):
        return "Groceries"

    if any(k in desc_upper or k in cat_upper for k in ["PEST CONTROL", "ANTICIMEX", "SURETYCAM"]):
        return "Home Improvement"

    if any(k in desc_upper or k in cat_upper for k in ["AMAZON", "EBAY", "MERCHANDISE", "VARIETY STORE"]):
        return "Shopping"

    if any(k in desc_upper or k in cat_upper for k in ["GREAT CLIPS", "HAIR"]):
        return "Personal Care"

    if any(k in desc_upper or k in cat_upper for k in ["DONATION", "GNOME FOUNDATION"]):
        return "Charity"

    # Default based on sign
    return "Credit Card Payment" if amount > 0 else "Shopping"


def parse_citi_pdf_statement(pdf_bytes: bytes) -> StatementPeriod:
    """
    Parse a Citi credit card statement PDF binary into a structured StatementPeriod object.
    Uses pdftotext layout alignment, extracting billing period, previous balance,
    closing balance, payments, credits, purchases, fees, and individual transactions.
    """
    text = ""
    try:
        proc = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf_bytes, capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            text = proc.stdout.decode("utf-8", errors="ignore")
    except Exception:
        pass

    start_date_str = ""
    end_date_str = ""

    # Billing Period: MM/DD/YY-MM/DD/YY (e.g. 09/10/26-10/09/26)
    m_bp = re.search(r"Billing Period:\s*(\d{2}/\d{2}/\d{2,4})\s*-\s*(\d{2}/\d{2}/\d{2,4})", text)
    if m_bp:
        start_date_str = parse_date(m_bp.group(1))
        end_date_str = parse_date(m_bp.group(2))

    # New balance
    m_new = re.search(r"New [Bb]alance(?:\s+as\s+of\s+\S+)?:?\s*\$?([0-9,]+\.[0-9]{2})", text)
    closing_bal = float(m_new.group(1).replace(",", "")) if m_new else 0.0

    # Previous balance
    m_prev = re.search(r"Previous [Bb]alance:?\s*\$?([0-9,]+\.[0-9]{2})", text)
    prev_bal = float(m_prev.group(1).replace(",", "")) if m_prev else 0.0

    # Purchases
    m_purch = re.search(r"Purchases\s+\+?\$?([0-9,]+\.[0-9]{2})", text)
    purchases = float(m_purch.group(1).replace(",", "")) if m_purch else 0.0

    # Payments
    m_pay = re.search(r"Payments\s+-?\$?([0-9,]+\.[0-9]{2})", text)
    payments = float(m_pay.group(1).replace(",", "")) if m_pay else 0.0

    # Credits
    m_cred = re.search(r"Credits\s+-?\$?([0-9,]+\.[0-9]{2})", text)
    credits_amt = float(m_cred.group(1).replace(",", "")) if m_cred else 0.0

    # Fees
    m_fees = re.search(r"Fees(?:\s+Charged)?:?\s*\+?\$?([0-9,]+\.[0-9]{2})", text)
    fees = float(m_fees.group(1).replace(",", "")) if m_fees else 0.0

    # Interest
    m_int = re.search(r"Interest(?:\s+Charged)?:?\s*\+?\$?([0-9,]+\.[0-9]{2})", text)
    interest = float(m_int.group(1).replace(",", "")) if m_int else 0.0

    transactions: List[CitiTransaction] = []
    end_year = int(end_date_str[:4]) if end_date_str else datetime.now().year
    start_year = int(start_date_str[:4]) if start_date_str else end_year

    # Extract transactions from tabular text
    for line in text.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        if any(h in line_clean.upper() for h in ["PAGE ", "BILLING PERIOD", "NEW BALANCE", "ACCOUNT SUMMARY", "TRANS. DATE"]):
            continue

        # Look for pattern: [MM/DD]  [MM/DD]  Description  [-]$Amount
        # e.g.: 09/09  09/10  DD *DOORDASH NANXIANGS SAN FRANCISCO CA  $9.58
        # or:          09/18  ONLINE PAYMENT, THANK YOU  -$5,369.50
        m_row = re.search(r"(?:(\d{2}/\d{2})\s+)?(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[0-9,]+\.[0-9]{2})$", line_clean)
        if m_row:
            tx_date_raw, post_date_raw, desc_raw, amt_str = m_row.groups()
            date_to_use = tx_date_raw or post_date_raw
            m_month, m_day = int(date_to_use[:2]), int(date_to_use[3:])
            yr = end_year if m_month <= 10 else start_year
            date_str = f"{yr:04d}-{m_month:02d}-{m_day:02d}"

            raw_amt = float(amt_str.replace("$", "").replace(",", ""))
            # In Citi PDFs, payments/credits are negative (-$5369.50), purchases positive ($9.58).
            # In Monarch, purchases are negative (-9.58), payments positive (+5369.50).
            monarch_amount = -raw_amt

            merchant = clean_merchant_name(desc_raw)
            cat = infer_category(desc_raw, monarch_amount)
            transactions.append(CitiTransaction(
                date=date_str,
                merchant=merchant,
                category=cat,
                account="Citi Credit Card",
                original_statement=desc_raw.strip(),
                notes=f"Statement Date: {end_date_str}",
                amount=monarch_amount,
            ))

    return StatementPeriod(
        statement_date=end_date_str,
        start_date=start_date_str,
        end_date=end_date_str,
        previous_balance=prev_bal,
        closing_balance=closing_bal,
        purchases=purchases,
        payments_and_credits=payments + credits_amt,
        fees=fees,
        interest=interest,
        transactions=transactions,
    )


def parse_citi_dataset(raw_data: Dict[str, Any]) -> CitiAccount:
    """
    Parse captured Citi JSON dataset into a fully populated CitiAccount object.
    Combines account overview, statements catalog/PDFs, and API transactions.
    """
    overview = raw_data.get("account_overview", {})
    balances_data = overview.get("balances_data", {})
    ledger_list = balances_data.get("accountLedgerData", [])
    
    card_name = "Citi Credit Card"
    account_number = "0000"
    current_balance = 0.0
    credit_limit = 0.0
    available_credit = 0.0
    account_id = ""

    if ledger_list:
        card = ledger_list[0]
        meta = card.get("accountMetaData", {})
        card_name = meta.get("productNameAndDisplayAccountNo", card_name)
        account_number = card.get("displayAccountNumber", "0000")
        account_id = card.get("accountId", "")

        bal_info = card.get("accountBalance", {})
        current_balance = float(bal_info.get("currentBalanceAmount", 0.0))
        credit_limit = float(bal_info.get("creditLimit", 0.0))
        available_credit = float(bal_info.get("availableCreditAmount", 0.0))

    cardholder = overview.get("cardholder", "")

    account = CitiAccount(
        card_name=card_name,
        account_number=account_number,
        cardholder=cardholder,
        current_balance=current_balance,
        credit_limit=credit_limit,
        available_credit=available_credit,
        account_id=account_id,
    )

    # 1. Parse statement periods from statement PDFs
    for s_entry in raw_data.get("statements", []):
        b64 = s_entry.get("pdf_base64")
        if b64:
            try:
                pdf_bytes = base64.b64decode(b64)
                stmt = parse_citi_pdf_statement(pdf_bytes)
                if stmt.end_date:
                    account.statements.append(stmt)
            except Exception:
                pass

    # If no PDFs were parsed but catalog exists, create synthetic StatementPeriod checkpoints
    if not account.statements:
        for year_group in raw_data.get("statements_catalog", {}).get("statementsByYear", []):
            year = year_group.get("displayYearTitle", "")
            for s in year_group.get("statementsByMonth", []):
                s_date = parse_date(s.get("statementDate", ""))
                account.statements.append(StatementPeriod(
                    statement_date=s_date,
                    start_date=s_date,
                    end_date=s_date,
                    previous_balance=0.0,
                    closing_balance=0.0,
                ))

    # 2. Parse transactions from API records
    tx_container = raw_data.get("transactions", {})
    posted_raw = tx_container.get("postedTransactions", [])
    pending_raw = tx_container.get("pendingTransactions", [])

    for r in posted_raw:
        sale_date_raw = r.get("transactionSaleDate") or r.get("transactionPurchaseDate", "")
        date_iso = parse_date(sale_date_raw)

        cleansed = r.get("cleansedName") or ""
        desc = r.get("transactionDescription") or cleansed
        raw_amt = float(r.get("transactionAmount", 0.0))

        # Check raw category from extendedDescriptions
        raw_cat = None
        for ext in r.get("extendedDescriptions", []):
            if ext.get("fieldIndicator") == "CATEGORY":
                raw_cat = ext.get("displayValue")
                break

        # In Citi transactions API, purchases are positive numbers (e.g. 7.30),
        # while payments are negative numbers (e.g. -59.11).
        # In Monarch, purchases are negative (-7.30) and payments are positive (+59.11).
        monarch_amount = -raw_amt

        merchant = cleansed if (cleansed and "DOORDASH" not in cleansed.upper()) else clean_merchant_name(desc)
        cat = infer_category(merchant, monarch_amount, raw_category=raw_cat)
        tx_id = r.get("transactionAuthorizationId") or r.get("citiTransactionId")

        account.historical_transactions.append(CitiTransaction(
            date=date_iso,
            merchant=merchant,
            category=cat,
            account=account.display_name,
            original_statement=desc.strip(),
            notes=f"Auth: {tx_id}" if tx_id else "",
            amount=monarch_amount,
            transaction_id=tx_id,
            raw_category=raw_cat,
        ))

    # Parse pending / unbilled transactions
    for r in pending_raw:
        sale_date_raw = r.get("transactionSaleDate") or r.get("transactionPurchaseDate", "")
        if not sale_date_raw and r.get("authorizationTimeStamp"):
            # e.g. "Oct 17, 2026 04:02 PM ET"
            try:
                dt = datetime.strptime(r["authorizationTimeStamp"].split(" ET")[0].strip(), "%b %d, %Y %I:%M %p")
                sale_date_raw = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        date_iso = parse_date(sale_date_raw)
        cleansed = r.get("cleansedName") or ""
        desc = r.get("transactionDescription") or cleansed
        raw_amt = float(r.get("transactionAmount", 0.0))

        raw_cat = None
        for ext in r.get("extendedDescriptions", []):
            if ext.get("fieldIndicator") == "CATEGORY":
                raw_cat = ext.get("displayValue")
                break

        monarch_amount = -raw_amt
        merchant = cleansed if (cleansed and "DOORDASH" not in cleansed.upper()) else clean_merchant_name(desc)
        cat = infer_category(merchant, monarch_amount, raw_category=raw_cat)
        tx_id = r.get("transactionAuthorizationId") or r.get("citiTransactionId")

        account.recent_transactions.append(CitiTransaction(
            date=date_iso,
            merchant=merchant,
            category=cat,
            account=account.display_name,
            original_statement=desc.strip(),
            notes=f"Pending (Auth: {tx_id})" if tx_id else "Pending",
            amount=monarch_amount,
            transaction_id=tx_id,
            raw_category=raw_cat,
        ))

    return account
