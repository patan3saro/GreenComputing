from __future__ import annotations

from pathlib import Path
import sys

# ---------------------------------------------------------------
# Config utente (solo queste tre costanti!)
# ---------------------------------------------------------------
TRACE_PATH = Path(r"C:\Users\Controllo\PycharmProjects\GreenComputing\sumo_rome\trace.xml")
SAVE: bool = True                              # False → solo anteprima a schermo
SAVE_FILENAME = "animation.mp4"               # ".mp4" oppure ".gif"
FPS = 25                                       # fotogrammi al secondo
# ---------------------------------------------------------------

# Se vuoi forzare sempre GIF (anche se hai ffmpeg) metti SAVE_FILENAME = "animation.gif"

# ---------------------------------------------------------------
#        Da qui in giù non serve modificare nulla
# ---------------------------------------------------------------
import matplotlib

# Imposta il backend PRIMA di importare pyplot (obbligatorio)
try:
    matplotlib.use("TkAgg", force=True)  # ideale su Windows desktop
except Exception:
    matplotlib.use("Agg", force=True)    # fallback headless

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter, writers


def load_trace(filepath: Path) -> pd.DataFrame:
    """Carica il file di traccia in un DataFrame."""
    if filepath.suffix.lower() == ".csv":
        df = pd.read_csv(filepath)
    elif filepath.suffix.lower() in {".xml", ".xml.gz"}:
        try:
            from mobility_manager import extract_trace_dataframe  # type: ignore
        except ImportError as exc:
            raise SystemExit(
                "mobility_manager non trovato; aggiungilo al PYTHONPATH oppure converti prima l'XML in CSV."
            ) from exc
        df = extract_trace_dataframe(filepath)
    else:
        raise SystemExit("Tipo di file non supportato (serve .xml o .csv)")

    required_cols = {"id", "position_x", "position_y", "time"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Colonne mancanti nel file di input: {', '.join(sorted(missing))}")

    return df


def _save_animation(anim: FuncAnimation, outfile: Path) -> None:
    """Salva animazione gestendo MP4↔GIF e disponibilità writer."""
    suffix = outfile.suffix.lower()

    if suffix == ".mp4":
        if writers.is_available("ffmpeg"):
            anim.save(outfile, writer="ffmpeg", fps=FPS, dpi=150)
        else:
            print(
                "⚠️  ffmpeg non disponibile: sarà creata una GIF di fallback.\n"
                "    Scarica ffmpeg per Windows e aggiungilo a PATH se vuoi l'MP4."
            )
            gif_path = outfile.with_suffix(".gif")
            anim.save(gif_path, writer=PillowWriter(fps=FPS))
            print(f"Animazione salvata in {gif_path}")
            return
    elif suffix == ".gif":
        anim.save(outfile, writer=PillowWriter(fps=FPS))
    else:
        raise SystemExit("Estensione non supportata: usa .mp4 o .gif")

    print(f"Animazione salvata in {outfile}")


def animate(df: pd.DataFrame, save_file: Path | None = None) -> None:
    """Crea e (opzionalmente) salva l'animazione."""
    fig, ax = plt.subplots(figsize=(8, 8))
    scatter = ax.scatter([], [], s=10)

    ax.set_xlim(df["position_x"].min(), df["position_x"].max())
    ax.set_ylim(df["position_y"].min(), df["position_y"].max())
    ax.set_xlabel("X [m]")
    ax.set_ylabel("Y [m]")

    times = sorted(df["time"].unique())

    def update(frame_time):
        current = df[df["time"] == frame_time]
        scatter.set_offsets(current[["position_x", "position_y"]].values)
        ax.set_title(f"Posizione veicoli — t = {frame_time:.1f}s")
        return scatter,

    anim = FuncAnimation(
        fig,
        update,
        frames=times,
        blit=True,
        interval=1000 / FPS,
        repeat=False,
    )

    if save_file is not None:
        _save_animation(anim, save_file)

    plt.tight_layout()
    plt.show()


def main() -> None:  # noqa: D401
    trace_path = TRACE_PATH.expanduser().resolve()
    if not trace_path.exists():
        raise SystemExit(f"File di traccia non trovato: {trace_path}")

    df = load_trace(trace_path)

    out_path: Path | None = None
    if SAVE:
        out_path = trace_path.with_name(SAVE_FILENAME)

    animate(df, out_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
