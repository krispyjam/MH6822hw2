# run_compliance_check.py
import argparse
import json
import sys
from src import module1_parser, module2_upi_lookup, module3_compliance

def save_json(data, filename):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated: {filename}")

def main():
    parser = argparse.ArgumentParser(description="OTC Derivatives Compliance Engine")
    parser.add_argument("--input", required=True, help="Path to input trades.json")
    parser.add_argument("--regimes", required=True, help="Comma-separated regimes, e.g., CFTC,EMIR")
    
    args = parser.parse_args()

    try:
        # --- Step 1: Parser Output ---
        print("Running Module 1...")
        m1_results = module1_parser.run_module1(args.input)
        save_json(m1_results, "output_m1_parsed_trades.json")
        
        # --- Step 2: UPI Engine Output ---
        print("Running Module 2...")
        m2_results = module2_upi_lookup.run_module2(m1_results)
        save_json(m2_results, "output_m2_upi_templates.json")
        
        # --- Step 3: Compliance Checker Output (Final Report) ---
        print("Running Module 3...")
        m3_results = module3_compliance.run_module3(m2_results)
        save_json(m3_results, "output_m3_final_report.json")
            
        print("\n--- ALL MODULE OUTPUTS GENERATED SUCCESSFULLY ---")

    except Exception as e:
        print(f"Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()