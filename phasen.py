"""
phasen.py

Definiert die drei Studien-Sitzungen mit ihren Zeitfenstern (Stand:
Studienzeitraum 10.8.-30.8.2026).
Freischaltung ist rein datumsbasiert -- kein manuelles Freischalten pro
Person noetig.

Zeiten werden bewusst NAIV verglichen (reines datetime.date, ohne
Zeitzonen-Objekt), auf Basis der Server-lokalen Zeit von Streamlit Cloud.
Das reicht fuer taggenaue Fenster; wuerde Praezision auf die Stunde noetig,
muesste hier eine Zeitzone explizit ergaenzt werden (aktuell keine
Anforderung, da Sitzungsfenster jeweils mehrtaegig sind).
"""

import datetime
from typing import Optional
import streamlit as st

PHASEN = {
    "sitzung1": {
        "titel": "Input – Deine Stimme zählt!",
        "beschreibung": (
            "Du entwickelst deine eigenen Positionen zum Thema. Unterstützt durch den "
            "Chatbot Sokra: perspektivenreich, evidenzbasiert und konstruktiv."
        ),
        "start": datetime.date(2026, 8, 10),
        "ende": datetime.date(2026, 8, 16),
        "icon": "1️⃣",
    },
    "sitzung2": {
        "titel": "Austausch – Gemeinsam weiter!",
        "beschreibung": (
            "Hier kommen alle Perspektiven zusammen. In dieser Sitzung diskutiert ihr die "
            "bestehenden Vorschläge, entwickelt Kompromisse und entscheidet, wie die "
            "Vorschläge weiter verarbeitet werden."
        ),
        "start": datetime.date(2026, 8, 19),
        "ende": datetime.date(2026, 8, 23),
        "icon": "2️⃣",
    },
    "sitzung3": {
        "titel": "Abstimmung – Du hast die Wahl!",
        "beschreibung": (
            "Nun wird abgestimmt. Alle nach Phase 2 verbleibenden Positionen werden zur Wahl "
            "freigegeben. Daraus ergibt sich, welche Policy-Optionen als Empfehlungen oder "
            "sogar direkt umsetzbare Maßnahmen in dem Abschlussbericht landen, der an die "
            "politischen Entscheidungsträger weitergereicht wird."
        ),
        "start": datetime.date(2026, 8, 26),
        "ende": datetime.date(2026, 8, 30),
        "icon": "3️⃣",
    },
}


def status(phase_key: str, today: Optional[datetime.date] = None, participant_id: Optional[str] = None) -> str:
    """Gibt 'bevorstehend', 'aktiv' oder 'abgeschlossen' zurueck.

    Manueller Schalthebel PRO SITZUNG, gilt fuer ALLE (Secrets, kein Redeploy
    noetig):

        [testing]
        sitzung1 = "aktiv"        # override -- ignoriert das Datum
        sitzung2 = "auto"         # oder Zeile weglassen -- normale Datumslogik
        sitzung3 = "gesperrt"

    Gueltige Override-Werte: "aktiv", "gesperrt", "abgeschlossen", "auto"
    (oder Zeile/Block ganz weglassen -- "auto" ist der Standard). WICHTIG:
    vor dem 10.8. den [testing]-Block entfernen oder alles auf "auto"
    setzen, sonst greift die Datums-Sperre waehrend der echten Studie
    nicht.

    Zweiter, GEZIELTERER Schalthebel -- einzelne Testperson(en) bekommen
    IMMER Zugriff auf ALLE Sitzungen, unabhaengig vom Datum, waehrend fuer
    alle anderen (echten Teilnehmenden) die normale Datumslogik unveraendert
    gilt. Damit kann der Autor auf der echten, live laufenden App an Sitzung
    2/3 weiterarbeiten/stichprobenartig testen, ohne dass die Sitzungen fuer
    echte Teilnehmende vorzeitig sichtbar werden:

        [testing]
        tester_ids = ["P-ADMIN-TEST"]   # Liste eigener Test-Pseudonyme

    Ersetzt NICHT die Empfehlung, Sitzung-2/3-Entwicklung primaer lokal auf
    einem separaten Branch zu machen -- das hier loest nur "wer sieht was",
    nicht "ein Deploy unterbricht laufende Sitzungen"."""
    tester_ids = st.secrets.get("testing", {}).get("tester_ids", [])
    if participant_id and participant_id in tester_ids:
        return "aktiv"

    override = st.secrets.get("testing", {}).get(phase_key, "auto")
    if override in ("aktiv", "gesperrt", "abgeschlossen"):
        return override if override != "gesperrt" else "bevorstehend"

    today = today or datetime.date.today()
    p = PHASEN[phase_key]
    if today < p["start"]:
        return "bevorstehend"
    if today > p["ende"]:
        return "abgeschlossen"
    return "aktiv"
