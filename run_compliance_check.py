# run_compliance_check.py
import argparse
import json
import sys
from src import module1_parser, module2_upi_lookup, module3_compliance

def main():
    # 1. Setup argument parser to handle CLI commands
    parser = argparse.ArgumentParser(description="RegTech Compliance Engine")
    parser.add_argument("--input", required=True, help="Path to input trades.json")
    parser.add_argument("--regimes", required=True, help="Comma-separated regimes, e.g., CFTC,EMIR")
    
    args = parser.parse_args()
    regimes_list = args.regimes.split(",")

    print(f"--- Running Compliance Check on {args.input} for {regimes_list} ---")

    try:
        # Phase 1: Parsing
        m1_output = module1_parser.run_module1(args.input)
        
        # Phase 2: UPI Lookup
        m2_output = module2_upi_lookup.run_module2(m1_output)
        
        # Phase 3: Compliance Audit
        m3_output = module3_compliance.run_module3(m2_output)
        
        # Save output
        output_file = "final_compliance_report.json"
        with open(output_file, "w") as f:
            json.dump(m3_output, f, indent=2)
        
        print(f"SUCCESS: Report generated as {output_file}")

    except Exception as e:
        print(f"ERROR: Pipeline failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()