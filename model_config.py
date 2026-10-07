"""
model_config.py

Zentrale Stelle für den Modell-Anbieter der Live-Apps (Sitzung 1 + 2).
Umschaltbar OHNE Code-Änderung, allein über Streamlit-Cloud-Secrets:

    [model_provider]
    name = "anthropic"   # oder "deepseek"

Hintergrund: DeepSeek bietet seit V4 eine Anthropic-API-kompatible
Schnittstelle an (base_url https://api.deepseek.com/anthropic) -- das
Anthropic-SDK, alle Tool-Definitionen (name/input_schema/description) und
die komplette Antwort-Verarbeitung (response.content, block.type,
stop_reason) bleiben dadurch UNVERÄNDERT nutzbar. Es ändert sich nur:
welcher Client instanziiert wird, und welcher Modellname übergeben wird.
Quelle: https://api-docs.deepseek.com/guides/anthropic_api (abgerufen
30.07.2026 -- bei Zweifeln dort gegenprüfen, Kompatibilitätsdetails können
sich ändern).

BEKANNTE EINSCHRÄNKUNGEN, NICHT durch dieses Modul gelöst (laut DeepSeeks
eigener Kompatibilitätstabelle, Stand 30.07.2026):
- `cache_control` wird von DeepSeeks Anthropic-Schicht IGNORIERT (kein
  Fehler, aber auch kein Kosten-/Geschwindigkeitsvorteil -- 
  with_cache_breakpoint()/get_system_block() aus gpr_core.py laufen
  unverändert durch, wirken bei DeepSeek nur einfach ins Leere).
- Anthropics server-seitiges `web_search`-Tool (type="web_search_20250305")
  ist in der Kompatibilitätstabelle NICHT als unterstützt dokumentiert --
  deshalb wird es bei provider="deepseek" aus der Tool-Liste entfernt
  (siehe filter_tools()). Für die Sitzung-1-Kernaufgabe (RAG-Suche im
  eigenen Corpus über `search_corpus`) macht das keinen Unterschied, das
  ist ein eigenes, normales Custom-Tool und läuft unverändert.
- Bilder/Dokumente als Content-Block werden von DeepSeeks Anthropic-Layer
  nicht unterstützt -- für Aigora irrelevant, wird nirgends genutzt.
"""

import streamlit as st
from anthropic import Anthropic

DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5"


def get_provider() -> str:
    return st.secrets.get("model_provider", {}).get("name", "anthropic")


def get_model_name() -> str:
    if get_provider() == "deepseek":
        return st.secrets.get("model_provider", {}).get("deepseek_model", DEEPSEEK_DEFAULT_MODEL)
    return ANTHROPIC_DEFAULT_MODEL


def get_client() -> Anthropic:
    if get_provider() == "deepseek":
        return Anthropic(
            base_url=DEEPSEEK_ANTHROPIC_BASE_URL,
            api_key=st.secrets["deepseek"]["api_key"],
        )
    return Anthropic()  # nutzt ANTHROPIC_API_KEY aus der Umgebung, siehe bootstrap_secrets.py


def filter_tools(tools: list) -> list:
    """Entfernt Anthropics server-seitiges web_search-Tool bei DeepSeek --
    siehe Modul-Docstring, Unterstützung ist dort nicht dokumentiert."""
    if get_provider() != "deepseek":
        return tools
    return [t for t in tools if t.get("name") != "web_search"]
