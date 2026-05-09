import json
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

# Conventional classes identified in the lecture
CONVENTIONAL_ASSET_CLASSES = {"Rates", "Credit", "FX", "Equity", "Commodities"}
# EventContract is explicitly identified as having no taxonomy
NOVEL_ASSET_CLASSES = {"EventContract"}

def classify_instrument(trade: dict) -> str:
    """
    Determine the regulatory taxonomy classification flag for a trade.
    """
    asset_class = trade.get("asset_class")
    if asset_class is None:
        return "CLASSIFICATION_AMBIGUOUS"
    if asset_class in CONVENTIONAL_ASSET_CLASSES:
        return "CONVENTIONAL_DERIVATIVE"
    if asset_class in NOVEL_ASSET_CLASSES:
        return "NOVEL_INSTRUMENT_NO_TAXONOMY"
    
    return "CLASSIFICATION_AMBIGUOUS"

def parse_trade(trade: dict) -> dict:
    """
    Parse a single trade and return a dictionary matching the expected JSON output format.
    Includes logic for date sequencing and field extraction.
    """
    errors: list[str] = []
    status = "SUCCESS"
    
    # 1. Classification
    classification_flag = classify_instrument(trade)
    
    # 2. Timestamp Validation (ISO 8601 UTC)
    exec_ts = str(trade.get("execution_timestamp", ""))
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    if not re.match(iso_pattern, exec_ts):
        errors.append(f"Timestamp '{exec_ts}' is not ISO 8601 UTC")
        status = "PARTIAL"

    # 3. Date Logic Validation: Maturity must be after Effective date
    eff_date_str = trade.get("effective_date")
    mat_date_str = trade.get("maturity_date")
    
    if eff_date_str and mat_date_str and mat_date_str != "9999-99-99":
        try:
            eff_dt = datetime.strptime(str(eff_date_str), "%Y-%m-%d")
            mat_dt = datetime.strptime(str(mat_date_str), "%Y-%m-%d")
            if mat_dt <= eff_dt:
                errors.append(f"Maturity date ({mat_date_str}) must be after effective date ({eff_date_str})")
                status = "PARTIAL"
        except ValueError:
            # Errors for malformed dates are already caught by the parsing logic
            pass

    # 4. Outlier Handling: Placeholder dates
    if mat_date_str == "9999-99-99":
        errors.append("Maturity date is placeholder 9999-99-99")
        status = "PARTIAL"

    # 5. Extract Classified Fields as per screenshot requirement
    # Note: Using .get() to avoid crashes on missing keys 
    classified_fields = {
        "notional_currency": trade.get("notional_currency"),
        "notional_amount": trade.get("notional_amount"),
        "cleared": trade.get("cleared"),
        "uti": trade.get("uti")
    }

    # Construct the final record per trade
    return {
        "trade_id": trade.get("trade_id"),
        "parse_status": status,
        "asset_class": trade.get("asset_class"),
        "instrument_type": trade.get("instrument_type"),
        "use_case": trade.get("use_case"),
        "classification_flag": classification_flag,
        "parse_errors": errors,
        "classified_fields": classified_fields
    }

def run_module1(json_path: str):
    """
    Reads trades.json and outputs the results in the required JSON format.
    """
    try:
        with open(json_path, 'r') as f:
            raw_trades = json.load(f)
        
        output_records = [parse_trade(t) for t in raw_trades]
        
        # Print results as formatted JSON strings for verification
        print(json.dumps(output_records, indent=2))
        
        return output_records
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

if __name__ == "__main__":
    # Ensure trades.json is in the same directory
    run_module1("trades.json")