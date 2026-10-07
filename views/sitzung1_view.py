"""
views/sitzung1_view.py

Sitzung 1 (GPR-Dialog). Inhaltliche Logik unveraendert aus gpr_core.py
importiert (Prompt, Tools, Hilfsfunktionen) -- diese Datei kuemmert sich
nur um Darstellung + Speicherung.

Gegenueber der urspruenglichen Standalone-Version (streamlit_app.py, altes
Repo) zwei Aenderungen:
1. Kein eigenes Login mehr -- participant_id kommt von der Phasen-Huelle
   (streamlit_app.py -> access_control.py).
2. Speicherung ueber SurfDrive statt lokaler Festplatte, da Streamlit
   Cloud lokale Dateien nicht dauerhaft ueber Neustarts hinweg behaelt.
   Deterministischer Dateiname pro Teilnehmer (nicht Zeitstempel) --
   dadurch funktioniert "Sitzung fortsetzen" automatisch: beim Aufruf von
   render() wird zuerst versucht, ein bestehendes Log zu laden, bevor eine
   neue (kostenpflichtige) Begruessung generiert wird.
"""

import json
import os
import re
import streamlit as st

from gpr_core import (
    TOOLS, call_search_tool, serialize_content,
    get_system_block, with_cache_breakpoint,
)
import surfdrive_storage as sd
from model_config import get_client, get_model_name, filter_tools
from branding import AGENT_AVATAR, DIMENSIONS_GRAPHIC_PATH, dimensions_graphic_available
from phasen import PHASEN
from survey_gate import render_postsurvey_link
from voice_io import (
    transcribe_audio, synthesize_speech,
    GERMAN_VOICES, TTS_RATES, DEFAULT_TTS_VOICE, DEFAULT_TTS_RATE,
)

client = get_client()

# ---------------------------------------------------------------------
# FESTE BEGRUESSUNGSNACHRICHT (ENTWURF -- zur Ratifizierung durch der Autor)
#
# Bewusst NICHT vom Modell generiert, sondern hartkodiert: garantiert
# wortgleich fuer alle Teilnehmenden (methodisch wichtig fuer
# Vergleichbarkeit), keine Sampling-Varianz von Zug zu Zug. Wird als
# ERSTE Nachricht direkt in den Verlauf geschrieben, OHNE einen Modell-
# Aufruf zu verbrauchen -- der erste echte Modell-Aufruf passiert erst,
# wenn die Person auf die abschliessende Zeit-/Tiefe-Frage antwortet
# (NICHT mehr auf eine inhaltliche Eroeffnungsfrage -- siehe unten).
#
# GEAENDERT (siehe Chatverlauf/CHANGELOG_SOKRA.md): war vorher ein einziger
# langer Block, der SOFORT die inhaltliche Eroeffnungsfrage stellte -- kam
# als "erschlagend" zurueck. Jetzt bewusst weicher gestaffelt: erst kurze
# Begruessung+Ueberblick, DANN Framework+Regeln, DANN die neue Zeit-/Tiefe-
# Frage als Abschluss -- ALL DAS bleibt vollstaendig hartkodiert und
# wortgleich fuer alle Teilnehmenden, wie bisher. NUR die inhaltliche Frage
# ("was faellt dir ein") stellt jetzt SOKRA SELBST im ersten echten Modell-
# Zug (siehe Abschnitt 9 in gpr_core.py), NICHT mehr hier hartkodiert --
# weil Sokra davor kurz auf die Zeit-/Tiefe-Antwort der Person eingehen
# soll, was sich nicht vorab wortgleich skripten laesst. Das ist der
# einzige Teil, der nicht mehr fuer alle identisch ist.
# ---------------------------------------------------------------------

_WELCOME_PART1 = """Hallo und herzlich willkommen bei Aigora!

Ich bin Sokra, dein Assistent für diese Studie zur deutschen Wärmewende (Heizungswende) – eigens für diese Anwendung entwickelt, mit einer sorgfältig und ausgewogen zusammengestellten Wissensbasis im Hintergrund.

In dieser Sitzung entwickelst du Schritt für Schritt deine eigene, gut durchdachte Position zur Wärmewende – keine vorgefertigte Meinung, sondern wirklich deine. Dabei unterstütze ich dich mit Information und gezielten Rückfragen, ohne dich in eine bestimmte Richtung zu drängen."""

_WELCOME_PART2 = """**Wie läuft das ab?**

Wir gehen dabei sechs Politik-Bausteine durch, angelehnt an ein etabliertes politikwissenschaftliches Modell (Cashore & Howlett, 2007): drei zum Zweck – was soll erreicht werden – und drei zu den Mitteln – wie soll es erreicht werden, jeweils vom Groben/Abstrakten zum Konkreten. Die Grafik gibt dir einen Überblick:

1. **Übergeordnete Ziele** – Welches gesellschaftliche Ergebnis soll die Wärmewende am Ende bewirken? Die grundsätzliche Werte-Ebene.
2. **Konkrete Ziele** – Was soll die Politik ganz konkret erreichen, die Zielgröße, die so im Gesetz steht?
3. **Zwischenziele** – Welche granularen Zwischenschritte sind dafür nötig?
4. **Umsetzungslogik** – Bevor ein konkretes Instrument feststeht: welche grundsätzliche Steuerungsphilosophie soll gelten – eher verbindliche Vorgaben, eher Freiwilligkeit, oder eher der Markt? Diese Weichenstellung prägt alles Weitere.
5. **Instrumententyp** – Welche Art von Werkzeug soll das umsetzen – Förderung, Steuer/Abgabe, gesetzliche Vorschrift, oder Aufklärung/Beratung?
6. **Feinausgestaltung** – Ist das Werkzeug gewählt: wie genau wird es justiert, z.B. wie hoch ein Fördersatz oder eine Abgabe ausfällt? Oft entscheidet gerade dieses Detail über die reale Wirkung.

Bei jeder Ebene bekommst du zu Beginn eine kurze Übersicht mit den wichtigsten Diskussionspunkten – das sind bewusst kuratierte Denkanstöße, keine abschließende Liste, du darfst jederzeit darüber hinausgehen. Tempo, Tiefe und Reihenfolge bestimmst du selbst, und Rückfragen sind jederzeit willkommen.

**Sprechen statt tippen:** Du kannst deine Antworten auch einsprechen (Mikrofon-Symbol unten) – die Aufnahme wird zur Umwandlung in Text an Azure AI Speech (Microsoft) übertragen, datenschutzkonform ohne dauerhafte Speicherung. Vorlesen lassen kannst du dir meine Antworten ebenso, Stimme und Tempo kannst du dabei frei wählen. Oft noch schneller und zuverlässiger ist die Diktierfunktion deines eigenen Geräts (Windows: Win+H, Mac: Diktat in den Systemeinstellungen) – die schreibt direkt sichtbar ins Textfeld. Und ganz klassisch eintippen geht natürlich genauso.

**Dein Fortschritt im Blick:** Am linken Rand findest du eine ein-/ausklappbare Übersicht der sechs Ebenen – auf einen Blick siehst du, was schon abgeschlossen ist und was noch aussteht, und kannst deine bisherigen Positionen dort jederzeit nachlesen.

Ein gutes Gespräch lebt von Perspektivenreichtum und guter Information – frag mich also jederzeit alles zur Wärmewende, das dich interessiert, ich steige auch gerne tief in ein Thema ein. Rückfragen, gemeinsam Nachdenken, Gedanken einfach mal laut ausprobieren – dafür bin ich da, das ist ausdrücklich erwünscht, nicht nur geduldet.

Damit ich mich darauf einstellen kann: **Wie viel Zeit hast du heute ungefähr, und möchtest du eher zügig durch alle sechs Ebenen, oder lieber in Ruhe und mit mehr Tiefe?** Es gibt hier kein Falsch – auch mehrere Sitzungen sind möglich, dein Fortschritt wird automatisch gespeichert."""

FIXED_WELCOME_FULL = _WELCOME_PART1 + "\n\n" + _WELCOME_PART2

LOG_FOLDER = "aigora_logs"


def _log_path(participant_id: str) -> str:
    return f"{LOG_FOLDER}/gpr_{participant_id}.json"


def _load_existing_session(participant_id: str):
    """Versucht, ein bestehendes Log von SurfDrive zu laden (Sitzungs-
    Fortsetzung). Gibt None zurueck, wenn keins existiert oder das Log
    beschaedigt ist -- in beiden Faellen beginnt eine neue Sitzung, statt
    mit einem Fehler abzubrechen."""
    raw = sd.download_text(_log_path(participant_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return [{"role": m["role"], "content": m["content"]} for m in data]
    except (ValueError, KeyError, TypeError):
        return None


def _save_session(participant_id: str, messages) -> None:
    clean_log = [
        {"role": m["role"], "content": serialize_content(m["content"])}
        for m in messages
    ]
    ok = sd.upload_text(_log_path(participant_id), json.dumps(clean_log, ensure_ascii=False, indent=2))
    st.session_state["_s1_save_failed"] = not ok


def _get_agent_response() -> None:
    """Ruft das Modell auf, verarbeitet Tool-Aufrufe. Faengt Verbindungs-/
    API-Fehler sichtbar ab (frueherer Bug: stilles leeres Chatfeld bei
    Verbindungsabbruch).

    WICHTIG: Sobald eine Assistant-Nachricht mit einem `tool_use`-Block
    angehaengt wird (naechste Zeile im while-Loop), VERLANGT die Anthropic-
    API zwingend ein passendes `tool_result` im naechsten User-Turn -- fehlt
    das, lehnt die API JEDEN weiteren Aufruf mit diesem Verlauf dauerhaft ab
    (nicht nur einmalig), und da dieser Verlauf nach jedem Zug auf SurfDrive
    gespeichert wird, wuerde ein Fehler in call_search_tool sonst die ganze
    Sitzung permanent blockieren. Deshalb bekommt JEDER tool_use-Block hier
    IMMER ein tool_result, auch im Fehlerfall (mit Fehlertext statt Ergebnis)."""
    try:
        response = client.messages.create(
            model=get_model_name(), max_tokens=4096, system=get_system_block(), tools=filter_tools(TOOLS),
            messages=with_cache_breakpoint(st.session_state.s1_messages),
        )

        while response.stop_reason == "tool_use":
            st.session_state.s1_messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "search_corpus":
                    try:
                        with st.spinner(f"Durchsuche Wissensbasis: '{block.input['query']}'..."):
                            result_text = call_search_tool(block.input)
                    except Exception as e:
                        result_text = f"Suche fehlgeschlagen ({e}). Bitte ohne dieses Suchergebnis antworten."
                else:
                    result_text = "Unbekanntes Tool, keine Ausführung möglich."
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            if tool_results:
                st.session_state.s1_messages.append({"role": "user", "content": tool_results})

            response = client.messages.create(
                model=get_model_name(), max_tokens=4096, system=get_system_block(), tools=filter_tools(TOOLS),
                messages=with_cache_breakpoint(st.session_state.s1_messages),
            )

        if response.stop_reason == "max_tokens":
            st.warning("Hinweis: Antwort wurde durch ein Längenlimit abgeschnitten.")

        # Nur die Text-Bloecke der finalen Antwort speichern, als EIN
        # zusammenhaengender String -- nicht die rohe Block-Liste. Grund
        # (siehe Bug-Report "zerschnipselte Antwort"): claude-sonnet-5
        # liefert bei dieser Art Zuegen manchmal mehrere separate Text-
        # Bloecke (vermutlich durch Denk-Unterbrechungen dazwischen), die
        # inhaltlich zusammengehoeren, aber beim gerundeten Zusammenfuegen
        # mit Absatz-Umbruch dazwischen wie unpassende Absaetze wirken UND
        # so vorgelesen werden. Direktes Aneinanderhaengen (kein Trenner)
        # behandelt sie als das, was sie sind: EIN durchgehender Text.
        # Ein String statt Block-Liste ist fuer die Anthropic-API beim
        # naechsten Aufruf genauso gueltig wie die Rohstruktur.
        final_text = "".join(
            getattr(block, "text", "") for block in response.content
            if getattr(block, "type", None) == "text"
        )
        st.session_state.s1_messages.append({"role": "assistant", "content": final_text})

    except Exception as e:
        st.error(
            f"Fehler bei der Verbindung zum Modell: {e}\n\n"
            f"Mögliche Ursachen: Internetverbindung, API-Key, oder ein "
            f"vorübergehendes Problem beim Anbieter. Bitte kurz warten und erneut versuchen."
        )


def _strip_ratified(text: str) -> str:
    """Blendet NUR den <ratified>-Block aus (fuer die Datenauswertung, nicht
    fuer Teilnehmende) -- alles davor und danach bleibt sichtbar. Regex
    ersetzt NUR den getroffenen Block, schneidet nicht faelschlich alles
    danach ab (frueherer Bug, siehe alte streamlit_app.py)."""
    return re.sub(r"<ratified.*?</ratified>", "", text, flags=re.DOTALL).strip()


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # Symbole, Piktogramme, Emoticons, Transport etc.
    "\U00002600-\U000027BF"  # Misc Symbole/Dingbats (u.a. Zwinkersmiley-Familie)
    "\U0001F1E0-\U0001F1FF"  # Flaggen
    "\U00002190-\U000021FF"  # Pfeile
    "]+", flags=re.UNICODE,
)


def _strip_links_for_speech(text: str) -> str:
    """Bereinigt Text fuer die Sprachausgabe (TTS): Markdown-Links "[Text]
    (URL)" werden zu nur "Text", Markdown-Formatierungszeichen (**fett**,
    *kursiv*, `code`, # Ueberschrift) und Emojis werden entfernt, statt
    woertlich vorgelesen zu werden ("Sternchen Sternchen", "Zwinkersmiley").
    Die sichtbare Chat-Darstellung ist davon nicht betroffen (nutzt
    _render_message, nicht diese Funktion) -- Formatierung/Links bleiben
    dort normal erhalten."""
    text = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", text)
    text = text.replace("`", "").replace("#", "")
    text = _EMOJI_PATTERN.sub("", text)
    return text


def _extract_plain_text(content) -> str:
    """Zieht den reinen, fuer die Person sichtbaren Antworttext aus einer
    Nachricht (String oder Block-Liste) -- fuer die Sprachausgabe (TTS),
    ohne den maschinenlesbaren <ratified>-Block vorzulesen und ohne rohe
    Links (siehe _strip_links_for_speech)."""
    if isinstance(content, str):
        return _strip_links_for_speech(_strip_ratified(content))
    if isinstance(content, list):
        parts = []
        for block in content:
            text = getattr(block, "text", None) if hasattr(block, "text") else (
                block.get("text") if isinstance(block, dict) else None
            )
            if text:
                parts.append(text)
        return _strip_links_for_speech(_strip_ratified("".join(parts)))
    return ""


def _render_message(role: str, text: str, show_audio: bool = False) -> None:
    display_text = _strip_ratified(text)
    if not display_text:
        return
    avatar = AGENT_AVATAR if role == "assistant" else None
    with st.chat_message("assistant" if role == "assistant" else "user", avatar=avatar):
        if show_audio and role == "assistant":
            _render_audio_player()
        st.markdown(display_text)


def _render_fixed_welcome(show_audio: bool = False) -> None:
    """Zeigt die feste Begruessungsnachricht MIT eingebetteter 6-Dimensionen-
    Grafik zwischen den beiden Textteilen. Die Grafik wird nur angezeigt,
    wenn die Datei bereits im Repo liegt (siehe branding.py) -- fehlt sie
    noch, erscheint einfach nur der Text, ohne Fehler."""
    with st.chat_message("assistant", avatar=AGENT_AVATAR):
        if show_audio:
            _render_audio_player()
        st.markdown(_WELCOME_PART1)
        if dimensions_graphic_available():
            st.image(DIMENSIONS_GRAPHIC_PATH, use_container_width=True)
        st.markdown(_WELCOME_PART2)


DIMENSION_ORDER = ["Goals", "Objectives", "Settings", "InstrumentLogic", "Tools", "Calibrations"]
DIMENSION_LABELS = {
    "Goals": "Übergeordnete Ziele",
    "Objectives": "Konkrete Ziele",
    "Settings": "Zwischenziele",
    "InstrumentLogic": "Umsetzungslogik",
    "Tools": "Instrumententyp",
    "Calibrations": "Feinausgestaltung",
}

_RATIFIED_RE = re.compile(
    r'<ratified dimension="(?P<dim>\w+)">\s*'
    r'<position>(?P<position>.*?)</position>\s*'
    r'<reasoning>(?P<reasoning>.*?)</reasoning>\s*'
    r'<breadth>(?P<breadth>\d)</breadth>\s*'
    r'<breadth_detail>(?P<detail>.*?)</breadth_detail>\s*'
    r'</ratified>',
    re.DOTALL,
)


def _collect_ratified_positions(messages) -> dict:
    """Liest alle bisher ratifizierten Positionen direkt aus dem
    Nachrichtenverlauf aus (keine separate Datenhaltung noetig, die
    <ratified>-Bloecke stehen ja schon drin) -- gruppiert nach Dimension,
    da eine Dimension seit der Mehrfachpositionen-Regel (siehe
    CHANGELOG_SOKRA.md) mehrere Eintraege haben kann."""
    result = {dim: [] for dim in DIMENSION_ORDER}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            raw = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                text = getattr(block, "text", None) if hasattr(block, "text") else (
                    block.get("text") if isinstance(block, dict) else None
                )
                if text:
                    parts.append(text)
            raw = "".join(parts)
        else:
            continue
        for m in _RATIFIED_RE.finditer(raw):
            dim = m.group("dim")
            if dim in result:
                result[dim].append({
                    "position": m.group("position").strip(),
                    "reasoning": m.group("reasoning").strip(),
                    "breadth": m.group("breadth").strip(),
                    "detail": m.group("detail").strip(),
                })
    return result


def _render_sidebar_progress() -> None:
    """Minimale, immer sichtbare Fortschrittsuebersicht in der Seitenleiste:
    Haekchen fuer erledigte Dimensionen, Pfeil fuer die (grob geschaetzte)
    aktuelle -- die erste noch unerledigte Dimension in der festen
    Reihenfolge. Aufklappen zeigt die ratifizierten Positionen im
    Originalwortlaut mit Ueberzeugungswert, wie von der Autor gewuenscht."""
    positions = _collect_ratified_positions(st.session_state.get("s1_messages", []))
    st.sidebar.markdown("### 📊 Dein Fortschritt")
    st.sidebar.caption(
        "👇 Klicke auf eine Ebene zum Auf-/Zuklappen — dort siehst du, was schon "
        "besprochen ist, und kannst deine bisherigen Positionen nachlesen."
    )
    current_marked = False
    for dim in DIMENSION_ORDER:
        entries = positions[dim]
        if entries:
            icon = "✅"
        elif not current_marked:
            icon = "👉"
            current_marked = True
        else:
            icon = "⚪"
        # Die aktuelle Ebene ist beim ersten Anzeigen automatisch aufgeklappt
        # (nicht nur per Caption erklaert) -- soll neuen Nutzer:innen sofort
        # zeigen, dass/wie das klickbar ist, statt es nur zu behaupten.
        with st.sidebar.expander(f"**{icon} {DIMENSION_LABELS[dim]}**", expanded=(icon == "👉")):
            if not entries:
                st.caption("Noch nicht besprochen.")
            for entry in entries:
                st.markdown(f"**{entry['position']}**")
                st.caption(f"Begründung: {entry['reasoning']}")
                detail_suffix = f" — {entry['detail']}" if entry["detail"] else ""
                st.caption(f"Überzeugung: {entry['breadth']}/5{detail_suffix}")
                st.divider()


def _render_audio_player() -> None:
    """Zeigt den Sprachausgabe-Player fuer die aktuell letzte Assistant-
    Nachricht (falls vorhanden) -- wird von _render_message/
    _render_fixed_welcome INNERHALB der Sprechblase aufgerufen, VOR dem
    Text, damit der Player oberhalb steht statt darunter (Rueckmeldung).
    Autoplay standardmaessig an (soll IMMER vorlesen, ausser per Checkbox
    deaktiviert), aber per Hash-Vergleich (statt einem einfachen True/False-
    Flag) fest daran gebunden, WELCHER Audio-Inhalt schon automatisch
    abgespielt wurde -- verhindert zuverlaessig, dass derselbe Ton bei einem
    Rerun ein zweites Mal ueberlappend autoplay't (Bug-Report: zwei Stimmen
    gleichzeitig)."""
    if not st.session_state.get("_s1_tts_enabled", True):
        return
    audio_bytes = st.session_state.get("_s1_last_audio")
    if audio_bytes:
        audio_hash = hash(audio_bytes)
        autoplay = st.session_state.get("_s1_autoplayed_hash") != audio_hash
        st.audio(audio_bytes, format="audio/mp3", autoplay=autoplay)
        st.session_state["_s1_autoplayed_hash"] = audio_hash
    elif "_s1_last_voice_error" in st.session_state:
        detail = st.session_state.pop("_s1_last_voice_error", "")
        st.warning(
            "Die Sprachausgabe konnte nicht erzeugt werden."
            + (f"\n\nDetails (nur für Debugging sichtbar): `{detail}`" if detail else "")
        )


def _regenerate_last_audio() -> None:
    """Erzeugt die Sprachausgabe der letzten Antwort neu mit der gerade
    gewaehlten Stimme/Tempo -- als on_change-Callback der beiden Dropdowns,
    damit eine Aenderung sofort hoerbar wird, statt erst bei der naechsten
    neuen Nachricht zu wirken (frueherer Bug: Stimme/Tempo liessen sich
    waehrend/nach dem Abspielen scheinbar nicht mehr aendern)."""
    messages = st.session_state.get("s1_messages") or []
    if not messages or messages[-1]["role"] != "assistant" or not st.session_state.get("_s1_tts_enabled"):
        return
    answer_text = _extract_plain_text(messages[-1]["content"])
    voice = GERMAN_VOICES[st.session_state["_s1_tts_voice_label"]]
    rate = TTS_RATES[st.session_state["_s1_tts_rate_label"]]
    st.session_state["_s1_last_audio"] = synthesize_speech(answer_text, voice=voice, rate=rate)


def render(participant_id: str) -> None:
    phase = PHASEN["sitzung1"]
    st.header(f"{phase['icon']} {phase['titel']}")
    st.caption(phase["beschreibung"])

    # Sprachausgabe-Player optisch ans Aigora-Gruen angleichen, statt dem
    # Standard-Grau des Browsers -- accent-color faerbt Play-Knopf/Regler in
    # Chromium-Browsern (Edge/Chrome, die meistgenutzten), zusaetzlich
    # abgerundete Ecken/Schatten passend zum Rest des Interfaces.
    st.markdown(
        """
        <style>
        audio {
            width: 100%;
            accent-color: #2e7d32;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.15);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "s1_messages" not in st.session_state:
        existing = _load_existing_session(participant_id)
        if existing:
            st.session_state.s1_messages = existing
            st.info("Deine bisherige Sitzung wurde geladen — du kannst dort weitermachen, wo du aufgehört hast.")
        else:
            st.session_state.s1_messages = [{"role": "assistant", "content": FIXED_WELCOME_FULL}]
            _save_session(participant_id, st.session_state.s1_messages)

        # Begruessungs-Audio erzeugen, wenn die Begruessung noch die EINZIGE
        # Nachricht ist -- gilt fuer brandneue Sitzungen GENAUSO wie fuer eine
        # geladene Sitzung, die noch nicht ueber die Begruessung hinausgekommen
        # ist (frueherer Bug: stand nur im "brandneu"-Zweig, wurde bei jedem
        # erneuten Laden derselben, noch unbeantworteten Begruessung
        # uebersprungen). Stimm-/Tempo-Dropdowns existieren an dieser Stelle im
        # Code noch nicht (werden erst weiter unten gerendert), daher bewusst
        # die Standardwerte statt einer noch nicht vorhandenen Auswahl.
        if (len(st.session_state.s1_messages) == 1
                and st.session_state.s1_messages[0].get("content") == FIXED_WELCOME_FULL):
            st.session_state["_s1_last_audio"] = synthesize_speech(
                _strip_links_for_speech(_strip_ratified(FIXED_WELCOME_FULL)),
                voice=DEFAULT_TTS_VOICE, rate=DEFAULT_TTS_RATE,
            )

    if st.session_state.get("_s1_save_failed"):
        st.warning(
            "Die letzte Speicherung ist fehlgeschlagen (z.B. kurzes Netzwerkproblem). "
            "Deine Antworten bleiben in dieser Sitzung erhalten und werden beim nächsten "
            "erfolgreichen Speichern gesichert — bitte diesen Tab bis dahin nicht schließen."
        )

    _render_sidebar_progress()
    with st.sidebar:
        render_postsurvey_link(participant_id)  # unaufdringlich, nicht erzwungen -- Person entscheidet selbst, wann "fertig"

    for i, msg in enumerate(st.session_state.s1_messages):
        content = msg["content"]
        is_last = i == len(st.session_state.s1_messages) - 1

        # Die feste Begruessung (egal ob frisch erzeugt oder aus einem
        # bestehenden Log geladen) bekommt IMMER die Spezialdarstellung
        # mit Grafik, nie die generische Textdarstellung.
        if i == 0 and msg["role"] == "assistant" and isinstance(content, str) and content == FIXED_WELCOME_FULL:
            _render_fixed_welcome(show_audio=is_last)
            continue

        if isinstance(content, str):
            _render_message(msg["role"], content, show_audio=is_last)
        elif isinstance(content, list):
            # Nachrichten mit tool_use-Block sind interne Zwischenschritte
            # (bereits live als Spinner gezeigt) -- nicht nochmal als
            # eigene Sprechblase anzeigen, sonst zerreisst das eine
            # zusammenhaengende Antwort in Bruchstuecke.
            contains_tool_use = any(
                (block.get("type") == "tool_use" if isinstance(block, dict) else getattr(block, "type", None) == "tool_use")
                for block in content
            )
            if contains_tool_use:
                continue
            # Alle Text-Bloecke EINER Nachricht zu EINER Sprechblase
            # zusammenfassen, statt pro Block eine eigene Blase zu rendern --
            # sonst zerreisst eine zusammenhaengende Antwort in viele kleine
            # Haeppchen (siehe Bug-Report: passiert v.a., wenn die Antwort
            # mehrere separate Text-Bloecke enthaelt, z.B. durch Extended
            # Thinking zwischen den Textabschnitten).
            texts = [
                (getattr(block, "text", None) if hasattr(block, "text") else (
                    block.get("text") if isinstance(block, dict) else None
                ))
                for block in content
            ]
            combined = "".join(t for t in texts if t)
            if combined:
                _render_message(msg["role"], combined, show_audio=is_last)

    # Alle 6 Dimensionen ratifiziert -> Sitzung inhaltlich abgeschlossen,
    # Nachbefragung prominent im Chat anbieten (zusaetzlich zum
    # unaufdringlichen Sidebar-Link, der davor schon die ganze Zeit da war).
    positions = _collect_ratified_positions(st.session_state.s1_messages)
    if all(positions[dim] for dim in DIMENSION_ORDER):
        render_postsurvey_link(participant_id)

    tts_col1, tts_col2, tts_col3 = st.columns([2, 2, 2])
    with tts_col1:
        st.checkbox("🔊 Antworten vorlesen", value=True, key="_s1_tts_enabled")
    with tts_col2:
        st.selectbox(
            "Stimme", options=list(GERMAN_VOICES.keys()),
            index=list(GERMAN_VOICES.values()).index(DEFAULT_TTS_VOICE),
            key="_s1_tts_voice_label", label_visibility="collapsed",
            on_change=_regenerate_last_audio,
        )
    with tts_col3:
        st.selectbox(
            "Tempo", options=list(TTS_RATES.keys()),
            index=list(TTS_RATES.values()).index(DEFAULT_TTS_RATE),
            key="_s1_tts_rate_label", label_visibility="collapsed",
            on_change=_regenerate_last_audio,
        )

    user_input = None

    # Sprachaufnahme jetzt ueber Streamlits eingebaute Audio-Unterstuetzung
    # direkt im Chat-Eingabefeld (accept_audio=True) statt einem separaten
    # audio_input-Widget + eigenem Entwurfs-Textfeld weiter unten auf der
    # Seite. Zwei Vorteile: (1) die transkribierte Nachricht landet direkt
    # im ECHTEN Eingabefeld zur Kontrolle/Bearbeitung, nicht in einem
    # zusaetzlichen Feld (Rueckmeldung), (2) umgeht den bisherigen
    # Scroll-nach-oben-Bug des separaten audio_input-Widgets komplett, da
    # kein eigenes Recorder-Widget mehr extra gemountet wird. Muster laut
    # Streamlits eigener Doku (chat-ui.md, "Dictation with speech-to-text"):
    # bei reiner Audio-Eingabe (kein getippter Text) wird transkribiert und
    # der Text per session_state zurueck ins Eingabefeld gesetzt, statt
    # sofort abzuschicken -- die Person sieht/bearbeitet den erkannten Text
    # dort und schickt ihn per erneutem Enter/Klick wirklich ab.
    #
    # WICHTIG: Streamlit verbietet, st.session_state[key] fuer ein Widget zu
    # setzen, NACHDEM es in diesem Durchlauf bereits instanziiert wurde (hier:
    # nachdem st.chat_input(key="_s1_chat_input", ...) schon gelaufen ist) --
    # das wirft eine StreamlitAPIException, auch wenn direkt danach
    # st.rerun() folgt. Deshalb wird der transkribierte Text zunaechst unter
    # einem ANDEREN Key zwischengespeichert und erst GANZ OBEN im naechsten
    # Durchlauf (siehe render(), vor dem Widget-Aufruf) ins Eingabefeld
    # uebertragen.
    if "_s1_pending_transcript" in st.session_state:
        st.session_state["_s1_chat_input"] = st.session_state.pop("_s1_pending_transcript")

    prompt = st.chat_input(
        "Deine Antwort... (oder Mikrofon-Symbol zum Einsprechen)",
        accept_audio=True, key="_s1_chat_input",
    )
    if prompt:
        if prompt.text:
            user_input = prompt.text
        elif prompt.audio:
            with st.spinner("Transkribiere deine Sprachaufnahme..."):
                transcribed = transcribe_audio(prompt.audio.getvalue())
            if transcribed:
                st.session_state["_s1_pending_transcript"] = transcribed
                st.rerun()
            else:
                detail = st.session_state.get("_s1_last_voice_error", "")
                st.warning(
                    "Die Sprachaufnahme konnte nicht transkribiert werden."
                    + (f"\n\nDetails (nur für Debugging sichtbar): `{detail}`" if detail else "")
                )

    if user_input:
        st.session_state.s1_messages.append({"role": "user", "content": user_input})
        with st.spinner("Sokra denkt nach..."):
            _get_agent_response()
            if st.session_state.get("_s1_tts_enabled"):
                answer_text = _extract_plain_text(st.session_state.s1_messages[-1]["content"])
                voice = GERMAN_VOICES[st.session_state["_s1_tts_voice_label"]]
                rate = TTS_RATES[st.session_state["_s1_tts_rate_label"]]
                st.session_state["_s1_last_audio"] = synthesize_speech(answer_text, voice=voice, rate=rate)
            else:
                st.session_state["_s1_last_audio"] = None
        _save_session(participant_id, st.session_state.s1_messages)
        st.rerun()
