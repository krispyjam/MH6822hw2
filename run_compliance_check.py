import argparse
import json
import sys
import os
import csv
from pathlib import Path

# Ensure src is in the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import module1_parser
import module2_upi_lookup
import module3_compliance
import dashboard

def save_json(data, filename):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated JSON: {filename}")

def generate_csv_report(results, filename):
    """Flatten Module 3 results into a concise CSV summary for auditing."""
    headers = ["Trade ID", "LEI Validation", "UTI Validation", "CFTC Status", "EMIR Status", "Overall Compliance", "Findings"]
    
    with open(filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for res in results:
            # Aggregate findings from both CFTC and EMIR regimes
            cftc_data = res['regime_compliance']['CFTC']
            emir_data = res['regime_compliance']['EMIR']
            all_findings = set(cftc_data.get('findings', []) + emir_data.get('findings', []))
            
            writer.writerow({
                "Trade ID": res["trade_id"],
                "LEI Validation": res["lei_validation"],
                "UTI Validation": res["uti_validation"],
                "CFTC Status": cftc_data["status"],
                "EMIR Status": emir_data["status"],
                "Overall Compliance": res["overall_compliance"],
                "Findings": "; ".join(all_findings) if all_findings else "None"
            })
    print(f"Generated CSV Audit Summary: {filename}")

def main():
    parser = argparse.ArgumentParser(description="OTC Derivatives Compliance Engine (ReguVision)")
    parser.add_argument("--input", required=True, help="Path to input trades.json")
    parser.add_argument("--regimes", required=True, help="Comma-separated regimes, e.g., CFTC,EMIR")
    
    args = parser.parse_args()

    try:
        # --- Step 1: Parser ---
        print("Running Module 1: CDE Parsing...")
        m1_results = module1_parser.run_module1(args.input)
        save_json(m1_results, "output_m1_parsed_trades.json")
        
        # --- Step 2: UPI Engine ---
        print("Running Module 2: UPI Lookup & Field Validation...")
        m2_results = module2_upi_lookup.run_module2(m1_results)
        save_json(m2_results, "output_m2_upi_templates.json")
        
        # --- Step 3: Compliance Checker ---
        print("Running Module 3: Regulatory Compliance Audit...")
        m3_results = module3_compliance.run_module3(m2_results)
        save_json(m3_results, "output_m3_final_report.json")
        
        # --- Step 4: Automatic CSV Generation ---
        generate_csv_report(m3_results, "final_compliance_summary_report.csv")
        
        # --- Step 5: Module 5 HTML Dashboard ---
        print("Running Module 5: Generating HTML Compliance Dashboard...")
        base_dir = Path(__file__).resolve().parent
        model_args = {
            "base_dir": base_dir,
            "report_name": "output_m3_final_report.json",
            "trades_name": "trades.json",
            "m2_name": "output_m2_upi_templates.json",
        }
        output_path = base_dir / "output_m5_dashboard.html"
        dashboard.export_html(output_path, model_args)
        print(f"Generated HTML Dashboard: {output_path.name}")
            
        print("\n--- ALL ARTIFACTS GENERATED SUCCESSFULLY ---")

    except Exception as e:
        print(f"Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()