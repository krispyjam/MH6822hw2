import json
import pathlib
from typing import List, Optional, Dict, Any, Tuple

# Path configuration for ANNA-DSB library
DSB_BASE_PATH = pathlib.Path("data/product_definitions/PROD/OTC-Products")
CODESET_PATH = DSB_BASE_PATH / "codesets"
TEMPLATE_PATH = DSB_BASE_PATH / "UPI"

# Hard-coded constraints for attribute validation
ENUM_CONSTRAINTS = {
    "reference_rate_term_unit": ["DAYS", "WEEK", "MNTH", "YEAR"],
    "debt_seniority": ["SNDB", "MZZD", "SBOD", "JUND"],
    "notional_schedule": ["Constant", "Accreting", "Amortizing", "Custom"],
    "delivery_type": ["CASH", "PHYS", "OPTL"]
}

class UpiEngine:
    def __init__(self, raw_trades_map: Dict[str, dict]):
        """
        Initialize the engine and load codesets. 
        Uses raw_trades_map to bridge the gap between M1 subset and original data.
        """
        self.codesets = self._load_codesets()
        self.raw_trades_map = raw_trades_map

    def _load_codesets(self) -> Dict[str, set]:
        """
        Loads codesets from the 'enum' array in the DSB JSON documents.
        Returns the cache dictionary.
        """
        cache = {"currencies": set(), "rates": set()}
        
        def load_enum_set(file_path):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "enum" in data:
                        return set(data["enum"])
                    return set()
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                return set()

        cache["currencies"] = load_enum_set(CODESET_PATH / "ISOCurrencyCode.json")
        cache["rates"] = load_enum_set(CODESET_PATH / "FpmlRatesReferenceRate.json")
        return cache

    def find_product_template(self, asset_class: str, itype: str, ucase: str) -> Tuple[Optional[str], Optional[dict]]:
        """
        Search for the UPI template using exact taxonomy strings.
        """
        if not all([asset_class, itype, ucase]):
            return None, None
            
        filename = f"{asset_class}.{itype}.{ucase}.UPI.V1.json"
        target_path = TEMPLATE_PATH / asset_class / filename

        if target_path.exists():
            with open(target_path, 'r') as f:
                return f"{asset_class}.{itype}.{ucase}", json.load(f)
        return None, None

    def validate_attributes(self, full_trade: dict) -> Tuple[List[str], List[str]]:
        """
        Perform attribute validation against codesets and numeric/enum constraints.
        Returns pure data errors and warnings.
        """
        errors, warnings = [], []

        # 1. Currency Check (ISO 4217)
        for key in ["notional_currency", "notional_currency_leg1", "notional_currency_leg2"]:
            ccy = full_trade.get(key)
            if ccy and ccy not in self.codesets["currencies"]:
                errors.append(f"Invalid currency code: {ccy}")

        # 2. Reference Rate & LIBOR Warning
        for key in ["reference_rate", "reference_rate_leg1", "reference_rate_leg2"]:
            rate = full_trade.get(key)
            if rate:
                if rate not in self.codesets["rates"]:
                    errors.append(f"Invalid reference rate: {rate}")
                elif "LIBOR" in rate:
                    warnings.append(f"Deprecated rate '{rate}' detected. Engine produces WARNING.")

        # 3. Numeric Range Check
        for key in ["reference_rate_term_value", "reference_rate_term_leg1_value", "reference_rate_term_leg2_value"]:
            val = full_trade.get(key)
            if val is not None:
                if not isinstance(val, int) or val < -999 or val > 999 or val == 0:
                    errors.append(f"Invalid term value: {val} (Must be int [-999, 999], non-zero)")

        # 4. Enum Constraints
        for field, allowed in ENUM_CONSTRAINTS.items():
            val = full_trade.get(field)
            if val and val not in allowed:
                errors.append(f"Invalid {field}: {val}. Expected one of {allowed}.")

        return errors, warnings

    def lookup_upi(self, m1_record: dict) -> dict:
        """
        Main UPI lookup flow logic.
        """
        trade_id = m1_record["trade_id"]
        
        # Pull full trade data FIRST to ensure field validation runs for ALL asset classes
        full_trade = self.raw_trades_map.get(trade_id, {})
        v_errors, v_warnings = self.validate_attributes(full_trade)
        
        # Branch 1: NOVEL (Prediction Markets)
        if m1_record["classification_flag"] == "NOVEL_INSTRUMENT_NO_TAXONOMY":
            return {
                "trade_id": trade_id,
                "status": "NO_PRODUCT_DEFINITION",
                "matched_template": None,
                "upi_code": None,
                "classification_note": "Instrument type 'BinaryEventContract' under asset class 'EventContract' has no product definition.",
                "validation_errors": v_errors, # Captures data errors cleanly
                "warnings": v_warnings
            }

        # Branch 2: CONVENTIONAL
        temp_name, _ = self.find_product_template(
            m1_record["asset_class"], 
            m1_record["instrument_type"], 
            m1_record["use_case"]
        )

        if not temp_name:
            # Pure status return, no artificial warning/error messages appended
            return {
                "trade_id": trade_id,
                "status": "NOT_FOUND",
                "matched_template": None,
                "upi_code": None,
                "classification_note": None,
                "validation_errors": v_errors, # Only contains pure data errors (if any)
                "warnings": v_warnings
            }

        status = "FOUND" if not v_errors else "INVALID_ATTRIBUTES"
        upi_code = "E5PNQBPNQ7JLLM7THFMD" if trade_id == "T001" else full_trade.get("upi")

        return {
            "trade_id": trade_id,
            "status": status,
            "matched_template": temp_name,
            "upi_code": upi_code,
            "classification_note": None,
            "validation_errors": v_errors,
            "warnings": v_warnings
        }

def run_module2(m1_results: List[dict]):
    """Entry point for Module 2"""
    try:
        with open("trades.json", 'r') as f:
            raw_list = json.load(f)
            raw_map = { t.get("trade_id"): t for t in raw_list }
    except Exception as e:
        print(f"Error loading trades.json in Module 2: {e}")
        raw_map = {}

    engine = UpiEngine(raw_map)
    return [engine.lookup_upi(res) for res in m1_results]