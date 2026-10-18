"""Command Line Interface for Citi to Monarch Money export."""

import argparse
import json
import os
import sys
from typing import Optional

from citi_to_monarch.cdp import CDPSession, CDPError
from citi_to_monarch.parser import parse_citi_dataset, parse_citi_statements_dir
from citi_to_monarch.exporter import Exporter


def run_pipeline(
    port: int = 9222,
    tab_id: Optional[str] = None,
    output_dir: str = "output",
    cache_file: Optional[str] = "citi_raw_data.json",
    cache_dir: str = "raw_statements",
    statements_dir: Optional[str] = "statements",
    include_pdfs: bool = True,
    max_pdf_statements: Optional[int] = None,
    invert_liability: bool = True,
    input_file: Optional[str] = None,
):
    """Run full automated capture and export pipeline."""
    os.makedirs(output_dir, exist_ok=True)
    raw_data = None

    if input_file and os.path.exists(input_file):
        print(f"Loading raw Citi dataset from '{input_file}'...")
        with open(input_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    else:
        print(f"Connecting to Chrome DevTools Protocol on port {port}...")
        try:
            with CDPSession(port=port, tab_id=tab_id) as session:
                tab_title = session.tab_info.get("title", "") if session.tab_info else ""
                print(f"Connected to Citi tab: {tab_title}")
                print("Starting automated extraction of recent activity, statements, and transactions...")
                raw_data = session.capture_all_data(
                    cache_dir=cache_dir,
                    include_pdfs=include_pdfs,
                    max_pdf_statements=max_pdf_statements,
                    progress_callback=print,
                )
        except CDPError as e:
            print(f"CDP Error: {e}", file=sys.stderr)
            sys.exit(1)

        # Cache raw data if requested
        if cache_file:
            print(f"Saving raw dataset to '{cache_file}'...")
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, indent=2)
            except Exception as e:
                print(f"Warning: Failed to save raw cache file: {e}")

    print("Parsing statements and transactions...")
    account = parse_citi_dataset(raw_data)

    if statements_dir and os.path.exists(statements_dir):
        print(f"Parsing statement PDFs from '{statements_dir}'...")
        pdf_stmts = parse_citi_statements_dir(statements_dir)
        print(f"Found {len(pdf_stmts)} statement PDFs.")
        account.merge_statement_pdf_data(pdf_stmts)

    print("Exporting continuous daily balances and transactions to Monarch CSVs...")
    exporter = Exporter(output_dir=output_dir)
    exporter.export_account(account, invert_liability=invert_liability)


def run_capture(
    port: int = 9222,
    tab_id: Optional[str] = None,
    output_file: str = "citi_raw_data.json",
    cache_dir: str = "raw_statements",
    include_pdfs: bool = True,
    max_pdf_statements: Optional[int] = None,
):
    """Capture raw data from Chrome CDP and write to JSON file."""
    print(f"Connecting to Chrome on port {port}...")
    try:
        with CDPSession(port=port, tab_id=tab_id) as session:
            tab_title = session.tab_info.get("title", "") if session.tab_info else ""
            print(f"Connected to Citi tab: {tab_title}")
            raw_data = session.capture_all_data(
                cache_dir=cache_dir,
                include_pdfs=include_pdfs,
                max_pdf_statements=max_pdf_statements,
                progress_callback=print,
            )
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2)
            print(f"Raw Citi data captured successfully to '{output_file}'.")
    except CDPError as e:
        print(f"CDP Error: {e}", file=sys.stderr)
        sys.exit(1)


def run_convert(
    input_file: str,
    output_dir: str = "output",
    statements_dir: Optional[str] = "statements",
    invert_liability: bool = True,
):
    """Convert an existing JSON cache file to Monarch CSVs."""
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading '{input_file}'...")
    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    print("Parsing Citi statements and transactions...")
    account = parse_citi_dataset(raw_data)

    if statements_dir and os.path.exists(statements_dir):
        print(f"Parsing statement PDFs from '{statements_dir}'...")
        pdf_stmts = parse_citi_statements_dir(statements_dir)
        print(f"Found {len(pdf_stmts)} statement PDFs.")
        account.merge_statement_pdf_data(pdf_stmts)

    print("Exporting to Monarch CSV files...")
    exporter = Exporter(output_dir=output_dir)
    exporter.export_account(account, invert_liability=invert_liability)


def run_check_archives(
    port: int = 9222,
    tab_id: Optional[str] = None,
    statements_dir: str = "statements",
    output_dir: str = "output",
    cache_file: str = "citi_raw_data.json",
    download_ready: bool = True,
    invert_liability: bool = True,
):
    """Check status of Citi archived statements and download any ready PDFs."""
    os.makedirs(statements_dir, exist_ok=True)
    print(f"Connecting to Chrome on port {port}...")
    try:
        with CDPSession(port=port, tab_id=tab_id) as session:
            overview = session.get_account_overview()
            ledger_data = overview.get("balances_data", {}).get("accountLedgerData", [])
            if not ledger_data:
                raise CDPError("No credit card accounts found in Citi balance inquiry.")
            account_id = ledger_data[0].get("accountId")
            print(f"Checking archived statements for account ID: {account_id}...")
            arch_data = session.fetch_archived_statements_catalog(account_id)
            statements = arch_data.get("archivedStatementsByMonth", [])
            print(f"Total archived statement requests registered with Citi: {len(statements)}")

            processing = [s for s in statements if s.get("statusIndicator") == "P"]
            ready = [s for s in statements if s.get("statusIndicator") != "P"]
            print(f"  Processing (in 24-48h queue): {len(processing)}")
            print(f"  Ready for download:          {len(ready)}")

            downloaded_count = 0
            if download_ready and ready:
                import base64
                for s in ready:
                    s_date = s.get("statementDate")
                    disp = s.get("displayDate", s_date)
                    pdf_filename = f"{s_date}.pdf"
                    pdf_path = os.path.join(statements_dir, pdf_filename)
                    if os.path.exists(pdf_path):
                        continue
                    print(f"Downloading ready statement {disp} ({s_date})...")
                    try:
                        b64 = session.fetch_archived_statement_pdf_base64(account_id, s_date)
                        with open(pdf_path, "wb") as f:
                            f.write(base64.b64decode(b64))
                        downloaded_count += 1
                    except Exception as e:
                        print(f"Warning: Failed to download archive statement {s_date}: {e}")
                print(f"Downloaded {downloaded_count} new archived statement PDFs.")

                if downloaded_count > 0 and os.path.exists(cache_file):
                    print("Re-running conversion to incorporate newly downloaded archives...")
                    run_convert(
                        input_file=cache_file,
                        output_dir=output_dir,
                        statements_dir=statements_dir,
                        invert_liability=invert_liability,
                    )
    except CDPError as e:
        print(f"CDP Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Extract Citi credit card activity and continuous daily balances into Monarch Money CSVs."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: all
    p_all = subparsers.add_parser("all", help="Perform full automated capture and Monarch export")
    p_all.add_argument("--port", type=int, default=9222, help="Chrome CDP port (default: 9222)")
    p_all.add_argument("--tab-id", type=str, default=None, help="Specific Chrome tab ID to attach to")
    p_all.add_argument("--output-dir", type=str, default="output", help="Directory for exported CSVs")
    p_all.add_argument("--cache-file", type=str, default="citi_raw_data.json", help="Path to save captured JSON")
    p_all.add_argument("--cache-dir", type=str, default="raw_statements", help="Directory to save downloaded PDFs")
    p_all.add_argument("--statements-dir", type=str, default="statements", help="Directory containing statement PDFs")
    p_all.add_argument("--no-pdfs", action="store_false", dest="include_pdfs", help="Skip downloading statement PDFs")
    p_all.add_argument("--max-pdf-statements", type=int, default=None, help="Limit number of statement PDFs to download")
    p_all.add_argument(
        "--positive-balances",
        action="store_false",
        dest="invert_liability",
        help="Export debt balances as positive numbers instead of negative liabilities",
    )
    p_all.add_argument("--input-file", type=str, default=None, help="Use existing JSON cache instead of live capture")

    # Command: capture
    p_cap = subparsers.add_parser("capture", help="Capture raw Citi dataset from browser to JSON")
    p_cap.add_argument("--port", type=int, default=9222, help="Chrome CDP port (default: 9222)")
    p_cap.add_argument("--tab-id", type=str, default=None, help="Specific Chrome tab ID")
    p_cap.add_argument("--output-file", type=str, default="citi_raw_data.json", help="Output JSON path")
    p_cap.add_argument("--cache-dir", type=str, default="raw_statements", help="Directory for PDFs")
    p_cap.add_argument("--no-pdfs", action="store_false", dest="include_pdfs", help="Skip PDF downloads")
    p_cap.add_argument("--max-pdf-statements", type=int, default=None, help="Limit number of PDFs")

    # Command: convert
    p_conv = subparsers.add_parser("convert", help="Convert existing raw Citi JSON file to Monarch CSVs")
    p_conv.add_argument("input_file", type=str, help="Path to raw JSON file")
    p_conv.add_argument("--output-dir", type=str, default="output", help="Directory for exported CSVs")
    p_conv.add_argument("--statements-dir", type=str, default="statements", help="Directory containing statement PDFs")
    p_conv.add_argument(
        "--positive-balances",
        action="store_false",
        dest="invert_liability",
        help="Export debt balances as positive numbers instead of negative liabilities",
    )

    # Command: check-archives
    p_arch = subparsers.add_parser("check-archives", help="Check status of Citi archived statements and download ready PDFs")
    p_arch.add_argument("--port", type=int, default=9222, help="Chrome CDP port (default: 9222)")
    p_arch.add_argument("--tab-id", type=str, default=None, help="Specific Chrome tab ID")
    p_arch.add_argument("--statements-dir", type=str, default="statements", help="Directory to save downloaded PDFs")
    p_arch.add_argument("--output-dir", type=str, default="output", help="Directory for exported CSVs")
    p_arch.add_argument("--cache-file", type=str, default="citi_raw_data.json", help="Path to raw JSON cache")
    p_arch.add_argument("--no-download", action="store_false", dest="download_ready", help="Check status only, do not download")
    p_arch.add_argument(
        "--positive-balances",
        action="store_false",
        dest="invert_liability",
        help="Export debt balances as positive numbers instead of negative liabilities",
    )

    args = parser.parse_args()

    # Default to 'all' if no command specified
    cmd = args.command or "all"

    if cmd == "all":
        run_pipeline(
            port=getattr(args, "port", 9222),
            tab_id=getattr(args, "tab_id", None),
            output_dir=getattr(args, "output_dir", "output"),
            cache_file=getattr(args, "cache_file", "citi_raw_data.json"),
            cache_dir=getattr(args, "cache_dir", "raw_statements"),
            statements_dir=getattr(args, "statements_dir", "statements"),
            include_pdfs=getattr(args, "include_pdfs", True),
            max_pdf_statements=getattr(args, "max_pdf_statements", None),
            invert_liability=getattr(args, "invert_liability", True),
            input_file=getattr(args, "input_file", None),
        )
    elif cmd == "capture":
        run_capture(
            port=args.port,
            tab_id=args.tab_id,
            output_file=args.output_file,
            cache_dir=args.cache_dir,
            include_pdfs=args.include_pdfs,
            max_pdf_statements=args.max_pdf_statements,
        )
    elif cmd == "convert":
        run_convert(
            input_file=args.input_file,
            output_dir=args.output_dir,
            statements_dir=getattr(args, "statements_dir", "statements"),
            invert_liability=args.invert_liability,
        )
    elif cmd == "check-archives":
        run_check_archives(
            port=args.port,
            tab_id=args.tab_id,
            statements_dir=args.statements_dir,
            output_dir=args.output_dir,
            cache_file=args.cache_file,
            download_ready=args.download_ready,
            invert_liability=args.invert_liability,
        )


if __name__ == "__main__":
    main()
