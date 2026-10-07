"""
session_progress.py

Prueft, ob eine teilnehmende Person Sitzung 1 oder 2 bereits inhaltlich
abgeschlossen hat -- unabhaengig vom Kalenderfenster (siehe phasen.py).
Wird auf der Uebersichtsseite (streamlit_app.py) genutzt, um eine Kachel
automatisch als "erledigt" zu markieren, wenn auf SurfDrive schon ein
vollstaendiger Log liegt, statt dass Teilnehmende manuell Bescheid geben
muessen (siehe der Autor: "automatisch als erledigt markiert wenn Nutzer
das schon gemacht haben").

Bewusst schlank/fehlertolerant: jeder Netzwerk- oder Parse-Fehler fuehrt
zu "nicht erledigt" (nie zu einem Crash, siehe Architekturprinzip
"fehlende Daten duerfen nie die App crashen lassen"), und das Ergebnis
wird pro Sitzung kurz gecacht, damit nicht bei jedem Rerun (jeder Klick
in Streamlit) erneut ueber SurfDrive geprueft wird.
"""

import json

import streamlit as st

import surfdrive_storage as sd


@st.cache_data(ttl=120, show_spinner=False)
def _download_json(remote_path: str):
    raw = sd.download_text(remote_path)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def sitzung1_erledigt(participant_id: str) -> bool:
    """Alle 6 Dimensionen im GPR-Dialog ratifiziert."""
    try:
        from views.sitzung1_view import DIMENSION_ORDER, _collect_ratified_positions
    except ImportError:
        return False
    messages = _download_json(f"aigora_logs/gpr_{participant_id}.json")
    if not messages:
        return False
    try:
        positions = _collect_ratified_positions(messages)
        return all(positions.get(dim) for dim in DIMENSION_ORDER)
    except Exception:
        return False


def sitzung2_erledigt(participant_id: str) -> bool:
    """Bewertungsdatei aus Sitzung 2 traegt einen completed_at-Zeitstempel."""
    daten = _download_json(f"aigora_logs_moda/s2_bewertungen/{participant_id}.json")
    if not daten:
        return False
    return bool(daten.get("completed_at"))
