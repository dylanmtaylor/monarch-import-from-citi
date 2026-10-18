"""Unit tests for citi_to_monarch.exporter."""

import os
import tempfile
import unittest
from citi_to_monarch.parser import CitiAccount, StatementPeriod, CitiTransaction
from citi_to_monarch.exporter import Exporter


class TestExporter(unittest.TestCase):
    """Test exporting CSV files to disk."""

    def test_export_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            account = CitiAccount(
                card_name="Citi Double Cash Synthetic",
                account_number="9876",
                current_balance=20.00,
                credit_limit=2500.00,
            )
            stmt = StatementPeriod(
                statement_date="2026-06-30",
                start_date="2026-06-01",
                end_date="2026-06-30",
                previous_balance=0.00,
                closing_balance=20.00,
                transactions=[
                    CitiTransaction(
                        date="2026-06-15",
                        merchant="Synthetic Store",
                        category="Shopping",
                        account="Citi Double Cash Synthetic (9876)",
                        original_statement="SYNTHETIC STORE",
                        notes="",
                        amount=-20.00,
                    )
                ],
            )
            account.statements = [stmt]

            exporter = Exporter(output_dir=tmpdir)
            metrics = exporter.export_account(account)

            bal_file = metrics["balance_file"]
            txn_file = metrics["transaction_file"]

            self.assertTrue(os.path.exists(bal_file))
            self.assertTrue(os.path.exists(txn_file))

            with open(bal_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("Date,Balance", content)
                self.assertIn("2026-06-30,-20.00", content)

            with open(txn_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("Date,Merchant,Category,Account,Original Statement,Notes,Amount", content)
                self.assertIn("Synthetic Store,Shopping,Citi Double Cash Synthetic (9876),SYNTHETIC STORE,,-20.00", content)


if __name__ == "__main__":
    unittest.main()
