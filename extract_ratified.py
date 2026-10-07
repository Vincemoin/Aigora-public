"""
extract_ratified.py

Liest eine GPR-Gespraechs-Logdatei (JSON, aus gpr_v3.py oder streamlit_app.py)
und extrahiert alle <ratified>-Bloecke in eine strukturierte Form fuer den
spaeteren Clustering-Agenten. Erzeugt zwei Ausgaben:

1. Eine JSON-Datei (maschinenlesbar, fuer den Clustering-Agenten)
2. Eine Markdown-Uebersicht (fuer die manuelle Pruefung gegen den Original-Log)

WICHTIG: Der Parser ist bewusst TOLERANT gegen kleine Formatierungsfehler
(z.B. ein Anfuehrungszeichen direkt nach einem Tag-Namen), da LLM-generierte
Tags nie zu 100% garantiert perfekt sind. Alles, was trotzdem nicht geparst
werden konnte, wird explizit aufgelistet, nicht stillschweigend verworfen.

Nutzung:
    python extract_ratified.py pfad/zum/log.json
"""

import json
import re
import sys
import os
import datetime
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = "./extracted_profiles"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------
# SURFDRIVE-ZUGRIFF (neu): liest die Logs direkt aus dem aigora_logs/-
# Ordner, in den streamlit_app.py/sitzung1_view.py speichert -- kein
# manueller Download mehr noetig. Zugangsdaten kommen aus einer lokalen
# .env-Datei (SURFDRIVE_USERNAME/SURFDRIVE_PASSWORD), DIESELBEN Werte wie
# in den Streamlit-Cloud-Secrets unter [surfdrive] -- nur lokal separat
# hinterlegt, da dieses Skript ausserhalb von Streamlit laeuft und daher
# kein st.secrets zur Verfuegung hat.
# ---------------------------------------------------------------------

SURFDRIVE_LOG_FOLDER = "aigora_logs"


def _surfdrive_auth():
    username = os.environ.get("SURFDRIVE_USERNAME")
    password = os.environ.get("SURFDRIVE_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "SURFDRIVE_USERNAME/SURFDRIVE_PASSWORD fehlen. Bitte lokal in einer "
            ".env-Datei setzen (dieselben Zugangsdaten wie in den Streamlit-Cloud-"
            "Secrets unter [surfdrive])."
        )
    return HTTPBasicAuth(username, password)


def _surfdrive_base_url():
    username = os.environ.get("SURFDRIVE_USERNAME")
    return f"https://surfdrive.surf.nl/remote.php/dav/files/{username}"


def list_surfdrive_logs():
    """Listet alle Teilnehmer-Logs im aigora_logs/-Ordner auf SurfDrive
    (WebDAV PROPFIND, Tiefe 1) -- gibt sortierte Dateinamen zurueck,
    z.B. ['gpr_P-001.json', 'gpr_P-002.json', ...]."""
    url = f"{_surfdrive_base_url()}/{SURFDRIVE_LOG_FOLDER}"
    r = requests.request("PROPFIND", url, auth=_surfdrive_auth(),
                          headers={"Depth": "1"}, timeout=20)
    r.raise_for_status()
    ns = {"d": "DAV:"}
    root = ET.fromstring(r.content)
    files = []
    for resp in root.findall("d:response", ns):
        href = resp.find("d:href", ns).text
        fname = href.rstrip("/").split("/")[-1]
        if fname.endswith(".json") and fname.startswith("gpr_"):
            files.append(fname)
    return sorted(files)


def download_surfdrive_log(filename):
    """Laedt eine einzelne Log-Datei von SurfDrive als geparstes JSON."""
    url = f"{_surfdrive_base_url()}/{SURFDRIVE_LOG_FOLDER}/{filename}"
    r = requests.get(url, auth=_surfdrive_auth(), timeout=30)
    r.raise_for_status()
    return json.loads(r.text)

DIMENSION_ORDER = ["Goals", "Objectives", "Settings", "InstrumentLogic", "Tools", "Calibrations"]
DIMENSION_NAMES_DE = {
    "Goals": "Ziele",
    "Objectives": "Zwischenziele",
    "Settings": "Konkrete Anforderungen",
    "InstrumentLogic": "Umsetzungslogik",
    "Tools": "Instrumententyp",
    "Calibrations": "Feinausgestaltung",
}

# Toleranter Regex: erlaubt optionale Stör-Zeichen (z.B. ein Anfuehrungszeichen)
# direkt nach dem Tag-Namen, vor dem schliessenden ">". Genau das Muster, das
# den bekannten Fehler ("<breadth_detail\">") verursacht hat, wird hier
# aufgefangen, nicht als Fehler behandelt.
RATIFIED_PATTERN = re.compile(
    r'<ratified\s+dimension=["\']?(?P<dimension>\w+)["\']?\s*>\s*'
    r'<position>(?P<position>.*?)</position>\s*'
    r'<reasoning>(?P<reasoning>.*?)</reasoning>\s*'
    r'<breadth>(?P<breadth>.*?)</breadth>\s*'
    r'<breadth_detail[^>]*>(?P<breadth_detail>.*?)</breadth_detail>\s*'
    r'</ratified>',
    re.DOTALL
)

# Findet <ratified>-Bloecke, die vom obigen strengen Muster NICHT erfasst
# wurden, damit wir wissen, was manuell nachgeprueft werden muss.
RATIFIED_ROUGH_PATTERN = re.compile(r'<ratified.*?</ratified>', re.DOTALL)


def load_log(filepath):
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def get_all_assistant_text(log_data):
    """Sammelt allen Text aus Assistant-Nachrichten, in Reihenfolge."""
    texts = []
    for msg in log_data:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
    return texts


def extract_ratified_blocks(all_text):
    """Extrahiert alle sauber parsbaren <ratified>-Bloecke, plus eine Liste
    der nicht parsbaren Roh-Bloecke (fuer manuelle Nachpruefung)."""
    parsed = []
    unparsed = []

    for text in all_text:
        rough_matches = RATIFIED_ROUGH_PATTERN.findall(text)
        clean_matches = list(RATIFIED_PATTERN.finditer(text))

        for m in clean_matches:
            dim = m.group("dimension")
            if dim not in DIMENSION_ORDER:
                unparsed.append(m.group(0))
                continue
            parsed.append({
                "dimension": dim,
                "position": m.group("position").strip(),
                "reasoning": m.group("reasoning").strip(),
                "breadth": m.group("breadth").strip(),
                "breadth_detail": m.group("breadth_detail").strip(),
            })

        # Grobe Treffer, die NICHT im sauberen Muster auftauchten -> vermutlich
        # fehlerhaft formatiert, zur manuellen Pruefung vormerken
        if len(rough_matches) > len(clean_matches):
            clean_texts = set(m.group(0) for m in clean_matches)
            for rough in rough_matches:
                if rough not in clean_texts:
                    unparsed.append(rough)

    return parsed, unparsed


def build_profile(parsed_blocks, log_filepath):
    """Baut das strukturierte Profil im Schema-Format (Liste pro Dimension,
    da mehrere ratifizierte Unterpositionen pro Dimension normal sind)."""
    dimensions = {dim: [] for dim in DIMENSION_ORDER}
    for block in parsed_blocks:
        dimensions[block["dimension"]].append({
            "position": block["position"],
            "reasoning": block["reasoning"],
            "breadth": block["breadth"],
            "breadth_detail": block["breadth_detail"],
        })

    populated_dimensions = [d for d in DIMENSION_ORDER if dimensions[d]]

    profile = {
        "participant_id": None,  # noch zu vergeben, sobald ein echtes ID-System existiert
        "log_reference": os.path.basename(log_filepath),
        "extraction_timestamp": datetime.datetime.now().isoformat(),
        "phase1_completed": len(populated_dimensions) == len(DIMENSION_ORDER),
        "completion_depth": len(populated_dimensions),
        "dimensions": dimensions,
    }
    return profile


def write_markdown_review(profile, unparsed, out_path, log_filepath):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Extraktions-Ueberpruefung: {os.path.basename(log_filepath)}\n\n")
        f.write(f"Erzeugt am: {profile['extraction_timestamp']}\n\n")
        f.write(f"**Abgedeckte Dimensionen:** {profile['completion_depth']} von 6 ")
        f.write(f"({'vollstaendig' if profile['phase1_completed'] else 'unvollstaendig'})\n\n")
        f.write("**Zum Gegenchecken:** vergleiche die unten aufgelisteten extrahierten Positionen ")
        f.write("mit dem Originaldialog (gleiche Log-Datei), um zu pruefen, ob die condensed_position ")
        f.write("und reasoning wirklich das wiedergeben, was der Teilnehmer gesagt hat.\n\n")
        f.write("---\n\n")

        for dim in DIMENSION_ORDER:
            entries = profile["dimensions"][dim]
            f.write(f"## {DIMENSION_NAMES_DE[dim]} ({dim})\n\n")
            if not entries:
                f.write("*Keine ratifizierten Positionen gefunden.*\n\n")
                continue
            for i, e in enumerate(entries, 1):
                f.write(f"**Unterposition {i}:**\n\n")
                f.write(f"- **Position:** {e['position']}\n")
                f.write(f"- **Begruendung:** {e['reasoning']}\n")
                f.write(f"- **Ueberzeugungsstaerke:** {e['breadth']}\n")
                f.write(f"- **Freitext-Detail:** {e['breadth_detail'] or '*(leer)*'}\n\n")
            f.write("\n")

        if unparsed:
            f.write("---\n\n")
            f.write(f"## ⚠️ Nicht sauber geparste Bloecke ({len(unparsed)})\n\n")
            f.write("Diese Bloecke wurden im Log gefunden, aber nicht ins Schema uebernommen ")
            f.write("(vermutlich Formatierungsfehler) -- bitte manuell im Original-Log pruefen:\n\n")
            for i, u in enumerate(unparsed, 1):
                f.write(f"**Block {i}:**\n```\n{u}\n```\n\n")


def process_log_data(log_data, log_filepath):
    """Kernverarbeitung, unabhaengig davon, ob log_data von einer lokalen
    Datei oder direkt von SurfDrive kommt."""
    all_text = get_all_assistant_text(log_data)
    parsed_blocks, unparsed = extract_ratified_blocks(all_text)
    profile = build_profile(parsed_blocks, log_filepath)

    stem = os.path.splitext(os.path.basename(log_filepath))[0]

    # participant_id jetzt automatisch aus dem Dateinamen ableiten
    # (gpr_P-001.json -> "P-001") -- vorher stand hier hart "None", weil es
    # noch kein ID-System gab; das hat sich mit dem Zugangscode-Login
    # (access_control.py) geaendert: der Dateiname IST bereits die ID.
    if stem.startswith("gpr_"):
        profile["participant_id"] = stem[len("gpr_"):]

    json_out = os.path.join(OUTPUT_DIR, f"{stem}_extracted.json")
    md_out = os.path.join(OUTPUT_DIR, f"{stem}_extracted_review.md")

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    write_markdown_review(profile, unparsed, md_out, log_filepath)

    return {
        "datei": os.path.basename(log_filepath),
        "dimensionen_abgedeckt": profile["completion_depth"],
        "vollstaendig": profile["phase1_completed"],
        "anzahl_positionen": len(parsed_blocks),
        "nicht_geparste_bloecke": len(unparsed),
    }


def process_single_log(log_filepath):
    """Verarbeitet eine einzelne LOKALE Log-Datei."""
    log_data = load_log(log_filepath)
    return process_log_data(log_data, log_filepath)


def process_surfdrive_logs():
    """Verarbeitet ALLE Logs direkt von SurfDrive -- kein manueller
    Download noetig. Gleiche Ausgabe (JSON + Markdown pro Person,
    CSV-Uebersicht) wie der bisherige Ordner-Modus."""
    filenames = list_surfdrive_logs()
    if not filenames:
        print(f"Keine Logs im SurfDrive-Ordner '{SURFDRIVE_LOG_FOLDER}/' gefunden.")
        return

    print(f"Gefunden: {len(filenames)} Logs auf SurfDrive. Verarbeite alle...\n")
    summaries = []
    for fname in filenames:
        try:
            log_data = download_surfdrive_log(fname)
            summary = process_log_data(log_data, fname)
            summaries.append(summary)
            flag = "  <-- unvollstaendig!" if not summary["vollstaendig"] else ""
            warn = f"  ({summary['nicht_geparste_bloecke']} nicht geparst!)" if summary["nicht_geparste_bloecke"] else ""
            print(f"  {fname}: {summary['dimensionen_abgedeckt']}/6 Dimensionen, "
                  f"{summary['anzahl_positionen']} Positionen{flag}{warn}")
        except Exception as e:
            print(f"  {fname}: FEHLER beim Verarbeiten -- {e}")

    overview_path = os.path.join(OUTPUT_DIR, "uebersicht_alle_teilnehmende.csv")
    write_overview_csv(summaries, overview_path)

    vollstaendig_count = sum(1 for s in summaries if s["vollstaendig"])
    print(f"\nFertig: {len(summaries)} Dateien verarbeitet, {vollstaendig_count} davon vollstaendig (6/6 Dimensionen).")
    print(f"Uebersichtstabelle: {overview_path}")
    print(f"Einzelne JSON/Markdown-Dateien: {OUTPUT_DIR}/")


def write_overview_csv(summaries, out_path):
    """Kurzuebersicht ueber alle verarbeiteten Log-Dateien -- fuer den
    schnellen Blick, ohne jede einzelne Datei oeffnen zu muessen."""
    import csv
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "datei", "dimensionen_abgedeckt", "vollstaendig",
            "anzahl_positionen", "nicht_geparste_bloecke",
        ])
        writer.writeheader()
        for s in summaries:
            writer.writerow(s)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "surfdrive":
        process_surfdrive_logs()
        return

    if len(sys.argv) < 2:
        print("Nutzung:")
        print("  python extract_ratified.py surfdrive           (alle Logs direkt von SurfDrive)")
        print("  python extract_ratified.py pfad/zum/log.json    (einzelne lokale Datei)")
        print("  python extract_ratified.py pfad/zum/ordner/     (alle lokalen .json-Logs darin)")
        return

    input_path = sys.argv[1]

    if not os.path.exists(input_path):
        print(f"Pfad nicht gefunden: {input_path}")
        return

    if os.path.isdir(input_path):
        # Ordner-Modus: alle passenden Log-Dateien darin verarbeiten.
        # Filter erweitert auf das aktuelle Namensschema "gpr_{participant_id}.json"
        # (deterministischer Dateiname, siehe sitzung1_view.py) -- die alten
        # Praefixe (gpr_v3_/gpr_streamlit_, Zeitstempel-basiert) bleiben als
        # Fallback fuer bereits vorhandene alte Logs weiter erkannt.
        log_files = sorted(
            f for f in os.listdir(input_path)
            if f.endswith(".json") and f.startswith("gpr_")
        )
        if not log_files:
            print(f"Keine passenden Log-Dateien (gpr_*.json) in {input_path} gefunden.")
            return

        print(f"Gefunden: {len(log_files)} Log-Dateien. Verarbeite alle...\n")
        summaries = []
        for fname in log_files:
            full_path = os.path.join(input_path, fname)
            try:
                summary = process_single_log(full_path)
                summaries.append(summary)
                flag = "  <-- unvollstaendig!" if not summary["vollstaendig"] else ""
                warn = f"  ({summary['nicht_geparste_bloecke']} nicht geparst!)" if summary["nicht_geparste_bloecke"] else ""
                print(f"  {fname}: {summary['dimensionen_abgedeckt']}/6 Dimensionen, "
                      f"{summary['anzahl_positionen']} Positionen{flag}{warn}")
            except Exception as e:
                print(f"  {fname}: FEHLER beim Verarbeiten -- {e}")

        overview_path = os.path.join(OUTPUT_DIR, "uebersicht_alle_teilnehmende.csv")
        write_overview_csv(summaries, overview_path)

        vollstaendig_count = sum(1 for s in summaries if s["vollstaendig"])
        print(f"\nFertig: {len(summaries)} Dateien verarbeitet, {vollstaendig_count} davon vollstaendig (6/6 Dimensionen).")
        print(f"Uebersichtstabelle: {overview_path}")
        print(f"Einzelne JSON/Markdown-Dateien: {OUTPUT_DIR}/")

    else:
        # Einzeldatei-Modus (wie bisher)
        summary = process_single_log(input_path)
        print(f"Gefunden: {summary['anzahl_positionen']} sauber geparste ratifizierte Positionen "
              f"({summary['dimensionen_abgedeckt']} von 6 Dimensionen abgedeckt).")
        if summary["nicht_geparste_bloecke"]:
            print(f"WARNUNG: {summary['nicht_geparste_bloecke']} Bloecke konnten nicht sauber geparst werden, "
                  f"siehe Markdown-Datei fuer Details.")
        stem = os.path.splitext(os.path.basename(input_path))[0]
        print(f"\nJSON (fuer Clustering-Agent): {OUTPUT_DIR}/{stem}_extracted.json")
        print(f"Markdown (zum Gegenchecken):   {OUTPUT_DIR}/{stem}_extracted_review.md")


if __name__ == "__main__":
    main()
