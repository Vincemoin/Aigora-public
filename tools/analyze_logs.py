"""
analyze_logs.py

Lokales Analyse-Dashboard fuer die Sitzung-1-Dialogs (SurfDrive). Bewusst
EIGENSTAENDIG und NICHT Teil der deployten App (wie extract_ratified.py/
patch_links.py) -- ein Dashboard mit allen Teilnehmer-Profilen darf niemals
ueber die oeffentliche Studien-URL erreichbar sein.

Start:
    streamlit run analyze_logs.py

Braucht lokal eine .env-Datei mit:
    SURFDRIVE_USERNAME=...
    SURFDRIVE_PASSWORD=...   (dieselben Werte wie in den Streamlit-Cloud-
                               Secrets unter [surfdrive])
    ANTHROPIC_API_KEY=...

Caching: Analyse-Ergebnisse (inkl. LLM-Ernsthaftigkeits-Check) werden lokal
unter CACHE_DIR pro Teilnehmer-ID gespeichert, verknuepft mit einem Hash des
Log-Inhalts. Ein Log wird nur dann neu verarbeitet (und der LLM-Aufruf nur
dann erneut gemacht), wenn sich der Hash gegenueber dem Cache geaendert hat
-- kein automatisches Nachladen, nur ueber den "Aktualisieren"-Button.
"""

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET

import requests
import streamlit as st
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from anthropic import Anthropic

load_dotenv()

SURFDRIVE_LOG_FOLDER = "aigora_logs"


def _surfdrive_base_url():
    username = os.environ.get("SURFDRIVE_USERNAME")
    return f"https://surfdrive.surf.nl/remote.php/dav/files/{username}"
CACHE_DIR = "./log_analysis_cache"
JUDGE_MODEL = "claude-haiku-4-5-20251001"

DIMENSION_ORDER = ["Goals", "Objectives", "Settings", "InstrumentLogic", "Tools", "Calibrations"]
DIMENSION_LABELS = {
    "Goals": "Übergeordnete Ziele",
    "Objectives": "Konkrete Ziele",
    "Settings": "Zwischenziele",
    "InstrumentLogic": "Umsetzungslogik",
    "Tools": "Instrumententyp",
    "Calibrations": "Feinausgestaltung",
}

RATIFIED_PATTERN = re.compile(
    r'<ratified\s+dimension=["\']?(?P<dimension>\w+)["\']?\s*>\s*'
    r'<position>(?P<position>.*?)</position>\s*'
    r'<reasoning>(?P<reasoning>.*?)</reasoning>\s*'
    r'<breadth>(?P<breadth>.*?)</breadth>\s*'
    r'<breadth_detail[^>]*>(?P<breadth_detail>.*?)</breadth_detail>\s*'
    r'</ratified>',
    re.DOTALL,
)

os.makedirs(CACHE_DIR, exist_ok=True)


# ---------------------------------------------------------------------
# SurfDrive-Zugriff (gleiches Muster wie extract_ratified.py)
# ---------------------------------------------------------------------

def _surfdrive_auth():
    username = os.environ.get("SURFDRIVE_USERNAME")
    password = os.environ.get("SURFDRIVE_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "SURFDRIVE_USERNAME/SURFDRIVE_PASSWORD fehlen in der lokalen .env-Datei."
        )
    return HTTPBasicAuth(username, password)


def list_surfdrive_logs():
    url = f"{_surfdrive_base_url()}/{SURFDRIVE_LOG_FOLDER}"
    r = requests.request("PROPFIND", url, auth=_surfdrive_auth(),
                          headers={"Depth": "1"}, timeout=20)
    r.raise_for_status()
    ns = {"d": "DAV:"}
    root = ET.fromstring(r.content)
    files = []
    for resp in root.findall("d:response", ns):
        href = resp.find("d:href", ns).text
        fname = href.rstrip("/").split("/")[-1]
        if fname.endswith(".json") and fname.startswith("gpr_"):
            files.append(fname)
    return sorted(files)


def download_surfdrive_log_raw(filename):
    """Laedt eine Log-Datei als ROHEN Text (fuer Hash-Vergleich UND JSON-Parsing)."""
    url = f"{_surfdrive_base_url()}/{SURFDRIVE_LOG_FOLDER}/{filename}"
    r = requests.get(url, auth=_surfdrive_auth(), timeout=30)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

def _cache_path(participant_id):
    return os.path.join(CACHE_DIR, f"{participant_id}.json")


def load_cached(participant_id):
    path = _cache_path(participant_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_cache(participant_id, data):
    with open(_cache_path(participant_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_cached_participant_ids():
    ids = []
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".json"):
            ids.append(fname[: -len(".json")])
    return sorted(ids)


# ---------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------

def _extract_text(content):
    """Liest den lesbaren Text aus einem Nachrichten-Content -- egal ob
    (neueres Format) reiner String oder (altes/Zwischenschritt-Format)
    Liste von Bloecken mit tool_use/tool_result/text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def collect_ratified_positions(messages):
    result = {dim: [] for dim in DIMENSION_ORDER}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        text = _extract_text(msg.get("content"))
        for m in RATIFIED_PATTERN.finditer(text):
            dim = m.group("dimension")
            if dim in result:
                result[dim].append({
                    "position": m.group("position").strip(),
                    "reasoning": m.group("reasoning").strip(),
                    "breadth": m.group("breadth").strip(),
                    "detail": m.group("breadth_detail").strip(),
                })
    return result


def build_transcript_text(messages):
    """Reiner Text-Verlauf (Rolle: Text pro Zeile) -- fuer den LLM-Ernst-
    haftigkeits-Check UND als Basis fuer die lesbare Chat-Darstellung."""
    lines = []
    for msg in messages:
        text = _extract_text(msg.get("content")).strip()
        if not text:
            continue
        role_label = "Person" if msg.get("role") == "user" else "Sokra"
        lines.append(f"{role_label}: {text}")
    return "\n\n".join(lines)


JUDGE_SYSTEM_PROMPT = """Du bewertest ein Studien-Gespraech zwischen einer Testperson und einem KI-Assistenten (Sokra) zum Thema deutsche Waermewende. Beurteile NUR eine Frage: hat sich die Person ERNSTHAFT mit dem Thema auseinandergesetzt (auch kurz, skeptisch oder ablehnend ist ernsthaft), oder hat sie den Chatbot erkennbar nur getestet/trollt/unsinnige Eingaben gemacht, ohne inhaltlich mitzumachen?

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, keine weitere Erklaerung drumherum:
{"ernsthaft": true oder false, "begruendung": "ein bis zwei Saetze"}"""


def judge_seriousness(client, transcript_text):
    if not transcript_text.strip():
        return False, "Leerer oder nahezu leerer Dialog."
    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=300,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript_text[:15000]}],
        )
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return bool(data.get("ernsthaft")), str(data.get("begruendung", ""))
    except Exception as e:
        return False, f"Konnte nicht automatisch bewertet werden (Fehler: {e})"


def analyze_log(client, participant_id, raw_text):
    messages = json.loads(raw_text)
    positions = collect_ratified_positions(messages)
    complete = all(positions[dim] for dim in DIMENSION_ORDER)
    transcript_text = build_transcript_text(messages)
    serious, serious_reasoning = judge_seriousness(client, transcript_text)

    return {
        "participant_id": participant_id,
        "hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "message_count": len(messages),
        "complete": complete,
        "serious": serious,
        "serious_reasoning": serious_reasoning,
        "positions": positions,
        "messages": messages,
    }


def refresh_all(progress_callback=None):
    """Prueft alle SurfDrive-Logs, verarbeitet NUR neue/geaenderte (Hash-
    Vergleich gegen den Cache) -- unveraenderte Logs werden nicht erneut
    heruntergeladen/analysiert."""
    client = Anthropic()
    filenames = list_surfdrive_logs()
    total = len(filenames)
    processed, skipped, failed = 0, 0, 0

    for i, fname in enumerate(filenames):
        participant_id = fname[len("gpr_"):-len(".json")]
        if progress_callback:
            progress_callback(i, total, participant_id)
        try:
            raw_text = download_surfdrive_log_raw(fname)
            new_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            cached = load_cached(participant_id)
            if cached and cached.get("hash") == new_hash:
                skipped += 1
                continue
            result = analyze_log(client, participant_id, raw_text)
            save_cache(participant_id, result)
            processed += 1
        except Exception as e:
            failed += 1
            st.warning(f"Fehler bei {fname}: {e}")

    return {"total": total, "processed": processed, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

st.set_page_config(page_title="Aigora – Log-Analyse", layout="wide")
st.title("📋 Aigora – Log-Analyse")

with st.sidebar:
    st.subheader("Profile")
    if st.button("🔄 Neue/geänderte Logs verarbeiten", use_container_width=True):
        progress_bar = st.progress(0, text="Starte...")

        def _progress(i, total, pid):
            progress_bar.progress((i + 1) / max(total, 1), text=f"Prüfe {pid}...")

        summary = refresh_all(progress_callback=_progress)
        progress_bar.empty()
        st.success(
            f"Fertig: {summary['processed']} neu verarbeitet, "
            f"{summary['skipped']} unverändert übersprungen, "
            f"{summary['failed']} Fehler (von {summary['total']} Logs insgesamt)."
        )

    participant_ids = list_cached_participant_ids()
    if not participant_ids:
        st.info("Noch keine Profile im Cache. Zuerst oben aktualisieren.")
        st.stop()

    selected = st.radio("Profil auswählen", participant_ids, label_visibility="collapsed")

data = load_cached(selected)

st.header(f"Profil: {selected}")

col1, col2 = st.columns(2)
with col1:
    if data["complete"]:
        st.success("✅ Vollständig -- alle 6 Dimensionen ratifiziert")
    else:
        missing = [DIMENSION_LABELS[d] for d in DIMENSION_ORDER if not data["positions"][d]]
        st.warning(f"⚠️ Unvollständig -- fehlend: {', '.join(missing)}")
with col2:
    if data["serious"]:
        st.success(f"✅ Ernsthaft -- {data['serious_reasoning']}")
    else:
        st.warning(f"⚠️ Möglicherweise nicht ernsthaft -- {data['serious_reasoning']}")

st.caption(f"{data['message_count']} Nachrichten insgesamt")

st.divider()
st.subheader("Ratifizierte Positionen")
for dim in DIMENSION_ORDER:
    entries = data["positions"][dim]
    with st.expander(f"{'✅' if entries else '⚪'} {DIMENSION_LABELS[dim]} ({len(entries)})", expanded=bool(entries)):
        if not entries:
            st.caption("Keine ratifizierten Positionen.")
        for entry in entries:
            st.markdown(f"**{entry['position']}**")
            st.caption(f"Begründung: {entry['reasoning']}")
            detail_suffix = f" — {entry['detail']}" if entry["detail"] else ""
            st.caption(f"Überzeugung: {entry['breadth']}/5{detail_suffix}")
            st.divider()

st.divider()
st.subheader("Gesamter Dialog")
_RATIFIED_STRIP = re.compile(r"<ratified.*?</ratified>", re.DOTALL)
for msg in data["messages"]:
    text = _extract_text(msg.get("content"))
    text = _RATIFIED_STRIP.sub("", text).strip()
    if not text:
        continue
    role = msg.get("role")
    with st.chat_message("assistant" if role == "assistant" else "user"):
        st.markdown(text)
