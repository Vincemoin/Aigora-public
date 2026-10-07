"""
streamlit_app.py

Aigora -- Haupt-Einstiegspunkt. EIN Zugangscode pro Teilnehmer/in fuer die
gesamte Studie, danach eine Uebersicht mit drei Sitzungs-Kacheln, die je
nach Datum gesperrt/entsperrt sind (siehe phasen.py). Laeuft primaer auf
Streamlit Cloud, keine lokalen Dateien: alle persistenten Daten (Chatlogs
etc.) gehen ueber SurfDrive (surfdrive_storage.py), alle Zugangsdaten ueber
Streamlit-Cloud-Secrets (bootstrap_secrets.py, access_control.py).

WICHTIG: bootstrap() muss vor den Imports von gpr_core/views passieren,
da retrieve.py beim Import einen OpenAI-Client aufbaut, der die
Umgebungsvariable OPENAI_API_KEY bereits gesetzt erwartet.
"""

import streamlit as st

from bootstrap_secrets import bootstrap
bootstrap()

from access_control import require_login
from phasen import PHASEN, status
from views import sitzung1_view, sitzung2_view, sitzung3_view
from branding import get_page_icon, render_title_bar, ABLAUF_GRAPHIC_PATH, ablauf_graphic_available
from survey_gate import presurvey_url, postsurvey_url, postsurvey2_url, postsurvey3_url
from session_progress import sitzung1_erledigt, sitzung2_erledigt

st.set_page_config(page_title="Aigora", page_icon=get_page_icon(), layout="centered")

participant_id = require_login()

if "aktuelle_ansicht" not in st.session_state:
    st.session_state.aktuelle_ansicht = "uebersicht"

VIEWS = {
    "sitzung1": sitzung1_view.render,
    "sitzung2": sitzung2_view.render,
    "sitzung3": sitzung3_view.render,
}


def render_uebersicht() -> None:
    render_title_bar()
    st.caption(f"Angemeldet als: {participant_id}")
    st.write("Wähle eine Sitzung:")

    # Sitzungslabel je Kachel: Sitzung 3 "abstimmen", 1/2 "starten" (siehe
    # der Autor) -- sonst identisches Verhalten.
    POST_SURVEY = {
        "sitzung1": ("Anschlussbefragung starten", postsurvey_url),
        "sitzung2": ("Anschlussbefragung starten", postsurvey2_url),
        "sitzung3": ("Abschlussbefragung starten", postsurvey3_url),
    }
    # SurfDrive-basierte automatische "erledigt"-Erkennung, unabhaengig vom
    # Kalenderfenster (siehe der Autor: "automatisch als erledigt markiert,
    # wenn Nutzer das schon gemacht haben") -- betrifft nur Sitzung 1/2,
    # da nur dort ein eindeutiges Abschlusskriterium ohne grossen Aufwand
    # pruefbar ist. Jeder Fehler faellt zurueck auf die normale Datumslogik.
    ERLEDIGT_CHECK = {"sitzung1": sitzung1_erledigt, "sitzung2": sitzung2_erledigt}

    for key, phase in PHASEN.items():
        s = status(key, participant_id=participant_id)
        if s == "aktiv" and key in ERLEDIGT_CHECK:
            try:
                if ERLEDIGT_CHECK[key](participant_id):
                    s = "abgeschlossen"
            except Exception:
                pass

        st.subheader(f"{phase['icon']} {phase['titel']}")
        st.caption(phase["beschreibung"])
        st.caption(f"Zeitfenster: {phase['start'].strftime('%d.%m.%Y')} – {phase['ende'].strftime('%d.%m.%Y')}")

        post_label, post_url_fn = POST_SURVEY[key]
        post_url = post_url_fn(participant_id)
        pre_url = presurvey_url(participant_id) if key == "sitzung1" else ""

        knopf_specs = []
        if pre_url:
            knopf_specs.append("pre")
        knopf_specs.append("sitzung")
        if post_url:
            knopf_specs.append("post")
        cols = st.columns(len(knopf_specs))

        for col, spec in zip(cols, knopf_specs):
            with col:
                if spec == "pre":
                    st.link_button("📝 Vorabbefragung starten", pre_url, use_container_width=True)
                elif spec == "post":
                    st.link_button(f"📝 {post_label}", post_url, use_container_width=True)
                else:
                    if s == "aktiv":
                        if st.button("▶️ Sitzung starten", key=f"open_{key}", type="primary", use_container_width=True):
                            st.session_state.aktuelle_ansicht = key
                            st.rerun()
                    elif s == "bevorstehend":
                        st.button("🔒 Gesperrt", key=f"locked_{key}", disabled=True, use_container_width=True)
                    else:  # abgeschlossen
                        if st.button("✅ Ansehen", key=f"open_{key}_done", use_container_width=True):
                            st.session_state.aktuelle_ansicht = key
                            st.rerun()
        st.divider()

    if ablauf_graphic_available():
        st.image(ABLAUF_GRAPHIC_PATH, use_container_width=True)


if st.session_state.aktuelle_ansicht == "uebersicht":
    render_uebersicht()
else:
    if st.button("← Zurück zur Übersicht"):
        st.session_state.aktuelle_ansicht = "uebersicht"
        st.rerun()
    VIEWS[st.session_state.aktuelle_ansicht](participant_id)
