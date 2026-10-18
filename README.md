# monarch-import-from-citi

Automated extraction and conversion tool for **Citi** credit card accounts (Citi Double Cash®, Custom Cash®, Diamond Preferred®, Premier®, etc.) into **Monarch Money**-compatible CSV imports.

Connects to an authenticated Citibank session in Google Chrome via Chrome DevTools Protocol (CDP), captures online recent activity, historical statements (both catalog and statement PDFs), and transactions back to account inception, parses transactions and statement closing balances, and exports:
1. **Continuous Daily Balance History** (`Date,Balance`) across all calendar days back to account inception, integrating verified statement checkpoints.
2. **Standard Transactions** (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`) with automatic merchant cleaning and category inference.
3. **Full Multi-Year Statement Archive Coverage**: Seamlessly downloads and parses statement PDFs and paginated JSON transactions across years (YTD, prior years, and historical date ranges) to reconstruct complete card history.

---

## Features

- **Automated Statement History Extraction**:
  - Automatically fetches all available statement periods from Citi's online statement repository (up to 24 billing periods).
  - Automatically downloads and parses statement PDFs via `pdftotext` to extract verified billing cycle start/end dates, previous balances, new balances, payments, credits, and purchases.
- **Continuous Daily Balance Interpolation**:
  - Reconstructs uninterrupted daily balances forward-filled from account open date up to the present day, perfectly aligning with official statement closing checkpoints.
  - Supports standard liability representation (negative decimal balance for Monarch liabilities where Assets - Liabilities = Net Worth).
- **Comprehensive Transaction Extraction**:
  - Automatically handles pagination across recent unbilled activity, Year-to-Date (YTD), Prior Year, and earlier date ranges.
  - Normalizes merchant descriptions (removes digital account numbers, PayPal prefixes, terminal numbers, state codes) and infers standard Monarch categories.
- **Chrome CDP Session Extraction**:
  - Reuses your active, authenticated Chrome browser session via CDP (port `9222`) without requiring credential storage or password exposure.
- **Monarch Money Import Ready**:
  - Strict compliance with Monarch's CSV specifications for Balances (`Date,Balance`) and Transactions (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`).
- **Zero PII Committed**:
  - All account numbers, financial amounts, raw JSON captures, PDF statements, and CSV exports are safely excluded via `.gitignore`.

---

## Installation

```bash
git clone https://github.com/dylanmtaylor/monarch-import-from-citi.git
cd monarch-import-from-citi
pip install -e .
```

### Dependencies
- Python 3.9+
- `websocket-client>=1.6.0`
- `poppler-utils` (provides `pdftotext` for statement PDF parsing)

---

## Quickstart

### 1. Launch Chrome with Remote Debugging
Ensure Chrome is running with `--remote-debugging-port=9222` and log into [Citibank Online](https://online.citi.com):

```bash
google-chrome --remote-debugging-port=9222
# or on Flatpak:
flatpak run com.google.Chrome --remote-debugging-port=9222
```

### 2. Run Capture & Convert
Run the automated pipeline to capture statement data and generate Monarch CSVs:

```bash
citi-to-monarch all
# or directly via python:
python3 -m citi_to_monarch.cli all
```

Or specify a custom output directory:

```bash
citi-to-monarch all --output-dir ./output
```

---

## CLI Commands

The CLI supports modular workflows:

- **`all`**: Complete pipeline — captures from browser (or input file), parses statement checkpoints and transactions, and exports Monarch CSVs.
  ```bash
  citi-to-monarch all [--port 9222] [--output-dir output] [--cache-file citi_raw_data.json] [--statements-dir statements]
  ```
- **`capture`**: Capture raw Citi account data, statement catalog, PDFs, and transactions to a JSON cache file.
  ```bash
  citi-to-monarch capture [--output-file citi_raw_data.json] [--cache-dir raw_statements]
  ```
- **`convert`**: Convert an existing JSON cache file to Monarch CSVs without connecting to the browser, merging any historical statement PDFs:
  ```bash
  citi-to-monarch convert citi_raw_data.json [--statements-dir statements] [--output-dir output]
  ```

### Backfilling Historical Statements
Citi makes up to 24 months of statement PDFs available immediately in the online portal, with older statements (back to account opening) available upon request via Citi's Archived Statements portal. Any downloaded statement PDFs placed in `statements/` (or specified via `--statements-dir`) will automatically be parsed, merged with transactions, and stitched into continuous daily balance history.

---

## Testing

Run the full synthetic test suite (100% synthetic fixtures, zero network calls):

```bash
python3 -m unittest discover tests -v
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
