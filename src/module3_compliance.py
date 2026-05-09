import re
import json
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from stdnum.iso7064 import mod_97_10

class ComplianceChecker:
    def __init__(self, m2_results: List[dict], trades_path: str = "trades.json"):
        """
        Initializes the compliance engine with Module 2 results and raw trade data.
        Bridges the gap using trade_id to access fields not present in the UPI template.
        """
        self.m2_results = {res['trade_id']: res for res in m2_results}
        self.today = datetime.now().date()
        try:
            with open(trades_path, 'r') as f:
                self.raw_map = {t['trade_id']: t for t in json.load(f)}
        except Exception as e:
            print(f"Error loading trades in M3: {e}")
            self.raw_map = {}

    def validate_lei(self, value: Optional[str], label: str) -> Tuple[bool, str]:
        """
        Validates LEI check digits using ISO 7064 MOD 97-10.
        Specific labeling identifies if the error belongs to Reporting or Other counterparty.
        """
        if not value or str(value).strip().upper() == "MISSING_LEI":
            return False, f"{label} LEI is missing or placeholder"
        
        lei_str = str(value).strip().upper()
        if len(lei_str) != 20:
            return False, f"{label} LEI length error: {len(lei_str)}"
        
        if mod_97_10.is_valid(lei_str):
            return True, ""
        else:
            return False, f"Invalid {label} counterparty LEI check digits: {lei_str}"

    def validate_uti(self, uti: Optional[str], reporting_lei: str) -> Tuple[bool, str]:
        """
        Validates UTI according to ISO 23897.
        Ensures the namespace (first 20 chars) matches the cleaned Reporting LEI.
        """
        if not uti:
            return False, "UTI is missing or null"
        
        uti_str = str(uti).strip().upper()
        clean_rep_lei = str(reporting_lei).strip().upper()
        
        if len(uti_str) > 52:
            return False, f"UTI length {len(uti_str)} exceeds 52 characters"
        
        if not uti_str.startswith(clean_rep_lei):
            return False, f"UTI namespace mismatch: must start with reporting LEI {clean_rep_lei}"
        
        suffix = uti_str[20:]
        if not re.match(r"^[A-Z0-9-]*$", suffix):
            return False, "UTI suffix contains invalid characters"
        return True, ""

    def _get_common_logic_findings(self, raw_trade: dict, m2_res: dict) -> List[str]:
        """
        Validates CDE fields shared across regimes.
        Enhanced for Swaps (T011) to check both notional legs if single amount is missing.
        """
        findings = []
        
        # 1. UPI Requirement
        if not raw_trade.get("upi") and not m2_res.get("upi_code"):
            findings.append("Compliance Violation: UPI is mandatory and missing")

        # 2. Date Validation (Future effective dates allowed, no placeholders)
        for f in ["effective_date", "maturity_date"]:
            val = raw_trade.get(f)
            if not val or val == "9999-99-99":
                findings.append(f"Invalid {f}: {val}")
            else:
                try:
                    datetime.strptime(str(val), "%Y-%m-%d")
                except ValueError:
                    findings.append(f"Malformed {f}: {val}")

        # Date Chronology
        eff, mat = raw_trade.get("effective_date"), raw_trade.get("maturity_date")
        if eff and mat and eff != "9999-99-99" and mat != "9999-99-99":
            try:
                if datetime.strptime(str(mat), "%Y-%m-%d") <= datetime.strptime(str(eff), "%Y-%m-%d"):
                    findings.append("maturity_date must be after effective_date")
            except ValueError: pass

        # 3. Notional Amount Check (Enhanced for T011 Legs)
        amt = raw_trade.get("notional_amount")
        leg1 = raw_trade.get("notional_amount_leg1")
        leg2 = raw_trade.get("notional_amount_leg2")

        # Logic: Valid if (amt > 0) OR (leg1 > 0 AND leg2 > 0)
        has_valid_single = isinstance(amt, (int, float)) and amt > 0
        has_valid_legs = (isinstance(leg1, (int, float)) and leg1 > 0) and \
                         (isinstance(leg2, (int, float)) and leg2 > 0)

        if not (has_valid_single or has_valid_legs):
            findings.append(f"Invalid notional_amount logic: amt={amt}, leg1={leg1}, leg2={leg2}")

        # 4. Format checks
        if not isinstance(raw_trade.get("action_type"), str):
            findings.append("action_type must be a string")
        if not isinstance(raw_trade.get("cleared"), bool):
            findings.append("cleared must be boolean")
            
        return findings

    def check_cftc_compliance(self, m2_res: dict, raw_trade: dict, id_errors: List[str]) -> Dict:
        """Evaluates compliance against CFTC rules for conventional/novel assets."""
        findings = id_errors.copy()
        if raw_trade.get("asset_class") == "EventContract":
            return {"status": "CONDITIONAL", "findings": ["CFTC: EventContract requires DCM conditional reporting."]}
        
        findings.extend(self._get_common_logic_findings(raw_trade, m2_res))
        return {"status": "NONCOMPLIANT" if findings else "COMPLIANT", "findings": findings}

    def check_emir_compliance(self, m2_res: dict, raw_trade: dict, id_errors: List[str]) -> Dict:
        """Evaluates compliance against EMIR rules, specifically the Margin Trap."""
        findings = id_errors.copy()
        if raw_trade.get("asset_class") == "EventContract":
            return {"status": "NOT_APPLICABLE", "findings": ["EMIR: Not applicable (GlüStV 2021)."]}

        findings.extend(self._get_common_logic_findings(raw_trade, m2_res))

        # EMIR Portfolio Code (Regex PORT-XXXX)
        p_code = str(raw_trade.get("collateral_portfolio_code") or "")
        if not re.match(r"^PORT-[A-Z0-9]{4}$", p_code):
            findings.append(f"EMIR Violation: Invalid portfolio code format '{p_code}'")

        # EMIR Margin Trap: Null is a reporting violation
        for field in ["initial_margin_posted", "variation_margin_posted"]:
            if raw_trade.get(field) is None:
                findings.append(f"EMIR Violation: {field} cannot be null.")

        return {"status": "NONCOMPLIANT" if findings else "COMPLIANT", "findings": findings}

    def run_compliance_check(self) -> List[dict]:
        """Main execution loop for all trades provided by Module 2."""
        results = []
        for tid, m2_res in self.m2_results.items():
            raw_trade = self.raw_map.get(tid, {})
            rep_lei = str(raw_trade.get("reporting_counterparty_lei") or "")
            oth_lei = str(raw_trade.get("other_counterparty_lei") or "")

            # Precise identifier audit
            lei_rep_ok, lei_rep_err = self.validate_lei(rep_lei, "reporting")
            lei_oth_ok, lei_oth_err = self.validate_lei(oth_lei, "other")
            uti_ok, uti_err = self.validate_uti(raw_trade.get("uti"), rep_lei)

            id_errors = [e for e in [lei_rep_err, lei_oth_err, uti_err] if e]
            cftc_res = self.check_cftc_compliance(m2_res, raw_trade, id_errors)
            emir_res = self.check_emir_compliance(m2_res, raw_trade, id_errors)

            results.append({
                "trade_id": tid,
                "lei_validation": "VALID" if (lei_rep_ok and lei_oth_ok) else "INVALID",
                "uti_validation": "VALID" if uti_ok else "INVALID",
                "regime_compliance": {"CFTC": cftc_res, "EMIR": emir_res},
                "overall_compliance": "MATCH" if cftc_res["status"] == emir_res["status"] else "ASYMMETRY"
            })
        return results

def run_module3(m2_output: List[dict]):
    checker = ComplianceChecker(m2_output)
    return checker.run_compliance_check()