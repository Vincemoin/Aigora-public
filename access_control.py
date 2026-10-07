"""
access_control.py

Zugangscode-Login: EIN Code pro Teilnehmer/in fuer die gesamte Studie
(alle drei Sitzungen), zugeordnet ueber st.secrets["access_codes"], z.B.:

    [access_codes]
    "AB12CD" = "P-001"

Bewusst simpel gehalten (keine Passwort-Hashes, kein Session-Token) --
angemessen fuer ~20 Teilnehmende mit individuell per E-Mail verschickten
Codes, nicht oeffentlich einsehbar. Ersetzt den fruaheren Link+Token-Zugang
(siehe Sicherheitsvorfall-Notiz im Uebergabedokument) vollstaendig.
"""

import streamlit as st

from branding import render_title_bar


def require_login() -> str:
    """Zeigt ein Login-Formular, falls noch nicht eingeloggt. Gibt die
    participant_id zurueck, sobald ein gueltiger Code eingegeben wurde.
    Haelt die Ausfuehrung des restlichen Skripts an (st.stop()), solange
    kein gueltiger Code vorliegt -- alles unterhalb dieses Aufrufs in
    streamlit_app.py laeuft also nur fuer eingeloggte Personen."""
    if "participant_id" in st.session_state:
        return st.session_state["participant_id"]

    render_title_bar()
    st.write("Bitte gib deinen persönlichen Zugangscode ein (aus der E-Mail-Einladung).")

    code = st.text_input("Zugangscode", type="password")
    submitted = st.button("Anmelden")

    if submitted:
        access_codes = st.secrets.get("access_codes", {})
        participant_id = access_codes.get(code)
        if participant_id:
            st.session_state["participant_id"] = participant_id
            st.rerun()
        else:
            st.error(
                "Zugangscode nicht erkannt. Bitte Gross-/Kleinschreibung und "
                "Leerzeichen prüfen, oder wende dich an die Studienleitung."
            )

    st.stop()
