"""Unit tests for citi_to_monarch.cli."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch
from citi_to_monarch.cli import run_convert, run_pipeline, run_check_archives


class TestCLI(unittest.TestCase):
    """Test CLI functionality with synthetic fixtures."""

    def setUp(self):
        self.synthetic_payload = {
            "account_overview": {
                "cardholder": "SYNTHETIC USER",
                "balances_data": {
                    "accountLedgerData": [
                        {
                            "accountId": "test-uuid-9999",
                            "displayAccountNumber": "1111",
                            "accountMetaData": {
                                "productNameAndDisplayAccountNo": "Citi Double Cash Synthetic - 1111"
                            },
                            "accountBalance": {
                                "currentBalanceAmount": "50.00",
                                "creditLimit": "3000.0",
                                "availableCreditAmount": "2950.00"
                            }
                        }
                    ]
                }
            },
            "statements_catalog": {
                "statementsByYear": [
                    {
                        "displayYearTitle": "2026",
                        "statementsByMonth": [
                            {"statementDate": "10/09/2026", "displayDate": "October 09"}
                        ]
                    }
                ]
            },
            "transactions": {
                "postedTransactions": [
                    {
                        "transactionAuthorizationId": "auth-100",
                        "transactionSaleDate": "10/10/2026",
                        "cleansedName": "Synthetic Grocery",
                        "transactionDescription": "SYNTHETIC GROCERY",
                        "transactionAmount": 50.00,
                    }
                ],
                "pendingTransactions": []
            }
        }

    def test_run_convert(self):
        """Test converting an input JSON file to output CSVs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test_input.json")
            out_dir = os.path.join(tmpdir, "output")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.synthetic_payload, f)

            run_convert(input_file=json_path, output_dir=out_dir, statements_dir=os.path.join(tmpdir, "statements"))

            bal_file = os.path.join(out_dir, "citi_balances_citi_double_cash_synthetic_1111_1111.csv")
            txn_file = os.path.join(out_dir, "citi_transactions_citi_double_cash_synthetic_1111_1111.csv")

            self.assertTrue(os.path.exists(bal_file))
            self.assertTrue(os.path.exists(txn_file))

    def test_run_pipeline_with_input_file(self):
        """Test full pipeline using pre-cached input file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test_input.json")
            out_dir = os.path.join(tmpdir, "output")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.synthetic_payload, f)

            run_pipeline(
                input_file=json_path,
                output_dir=out_dir,
                statements_dir=os.path.join(tmpdir, "statements"),
                cache_file=None,
            )

            bal_file = os.path.join(out_dir, "citi_balances_citi_double_cash_synthetic_1111_1111.csv")
            txn_file = os.path.join(out_dir, "citi_transactions_citi_double_cash_synthetic_1111_1111.csv")

            self.assertTrue(os.path.exists(bal_file))
            self.assertTrue(os.path.exists(txn_file))

    @patch("citi_to_monarch.cli.CDPSession")
    def test_run_check_archives(self, mock_cdp_class):
        """Test check-archives logic with mock CDP session."""
        mock_instance = mock_cdp_class.return_value.__enter__.return_value
        mock_instance.get_account_overview.return_value = self.synthetic_payload["account_overview"]
        mock_instance.fetch_archived_statements_catalog.return_value = {
            "archivedStatementsByMonth": [
                {"statementDate": "202410", "statusIndicator": "P", "displayDate": "Oct 2024"},
                {"statementDate": "202409", "statusIndicator": "A", "displayDate": "Sep 2024"},
            ]
        }
        mock_instance.fetch_archived_statement_pdf_base64.return_value = "JVBERi0xLjQK"

        with tempfile.TemporaryDirectory() as tmpdir:
            stmts_dir = os.path.join(tmpdir, "statements")
            run_check_archives(
                port=9222,
                statements_dir=stmts_dir,
                output_dir=os.path.join(tmpdir, "output"),
                cache_file=os.path.join(tmpdir, "nonexistent.json"),
                download_ready=True,
            )
            self.assertTrue(os.path.exists(os.path.join(stmts_dir, "202409.pdf")))


if __name__ == "__main__":
    unittest.main()
