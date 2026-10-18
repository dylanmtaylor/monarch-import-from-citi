"""Unit tests for citi_to_monarch.converter."""

import csv
import io
import unittest
from datetime import datetime, timedelta
from citi_to_monarch.parser import CitiAccount, StatementPeriod, CitiTransaction
from citi_to_monarch.converter import convert_balances_to_csv, convert_transactions_to_csv


class TestConverter(unittest.TestCase):
    """Test Monarch CSV formatting and daily balance calculations with synthetic fixtures."""

    def setUp(self):
        self.account = CitiAccount(
            card_name="Citi Double Cash Synthetic",
            account_number="5678",
            current_balance=45.00,
            credit_limit=5000.00,
            available_credit=4955.00,
        )

        # Period 1: Jan 1 to Jan 31
        stmt1 = StatementPeriod(
            statement_date="2026-01-31",
            start_date="2026-01-01",
            end_date="2026-01-31",
            previous_balance=0.00,
            closing_balance=75.00,
            transactions=[
                CitiTransaction(
                    date="2026-01-10",
                    merchant="Synthetic Merchant A",
                    category="Shopping",
                    account="Citi Double Cash Synthetic (5678)",
                    original_statement="SYNTHETIC PURCHASE 1",
                    notes="Statement Date: 2026-01-31",
                    amount=-75.00,
                )
            ],
        )

        # Period 2: Feb 1 to Feb 28
        stmt2 = StatementPeriod(
            statement_date="2026-02-28",
            start_date="2026-02-01",
            end_date="2026-02-28",
            previous_balance=75.00,
            closing_balance=45.00,
            transactions=[
                CitiTransaction(
                    date="2026-02-05",
                    merchant="Payment - Thank You",
                    category="Credit Card Payment",
                    account="Citi Double Cash Synthetic (5678)",
                    original_statement="ONLINE PAYMENT",
                    notes="Statement Date: 2026-02-28",
                    amount=75.00,
                ),
                CitiTransaction(
                    date="2026-02-15",
                    merchant="Synthetic Merchant B",
                    category="Subscriptions",
                    account="Citi Double Cash Synthetic (5678)",
                    original_statement="SYNTHETIC PURCHASE 2",
                    notes="Statement Date: 2026-02-28",
                    amount=-45.00,
                ),
            ],
        )

        self.account.statements = [stmt1, stmt2]

    def test_convert_balances_to_csv(self):
        """Test formatting of balance history CSV."""
        daily_balances = [
            {"date": "2026-01-01", "balance": 0.00},
            {"date": "2026-01-02", "balance": -75.50},
        ]
        csv_text = convert_balances_to_csv(daily_balances)
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(reader[0], ["Date", "Balance"])
        self.assertEqual(reader[1], ["2026-01-01", "0.00"])
        self.assertEqual(reader[2], ["2026-01-02", "-75.50"])

    def test_convert_transactions_to_csv(self):
        """Test formatting of transactions CSV."""
        txns = [
            CitiTransaction(
                date="2026-01-10",
                merchant="Synthetic Merchant",
                category="Shopping",
                account="Citi Double Cash (5678)",
                original_statement="SYNTHETIC PURCHASE",
                notes="Auth: 99999",
                amount=-29.99,
            )
        ]
        csv_text = convert_transactions_to_csv(txns, "Citi Double Cash (5678)")
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(
            reader[0],
            ["Date", "Merchant", "Category", "Account", "Original Statement", "Notes", "Amount"],
        )
        self.assertEqual(
            reader[1],
            ["2026-01-10", "Synthetic Merchant", "Shopping", "Citi Double Cash (5678)", "SYNTHETIC PURCHASE", "Auth: 99999", "-29.99"],
        )

    def test_compute_daily_balances_continuity(self):
        """Test that daily balances are continuous without calendar gaps."""
        daily = self.account.compute_daily_balances(invert_liability=True)
        self.assertTrue(len(daily) > 60)

        # Verify no missing calendar days
        for i in range(len(daily) - 1):
            d1 = datetime.strptime(daily[i]["date"], "%Y-%m-%d")
            d2 = datetime.strptime(daily[i + 1]["date"], "%Y-%m-%d")
            self.assertEqual((d2 - d1).days, 1, f"Gap detected between {daily[i]['date']} and {daily[i+1]['date']}")

        # Verify checkpoints
        jan31 = [d for d in daily if d["date"] == "2026-01-31"][0]
        self.assertEqual(jan31["balance"], -75.00)

        feb28 = [d for d in daily if d["date"] == "2026-02-28"][0]
        self.assertEqual(feb28["balance"], -45.00)

    def test_compute_daily_balances_positive_option(self):
        """Test positive balance history output when invert_liability is False."""
        daily = self.account.compute_daily_balances(invert_liability=False)
        jan31 = [d for d in daily if d["date"] == "2026-01-31"][0]
        self.assertEqual(jan31["balance"], 75.00)


if __name__ == "__main__":
    unittest.main()
