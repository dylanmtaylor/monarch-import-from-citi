"""Unit tests for citi_to_monarch.parser."""

import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
from citi_to_monarch.parser import (
    parse_date,
    clean_merchant_name,
    infer_category,
    parse_citi_pdf_statement,
    parse_citi_statements_dir,
    parse_citi_dataset,
    CitiTransaction,
    StatementPeriod,
    CitiAccount,
)


class TestParser(unittest.TestCase):
    """Test parser functionality with 100% synthetic test fixtures."""

    def test_parse_date_formats(self):
        """Test parsing diverse date formats into standard ISO YYYY-MM-DD."""
        self.assertEqual(parse_date("2026-10-09"), "2026-10-09")
        self.assertEqual(parse_date("20261009"), "2026-10-09")
        self.assertEqual(parse_date("10/09/2026"), "2026-10-09")
        self.assertEqual(parse_date("09/10/26"), "2026-09-10")
        self.assertEqual(parse_date("10/09", default_year=2026), "2026-10-09")
        self.assertEqual(parse_date("Oct 9, 2026"), "2026-10-09")
        self.assertEqual(parse_date("October 09, 2026"), "2026-10-09")

    def test_clean_merchant_name(self):
        """Test merchant cleaning rules for synthetic test descriptions."""
        cases = [
            ("ONLINE PAYMENT, THANK YOU", "Payment - Thank You"),
            ("DD *DOORDASH 7THSTREET SAN FRANCISCO CA Digital Account Number XXXXXXXXXXXX9564", "DoorDash"),
            ("PAYPAL *EBAY 800-456-3 4029357733 CA Digital Account Number XXXXXXXXXXXX9346", "eBay"),
            ("STARBUCKS 70793 PITTSBURGH PA", "Starbucks"),
            ("AMAZON MKTPL*5L3W01PY2 SEATTLE WA", "Amazon"),
            ("WWW COSTCO COM ISSAQUAH WA", "Costco"),
            ("SURETYCAM, LLC COLUMBUS OH", "SuretyCam"),
            ("THE HERITAGE HOTEL NEW YORK NY", "The Heritage Hotel"),
            ("BURGER KING #1234 RALEIGH NC", "Burger King"),
            ("FIVE GUYS BURGERS & FRIES DURHAM NC", "Five Guys"),
            ("DELTA 00624683849414 DELTA.COM CA", "Delta Air Lines"),
            ("CHWYINC*GPAYZGHHNOEOUG 8006724399 FL", "Chewy"),
        ]
        for raw, expected in cases:
            self.assertEqual(clean_merchant_name(raw), expected)

    def test_infer_category(self):
        """Test category inference rules."""
        self.assertEqual(infer_category("Payment - Thank You", 100.0), "Credit Card Payment")
        self.assertEqual(infer_category("DoorDash", -25.50, raw_category="Restaurants - EATING PLACE"), "Restaurants")
        self.assertEqual(infer_category("The Heritage Hotel", -200.0, raw_category="LODGING, HOTELS"), "Travel")
        self.assertEqual(infer_category("Starbucks", -6.50), "Coffee Shops")
        self.assertEqual(infer_category("Costco", -85.00), "Groceries")
        self.assertEqual(infer_category("Amazon", -45.00, raw_category="Merchandise - VARIETY STORE"), "Shopping")
        self.assertEqual(infer_category("Udemy", -15.00), "Subscriptions")
        self.assertEqual(infer_category("Great Clips", -24.00), "Personal Care")
        self.assertEqual(infer_category("Gnome Foundation", -10.0), "Charity")

    @patch("subprocess.run")
    def test_parse_citi_pdf_statement(self, mock_run):
        """Test parsing of statement PDF via synthetic pdftotext output."""
        synthetic_text = """
Billing Period: 09/10/26-10/09/26
New balance as of 10/09/26: $1,250.00
Account Summary
Previous balance $1,000.00
Payments -$500.00
Credits -$50.00
Purchases +$800.00
Fees +$0.00
Interest +$0.00
New balance $1,250.00

09/15 09/15 ONLINE PAYMENT, THANK YOU -$500.00
09/20 09/20 SAMPLE RESTAURANT SAN FRANCISCO CA $45.00
09/25 09/25 SAMPLE STORE NEW YORK NY $755.00
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = synthetic_text.encode("utf-8")
        mock_run.return_value = mock_proc

        stmt = parse_citi_pdf_statement(b"%PDF-synthetic-bytes")
        self.assertEqual(stmt.statement_date, "2026-10-09")
        self.assertEqual(stmt.start_date, "2026-09-10")
        self.assertEqual(stmt.end_date, "2026-10-09")
        self.assertEqual(stmt.previous_balance, 1000.00)
        self.assertEqual(stmt.closing_balance, 1250.00)
        self.assertEqual(stmt.purchases, 800.00)
        self.assertEqual(stmt.payments_and_credits, 550.00)
        self.assertEqual(len(stmt.transactions), 3)

        # In Monarch, payment is positive (+500), purchase is negative (-45, -755)
        self.assertEqual(stmt.transactions[0].amount, 500.00)
        self.assertEqual(stmt.transactions[1].amount, -45.00)
        self.assertEqual(stmt.transactions[2].amount, -755.00)

    def test_parse_synthetic_dataset(self):
        """Test parsing complete synthetic JSON dataset structure."""
        synthetic_payload = {
            "account_overview": {
                "cardholder": "SAMPLE CITIZEN",
                "balances_data": {
                    "accountLedgerData": [
                        {
                            "accountId": "synth-uuid-1234",
                            "displayAccountNumber": "9999",
                            "accountMetaData": {
                                "productNameAndDisplayAccountNo": "Citi Double Cash Card - 9999"
                            },
                            "accountBalance": {
                                "currentBalanceAmount": "250.00",
                                "creditLimit": "10000.0",
                                "availableCreditAmount": "9750.00"
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
                        "transactionAuthorizationId": "auth-1",
                        "transactionSaleDate": "10/16/2026",
                        "cleansedName": "Sample Grocery",
                        "transactionDescription": "SAMPLE GROCERY MARKET",
                        "transactionAmount": 50.00,
                        "extendedDescriptions": [
                            {"fieldIndicator": "CATEGORY", "displayValue": "Groceries"}
                        ]
                    },
                    {
                        "transactionAuthorizationId": "auth-2",
                        "transactionSaleDate": "10/14/2026",
                        "cleansedName": "ONLINE PAYMENT, THANK YOU",
                        "transactionDescription": "ONLINE PAYMENT, THANK YOU",
                        "transactionAmount": -200.00,
                        "extendedDescriptions": []
                    }
                ],
                "pendingTransactions": [
                    {
                        "transactionAuthorizationId": "auth-3",
                        "transactionSaleDate": "10/17/2026",
                        "cleansedName": "Coffee Shop",
                        "transactionDescription": "CORNER COFFEE SHOP",
                        "transactionAmount": 5.25,
                        "extendedDescriptions": []
                    }
                ]
            }
        }

        account = parse_citi_dataset(synthetic_payload)
        self.assertEqual(account.card_name, "Citi Double Cash Card - 9999")
        self.assertEqual(account.account_number, "9999")
        self.assertEqual(account.current_balance, 250.00)
        self.assertEqual(account.credit_limit, 10000.00)
        self.assertEqual(account.cardholder, "SAMPLE CITIZEN")
        self.assertEqual(account.display_name, "Citi Double Cash Card (9999)")

        all_tx = account.get_all_transactions()
        self.assertEqual(len(all_tx), 3)

        # Verify amounts: purchase is -50, payment is +200, pending is -5.25
        purchases = [t for t in all_tx if t.amount < 0]
        payments = [t for t in all_tx if t.amount > 0]
        self.assertEqual(len(purchases), 2)
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].amount, 200.00)

    def test_parse_citi_pdf_statement_synthetic_str(self):
        """Test parsing of statement PDF directly from synthetic layout string."""
        synthetic_text = """
Billing Period: 08/10/26-09/09/26
New balance as of 09/09/26: $845.50
Account Summary
Previous balance $1,200.00
Payments -$1,200.00
Credits -$0.00
Purchases +$845.50
Fees +$0.00
Interest +$0.00
New balance $845.50

08/12 08/12 ONLINE PAYMENT, THANK YOU -$1,200.00
08/18 08/19 SAMPLE BOOKSTORE SEATTLE WA $45.50
08/25 08/26 SAMPLE GROCERY MARKET PORTLAND OR $800.00
        """
        stmt = parse_citi_pdf_statement(synthetic_text)
        self.assertEqual(stmt.statement_date, "2026-09-09")
        self.assertEqual(stmt.start_date, "2026-08-10")
        self.assertEqual(stmt.end_date, "2026-09-09")
        self.assertEqual(stmt.previous_balance, 1200.00)
        self.assertEqual(stmt.closing_balance, 845.50)
        self.assertEqual(stmt.purchases, 845.50)
        self.assertEqual(stmt.payments_and_credits, 1200.00)
        self.assertEqual(len(stmt.transactions), 3)
        self.assertEqual(stmt.transactions[0].amount, 1200.00)
        self.assertEqual(stmt.transactions[1].amount, -45.50)
        self.assertEqual(stmt.transactions[2].amount, -800.00)

    def test_merge_statement_pdf_data(self):
        """Test merging PDF statement periods into CitiAccount."""
        account = CitiAccount(
            card_name="Citi Double Cash Synthetic - 9999",
            account_number="9999",
            current_balance=50.00,
        )
        existing_stmt = StatementPeriod(
            statement_date="2026-10-09",
            start_date="2026-09-10",
            end_date="2026-10-09",
            previous_balance=0.0,
            closing_balance=0.0,
        )
        account.statements = [existing_stmt]

        new_pdf_stmts = [
            StatementPeriod(
                statement_date="2026-09-09",
                start_date="2026-08-10",
                end_date="2026-09-09",
                previous_balance=100.0,
                closing_balance=200.0,
            ),
            StatementPeriod(
                statement_date="2026-10-09",
                start_date="2026-09-10",
                end_date="2026-10-09",
                previous_balance=200.0,
                closing_balance=500.0,
            ),
        ]

        account.merge_statement_pdf_data(new_pdf_stmts)
        self.assertEqual(len(account.statements), 2)
        self.assertEqual(account.statements[0].end_date, "2026-09-09")
        self.assertEqual(account.statements[0].closing_balance, 200.0)
        self.assertEqual(account.statements[1].end_date, "2026-10-09")
        # Should be updated with real closing balance
        self.assertEqual(account.statements[1].closing_balance, 500.0)

    def test_parse_citi_statements_dir_empty_or_nonexistent(self):
        """Test parsing statements from empty or nonexistent directory."""
        stmts = parse_citi_statements_dir("/nonexistent/path/for/tests")
        self.assertEqual(stmts, [])


if __name__ == "__main__":
    unittest.main()
