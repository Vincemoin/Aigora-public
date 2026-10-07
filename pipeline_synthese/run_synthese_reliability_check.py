"""
Reliabilitaets-Check fuer RQ4 -- zweiter, unabhaengiger Durchlauf der
kompletten Synthese-Pipeline (Stufe A -> B -> C -> Finale Synthese) mit
IDENTISCHEM, eingefrorenem Input, um zu messen wie stabil das Ergebnis
gegenueber reiner LLM-Nichtdeterminiertheit ist (analog zu
pipeline_session2/run_reliability_check.py fuer das Clustering).

WICHTIG -- ueberschreibt NICHTS:
Die vier Pipeline-Skripte haben hartkodierte Ausgabepfade nach
data/synthese/ (die live vom Sitzung-3-View gelesenen Dateien). Dieser
Wrapper lenkt jeden Ein- und Ausgabepfad in einen frischen, zeitgestempelten
Ordner data/synthese_runs/reliability_<ts>/ um. data/synthese/ wird nur
gelesen (die eingefrorene dossiers.json wird einmal hineinkopiert) und nie
geschrieben.

Eingefrorener Input = data/synthese/dossiers.json im aktuellen Stand.
Begruendung: dossiers.json ist aus den nach Sitzungsende gesperrten
Sitzung-2-Rohdaten aggregiert und schliesst Test-Personas bereits aus;
eine Re-Aggregation waere inhaltlich identisch.

Aufruf (aus dem Repo-Wurzelverzeichnis):
    python pipeline_synthese/run_synthese_reliability_check.py
"""
import os
import sys
import json
import shutil
import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "pipeline_synthese"))
os.chdir(REPO)

TS = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
RUN_DIR = os.path.join(REPO, "data", "synthese_runs", f"reliability_{TS}")
os.makedirs(RUN_DIR, exist_ok=True)

LIVE_DOSSIERS = os.path.join(REPO, "data", "synthese", "dossiers.json")
DOSS = os.path.join(RUN_DIR, "dossiers.json")            # eingefrorener Input
FILT = os.path.join(RUN_DIR, "standpunkt_filter.json")
KAND = os.path.join(RUN_DIR, "kandidaten_final.json")
EMPF = os.path.join(RUN_DIR, "empfehlung_final.json")
ARCHIV = os.path.join(RUN_DIR, "archiv")

shutil.copy2(LIVE_DOSSIERS, DOSS)
print(f"Eingefrorener Input kopiert: {DOSS}")

import synthese_standpunkt_filter as sA
import synthese_stufe_b as sB
import synthese_stufe_c as sC
import synthese_final_synthese as sF

sA.DOSSIERS_PATH = DOSS
sA.OUTPUT_PATH = FILT
for m in (sB, sC):
    m.DOSSIERS_PATH = DOSS
    m.FILTER_PATH = FILT
sF.DOSSIERS_PATH = DOSS
sF.FILTER_PATH = FILT
sF.KANDIDATEN_OUT = KAND
sF.EMPFEHLUNG_OUT = EMPF
sF.RUNS_DIR = ARCHIV

# --- Sicherheits-Check: kein Pfad zeigt mehr auf die Live-Dateien ---
LIVE_DIR = os.path.normpath(os.path.join(REPO, "data", "synthese"))
zu_pruefen = {
    "sA.DOSSIERS_PATH": sA.DOSSIERS_PATH, "sA.OUTPUT_PATH": sA.OUTPUT_PATH,
    "sB.DOSSIERS_PATH": sB.DOSSIERS_PATH, "sB.FILTER_PATH": sB.FILTER_PATH,
    "sC.DOSSIERS_PATH": sC.DOSSIERS_PATH, "sC.FILTER_PATH": sC.FILTER_PATH,
    "sF.DOSSIERS_PATH": sF.DOSSIERS_PATH, "sF.FILTER_PATH": sF.FILTER_PATH,
    "sF.KANDIDATEN_OUT": sF.KANDIDATEN_OUT, "sF.EMPFEHLUNG_OUT": sF.EMPFEHLUNG_OUT,
    "sF.RUNS_DIR": sF.RUNS_DIR,
}
for name, pfad in zu_pruefen.items():
    voll = os.path.normpath(os.path.join(REPO, pfad))
    schreibend = name.endswith(("OUTPUT_PATH", "FILTER_PATH", "_OUT", "RUNS_DIR"))
    if schreibend and os.path.dirname(voll) == LIVE_DIR:
        raise SystemExit(f"ABBRUCH: {name} zeigt noch auf die Live-Datei {voll}")
    print(f"  {name:24s} -> {pfad}")

print("\nAlle Schreibpfade zeigen in den Reliabilitaets-Ordner. Live-Daten unangetastet.\n")

for schritt, modul in [("Stufe A (standpunkt_filter)", sA),
                       ("Stufe B (diskursgewinner)", sB),
                       ("Stufe C (substanzpruefung)", sC),
                       ("Finale Synthese", sF)]:
    print(f"\n{'='*60}\n{schritt}\n{'='*60}")
    modul.main()

meta = {
    "typ": "synthese_reliability_check",
    "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "eingefrorener_input": "data/synthese/dossiers.json (Stand des Kopierzeitpunkts)",
    "vergleich_gegen": "data/synthese/empfehlung_final.json (Live-Lauf 26.8.)",
    "modell": "claude-sonnet-5",
}
with open(os.path.join(RUN_DIR, "_meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"\n\nFERTIG. Alle Ausgaben in: {RUN_DIR}")
