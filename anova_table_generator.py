import os
import json
import pandas as pd
import statsmodels.api as sm
from statsmodels.formula.api import ols

def extract_metric_data(file_path, metric, data_type):
    data = []
    if not os.path.exists(file_path):
        return data
    with open(file_path) as f:
        for line in f:
            try:
                record = json.loads(line)
                entries = record.get("assignments", []) if "assignments" in record else record.get("details", [])
                for entry in entries:
                    if metric == "energy":
                        val = entry.get("details", {}).get("other", {}).get("energies", {}).get("total_energy") if "assignments" in record else entry.get("other", {}).get("energies", {}).get("total_energy")
                    else:
                        val = entry.get("details", {}).get("offloading_time") if "assignments" in record else entry.get("other", {}).get("offloading_time")
                    if isinstance(val, (int, float)):
                        data.append({"value": val, "type": data_type})
            except json.JSONDecodeError:
                continue
    return data

def run_split_anova(df, metric, parameter_name):
    results = []
    for group in ['alloc', 'real']:
        subset = df[df['type'] == group]
        if subset['parameter_value'].nunique() < 2:
            results.append((group, None, f"Not enough parameter variation for {group}"))
            continue
        model = ols('value ~ C(parameter_value)', data=subset).fit()
        anova_table = sm.stats.anova_lm(model, typ=2)
        results.append((group, anova_table, None))
    return results

def analyze_directory(base_path):
    for parameter in sorted(os.listdir(base_path)):
        param_path = os.path.join(base_path, parameter)
        if not os.path.isdir(param_path):
            continue

        print(f"\n### PARAMETER: {parameter}\n")

        for metric in ["offloading_time", "energy"]:
            all_data = []

            for val_folder in sorted(os.listdir(param_path)):
                val_path = os.path.join(param_path, val_folder)
                if not os.path.isdir(val_path):
                    continue
                val_str = val_folder.replace("val_", "").replace("_", ".")
                try:
                    val_float = float(val_str)
                except ValueError:
                    continue

                for seed_folder in os.listdir(val_path):
                    seed_path = os.path.join(val_path, seed_folder)
                    if not os.path.isdir(seed_path):
                        continue
                    alloc_file = os.path.join(seed_path, "allocations.txt")
                    real_file = os.path.join(seed_path, "realization.txt")
                    all_data += [
                        {**item, "parameter_value": val_float}
                        for item in extract_metric_data(alloc_file, metric, "alloc")
                    ] + [
                        {**item, "parameter_value": val_float}
                        for item in extract_metric_data(real_file, metric, "real")
                    ]

            if not all_data:
                print(f"[WARN] No data for {metric} on parameter {parameter}")
                continue

            df = pd.DataFrame(all_data)
            results = run_split_anova(df, metric, parameter)

            print(f"\n% LaTeX table for {metric} under parameter {parameter}")
            print("\\begin{table}")
            print("\\centering")
            print(f"\\caption{{ANOVA on {metric} grouped by {parameter}}}")
            print(f"\\label{{tab:anova_{metric}_{parameter}}}")
            print("\\begin{tabular}{llrrrr}")
            print("\\toprule")
            print("Group & Source & Sum Sq & df & F & PR($>$F) \\\\")
            print("\\midrule")
            for group, table, err in results:
                if table is None:
                    print(f"{group} & -- & -- & -- & -- & -- \\\\")
                else:
                    for idx, row in table.iterrows():
                        print(f"{group} & {idx} & {row['sum_sq']:.3e} & {int(row['df'])} & "
                              f"{row['F']:.3e} & {row['PR(>F)']:.3e} \\\\")
            print("\\bottomrule")
            print("\\end{tabular}")
            print("\\end{table}")


if __name__ == "__main__":
    ROOT_DIR = "results_simplified"
    all_dates = [d for d in os.listdir(ROOT_DIR) if os.path.isdir(os.path.join(ROOT_DIR, d))]
    if not all_dates:
        print("[ERROR] No experiment folders found.")
        exit(1)

    latest = sorted(all_dates, reverse=True)[0]
    base_dir = os.path.join(ROOT_DIR, latest)

    analyze_directory(base_dir)
