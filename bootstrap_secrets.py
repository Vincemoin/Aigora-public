"""
bootstrap_secrets.py

Kopiert benoetigte API-Keys aus st.secrets in Umgebungsvariablen, DAMIT
Code, der ueber os.environ liest (Anthropic-SDK, OpenAI-SDK in retrieve.py,
beide bisher ueber lokale .env-Dateien mit load_dotenv() versorgt), OHNE
Aenderung weiterlaeuft. Lokales .env entfaellt komplett -- Streamlit-Cloud-
Secrets sind jetzt die einzige Quelle fuer Zugangsdaten.

WICHTIG: bootstrap() muss aufgerufen werden, BEVOR irgendein Modul
importiert wird, das retrieve.py (und damit den OpenAI-Client) laedt --
also ganz oben in streamlit_app.py, vor den Imports von gpr_core/views.
"""

import os
import streamlit as st


def bootstrap():
    os.environ["ANTHROPIC_API_KEY"] = st.secrets["anthropic"]["api_key"]
    os.environ["OPENAI_API_KEY"] = st.secrets["openai"]["api_key"]
