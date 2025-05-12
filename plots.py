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
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
    os.makedirs(base_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_dir = os.path.join(base_dir, timestamp)
    os.makedirs(date_dir)

    metric_dir = os.path.join(date_dir, metric)
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
    ylabel = "Average Energy Consumption (J)" if metric == "energy" else "Average Offloading Time (s)"
    title_metric = "Energy Consumption" if metric == "energy" else "Offloading Time"

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
    ylabel = "Average Energy Consumption (J)" if metric == "energy" else "Average Offloading Time (s)"
    title_metric = "Energy Consumption" if metric == "energy" else "Offloading Time"

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

if __name__ == "__main__":
    root = "results_simplified"

    print("Seleziona la metrica da analizzare:")
    print("1. Tempo di offloading")
    print("2. Consumo energetico")
    scelta = input("Inserisci 1 o 2: ").strip()

    if scelta == "1":
        metric = "offloading_time"
    elif scelta == "2":
        metric = "energy"
    else:
        print("[ERRORE] Scelta non valida. Uscita.")
        exit(1)

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
