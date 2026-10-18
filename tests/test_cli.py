"""Unit tests for citi_to_monarch.cli."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch
from citi_to_monarch.cli import run_convert, run_pipeline


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


if __name__ == "__main__":
    unittest.main()
