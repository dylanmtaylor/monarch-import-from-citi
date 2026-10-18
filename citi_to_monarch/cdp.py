"""Chrome DevTools Protocol (CDP) client for Citi credit card extraction."""

import base64
import json
import os
import time
import urllib.request
import websocket
from typing import Dict, Any, List, Optional, Callable


class CDPError(Exception):
    """Raised when CDP connection or data extraction fails."""
    pass


def find_citi_tab(port: int = 9222, tab_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Locate the Citi Credit Card tab in Chrome DevTools Protocol.

    Args:
        port: Chrome remote debugging port.
        tab_id: Optional specific tab ID to look for.

    Returns:
        Dict representing tab metadata from /json.
    """
    url = f"http://127.0.0.1:{port}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tabs = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise CDPError(
            f"Could not connect to Chrome debugging port {port}: {e}. "
            f"Ensure Chrome is running with --remote-debugging-port={port}"
        )

    if tab_id:
        for tab in tabs:
            if tab.get("id") == tab_id:
                return tab

    # Search by URL or Title
    for tab in tabs:
        tab_url = tab.get("url", "")
        tab_title = tab.get("title", "")
        if "online.citi.com" in tab_url and tab.get("type") == "page":
            return tab
        if "citibank" in tab_title.lower() and tab.get("type") == "page":
            return tab

    raise CDPError(
        "No open Citi tab found. Please log in to https://online.citi.com in Chrome."
    )


class CDPSession:
    """Manages WebSocket connection to Chrome CDP tab for Citi data extraction."""

    def __init__(self, port: int = 9222, tab_id: Optional[str] = None, timeout: float = 30.0):
        self.port = port
        self.tab_id = tab_id
        self.timeout = timeout
        self.ws: Optional[websocket.WebSocket] = None
        self.tab_info: Optional[Dict[str, Any]] = None
        self._msg_id = 0

    def connect(self) -> None:
        """Establish WebSocket connection to Chrome CDP tab."""
        self.tab_info = find_citi_tab(port=self.port, tab_id=self.tab_id)
        ws_url = self.tab_info.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CDPError(f"Tab {self.tab_info.get('id')} has no webSocketDebuggerUrl available.")

        try:
            self.ws = websocket.create_connection(
                ws_url,
                suppress_origin=True,
                timeout=self.timeout
            )
        except Exception as e:
            raise CDPError(f"Failed to connect to WebSocket {ws_url}: {e}")

    def close(self) -> None:
        """Close WebSocket connection."""
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def evaluate(self, expression: str, await_promise: bool = True) -> Any:
        """Evaluate a JavaScript expression inside the Citi page context."""
        if not self.ws:
            raise CDPError("WebSocket connection is not open.")

        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        }
        self.ws.send(json.dumps(msg))

        start_time = time.time()
        while time.time() - start_time < self.timeout:
            try:
                raw = self.ws.recv()
                data = json.loads(raw)
                if data.get("id") == self._msg_id:
                    result = data.get("result", {})
                    if "exceptionDetails" in result:
                        exc = result["exceptionDetails"]
                        raise CDPError(f"JavaScript evaluation failed: {exc}")
                    return result.get("result", {}).get("value")
            except websocket.WebSocketTimeoutException:
                pass

        raise CDPError(f"Timed out waiting for Runtime.evaluate response for msg id {self._msg_id}")

    def get_account_overview(self) -> Dict[str, Any]:
        """Extract account overview, balances, credit lines, and cardholder info."""
        js_code = r"""
        (async () => {
            function getCookie(name) {
                let match = document.cookie.match(new RegExp('(^|;\\s*)(' + name + ')=([^;]*)'));
                return match ? match[3] : null;
            }

            const headers = {
                'client_id': getCookie('client_id'),
                'businessCode': getCookie('businessCode'),
                'countryCode': getCookie('countryCode'),
                'channelId': getCookie('channelId'),
                'uuid': getCookie('speedLogin_uuid') || '',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json'
            };

            let balancesData = null;
            try {
                const resp = await fetch('/gcgapi/prod/public/v1/cbol/accounts/details/balances?isRedesignPage=true', {
                    headers: headers
                });
                if (resp.ok) {
                    balancesData = await resp.json();
                }
            } catch (e) {
                console.error("Failed to fetch balances API", e);
            }

            // Extract cardholder name from session storage or DOM
            let cardholder = "";
            try {
                let branding = sessionStorage.getItem('sessionPostBrandingStorage');
                if (branding) {
                    let parsed = JSON.parse(branding);
                    cardholder = parsed.loginName || "";
                }
            } catch (e) {}

            return {
                balances_data: balancesData,
                cardholder: cardholder,
                url: window.location.href,
                title: document.title
            };
        })()
        """
        return self.evaluate(js_code)

    def fetch_statements_catalog(self, account_id: str) -> Dict[str, Any]:
        """Fetch list of available statement periods for a credit card account."""
        js_code = f"""
        (async () => {{
            function getCookie(name) {{
                let match = document.cookie.match(new RegExp('(^|;\\\\s*)(' + name + ')=([^;]*)'));
                return match ? match[3] : null;
            }}

            const headers = {{
                'client_id': getCookie('client_id'),
                'businessCode': getCookie('businessCode'),
                'countryCode': getCookie('countryCode'),
                'channelId': getCookie('channelId'),
                'uuid': getCookie('speedLogin_uuid') || '',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json'
            }};

            const url = '/gcgapi/prod/public/v1/v2/digital/card/accounts/statements/accountsAndStatements/retrieve';
            const resp = await fetch(url, {{
                method: 'POST',
                headers: headers,
                body: JSON.stringify({{ accountId: {json.dumps(account_id)} }})
            }});

            if (!resp.ok) {{
                throw new Error(`Failed to fetch statements catalog: HTTP ${{resp.status}}`);
            }}
            return await resp.json();
        }})()
        """
        return self.evaluate(js_code)

    def fetch_statement_pdf_base64(self, account_id: str, statement_date: str) -> str:
        """Fetch statement PDF binary content as base64 string."""
        js_code = f"""
        (async () => {{
            function getCookie(name) {{
                let match = document.cookie.match(new RegExp('(^|;\\\\s*)(' + name + ')=([^;]*)'));
                return match ? match[3] : null;
            }}

            const headers = {{
                'client_id': getCookie('client_id'),
                'businessCode': getCookie('businessCode'),
                'countryCode': getCookie('countryCode'),
                'channelId': getCookie('channelId'),
                'uuid': getCookie('speedLogin_uuid') || '',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json'
            }};

            const url = '/gcgapi/prod/public/v1/v2/digital/card/accounts/statements/recent/retrieve';
            const body = JSON.stringify({{
                accountId: {json.dumps(account_id)},
                statementDate: {json.dumps(statement_date)},
                requestType: "RECENT STATEMENTS"
            }});

            const resp = await fetch(url, {{
                method: 'POST',
                headers: headers,
                body: body
            }});

            if (!resp.ok) {{
                throw new Error(`Failed to fetch PDF statement for ${{statement_date}}: HTTP ${{resp.status}}`);
            }}

            const blob = await resp.blob();
            return new Promise((resolve, reject) => {{
                const reader = new FileReader();
                reader.onloadend = () => {{
                    const res = reader.result;
                    const b64 = res.split(',')[1];
                    resolve(b64);
                }};
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            }});
        }})()
        """
        return self.evaluate(js_code)

    def fetch_archived_statements_catalog(self, account_id: str) -> Dict[str, Any]:
        """Fetch catalog of archived statements and their retrieval readiness status."""
        js_code = f"""
        (async () => {{
            function getCookie(name) {{
                let match = document.cookie.match(new RegExp('(^|;\\\\s*)(' + name + ')=([^;]*)'));
                return match ? match[3] : null;
            }}

            const headers = {{
                'client_id': getCookie('client_id') || '4a51fb19-a1a7-4247-bc7e-18aa56dd1c40',
                'businessCode': getCookie('businessCode') || 'GCB',
                'countryCode': getCookie('countryCode') || 'US',
                'channelId': getCookie('channelId') || 'CBOL',
                'uuid': getCookie('speedLogin_uuid') || '',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json;charset=UTF-8',
                'citi-correlation-id': 'req-' + Date.now()
            }};

            const url = '/gcgapi/prod/public/v1/v2/digital/card/accounts/statements/archiveStatements/retrieve';
            const resp = await fetch(url, {{
                method: 'POST',
                headers: headers,
                body: JSON.stringify({{ accountId: {json.dumps(account_id)} }}),
                credentials: 'include'
            }});

            if (!resp.ok) {{
                throw new Error(`Failed to fetch archived statements catalog: HTTP ${{resp.status}}`);
            }}
            return await resp.json();
        }})()
        """
        return self.evaluate(js_code)

    def fetch_archived_statement_pdf_base64(self, account_id: str, statement_date: str) -> str:
        """Fetch archived statement PDF binary content as base64 string."""
        js_code = f"""
        (async () => {{
            function getCookie(name) {{
                let match = document.cookie.match(new RegExp('(^|;\\\\s*)(' + name + ')=([^;]*)'));
                return match ? match[3] : null;
            }}

            const headers = {{
                'client_id': getCookie('client_id') || '4a51fb19-a1a7-4247-bc7e-18aa56dd1c40',
                'businessCode': getCookie('businessCode') || 'GCB',
                'countryCode': getCookie('countryCode') || 'US',
                'channelId': getCookie('channelId') || 'CBOL',
                'uuid': getCookie('speedLogin_uuid') || '',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json;charset=UTF-8',
                'citi-correlation-id': 'req-' + Date.now()
            }};

            const url = '/gcgapi/prod/public/v1/v2/digital/card/accounts/statements/recent/retrieve';
            const body = JSON.stringify({{
                accountId: {json.dumps(account_id)},
                statementDate: {json.dumps(statement_date)},
                requestType: "ARCHIVED STATEMENTS"
            }});

            const resp = await fetch(url, {{
                method: 'POST',
                headers: headers,
                body: body,
                credentials: 'include'
            }});

            if (!resp.ok) {{
                throw new Error(`Failed to fetch archived PDF statement for ${{statement_date}}: HTTP ${{resp.status}}`);
            }}

            const blob = await resp.blob();
            return new Promise((resolve, reject) => {{
                const reader = new FileReader();
                reader.onloadend = () => {{
                    const res = reader.result;
                    const b64 = res.split(',')[1];
                    resolve(b64);
                }};
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            }});
        }})()
        """
        return self.evaluate(js_code)

    def fetch_transactions_page(
        self,
        account_id: str,
        time_period_filter: Optional[Dict[str, Any]] = None,
        next_table_index: Optional[str] = None,
        next_sequence_number: Optional[str] = None,
        transaction_source: Optional[str] = None,
        more_transactions_flag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch a single page of transaction records from Citi transactions API."""
        payload: Dict[str, Any] = {"isRedesignPage": True}
        if time_period_filter:
            payload["timePeriodFilter"] = time_period_filter
        if next_table_index:
            payload["nextTableIndex"] = next_table_index
        if next_sequence_number:
            payload["nextTransactionSequenceNumber"] = next_sequence_number
        if transaction_source:
            payload["transactionSource"] = transaction_source
        if more_transactions_flag:
            payload["moreTransactionsFlag"] = more_transactions_flag

        js_code = f"""
        (async () => {{
            function getCookie(name) {{
                let match = document.cookie.match(new RegExp('(^|;\\\\s*)(' + name + ')=([^;]*)'));
                return match ? match[3] : null;
            }}

            const headers = {{
                'client_id': getCookie('client_id'),
                'businessCode': getCookie('businessCode'),
                'countryCode': getCookie('countryCode'),
                'channelId': getCookie('channelId'),
                'uuid': getCookie('speedLogin_uuid') || '',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json'
            }};

            const url = `/gcgapi/prod/public/v1/cbol/accounts/${{encodeURIComponent({json.dumps(account_id)})}}/transactions/retrieve`;
            const resp = await fetch(url, {{
                method: 'POST',
                headers: headers,
                body: JSON.stringify({json.dumps(payload)})
            }});

            if (!resp.ok) {{
                throw new Error(`Failed to fetch transactions: HTTP ${{resp.status}}`);
            }}
            return await resp.json();
        }})()
        """
        return self.evaluate(js_code)

    def fetch_all_transactions(
        self, account_id: str, progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Fetch all transactions across all available time periods back to account inception.
        Automatically navigates pagination across recent, YTD, prior year, and date ranges.
        """
        all_posted: List[Dict[str, Any]] = []
        all_pending: List[Dict[str, Any]] = []

        # 1. First fetch default / recent activity to get filter indicators and unbilled transactions
        if progress_callback:
            progress_callback("Fetching recent / unbilled activity...")
        initial_resp = self.fetch_transactions_page(account_id)
        if initial_resp.get("accountActivity"):
            act = initial_resp["accountActivity"]
            all_pending.extend(act.get("pendingTransactions", []))
            all_posted.extend(act.get("postedTransactions", []))

        # Check available filters
        filters = initial_resp.get("accountActivityFilters", {}).get("timePeriodFilters", [])
        
        # We will query:
        # - "YEAR_TO_DATE"
        # - "PRIOR_YEAR"
        # - Custom DATE_RANGE for earlier years (from earliest account date to prior year start)
        periods_to_query: List[Dict[str, Any]] = []

        has_ytd = any(f.get("filterIndicator") == "YEAR_TO_DATE" for f in filters)
        has_prior = any(f.get("filterIndicator") == "PRIOR_YEAR" for f in filters)

        if has_ytd:
            ytd_f = next(f for f in filters if f.get("filterIndicator") == "YEAR_TO_DATE")
            periods_to_query.append({
                "label": "Year to Date",
                "filter": {
                    "filterIndicator": "YEAR_TO_DATE",
                    "startDate": ytd_f.get("startDate", "01/01/2026"),
                    "endDate": ytd_f.get("endDate", "12/31/2026"),
                }
            })

        if has_prior:
            prior_f = next(f for f in filters if f.get("filterIndicator") == "PRIOR_YEAR")
            periods_to_query.append({
                "label": "Prior Year (2025)",
                "filter": {
                    "filterIndicator": "PRIOR_YEAR",
                    "startDate": prior_f.get("startDate", "01/01/2025"),
                    "endDate": prior_f.get("endDate", "12/31/2025"),
                }
            })

        # Earlier date ranges: e.g. 2024 back to 2016
        # Start date from initial response or catalog
        start_date_str = initial_resp.get("startDate", "10/09/2024")
        if start_date_str:
            periods_to_query.append({
                "label": f"Historical Range ({start_date_str} to 12/31/2024)",
                "filter": {
                    "filterIndicator": "DATE_RANGE",
                    "startDate": start_date_str,
                    "endDate": "12/31/2024",
                }
            })
            # Also check early 2024
            periods_to_query.append({
                "label": "Early 2024 (01/01/2024 to 10/08/2024)",
                "filter": {
                    "filterIndicator": "DATE_RANGE",
                    "startDate": "01/01/2024",
                    "endDate": "10/08/2024",
                }
            })

        for p in periods_to_query:
            label = p["label"]
            f_spec = p["filter"]
            if progress_callback:
                progress_callback(f"Querying transactions for {label}...")

            page_num = 1
            next_table = None
            next_seq = None
            tx_src = None
            more_flag = None

            while True:
                resp = self.fetch_transactions_page(
                    account_id=account_id,
                    time_period_filter=f_spec,
                    next_table_index=next_table,
                    next_sequence_number=next_seq,
                    transaction_source=tx_src,
                    more_transactions_flag=more_flag,
                )
                act = resp.get("accountActivity", {})
                posted = act.get("postedTransactions", [])
                pending = act.get("pendingTransactions", [])
                all_posted.extend(posted)
                all_pending.extend(pending)

                more_flag = act.get("moreTransactionsFlag")
                if more_flag == "true" and (act.get("nextTableIndex") or act.get("nextTransactionSequenceNumber")):
                    page_num += 1
                    next_table = act.get("nextTableIndex")
                    next_seq = act.get("nextTransactionSequenceNumber")
                    tx_src = act.get("transactionSource", "B")
                    if progress_callback:
                        progress_callback(f"  {label}: fetched page {page_num} ({len(posted)} records)...")
                else:
                    break

        return {
            "postedTransactions": all_posted,
            "pendingTransactions": all_pending,
            "initialActivity": initial_resp.get("accountActivity", {})
        }

    def capture_all_data(
        self,
        cache_dir: str = "raw_statements",
        include_pdfs: bool = True,
        max_pdf_statements: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Perform complete extraction of account data, statement catalog, statement PDFs,
        and full historical transaction records.
        """
        os.makedirs(cache_dir, exist_ok=True)

        if progress_callback:
            progress_callback("Extracting Citi card overview and balance data...")

        overview = self.get_account_overview()
        ledger_data = overview.get("balances_data", {}).get("accountLedgerData", [])
        if not ledger_data:
            raise CDPError("No credit card accounts found in Citi balance inquiry.")

        primary_card = ledger_data[0]
        account_id = primary_card.get("accountId")
        card_name = primary_card.get("accountMetaData", {}).get("productNameAndDisplayAccountNo", "Citi Credit Card")

        if progress_callback:
            progress_callback(f"Found active account: {card_name} (ID: {account_id})")
            progress_callback("Fetching statements catalog...")

        catalog = self.fetch_statements_catalog(account_id)

        # Collect statements to download
        statements_list: List[Dict[str, Any]] = []
        for year_group in catalog.get("statementsByYear", []):
            year_title = year_group.get("displayYearTitle", "")
            for stmt in year_group.get("statementsByMonth", []):
                stmt_info = dict(stmt)
                stmt_info["year"] = year_title
                statements_list.append(stmt_info)

        downloaded_statements: List[Dict[str, Any]] = []
        if include_pdfs and statements_list:
            to_download = statements_list if max_pdf_statements is None else statements_list[:max_pdf_statements]
            total = len(to_download)
            for idx, s in enumerate(to_download, 1):
                s_date = s.get("statementDate")
                disp_date = s.get("displayDate", "")
                year = s.get("year", "")
                clean_date = s_date.replace("/", "-")
                pdf_path = os.path.join(cache_dir, f"citi_statement_{clean_date}.pdf")

                if progress_callback:
                    progress_callback(f"Downloading statement PDF [{idx}/{total}]: {disp_date} {year} ({s_date})...")

                try:
                    if os.path.exists(pdf_path):
                        with open(pdf_path, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("utf-8")
                    else:
                        b64 = self.fetch_statement_pdf_base64(account_id, s_date)
                        with open(pdf_path, "wb") as f:
                            f.write(base64.b64decode(b64))

                    s_entry = dict(s)
                    s_entry["pdf_file"] = pdf_path
                    s_entry["pdf_base64"] = b64
                    downloaded_statements.append(s_entry)
                except Exception as e:
                    if progress_callback:
                        progress_callback(f"Warning: Failed to download statement {s_date}: {e}")

        # Fetch all transactions
        if progress_callback:
            progress_callback("Extracting full historical transaction activity...")
        tx_data = self.fetch_all_transactions(account_id, progress_callback=progress_callback)

        return {
            "account_overview": overview,
            "statements_catalog": catalog,
            "statements": downloaded_statements,
            "transactions": tx_data,
        }
