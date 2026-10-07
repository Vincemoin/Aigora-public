"""
synthese_download_bewertungen.py

Laedt alle echten Sitzung-2-Bewertungsdateien von SurfDrive
(aigora_logs_moda/s2_bewertungen/) herunter und legt sie lokal unter
data/session2_bewertungen_live/ ab -- Datengrundlage fuer
synthese_dossiers.py (Schritt 1 der Pause-2-Synthese-Pipeline).

Getrennt von data/session2_bewertungen/ (lokale Testdaten mit
_s2.json-Suffix, siehe session2_bewertungen.py), weil SurfDrive ein
ANDERES Dateinamensschema verwendet ({PID}.json, ohne _s2-Suffix --
siehe _sd_path() in views/sitzung2_view.py). Beide Ordner bewusst nicht
vermischen, damit Testdaten (Nullwerte) nie versehentlich in eine echte
Auswertung einfliessen.

Beliebig oft erneut ausfuehrbar (ueberschreibt bestehende Dateien) --
gedacht fuer den finalen Durchlauf am Stichtag, nachdem Nachzuegler
eingetroffen sind.

Nutzung:
    python synthese_download_bewertungen.py

Braucht .env: SURFDRIVE_USERNAME, SURFDRIVE_PASSWORD (dieselben Werte
wie in den Streamlit-Cloud-Secrets unter [surfdrive]).
"""

import json
import os
import xml.etree.ElementTree as ET

# Manche lokalen Rechner (u.a. wegen SSL-Inspection durch Antivirus-
# Software) kennen das Root-Zertifikat von surfdrive.surf.nl nicht in
# certifis Standard-Bundle -- truststore nutzt stattdessen den
# Betriebssystem-Zertifikatsspeicher. Gleiches Muster wie in
# session2_clustering_v4think.py, daher hier uebernommen statt eine
# eigene Loesung zu bauen.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

SURFDRIVE_FOLDER = "aigora_logs_moda/s2_bewertungen"
OUTPUT_DIR = "data/session2_bewertungen_live"


def _auth():
    username = os.environ.get("SURFDRIVE_USERNAME")
    password = os.environ.get("SURFDRIVE_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "SURFDRIVE_USERNAME/SURFDRIVE_PASSWORD fehlen. Bitte lokal in "
            "einer .env-Datei setzen (dieselben Werte wie in den "
            "Streamlit-Cloud-Secrets unter [surfdrive])."
        )
    return HTTPBasicAuth(username, password)


def _surfdrive_base_url():
    username = os.environ.get("SURFDRIVE_USERNAME")
    return f"https://surfdrive.surf.nl/remote.php/dav/files/{username}"


def list_files():
    """WebDAV PROPFIND, Tiefe 1 -- gibt alle .json-Dateinamen im Ordner
    zurueck. Keine feste Teilnehmerliste noetig, deckt auch neu
    hinzugekommene Nachzuegler automatisch ab."""
    url = f"{_surfdrive_base_url()}/{SURFDRIVE_FOLDER}"
    r = requests.request("PROPFIND", url, auth=_auth(), headers={"Depth": "1"}, timeout=20)
    r.raise_for_status()
    ns = {"d": "DAV:"}
    root = ET.fromstring(r.content)
    files = []
    for resp in root.findall("d:response", ns):
        href = resp.find("d:href", ns).text
        fname = href.rstrip("/").split("/")[-1]
        if fname.endswith(".json"):
            files.append(fname)
    return sorted(files)


def download_one(filename):
    url = f"{_surfdrive_base_url()}/{SURFDRIVE_FOLDER}/{filename}"
    r = requests.get(url, auth=_auth(), timeout=30)
    r.raise_for_status()
    return r.text


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    dateien = list_files()
    if not dateien:
        print(f"Keine Dateien im SurfDrive-Ordner '{SURFDRIVE_FOLDER}/' gefunden.")
        return

    n_ok, n_fehler = 0, 0
    for fname in dateien:
        try:
            raw = download_one(fname)
            json.loads(raw)  # nur zur Validierung, wirft bei kaputtem JSON
            with open(os.path.join(OUTPUT_DIR, fname), "w", encoding="utf-8") as f:
                f.write(raw)
            n_ok += 1
        except Exception as exc:
            print(f"  FEHLER bei {fname}: {exc}")
            n_fehler += 1

    print(f"\n{n_ok} Dateien heruntergeladen nach {OUTPUT_DIR}/, {n_fehler} Fehler.")


if __name__ == "__main__":
    main()
