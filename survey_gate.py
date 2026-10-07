"""
survey_gate.py

Reine, NICHT-blockierende Verlinkung zu den Vor-/Nachbefragungen -- KEIN
Gate mehr vor Sitzung 1 (die fruehere Ja/Nein-Abfrage "Hast du die
Vorab-Befragung schon ausgefuellt?" wurde auf Wunsch entfernt, siehe
Feedback: zu umstaendlich/verwirrend). Stattdessen einfache Links direkt
in der jeweiligen Sitzungs-Kachel der Uebersicht (streamlit_app.py), unter
Beschreibung/Zeitfenster.

Braucht in st.secrets (alle optional -- fehlt einer, wird der jeweilige
Link/Button einfach nicht angezeigt, blockiert nichts, siehe
Architekturprinzip "fehlende Konfiguration darf nie die App crashen/
blockieren"):
    [surveys]
    presurvey_url = "..."     # vor Sitzung 1
    postsurvey_url = "..."    # nach Sitzung 1
    postsurvey2_url = "..."   # nach Sitzung 2
    postsurvey3_url = "..."   # nach Sitzung 3 (Abschlussbefragung)
"""

import urllib.parse

import streamlit as st


def _survey_url(base_url: str, participant_id: str) -> str:
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}PID={urllib.parse.quote(participant_id)}"


def presurvey_link_line(participant_id: str) -> str:
    url = st.secrets.get("surveys", {}).get("presurvey_url", "")
    if not url:
        return ""
    return f"→ Hier entlang zur [Vorab-Befragung]({_survey_url(url, participant_id)})"


def postsurvey_link_line(participant_id: str) -> str:
    """Nachbefragung zu Sitzung 1."""
    url = st.secrets.get("surveys", {}).get("postsurvey_url", "")
    if not url:
        return ""
    return f"→ Hier entlang zur [Anschluss-Befragung]({_survey_url(url, participant_id)})"


def postsurvey2_link_line(participant_id: str) -> str:
    """Nachbefragung zu Sitzung 2."""
    url = st.secrets.get("surveys", {}).get("postsurvey2_url", "")
    if not url:
        return ""
    return f"→ Hier entlang zur [Nachbefragung – Sitzung 2]({_survey_url(url, participant_id)})"


# ── Rohe URLs (fuer Buttons statt Markdown-Zeilen, siehe streamlit_app.py) ──

def presurvey_url(participant_id: str) -> str:
    url = st.secrets.get("surveys", {}).get("presurvey_url", "")
    return _survey_url(url, participant_id) if url else ""


def postsurvey_url(participant_id: str) -> str:
    """Anschlussbefragung zu Sitzung 1."""
    url = st.secrets.get("surveys", {}).get("postsurvey_url", "")
    return _survey_url(url, participant_id) if url else ""


def postsurvey2_url(participant_id: str) -> str:
    """Anschlussbefragung zu Sitzung 2."""
    url = st.secrets.get("surveys", {}).get("postsurvey2_url", "")
    return _survey_url(url, participant_id) if url else ""


def postsurvey3_url(participant_id: str) -> str:
    """Abschlussbefragung zu Sitzung 3."""
    url = st.secrets.get("surveys", {}).get("postsurvey3_url", "")
    return _survey_url(url, participant_id) if url else ""


def render_postsurvey_link(participant_id: str) -> None:
    """Auffaellige Info-Box-Variante -- weiterhin genutzt in
    views/sitzung1_view.py (Sidebar + Chat-Callout nach Abschluss aller 6
    Dimensionen), unabhaengig von der kompakten Link-Zeile fuer die
    Uebersichtsseite."""
    postsurvey_url = st.secrets.get("surveys", {}).get("postsurvey_url", "")
    if not postsurvey_url:
        return
    st.info(
        "Hier geht's zur abschließenden Nachbefragung: "
        f"[➡️ Zur Nachbefragung]({_survey_url(postsurvey_url, participant_id)})"
    )
