"""
branding.py

Zentrale Stelle fuer Branding-Assets (Avatar, Titelbar-Logo, Eroeffnungs-
grafik), die in mehreren Sitzungen gebraucht werden. Faellt automatisch auf
einen neutralen Text-/Emoji-Titel zurueck, solange die echten Dateien noch
nicht im Repo liegen -- sobald der Autor sie unter den untenstehenden Pfaden
ablegt, greifen sie ohne weitere Code-Aenderung.

ABLAGEORTE IM REPO:
    assets/aigora_icon.png              -- Avatar fuer Sokra im Chat + Browser-Favicon
    assets/title_page_logo.png          -- Logo fuer die Titelbar (Login + Uebersicht)
    assets/6_dimensionen_grafik.png     -- Grafik fuer die Eroeffnungsnachricht (steht noch aus)
    assets/grafik_ablauf.png            -- Grafik des Studienablaufs (3 Sitzungen) fuer die Uebersicht
"""

import os

import streamlit as st

AVATAR_PATH = "assets/aigora_icon.png"
TITLE_PAGE_LOGO_PATH = "assets/title_page_logo.png"
DIMENSIONS_GRAPHIC_PATH = "assets/6_dimensionen_grafik.png"
ABLAUF_GRAPHIC_PATH = "assets/grafik_ablauf.png"

AGENT_AVATAR = AVATAR_PATH if os.path.exists(AVATAR_PATH) else "💬"


def dimensions_graphic_available() -> bool:
    return os.path.exists(DIMENSIONS_GRAPHIC_PATH)


def ablauf_graphic_available() -> bool:
    return os.path.exists(ABLAUF_GRAPHIC_PATH)


def title_page_logo_available() -> bool:
    return os.path.exists(TITLE_PAGE_LOGO_PATH)


def get_page_icon():
    """Fuer st.set_page_config(page_icon=...) -- Browser-Tab-Icon. Braucht
    ein geladenes Bildobjekt (kein roher Pfad-String), daher ueber PIL
    geoeffnet. Pillow ist bereits eine Kernabhaengigkeit von Streamlit
    selbst, keine zusaetzliche Ergaenzung in requirements.txt noetig."""
    if os.path.exists(AVATAR_PATH):
        from PIL import Image
        return Image.open(AVATAR_PATH)
    return "🗳️"


def render_title_bar() -> None:
    """Zeigt das Aigora-Logo als Titelbar (Login-Seite + Uebersicht), faellt
    auf einen Text-Titel zurueck, solange title_page_logo.png fehlt."""
    if title_page_logo_available():
        st.image(TITLE_PAGE_LOGO_PATH, use_container_width=True)
    else:
        st.title("🗳️ Aigora")
