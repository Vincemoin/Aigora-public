"""
surfdrive_storage.py

Minimaler WebDAV-Client fuer SurfDrive (Nextcloud-basiert) -- reine
HTTP-Anfragen ueber `requests` mit Basic Auth, keine Zusatz-Bibliothek
noetig, da SurfDrive/Nextcloud WebDAV Standard-HTTP-Methoden (GET/PUT/
MKCOL) unterstuetzt.

Bewusst schlank gehalten: KEIN Listing, KEINE Ordner-Rekursion -- wir
arbeiten ausschliesslich mit FESTEN, deterministischen Dateinamen pro
Teilnehmer und Sitzungstyp (z.B. "gpr_P-001.json"), NICHT mit Zeitstempel-
Dateinamen. Genau das macht "Sitzung fortsetzen" trivial: es gibt nur EINE
Datei pro Teilnehmer/Sitzungstyp, sie wird bei jedem Speichern
ueberschrieben (keine Diff-/Merge-Logik noetig).

Zugangsdaten kommen AUSSCHLIESSLICH aus st.secrets["surfdrive"], niemals
hartkodiert -- der Autor traegt Nutzername/App-Passwort selbst in die
Streamlit-Cloud-Secrets ein (siehe DEPLOYMENT_ANLEITUNG.md).
"""

from typing import Optional
import requests
from requests.auth import HTTPBasicAuth
import streamlit as st

def _creds():
    return st.secrets["surfdrive"]


def _auth():
    creds = _creds()
    return HTTPBasicAuth(creds["username"], creds["password"])


def _url(remote_path: str) -> str:
    base = f"https://surfdrive.surf.nl/remote.php/dav/files/{_creds()['username']}"
    return f"{base}/{remote_path.lstrip('/')}"


def ensure_folder(remote_path: str) -> bool:
    """Legt einen Ordner an (MKCOL). 405 = existiert bereits -- das ist okay,
    kein Fehlerfall. Muss einmalig fuer jede Ordnerebene aufgerufen werden
    (SurfDrive/Nextcloud legt keine verschachtelten Pfade automatisch an)."""
    try:
        r = requests.request("MKCOL", _url(remote_path), auth=_auth(), timeout=15)
        return r.status_code in (201, 405)
    except requests.RequestException:
        return False


def upload_text(remote_path: str, content: str) -> bool:
    """Speichert (ueberschreibt) eine Textdatei. Gibt True/False fuer Erfolg
    zurueck, wirft NIE eine Exception nach aussen -- der Aufrufer entscheidet,
    wie mit einem Fehlschlag umgegangen wird (siehe views/sitzung1_view.py:
    Session-State-Fallback statt Datenverlust bei einem einzelnen
    Netzwerkfehler)."""
    try:
        r = requests.put(
            _url(remote_path),
            data=content.encode("utf-8"),
            auth=_auth(),
            timeout=20,
        )
        return r.status_code in (200, 201, 204)
    except requests.RequestException:
        return False


def download_text(remote_path: str) -> Optional[str]:
    """Liest eine Textdatei. Gibt None zurueck, wenn sie nicht existiert
    (404) oder ein Verbindungsfehler auftritt -- beide Faelle werden vom
    Aufrufer identisch behandelt ("kein bestehendes Log gefunden, neue
    Sitzung beginnen")."""
    try:
        r = requests.get(_url(remote_path), auth=_auth(), timeout=20)
        if r.status_code == 200:
            return r.text
        return None
    except requests.RequestException:
        return None
