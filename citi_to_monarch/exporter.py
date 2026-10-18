"""Exports converted Citi balances and transactions to Monarch Money CSV files on disk."""

import os
from typing import Dict, Any, Optional
from citi_to_monarch.parser import CitiAccount
from citi_to_monarch.converter import convert_balances_to_csv, convert_transactions_to_csv


class Exporter:
    """Exports Monarch CSV files and displays detailed summary reports."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir

    def export_account(
        self, account: CitiAccount, invert_liability: bool = True
    ) -> Dict[str, Any]:
        """
        Export balance history and transaction CSVs for a Citi credit card account.
        
        Args:
            account: Populated CitiAccount object.
            invert_liability: Whether to negate debt balances for Monarch balance history.
            
        Returns:
            Dict containing output file paths and summary metrics.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        slug = account.slug
        display_name = account.display_name

        # 1. Compute and export daily balances
        daily_balances = account.compute_daily_balances(invert_liability=invert_liability)
        bal_csv = convert_balances_to_csv(daily_balances)
        bal_file = os.path.join(self.output_dir, f"citi_balances_{slug}.csv")
        with open(bal_file, "w", encoding="utf-8") as f:
            f.write(bal_csv)

        # 2. Export account transactions
        all_transactions = account.get_all_transactions()
        txn_csv = convert_transactions_to_csv(all_transactions, display_name)
        txn_file = os.path.join(self.output_dir, f"citi_transactions_{slug}.csv")
        with open(txn_file, "w", encoding="utf-8") as f:
            f.write(txn_csv)

        first_bal_date = daily_balances[0]["date"] if daily_balances else "N/A"
        last_bal_date = daily_balances[-1]["date"] if daily_balances else "N/A"
        current_bal_formatted = f"${account.current_balance:,.2f}"

        first_txn_date = all_transactions[0].date if all_transactions else "N/A"
        last_txn_date = all_transactions[-1].date if all_transactions else "N/A"

        metrics = {
            "account_name": account.card_name,
            "account_number": account.account_number,
            "display_name": display_name,
            "transactions_count": len(all_transactions),
            "transactions_range": f"{first_txn_date} to {last_txn_date}",
            "daily_balance_days": len(daily_balances),
            "daily_balance_range": f"{first_bal_date} to {last_bal_date}",
            "current_balance": account.current_balance,
            "balance_file": bal_file,
            "transaction_file": txn_file,
        }

        # Print formatted summary table
        print("\n" + "=" * 76)
        print(" Citi Credit Card -> Monarch Money Export Summary")
        print("=" * 76)
        print(f" Account:            {display_name}")
        print(f" Cardholder:         {account.cardholder or 'N/A'}")
        print(f" Current Balance:    {current_bal_formatted}")
        print(f" Total Credit Line:  ${account.credit_limit:,.2f}")
        print(f" Statements Parsed:  {len(account.statements)}")
        print("-" * 76)
        print(f" Total Transactions: {len(all_transactions):,} records ({first_txn_date} to {last_txn_date})")
        print(f" Balance History:    {len(daily_balances):,} uninterrupted daily points ({first_bal_date} to {last_bal_date})")
        print("-" * 76)
        print(f" -> Balance CSV:      {bal_file}")
        print(f" -> Transactions CSV: {txn_file}")
        print("=" * 76)
        print("Export completed successfully.")
        print("=" * 76 + "\n")

        return metrics
