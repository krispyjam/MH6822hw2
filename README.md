# OTC Derivatives Compliance Engine (NTU MH6822)

This repository contains an automated RegTech compliance engine designed to validate OTC derivative trades against ANNA-DSB product definitions and regulatory regimes (CFTC and EMIR). 

The engine processes both conventional asset classes and novel instruments (e.g., Prediction Markets / Event Contracts), demonstrating robust field validation and regime-specific logic as part of the Deliverable 1 & 2 requirements.

## Project Structure

- `src/`
  - `module1_parser.py`: Parses CDE fields and derives classification flags.
  - `module2_upi_lookup.py`: Evaluates ANNA-DSB UPI templates and enforces field constraints (ISO currencies, FpML rates, Enums).
  - `module3_compliance.py`: Final regulatory logic handling identifier audits, chronology checks, and regime-specific (CFTC/EMIR) routing.
- `data/product_definitions/`: Local repository of ANNA-DSB JSON product definitions.
- `trades.json`: The core dataset containing 35 trades (28 original + 7 custom-designed trades with intentional edge cases and traps).
- `run_compliance_check.py`: The main execution script.
- `.gitignore`: Specifies intentionally untracked files (e.g., `venv`, `__pycache__`).

### Generated Output Artifacts
Running the engine will generate a 3-stage audit trail:
1. `output_m1_parsed_trades.json`
2. `output_m2_upi_templates.json`
3. `output_m3_final_report.json`

## Key Compliance Features & Logic

- **Identifier Audits**: ISO 7064 MOD 97-10 check digits for LEIs; ISO 23897 namespace and length validation for UTIs.
- **Event Contract Handling**: Differentiates between `CFTC_REGULATED_DCM` (Conditional reporting) and `DECENTRALISED_BLOCKCHAIN_PLATFORM` (Not Applicable, flags missing LEIs for retail participants).
- **Attribute & Data Quality Rules**: Cross-references `notional_currency` against ISO standards and checks `reference_rate` against FpML codesets. Validates date chronologies (Effective Date vs. Maturity Date).
- **EMIR Specifics**: Detects EMIR "Margin Traps" (null margin values) and validates collateral portfolio codes via Regex (`^PORT-[A-Z0-9]{4}$`).
- **Comprehensive Test Coverage**: Includes intentionally malformed trades (e.g., invalid currencies, UTI namespace mismatches, incorrect dates) to demonstrate engine robustness.

## Prerequisites
- Python 3.8+
- Dependencies listed in `requirements.txt` (`pydantic`, `python-stdnum`).

## Installation and Execution

1. **Environment Setup & Installation**:
   Ensure you are in a clean environment and install required packages:
   ```bash
   pip install -r requirements.txt
2. **Run the Engine**:
    Execute the compliance check for specified regimes:
   ```bash
   python run_compliance_check.py --input trades.json --regimes CFTC,EMIR