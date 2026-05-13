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
        if not value or str(value).strip().upper() == "MISSING_LEI" or str(value).strip() == "":
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
        Validates CDE fields shared across regimes. Includes passing down pure M2 field errors.
        """
        findings = []
        
        # Directly import true field validation errors from Module 2
        if "validation_errors" in m2_res and m2_res["validation_errors"]:
            findings.extend(m2_res["validation_errors"])
        
        # 1. UPI Requirement (Skip for EventContract as per regulatory exclusion)
        if raw_trade.get("asset_class") != "EventContract":
            if not raw_trade.get("upi") and not m2_res.get("upi_code"):
                findings.append("Compliance Violation: UPI is mandatory and missing")

        # 2. Date Validation (Only validate if fields exist to avoid False Positives for EventContracts)
        for f in ["effective_date", "maturity_date"]:
            val = raw_trade.get(f)
            if val is not None:
                if val == "9999-99-99" or str(val).strip() == "":
                    findings.append(f"Invalid {f}: {val}")
                else:
                    try:
                        datetime.strptime(str(val), "%Y-%m-%d")
                    except ValueError:
                        findings.append(f"Malformed {f}: {val}")

        # Date Chronology (Only if both fields are present and valid)
        eff, mat = raw_trade.get("effective_date"), raw_trade.get("maturity_date")
        if all([eff, mat]) and eff != "9999-99-99" and mat != "9999-99-99":
            try:
                if datetime.strptime(str(mat), "%Y-%m-%d") <= datetime.strptime(str(eff), "%Y-%m-%d"):
                    findings.append("maturity_date must be after effective_date")
            except (ValueError, TypeError): pass

        # 3. Notional Amount Check
        amt = raw_trade.get("notional_amount")
        leg1 = raw_trade.get("notional_amount_leg1")
        leg2 = raw_trade.get("notional_amount_leg2")

        has_valid_single = isinstance(amt, (int, float)) and amt > 0
        has_valid_legs = (isinstance(leg1, (int, float)) and leg1 > 0) and \
                         (isinstance(leg2, (int, float)) and leg2 > 0)

        if not (has_valid_single or has_valid_legs):
            findings.append(f"Invalid notional_amount logic: amt={amt}, leg1={leg1}, leg2={leg2}")

        # 4. Format checks
        if "action_type" in raw_trade and not isinstance(raw_trade.get("action_type"), str):
            findings.append("action_type must be a string")
        if "cleared" in raw_trade and not isinstance(raw_trade.get("cleared"), bool):
            findings.append("cleared must be boolean")
            
        return findings

    def check_cftc_compliance(self, m2_res: dict, raw_trade: dict, id_errors: List[str]) -> Dict:
        """Evaluates compliance against CFTC rules for conventional and novel assets."""
        findings = id_errors.copy()
        
        common_findings = self._get_common_logic_findings(raw_trade, m2_res)
        findings.extend(common_findings)
        
        if raw_trade.get("asset_class") == "EventContract":
            platform = raw_trade.get("platform_type")
            if platform == "DECENTRALISED_BLOCKCHAIN_PLATFORM":
                status = "NOT_APPLICABLE"
                findings.append("Not a CFTC DCM")
                # Special check for retail participants on blockchain (missing LEI)
                rep_lei = str(raw_trade.get("reporting_counterparty_lei") or "").upper()
                if not rep_lei or rep_lei in ["MISSING_LEI", "NONE", ""]:
                    findings.append("Missing LEI (Retail participants on blockchain platforms)")
            elif platform == "CFTC_REGULATED_DCM":
                status = "CONDITIONAL"
            else:
                status = "NONCOMPLIANT"
                findings.append(f"Unknown Platform Type: {platform}")
            
            return {"status": status, "findings": list(set(findings))}
        
        return {"status": "NONCOMPLIANT" if findings else "COMPLIANT", "findings": list(set(findings))}

    def check_emir_compliance(self, m2_res: dict, raw_trade: dict, id_errors: List[str]) -> Dict:
        """Evaluates compliance against EMIR rules."""
        findings = id_errors.copy()
        
        common_findings = self._get_common_logic_findings(raw_trade, m2_res)
        findings.extend(common_findings)
        
        if raw_trade.get("asset_class") == "EventContract":
            return {"status": "NOT_APPLICABLE", "findings": list(set(findings))}

        # EMIR Portfolio Code Validation
        p_code = str(raw_trade.get("collateral_portfolio_code") or "")
        if not re.match(r"^PORT-[A-Z0-9]{4}$", p_code):
            findings.append(f"EMIR Violation: Invalid portfolio code format '{p_code}'")

        # EMIR Margin Trap Validation
        for field in ["initial_margin_posted", "variation_margin_posted"]:
            if raw_trade.get(field) is None:
                findings.append(f"EMIR Violation: {field} cannot be null.")

        return {"status": "NONCOMPLIANT" if findings else "COMPLIANT", "findings": list(set(findings))}

    def run_compliance_check(self) -> List[dict]:
        """Main execution loop auditing identifiers and regulatory status."""
        results = []
        for tid, m2_res in self.m2_results.items():
            raw_trade = self.raw_map.get(tid, {})
            rep_lei = str(raw_trade.get("reporting_counterparty_lei") or "")
            oth_lei = str(raw_trade.get("other_counterparty_lei") or "")
            
            # Identifier audit (Always run for all trades to ensure LEI detection)
            lei_rep_ok, lei_rep_err = self.validate_lei(rep_lei, "reporting")
            lei_oth_ok, lei_oth_err = self.validate_lei(oth_lei, "other")
            uti_ok, uti_err = self.validate_uti(raw_trade.get("uti"), rep_lei)

            id_errors = [e for e in [lei_rep_err, lei_oth_err, uti_err] if e]
            
            # For EventContract, UTI is not applicable per taxonomy
            if raw_trade.get("asset_class") == "EventContract":
                uti_status = "NOT_APPLICABLE"
                # Filter out UTI errors from findings for EventContracts
                id_errors = [e for e in id_errors if "UTI" not in e]
            else:
                uti_status = "VALID" if uti_ok else "INVALID"

            lei_status = "VALID" if (lei_rep_ok and lei_oth_ok) else "INVALID"

            cftc_res = self.check_cftc_compliance(m2_res, raw_trade, id_errors)
            emir_res = self.check_emir_compliance(m2_res, raw_trade, id_errors)

            results.append({
                "trade_id": tid,
                "lei_validation": lei_status,
                "uti_validation": uti_status,
                "regime_compliance": {"CFTC": cftc_res, "EMIR": emir_res},
                "overall_compliance": "MATCH" if cftc_res["status"] == emir_res["status"] else "ASYMMETRY"
            })
        return results

def run_module3(m2_output: List[dict]):
    checker = ComplianceChecker(m2_output)
    return checker.run_compliance_check()