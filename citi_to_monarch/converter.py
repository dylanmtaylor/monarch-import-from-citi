"""Converts parsed Citi transactions and balances to Monarch Money CSV format."""

import csv
import io
from typing import List, Dict, Any
from citi_to_monarch.parser import CitiTransaction


def convert_balances_to_csv(daily_balances: List[Dict[str, Any]]) -> str:
    """
    Format continuous daily balances into Monarch Money CSV format.
    Header: Date,Balance
    
    Args:
        daily_balances: List of dicts containing 'date' (YYYY-MM-DD) and 'balance' (float).
        
    Returns:
        CSV string conforming to Monarch Money Balance History specifications.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Date", "Balance"])

    for row in daily_balances:
        writer.writerow([row["date"], f"{row['balance']:.2f}"])

    return output.getvalue()


def convert_transactions_to_csv(
    transactions: List[CitiTransaction], account_display_name: str
) -> str:
    """
    Format transactions into Monarch Money CSV format.
    Header: Date,Merchant,Category,Account,Original Statement,Notes,Amount
    
    Args:
        transactions: List of CitiTransaction objects.
        account_display_name: Name of the account to write in the Account column.
        
    Returns:
        CSV string conforming to Monarch Money Transaction specifications.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Date", "Merchant", "Category", "Account", "Original Statement", "Notes", "Amount"])

    for tx in transactions:
        writer.writerow([
            tx.date,
            tx.merchant,
            tx.category,
            account_display_name,
            tx.original_statement,
            tx.notes,
            f"{tx.amount:.2f}",
        ])

    return output.getvalue()
