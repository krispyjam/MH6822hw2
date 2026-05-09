# OTC Derivatives Compliance Engine (NTU MH6822)

This repository contains an automated RegTech engine designed to validate OTC derivative trades against ANNA-DSB product definitions and regulatory requirements for CFTC and EMIR regimes.

## Project Structure
- `src/`: Core logic modules (Parser, UPI Engine, Compliance Checker).
- `data/product_definitions/`: Local copy of ANNA-DSB product definition files.
- `trades.json`: Input file containing raw trade data.
- `run_compliance_check.py`: Main entry point for the engine.
- `output_m1_parsed_trades.json`: Parsed CDE fields output.
- `output_m2_upi_templates.json`: UPI matching and template lookup output.
- `output_m3_final_report.json`: Final compliance and regulatory audit report.

## Prerequisites
- Python 3.8+

## Installation and Execution

1. **Install Dependencies**:
   Ensure you are in a clean environment and run:
   ```bash
   pip install -r requirements.txt
2. **Run the Engine**:
    Execute the compliance check for specified regimes:
   ```bash
   python run_compliance_check.py --input trades.json --regimes CFTC,EMIR