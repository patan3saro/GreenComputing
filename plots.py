import os
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
from datetime import datetime
import shutil

def setup_figure_dirs(metric):
    base_dir = "figures"
    os.makedirs(base_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    date_dir = os.path.join(base_dir, date_str)
    os.makedirs(date_dir, exist_ok=True)

    metric_dir = os.path.join(date_dir, metric)
    if os.path.exists(metric_dir):
        shutil.rmtree(metric_dir)  # Cancella solo la sottocartella della metrica
    os.makedirs(metric_dir)

    return metric_dir


def parse_alloc_times(file_path, metric="offloading_time"):
    values = []
    try:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    for assignment in data.get("assignments", []):
                        if metric == "energy":
                            val = assignment.get("details", {}).get("other", {}).get("energies", {}).get("total_energy")
                        else:
                            val = assignment.get("details", {}).get("offloading_time")
                        if isinstance(val, (int, float)):
                            values.append(val)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return values

def parse_real_times(file_path, metric="offloading_time"):
    values = []
    try:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    for entry in data.get("details", []):
                        if metric == "energy":
                            val = entry.get("other", {}).get("energies", {}).get("total_energy")
                        else:
                            val = entry.get("other", {}).get("offloading_time")
                        if isinstance(val, (int, float)):
                            values.append(val)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return values

def parse_total_utilities(file_path):
    values = []
    try:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    total = sum(a.get("details", {}).get("utility", 0) for a in data.get("assignments", []))
                    values.append(total)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return values

def analyze_parameter(base_dir, parameter, metric="offloading_time"):
    param_path = os.path.join(base_dir, parameter)
    results = []

    if not os.path.exists(param_path):
        print(f"[ERROR] Parametro '{parameter}' non trovato in {base_dir}")
        return pd.DataFrame()

    for val_folder in sorted(os.listdir(param_path)):
        val_path = os.path.join(param_path, val_folder)
        if not os.path.isdir(val_path):
            continue

        val_str = val_folder.replace("val_", "").replace("_", ".")
        try:
            value = float(val_str)
        except ValueError:
            print(f"[SKIP] Cartella ignorata: {val_folder}")
            continue

        print(f"[INFO] Elaboro {parameter} = {value}")

        alloc_means = []
        real_means = []

        for seed_folder in os.listdir(val_path):
            seed_path = os.path.join(val_path, seed_folder)
            if not os.path.isdir(seed_path):
                continue

            alloc_file = os.path.join(seed_path, "allocations.txt")
            real_file = os.path.join(seed_path, "realization.txt")

            if metric == "vs_utility":
                alloc_times = parse_total_utilities(alloc_file)
                real_times = []
            else:
                alloc_times = parse_alloc_times(alloc_file, metric)
                real_times = parse_real_times(real_file, metric)

            if alloc_times:
                alloc_means.append(np.mean(alloc_times))
            if real_times:
                real_means.append(np.mean(real_times))

        if alloc_means or real_means:
            alloc_mean = np.mean(alloc_means) if alloc_means else None
            alloc_ci = stats.t.interval(0.95, len(alloc_means)-1, loc=alloc_mean, scale=stats.sem(alloc_means)) if len(alloc_means) > 1 else (None, None)

            real_mean = np.mean(real_means) if real_means else None
            real_ci = stats.t.interval(0.95, len(real_means)-1, loc=real_mean, scale=stats.sem(real_means)) if len(real_means) > 1 else (None, None)

            results.append({
                "value": value,
                "alloc_mean": alloc_mean,
                "alloc_ci_low": alloc_ci[0],
                "alloc_ci_high": alloc_ci[1],
                "real_mean": real_mean,
                "real_ci_low": real_ci[0],
                "real_ci_high": real_ci[1]
            })
        else:
            print(f"[WARN] Nessun dato utile per {val_folder}")

    if not results:
        print("[ERROR] Nessun risultato aggregato disponibile.")
        return pd.DataFrame()

    return pd.DataFrame(results).sort_values(by="value")

def plot_results(df, parameter, metric, output_dir):
    df = df.dropna(subset=["alloc_mean", "real_mean"], how='all')

    if metric == "energy":
        ylabel = "Average Energy Consumption (J)"
        title_metric = "Energy Consumption"
    elif metric == "vs_utility":
        ylabel = "v(S)"
        title_metric = "Total Utility"
    else:
        ylabel = "Average Offloading Time (s)"
        title_metric = "Offloading Time"

    plt.figure(figsize=(10, 6))
    if df["alloc_mean"].notna().any():
        plt.plot(df["value"], df["alloc_mean"], label="Allocations", marker="o", color="blue")
        plt.fill_between(df["value"], df["alloc_ci_low"], df["alloc_ci_high"], alpha=0.2, color="blue")
    if df["real_mean"].notna().any():
        plt.plot(df["value"], df["real_mean"], label="Realizations", marker="o", color="green")
        plt.fill_between(df["value"], df["real_ci_low"], df["real_ci_high"], alpha=0.2, color="green")
    plt.xlabel(parameter)
    plt.ylabel(ylabel)
    plt.title(f"{title_metric} vs {parameter}")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    filename = os.path.join(output_dir, f"{metric}_vs_{parameter}.png")
    plt.savefig(filename)
    print(f"[INFO] Grafico salvato: {filename}")
    plt.show()

    plt.figure(figsize=(10, 6))
    plt.yscale("log")
    if df["alloc_mean"].notna().any():
        plt.plot(df["value"], df["alloc_mean"], label="Allocations", marker="o", color="blue")
        plt.fill_between(df["value"], df["alloc_ci_low"], df["alloc_ci_high"], alpha=0.2, color="blue")
    if df["real_mean"].notna().any():
        plt.plot(df["value"], df["real_mean"], label="Realizations", marker="o", color="green")
        plt.fill_between(df["value"], df["real_ci_low"], df["real_ci_high"], alpha=0.2, color="green")
    plt.xlabel(parameter)
    plt.ylabel("Log(" + ylabel + ")")
    plt.title(f"Log {title_metric} vs {parameter}")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    log_filename = os.path.join(output_dir, f"log_{metric}_vs_{parameter}.png")
    plt.savefig(log_filename)
    print(f"[INFO] Grafico logaritmico salvato: {log_filename}")
    plt.show()

def plot_bar_comparison(df, parameter, metric, output_dir):
    df = df.dropna(subset=["alloc_mean", "real_mean"], how='all')
    bar_width = 0.35
    indices = np.arange(len(df))

    if metric == "energy":
        ylabel = "Average Energy Consumption (J)"
        title_metric = "Energy Consumption"
    elif metric == "vs_utility":
        ylabel = "v(S)"
        title_metric = "Total Utility"
    else:
        ylabel = "Average Offloading Time (s)"
        title_metric = "Offloading Time"

    def bar_plot(log=False):
        fig, ax = plt.subplots(figsize=(10, 6))
        if log:
            ax.set_yscale("log")
        if df["alloc_mean"].notna().any():
            ax.bar(indices - bar_width/2, df["alloc_mean"], bar_width, label="Allocations", yerr=[
                df["alloc_mean"] - df["alloc_ci_low"],
                df["alloc_ci_high"] - df["alloc_mean"]
            ], capsize=5, color='blue')
        if df["real_mean"].notna().any():
            ax.bar(indices + bar_width/2, df["real_mean"], bar_width, label="Realizations", yerr=[
                df["real_mean"] - df["real_ci_low"],
                df["real_ci_high"] - df["real_mean"]
            ], capsize=5, color='green')
        ax.set_xlabel(parameter)
        ax.set_ylabel(ylabel + (" (log scale)" if log else ""))
        ax.set_title(f"{'Log ' if log else ''}{title_metric} Comparison vs {parameter}")
        ax.set_xticks(indices)
        ax.set_xticklabels([str(v) for v in df["value"]])
        ax.legend()
        ax.grid(True)
        fig.tight_layout()
        filename = os.path.join(output_dir, f"{'log_' if log else ''}{metric}_bar_vs_{parameter}.png")
        plt.savefig(filename)
        print(f"[INFO] Grafico a barre{' logaritmico' if log else ''} salvato: {filename}")
        plt.show()

    bar_plot(log=False)
    bar_plot(log=True)

def parse_success_rates(alloc_path, real_path):
    try:
        with open(alloc_path) as f_alloc, open(real_path) as f_real:
            alloc_lines = f_alloc.readlines()
            real_lines = f_real.readlines()
            alloc_counts = [len(json.loads(line).get("assignments", [])) for line in alloc_lines]
            real_counts = [len(json.loads(line).get("details", [])) for line in real_lines]
            return [r / a if a > 0 else 0 for r, a in zip(real_counts, alloc_counts)]
    except:
        return []

def analyze_realization_rates(base_dir):
    results = []
    for param in sorted(os.listdir(base_dir)):
        param_path = os.path.join(base_dir, param)
        if not os.path.isdir(param_path):
            continue
        for val in sorted(os.listdir(param_path)):
            val_path = os.path.join(param_path, val)
            try:
                val_f = float(val.replace("val_", "").replace("_", "."))
            except:
                continue
            rates = []
            for seed in os.listdir(val_path):
                seed_path = os.path.join(val_path, seed)
                alloc = os.path.join(seed_path, "allocations.txt")
                real = os.path.join(seed_path, "realization.txt")
                rates.extend(parse_success_rates(alloc, real))
            if rates:
                mean = np.mean(rates)
                ci = stats.t.interval(0.95, len(rates)-1, loc=mean, scale=stats.sem(rates)) if len(rates) > 1 else (None, None)
                results.append({
                    "parameter": param,
                    "value": val_f,
                    "realization_mean": mean,
                    "realization_ci_low": ci[0],
                    "realization_ci_high": ci[1],
                    "failure_mean": 1 - mean,
                    "failure_ci_low": 1 - ci[1] if ci[1] else None,
                    "failure_ci_high": 1 - ci[0] if ci[0] else None,
                })
    return pd.DataFrame(results)

def plot_realization_failure(df, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for param, group in df.groupby("parameter"):
        group = group.sort_values("value")
        x = np.arange(len(group))
        width = 0.5

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x, group["realization_mean"], width, label="Realized", color="green",
               yerr=[group["realization_mean"] - group["realization_ci_low"],
                     group["realization_ci_high"] - group["realization_mean"]], capsize=5)
        ax.bar(x, group["failure_mean"], width, bottom=group["realization_mean"], label="Failed", color="red",
               yerr=[group["failure_mean"] - group["failure_ci_low"],
                     group["failure_ci_high"] - group["failure_mean"]], capsize=5)
        ax.set_xticks(x)
        ax.set_xticklabels([str(v) for v in group["value"]])
        ax.set_xlabel(param)
        ax.set_ylabel("Task Percentages")
        ax.set_title(f"Task Realization vs Failure - {param}")
        ax.legend()
        ax.grid(True)
        fig.tight_layout()
        plt.savefig(os.path.join(output_dir, f"failures_vs_{param}.png"))
        plt.close()


import os
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
from datetime import datetime
import shutil

def setup_figure_dirs(metric):
    base_dir = "figures"
    os.makedirs(base_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    date_dir = os.path.join(base_dir, date_str)
    os.makedirs(date_dir, exist_ok=True)
    metric_dir = os.path.join(date_dir, metric)
    if os.path.exists(metric_dir):
        shutil.rmtree(metric_dir)
    os.makedirs(metric_dir)
    return metric_dir

def analyze_failure_components(base_dir):
    results = []
    for param in sorted(os.listdir(base_dir)):
        param_path = os.path.join(base_dir, param)
        if not os.path.isdir(param_path):
            continue
        for val_folder in sorted(os.listdir(param_path)):
            val_path = os.path.join(param_path, val_folder)
            try:
                val_f = float(val_folder.replace("val_", "").replace("_", "."))
            except:
                continue
            failed_all = []
            failed_alloc = []
            not_allocated = []
            for seed_folder in os.listdir(val_path):
                seed_path = os.path.join(val_path, seed_folder)
                if not os.path.isdir(seed_path):
                    continue
                try:
                    tasks_df = pd.read_csv(os.path.join(seed_path, "tasks.csv"))
                    with open(os.path.join(seed_path, "allocations.txt")) as f:
                        alloc_ids = {a["task"]["id"] for line in f for a in json.loads(line).get("assignments", [])}
                    with open(os.path.join(seed_path, "realization.txt")) as f:
                        real_ids = {d["task"]["task"]["id"] for line in f for d in json.loads(line).get("details", [])}
                    all_ids = set(tasks_df["id"])
                    failed = all_ids - real_ids
                    alloc_failed = alloc_ids - real_ids
                    not_alloc = all_ids - alloc_ids
                    failed_all.append(len(failed))
                    failed_alloc.append(len(alloc_failed))
                    not_allocated.append(len(not_alloc))
                except:
                    continue
            if failed_all:
                results.append({
                    "parameter": param,
                    "value": val_f,
                    "failed_total_mean": np.mean(failed_all),
                    "failed_total_ci": stats.sem(failed_all) * stats.t.ppf(0.975, len(failed_all)-1) if len(failed_all) > 1 else 0,
                    "failed_alloc_mean": np.mean(failed_alloc),
                    "not_allocated_mean": np.mean(not_allocated)
                })
    return pd.DataFrame(results)

def plot_failure_composition(df, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for param, group in df.groupby("parameter"):
        group = group.sort_values("value")
        x = np.arange(len(group))
        width = 0.3
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x - width / 2, group["not_allocated_mean"], width, label="Not Allocated", color="gray")
        ax.bar(x - width / 2, group["failed_alloc_mean"], width, bottom=group["not_allocated_mean"], label="Allocated but Failed", color="orange")
        ax.bar(x + width / 2, group["failed_total_mean"], width, label="Total Failures", edgecolor="black", fill=False, hatch="///", alpha=0.7)
        ax.set_xticks(x)
        ax.set_xticklabels([str(v) for v in group["value"]])
        ax.set_xlabel(param)
        ax.set_ylabel("Avg Number of Tasks")
        ax.set_title(f"Failure Composition - {param}")
        ax.legend()
        ax.grid(True)
        fig.tight_layout()
        out_path = os.path.join(output_dir, f"failure_composition_{param}.png")
        plt.savefig(out_path)
        print(f"[INFO] Grafico salvato: {out_path}")
        plt.close()


if __name__ == "__main__":
    root = "results_simplified"
    print("Seleziona la metrica da analizzare:")
    print("1. Tempo di offloading")
    print("2. Consumo energetico")
    print("3. Utility Totale v(S)")
    print("4. Composizione dei Task Falliti")
    scelta = input("Inserisci 1, 2, 3 o 4: ").strip()

    if scelta == "4":
        metric = "failure_composition"
        all_dates = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
        if not all_dates:
            print("[FATAL] Nessuna cartella trovata in results_simplified/")
            exit(1)
        latest = sorted(all_dates, reverse=True)[0]
        base_dir = os.path.join(root, latest)
        output_dir = setup_figure_dirs(metric)
        df = analyze_failure_components(base_dir)
        if not df.empty:
            df.to_csv(os.path.join(output_dir, "failure_composition_summary.csv"), index=False)
            plot_failure_composition(df, output_dir)
            print(f"[INFO] CSV e grafici salvati in {output_dir}")
        else:
            print("[WARN] Nessun dato disponibile.")
    elif scelta in {"1", "2", "3"}:
        if scelta == "1":
            metric = "offloading_time"
        elif scelta == "2":
            metric = "energy"
        elif scelta == "3":
            metric = "vs_utility"

        all_dates = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
        if not all_dates:
            print("[FATAL] Nessuna cartella trovata in results_simplified/")
            exit(1)

        latest = sorted(all_dates, reverse=True)[0]
        base_dir = os.path.join(root, latest)
        output_dir = setup_figure_dirs(metric)

        for parameter in sorted(os.listdir(base_dir)):
            param_path = os.path.join(base_dir, parameter)
            if not os.path.isdir(param_path):
                continue

            df = analyze_parameter(base_dir, parameter, metric=metric)
            print(df)

            if not df.empty:
                csv_file = os.path.join(output_dir, f"{metric}_{parameter}.csv")
                df.to_csv(csv_file, index=False)
                print(f"[INFO] CSV salvato: {csv_file}")
                plot_results(df, parameter, metric=metric, output_dir=output_dir)
                plot_bar_comparison(df, parameter, metric=metric, output_dir=output_dir)
    else:
        print("[ERRORE] Scelta non valida. Uscita.")
        exit(1)

