"""
views/sitzung2_view.py  (v6)

Layout: Top-Navigationsband (3 Phasen) im Hauptbereich, Sokra dauerhaft in
der Sidebar (Chat inkl. TTS-Wiedergabe pro Nachricht + Mikrofon-Diktat).
Alle Erklaertexte (Begruessung, Streitfrage, Uebersicht, Sichtweisen-
Kernaussage/Bandbreite) haben einen kleinen Vorlesen-Button direkt davor.

Fixes ggue. v5:
- speak_text() existierte nicht -- Absturz beim Vorlesen-Button in der
  Begruessung. Ersetzt durch synthesize_speech() + st.audio().
- _screen_phase0 rief _sokra_call() mit undefinierten Variablen auf --
  Absturz beim "An Sokra senden"-Button auf der Konsenspunkte-Seite.
- Mikrofon-Diktat schrieb Text in ein Textfeld, das Streamlit wegen der
  bestehenden Widget-Semantik (value= wird nach dem ersten Rendern
  ignoriert) nie tatsaechlich aktualisiert hat. Jetzt: Session-State wird
  VOR der Widget-Erzeugung gesetzt, kein value=-Parameter mehr noetig.
"""

import json
import datetime
import os
import re
import traceback

import streamlit as st

try:
    from sokra_s2_prompt import (
        SOKRA_S2_SYSTEM_PROMPT,
        build_global_context,
        build_diskutieren_msg,
        get_rag_context,
    )
    _SOKRA_OK = True
except ImportError:
    _SOKRA_OK = False

try:
    from session2_bewertungen import (
        laden, speichern, markiere_s1_status,
        lager_bewerten, standpunkt_bewerten, kompromiss_speichern,
        diskurs_ueberspringen, abschliessen,
        stufe1_diskurse, stufe2_diskurse,
        eigene_positionen_finden, alle_standpunkt_ids,
    )
    _BEW_OK = True
except ImportError:
    _BEW_OK = False

try:
    from voice_io import synthesize_speech, transcribe_audio
    _TTS_OK = True
except ImportError:
    _TTS_OK = False

import surfdrive_storage as sd
from model_config import get_client, get_model_name
from branding import AGENT_AVATAR

client = get_client()

STRUCTURE_PATH = "data/session2_diskurse.json"
LOG_FOLDER = "aigora_logs_moda"
_SUBFOLDERS = ["s2_bewertungen", "s2_chat", "chat", "errorlog"]


@st.cache_resource
def _ensure_folders():
    sd.ensure_folder(LOG_FOLDER)
    for sub in _SUBFOLDERS:
        sd.ensure_folder(f"{LOG_FOLDER}/{sub}")
    return True


ZA_LABELS = {
    0: "– kein Urteil –",
    1: "stimme gar nicht zu",
    2: "stimme eher nicht zu",
    3: "teils / teils",
    4: "stimme eher zu",
    5: "stimme voll zu",
}
ZA_OPTIONS = [0, 1, 2, 3, 4, 5]

LAGER_FARBEN = ["#1a6b3c", "#2d7d9a", "#7b5ea7", "#b06a20"]
EIGEN_FARBE = "#d4380d"

ABSTR_FARBEN = {
    "Übergeordnete Ziele": "#1a6b3c",
    "Konkrete Ziele": "#2d7d9a",
    "Zwischenziele": "#5c6bc0",
    "Umsetzungslogik": "#7b5ea7",
    "Instrumententyp": "#b06a20",
    "Feinausgestaltung": "#9e3030",
}

BEGRUESSUNG = """Schön, dass du wieder dabei bist. Dank der regen Beteiligung in Phase 1 ist eine beträchtliche Menge wertvoller, politikreifer Vorschläge entstanden.

In vielen Punkten herrscht bereits Einigkeit, doch in anderen Aspekten braucht es Austausch und Kompromissfindung. Das Herzstück von Aigora, und von Demokratie selbst, ist der Diskurs. Diese Sitzung dient dazu, die Positionen der anderen zu verstehen, dich selbst zu positionieren und wo möglich Kompromisse zu finden. Dabei kommt es ganz auf dich an: deine Einschätzung, dein Verständnis, deine Kompromissvorschläge.

Die Debattenlandschaft ist vielfältig, aber du musst nicht alles bearbeiten. Das Pflichtprogramm in 30 bis 50 Minuten hat drei Schritte:

1. Einigkeit prüfen: Wo besteht bereits Übereinstimmung?
2. Eigene Debatten vertiefen: die Themen, zu denen du in Phase 1 schon eine Position eingebracht hast.
3. Hauptdebatten positionieren: die wichtigsten Streitfragen, die für belastbare politische Ergebnisse entscheidend sind.

Wer möchte, kann danach noch weitere Debatten erkunden. Das kostet etwas mehr Zeit, ermöglicht aber noch tiefere Einblicke.

Du entscheidest dabei selbst, wie tief du in eine Debatte einsteigst: es reicht, die grundlegenden Sichtweisen zu bewerten, also die großen Lager mit ihren jeweiligen Kernaussagen. Wer möchte, kann zusätzlich auf einzelne Positionen innerhalb einer Sichtweise eingehen und dort differenzierter zustimmen oder widersprechen.

Sokra begleitet dich durchgehend in der Seitenleiste: dort kannst du ihm jederzeit Fragen stellen, per Text oder per Sprache, und dir seine Antworten vorlesen lassen. Über das Menü oben kannst du jederzeit frei zwischen den drei Phasen und einzelnen Themen wechseln.

Bereit? Dann geht's los."""

# Modul-Konstante (nicht mehr lokale Variable in _screen_phase0), damit
# session2_prep_audio.py denselben Text fuer die Vorab-Audioerzeugung
# nutzen kann wie die Anzeige hier -- verhindert, dass Text und Audio
# irgendwann auseinanderlaufen.
PHASE0_INTRO_TEXT = (
    "Bisher gibt es keine Stimmen oder Vorschläge aus Phase 1, die diesen "
    "Punkten widersprechen. Nun überprüfen wir, ob hier wirklich Einigkeit "
    "besteht, oder ob Gegenpositionen nur noch nicht ausformuliert wurden. "
    "Lies die folgenden Aussagen durch und bestimme deine Zustimmung (1-5) "
    "sowie eventuelle Kommentare (Bedingung, Änderung, Kompromiss, Gegenargument)."
)


# ── SURFdrive ─────────────────────────────────────────────────────────

def _sd_path(kind, pid):
    return f"{LOG_FOLDER}/{kind}/{pid}.json"

def _sd_load(pid, kind):
    raw = sd.download_text(_sd_path(kind, pid))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None

def _sd_save(pid, kind, obj):
    ok = sd.upload_text(_sd_path(kind, pid), json.dumps(obj, ensure_ascii=False, indent=2))
    if not ok:
        st.session_state["_save_failed"] = True
    return ok

def _log_err(pid, ctx, exc):
    existing = _sd_load(pid, "errorlog") or []
    existing.append({
        "ts": datetime.datetime.now().isoformat(),
        "ctx": ctx, "err": str(exc),
        "tb": traceback.format_exc()[-500:],
    })
    sd.upload_text(_sd_path("errorlog", pid), json.dumps(existing, ensure_ascii=False))


# ── State ─────────────────────────────────────────────────────────────

def _init_state(pid):
    if "s2_init" in st.session_state:
        return
    existing = _sd_load(pid, "s2_bewertungen")
    st.session_state.s2_bew = existing or (laden(pid) if _BEW_OK else {"diskurse": {}})
    st.session_state.s2_chat = _sd_load(pid, "s2_chat") or []
    st.session_state.s2_slider = {}
    st.session_state.s2_screen = "begruessung"
    st.session_state.s2_diskurs_id = None
    st.session_state.s2_init = True


def _get_bew_flat():
    result = {}
    for d_id, d_bew in (st.session_state.s2_bew.get("diskurse") or {}).items():
        flat = {}
        for l_id, v in d_bew.get("lager_bewertungen", {}).items():
            flat[l_id] = v.get("wert", 0) if isinstance(v, dict) else int(v)
        for s_id, v in d_bew.get("standpunkt_bewertungen", {}).items():
            if isinstance(v, dict) and v.get("quelle") == "direkt":
                flat[s_id] = v.get("wert", 0)
        if flat:
            result[d_id] = flat
    return result


def _save_diskurs(pid, diskurs_id, stufe=1):
    if not _BEW_OK or not diskurs_id:
        return
    sliders = st.session_state.s2_slider.get(diskurs_id, {})
    data = _load_struktur()
    d = _diskurs_by_id(data.get("diskurse", []), diskurs_id)
    if not d:
        return
    for key, wert in sliders.items():
        if not isinstance(wert, int):
            continue
        if key.startswith("L_"):
            l_id = key[2:]
            lager = next((l for l in d.get("lager", []) if l["id"] == l_id), None)
            if lager:
                sp_ids = [sp["id"] for sp in lager.get("standpunkte", [])]
                kommentar = sliders.get(f"K_L_{l_id}", "")
                lager_bewerten(st.session_state.s2_bew, diskurs_id,
                               l_id, wert, sp_ids, kommentar, stufe)
        elif key.startswith("S_"):
            sp_id = key[2:]
            sp_kommentar = sliders.get(f"K_S_{sp_id}", "")
            standpunkt_bewerten(st.session_state.s2_bew, diskurs_id,
                                sp_id, wert, kommentar=sp_kommentar, stufe=stufe)
    komp = sliders.get("KOMP", "")
    if komp and _BEW_OK:
        kompromiss_speichern(st.session_state.s2_bew, diskurs_id, komp, stufe)
    speichern(st.session_state.s2_bew)
    _sd_save(pid, "s2_bewertungen", st.session_state.s2_bew)


# ── Datenladen ─────────────────────────────────────────────────────────

@st.cache_resource
def _load_struktur():
    with open(STRUCTURE_PATH, encoding="utf-8") as f:
        return json.load(f)

def _diskurs_by_id(diskurse, d_id):
    return next((d for d in diskurse if d["id"] == d_id), None)


# ── TTS: automatisches Intro-Audio (vorab erzeugt, siehe session2_prep_audio.py) ─

AUDIO_S2_DIR = "assets/audio_s2"


def _auto_vorlesen(dateiname: str, ident: str, autoplay_moeglich: bool = False):
    """Zeigt eine VORAB erzeugte Audio-Datei (kein Live-TTS-Warten) --
    nur fuer die statischen Einleitungstexte (Begruessung, Konsenspunkte-
    Intro, pro Diskurs Streitfrage+Uebersicht), die fuer alle Teilnehmenden
    identisch sind (siehe session2_prep_audio.py, einmalig ausgefuehrt,
    kein Aufruf pro Person).

    autoplay_moeglich: NUR bei der allerersten Begruessung True (auf
    Wunsch) -- bei allen anderen Einleitungen bleibt der Player sichtbar
    und manuell bedienbar (Start/Stop/Spulen ueber die nativen Browser-
    Kontrollen), startet aber NIE von selbst. Zusaetzlich respektiert,
    wenn erlaubt, die Checkbox "🔊 Automatisch vorlesen" aus der Sidebar.

    `ident` verhindert wiederholtes Autoplay bei jedem Rerun INNERHALB
    desselben Bildschirms (z.B. beim Bewegen eines Sliders) -- dieselbe
    Hash/Ident-Vergleichslogik wie in Sitzung 1 fuer den Autoplay-
    Ueberlappungs-Bug. Fehlt die Datei (z.B. noch nicht generiert), wird
    einfach nichts angezeigt, kein Fehler."""
    pfad = os.path.join(AUDIO_S2_DIR, dateiname)
    if not os.path.exists(pfad):
        return
    autoplay_erlaubt = autoplay_moeglich and st.session_state.get("s2_autoplay", True)
    schon_gespielt = st.session_state.get("_s2_audio_ident") == ident
    with open(pfad, "rb") as f:
        st.audio(f.read(), format="audio/mp3", autoplay=autoplay_erlaubt and not schon_gespielt)
    st.session_state["_s2_audio_ident"] = ident


# ── Text+Mikro-Feld (Bugfix: Session-State VOR Widget-Erzeugung setzen) ─

def _text_feld_mit_mikro(label, key, placeholder, farbe_stil="neutral", height=90):
    """Textfeld mit Mikrofon-Diktat, farblich markiert.

    farbe_stil: "neutral" (eigener Kommentar, grauer Rahmen) oder
    "sokra" (Frage an Sokra, blauer Rahmen).

    WICHTIG: die Mikro-Verarbeitung laeuft VOR der Erzeugung des
    text_area-Widgets, damit ein neu transkribierter Text sofort im
    selben Durchlauf sichtbar wird. Streamlit ignoriert einen value=
    Parameter, sobald ein Widget mit diesem key einmal existiert --
    der einzige zuverlaessige Weg ist, st.session_state[key] VOR der
    Widget-Instanziierung zu setzen. Aus demselben Grund wird hier auch
    ein evtl. gesetztes "_clear_{key}"-Flag VOR der Widget-Erzeugung
    aufgeloest (siehe Bug: st.session_state[key] direkt NACH einem
    Button-Klick zu leeren wirft eine StreamlitAPIException, weil das
    Widget in diesem Durchlauf schon instanziiert wurde -- betraf den
    "An Sokra senden"-Button, der dadurch bei jedem Klick abstuerzte).

    BUGFIX (Rueckmeldung: "schmale blaue Balken" ueber den Feldern):
    fruehere Version oeffnete ein rohes <div> per st.markdown() und
    schloss es erst nach den Widgets per zweitem st.markdown() -- das
    umschliesst in Streamlit NICHTS, jedes Element (auch st.markdown
    selbst) landet als eigenstaendiger DOM-Knoten. Das <div> rendert sich
    dadurch als leere, schmale Zierleiste, waehrend Feld/Mikro daneben
    unabhaengig weiterlaufen -- genau das im Screenshot gemeldete
    Erscheinungsbild. Jetzt: echter st.container(border=True), der
    tatsaechlich alles einschliesst, was darin erzeugt wird. Die farbliche
    Unterscheidung kommt jetzt ueber ein Label-Icon (🗨️ Sokra / 📝 eigene
    Notiz) statt ueber einen (ohnehin nie funktionierenden) Rahmen.
    """
    icon = "🗨️" if farbe_stil == "sokra" else "📝"

    if st.session_state.pop(f"_clear_{key}", False):
        st.session_state[key] = ""
    elif key not in st.session_state:
        st.session_state[key] = ""

    with st.container(border=True):
        st.caption(f"{icon} {label}")
        col_txt, col_mic = st.columns([10, 1])

        # Mikro ZUERST verarbeiten (Reihenfolge der with-Bloecke, nicht der
        # visuellen Spaltenposition), damit session_state[key] aktuell ist,
        # BEVOR das Textfeld unten erzeugt wird.
        with col_mic:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if _TTS_OK:
                audio = st.audio_input("🎤", key=f"mic_{key}", label_visibility="collapsed")
                if audio is not None:
                    aktuelle_hash = hash(audio.getvalue())
                    if aktuelle_hash != st.session_state.get(f"mic_hash_{key}"):
                        st.session_state[f"mic_hash_{key}"] = aktuelle_hash
                        with st.spinner("Transkribiere..."):
                            text = transcribe_audio(audio.getvalue())
                        if text:
                            bestehend = st.session_state.get(key, "")
                            st.session_state[key] = (
                                (bestehend + " " + text).strip() if bestehend else text
                            )

        with col_txt:
            st.text_area(label, key=key, placeholder=placeholder, height=height,
                         label_visibility="collapsed")

    return st.session_state.get(key, "")


# ── Sokra ────────────────────────────────────────────────────────────

def _sokra_call(pid, user_msg, alle_diskurse, eigene_diskurs_ids,
                participant_eigene_pos, unwidersprochen):
    if not _SOKRA_OK:
        return "*(Sokra nicht verfügbar)*"

    kontext = build_global_context(
        alle_diskurse, unwidersprochen, eigene_diskurs_ids,
        _get_bew_flat(), participant_eigene_pos,
        st.session_state.s2_diskurs_id
    )
    messages = st.session_state.s2_chat + [{"role": "user", "content": user_msg}]
    system_blocks = [
        {"type": "text", "text": SOKRA_S2_SYSTEM_PROMPT},
        {"type": "text", "text": kontext, "cache_control": {"type": "ephemeral"}},
    ]
    rag_ctx = ""
    if _SOKRA_OK and any(
        w in user_msg.lower() for w in
        ["wie viel", "wie hoch", "kosten", "prozent", "quelle", "studie",
         "gesetz", "gmodg", "geg", "förderung", "bafa", "kfw"]
    ):
        try:
            rag_ctx = get_rag_context(user_msg)
        except Exception:
            pass
    if rag_ctx:
        system_blocks.append({"type": "text", "text": rag_ctx})

    try:
        resp = client.messages.create(
            model=get_model_name(),
            max_tokens=1024,
            system=system_blocks,
            messages=messages,
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        text = re.sub(r"<ui_action>.*?</ui_action>", "", raw, flags=re.DOTALL).strip()
        st.session_state.s2_chat.append({"role": "user", "content": user_msg})
        st.session_state.s2_chat.append({"role": "assistant", "content": text})
        _sd_save(pid, "s2_chat", st.session_state.s2_chat)
        return text
    except Exception as exc:
        _log_err(pid, "sokra", exc)
        return f"*(Fehler: {exc})*"


def _render_sidebar(pid, alle_diskurse, eigene_diskurs_ids,
                    participant_eigene_pos, unwidersprochen):
    """Sidebar enthaelt jetzt AUSSCHLIESSLICH Sokra (Chat, TTS pro
    Nachricht, Mikro-Diktat). Die Debatten-Navigation ist ins Menueband
    oben im Hauptbereich gewandert (siehe _render_topnav)."""
    with st.sidebar:
        st.markdown("### 🤖 Sokra")
        st.caption("Dein Moderator, immer erreichbar")
        st.checkbox("🔊 Nachrichten automatisch vorlesen", value=True, key="s2_autoplay")
        st.divider()

        chat_container = st.container(height=420)
        with chat_container:
            if not st.session_state.s2_chat:
                with st.chat_message("assistant", avatar=AGENT_AVATAR):
                    st.markdown(
                        "Ich bin dabei und begleite dich durch die Sitzung. "
                        "Stell mir Fragen, per Text oder Mikro, oder nutze "
                        "die 'Frage Sokra zu'-Felder bei den Sichtweisen."
                    )
            else:
                for idx, msg in enumerate(st.session_state.s2_chat[-10:]):
                    avatar = AGENT_AVATAR if msg["role"] == "assistant" else None
                    with st.chat_message(msg["role"], avatar=avatar):
                        st.markdown(msg["content"])
                        if msg["role"] == "assistant" and _TTS_OK:
                            audio_key = f"chat_tts_{idx}"
                            if st.button("▶ Vorlesen", key=f"btn_{audio_key}"):
                                audio = synthesize_speech(msg["content"])
                                if audio:
                                    st.session_state[f"audio_{audio_key}"] = audio
                            if st.session_state.get(f"audio_{audio_key}"):
                                st.audio(st.session_state[f"audio_{audio_key}"], format="audio/mp3")

        user_input = st.chat_input("Frage an Sokra...", key="sidebar_chat")
        if user_input:
            with st.spinner("Sokra..."):
                _sokra_call(pid, user_input, alle_diskurse, eigene_diskurs_ids,
                           participant_eigene_pos, unwidersprochen)
            st.rerun()

        if _TTS_OK:
            st.caption("Oder per Sprache:")
            audio_chat = st.audio_input("🎤 Frage einsprechen", key="sidebar_mic",
                                        label_visibility="collapsed")
            if audio_chat is not None:
                h = hash(audio_chat.getvalue())
                if h != st.session_state.get("sidebar_mic_hash"):
                    st.session_state["sidebar_mic_hash"] = h
                    with st.spinner("Transkribiere..."):
                        text = transcribe_audio(audio_chat.getvalue())
                    if text:
                        with st.spinner("Sokra..."):
                            _sokra_call(pid, text, alle_diskurse, eigene_diskurs_ids,
                                       participant_eigene_pos, unwidersprochen)
                        st.rerun()


# ── Top-Navigation (ersetzt die alte Sidebar-Liste) ────────────────────

def _render_topnav(pid, diskurse_aktiv, s1_ids, s2_ids, unwidersprochen):
    """Horizontales Menueband oben: drei Phasen, farblich markiert wo man
    sich gerade befindet, mit Dropdown fuer die jeweiligen Themen und
    Bearbeitungsstatus. 'Hauptdebatten' listet ALLE verbleibenden Debatten
    (nicht nur die drei wichtigsten), markiert diese aber als Kernthema."""
    bew = st.session_state.s2_bew.get("diskurse", {})

    def bearbeitet(d_id):
        return bool(bew.get(d_id, {}).get("lager_bewertungen"))

    echte_unwidersprochen = [
        u for u in unwidersprochen
        if "automatisch nachgetragen" not in u.get("titel", "").lower()
    ]
    konsens_bew = st.session_state.s2_bew.get("konsens_bewertungen", {})
    konsens_total = len(echte_unwidersprochen)
    konsens_done = sum(1 for u in echte_unwidersprochen if konsens_bew.get(u.get("id")))

    s1_done = sum(1 for d in s1_ids if bearbeitet(d))
    rest_ids = [d["id"] for d in diskurse_aktiv if d["id"] not in s1_ids]
    haupt_done = sum(1 for d in rest_ids if bearbeitet(d))

    aktueller_screen = st.session_state.s2_screen
    aktueller_diskurs = st.session_state.s2_diskurs_id

    def phase_stil(aktiv):
        if aktiv:
            return "background:#2d7d9a;color:#fff;border-radius:8px;padding:10px 12px;font-weight:700;text-align:center"
        return "background:#f0f0f0;color:#333;border-radius:8px;padding:10px 12px;font-weight:600;text-align:center"

    c1, c2, c3 = st.columns(3)

    with c1:
        aktiv = aktueller_screen == "phase0"
        st.markdown(
            f'<div style="{phase_stil(aktiv)}">'
            f'{"✅" if konsens_total and konsens_done>=konsens_total else "○"} '
            f'Einigkeit prüfen ({konsens_done}/{konsens_total})</div>',
            unsafe_allow_html=True
        )
        if st.button("Öffnen", key="topnav_btn_konsens", use_container_width=True):
            _save_diskurs(pid, aktueller_diskurs)
            st.session_state.s2_screen = "phase0"
            st.session_state.s2_diskurs_id = None
            st.rerun()

    with c2:
        aktiv = aktueller_screen == "diskurs" and aktueller_diskurs in s1_ids
        st.markdown(
            f'<div style="{phase_stil(aktiv)}">'
            f'{"✅" if s1_ids and s1_done==len(s1_ids) else "○"} '
            f'Eigene Debatten ({s1_done}/{len(s1_ids)})</div>',
            unsafe_allow_html=True
        )
        if s1_ids:
            idx = s1_ids.index(aktueller_diskurs) if aktueller_diskurs in s1_ids else 0
            gewaehlt = st.selectbox(
                "Thema wählen", s1_ids, index=idx,
                format_func=lambda d: f"{'✓' if bearbeitet(d) else '○'} "
                                       f"{_diskurs_by_id(diskurse_aktiv, d)['titel'][:32]}",
                key="topnav_dd_eigene", label_visibility="collapsed",
            )
            if st.button("Öffnen", key="topnav_btn_eigene", use_container_width=True):
                _save_diskurs(pid, aktueller_diskurs)
                st.session_state.s2_screen = "diskurs"
                st.session_state.s2_diskurs_id = gewaehlt
                st.rerun()
        else:
            st.caption("Du steigst direkt bei den Hauptdebatten ein, das ist völlig in Ordnung.")

    with c3:
        aktiv = aktueller_screen == "diskurs" and aktueller_diskurs in rest_ids
        st.markdown(
            f'<div style="{phase_stil(aktiv)}">'
            f'{"✅" if rest_ids and haupt_done==len(rest_ids) else "○"} '
            f'Hauptdebatten ({haupt_done}/{len(rest_ids)})</div>',
            unsafe_allow_html=True
        )
        if rest_ids:
            idx2 = rest_ids.index(aktueller_diskurs) if aktueller_diskurs in rest_ids else 0

            def label_rest(d):
                d_obj = _diskurs_by_id(diskurse_aktiv, d)
                kern = "⭐ " if d in s2_ids else ""
                haken = "✓ " if bearbeitet(d) else "○ "
                return f"{haken}{kern}{d_obj['titel'][:30]}"

            gewaehlt2 = st.selectbox(
                "Debatte wählen", rest_ids, index=idx2,
                format_func=label_rest,
                key="topnav_dd_haupt", label_visibility="collapsed",
            )
            if st.button("Öffnen", key="topnav_btn_haupt", use_container_width=True):
                _save_diskurs(pid, aktueller_diskurs)
                st.session_state.s2_screen = "diskurs"
                st.session_state.s2_diskurs_id = gewaehlt2
                st.rerun()

    st.caption("⭐ = Kernthema, für belastbare Ergebnisse besonders wichtig")
    st.divider()


# ── Slider-Hilfsfunktion ────────────────────────────────────────────────

def _slider_wert(diskurs_id, key):
    state_val = st.session_state.s2_slider.get(diskurs_id, {}).get(key)
    if state_val is not None:
        return state_val
    bew = st.session_state.s2_bew.get("diskurse", {}).get(diskurs_id, {})
    if key.startswith("L_"):
        l_id = key[2:]
        v = bew.get("lager_bewertungen", {}).get(l_id, {})
        return v.get("wert", 0) if isinstance(v, dict) else 0
    elif key.startswith("S_"):
        sp_id = key[2:]
        v = bew.get("standpunkt_bewertungen", {}).get(sp_id, {})
        return v.get("wert", 0) if isinstance(v, dict) else 0
    return 0


def _diskutieren_btn(label_item, position_text, eigenes_zitat,
                     pid, alle_diskurse, eigene_diskurs_ids,
                     participant_eigene_pos, unwidersprochen, btn_key):
    frage = _text_feld_mit_mikro(
        f"Frage Sokra zu: {label_item[:50]}",
        key=f"frage_{btn_key}",
        placeholder="Deine Frage an Sokra...",
        farbe_stil="sokra",
        height=68,
    )
    if frage and st.button("An Sokra senden", key=f"send_{btn_key}"):
        msg = build_diskutieren_msg(label_item, position_text, eigenes_zitat)
        msg += f"\nFrage: {frage}"
        with st.spinner("Sokra..."):
            _sokra_call(pid, msg, alle_diskurse, eigene_diskurs_ids,
                       participant_eigene_pos, unwidersprochen)
        st.session_state[f"_clear_frage_{btn_key}"] = True
        st.rerun()


def _render_lager(diskurs_id, lager, eigene_sp_ids, lager_idx,
                  pid, alle_diskurse, eigene_diskurs_ids,
                  participant_eigene_pos, unwidersprochen, stufe):
    l_id = lager["id"]
    alle_members = []
    seen_pids = set()
    for sp in lager.get("standpunkte", []):
        for m in sp.get("mitglieder", []):
            m_pid = m.get("participant_id", "")
            if m_pid not in seen_pids:
                seen_pids.add(m_pid)
                alle_members.append(m)
    n_p = len(alle_members)

    hat_eigene = any(sp["id"] in eigene_sp_ids for sp in lager.get("standpunkte", []))
    farbe = EIGEN_FARBE if hat_eigene else LAGER_FARBEN[lager_idx % len(LAGER_FARBEN)]

    eigen_badge = " 📍 **Deine Sichtweise**" if hat_eigene else ""
    st.markdown(
        f'<div style="border-left:4px solid {farbe};padding-left:10px;margin-bottom:4px">'
        f'<strong style="color:{farbe}">{lager.get("titel","")}</strong>{eigen_badge}'
        f'<span style="color:#888;font-size:.8rem"> · {n_p} Personen</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    st.markdown(lager.get("kernaussage", ""))
    if lager.get("bandbreite"):
        st.markdown(f"*Spannbreite:* {lager['bandbreite']}")

    current = _slider_wert(diskurs_id, f"L_{l_id}")
    za = st.select_slider(
        "Deine Einschätzung", options=ZA_OPTIONS, value=current,
        format_func=lambda x: ZA_LABELS[x],
        key=f"sl_L_{diskurs_id}_{l_id}", label_visibility="visible",
    )
    st.session_state.s2_slider.setdefault(diskurs_id, {})[f"L_{l_id}"] = za

    kommentar = _text_feld_mit_mikro(
        "Gib hier deine Ergänzungen, Bedingungen, Gegenargumente oder Kompromissvorschläge ein:",
        key=f"k_L_{diskurs_id}_{l_id}",
        placeholder='z.B. "Ich könnte zustimmen, wenn..." oder "Das sehe ich anders, weil..."',
        farbe_stil="neutral", height=90,
    )
    st.session_state.s2_slider.setdefault(diskurs_id, {})[f"K_L_{l_id}"] = kommentar

    standpunkte = lager.get("standpunkte", [])
    hat_direkte_sp_bewertung = any(
        st.session_state.s2_slider.get(diskurs_id, {}).get(f"S_{sp['id']}") is not None
        for sp in standpunkte
    )
    # BUGFIX: Python reduziert eine "and"-Kette NICHT auf True/False, sondern
    # gibt den letzten ausgewerteten Operanden zurueck -- war hier
    # "standpunkte" (eine Liste), sobald die ersten beiden Bedingungen
    # zutrafen. st.expander(expanded=<Liste>) stuerzt dann ab ("'list'
    # object cannot be interpreted as an integer"), reproduzierbar sobald
    # za in (2,3,4) ist. bool(...) erzwingt einen echten Wahrheitswert.
    zeige_nudge = bool(za in (2, 3, 4) and not hat_direkte_sp_bewertung and standpunkte)
    if zeige_nudge:
        st.info(
            "💡 Du kannst den einzelnen Positionen weiter unten unterschiedlich "
            "stark zustimmen, statt nur der Sichtweise insgesamt, und dort auch "
            "gezielt einen Kompromissvorschlag machen."
        )

    eigenes_zitat = None
    for sp in lager.get("standpunkte", []):
        if sp["id"] in eigene_sp_ids:
            for m in sp.get("mitglieder", []):
                eigenes_zitat = m.get("zitat", "")[:150]
                break

    _diskutieren_btn(
        lager.get("titel", ""), lager.get("kernaussage", ""),
        eigenes_zitat, pid, alle_diskurse, eigene_diskurs_ids,
        participant_eigene_pos, unwidersprochen,
        f"btn_L_{diskurs_id}_{l_id}"
    )

    if standpunkte:
        with st.expander(f"Einzelpositionen ({len(standpunkte)}) anzeigen", expanded=zeige_nudge):
            for sp in standpunkte:
                _render_standpunkt(diskurs_id, sp, eigene_sp_ids, farbe,
                                   pid, alle_diskurse, eigene_diskurs_ids,
                                   participant_eigene_pos, unwidersprochen, stufe)
                st.divider()


def _render_standpunkt(diskurs_id, sp, eigene_sp_ids, lager_farbe,
                       pid, alle_diskurse, eigene_diskurs_ids,
                       participant_eigene_pos, unwidersprochen, stufe):
    sp_id = sp["id"]
    abstr = sp.get("abstraktionsebene", "")
    farbe = ABSTR_FARBEN.get(abstr, lager_farbe)
    seen = set()
    mitglieder = []
    for m in sp.get("mitglieder", []):
        m_pid = m.get("participant_id", "")
        if m_pid not in seen:
            seen.add(m_pid)
            mitglieder.append(m)
    n = len(mitglieder)
    ist_eigen = sp_id in eigene_sp_ids

    badge = " · **Deine Position aus Phase 1**" if ist_eigen else ""
    st.markdown(
        f'<span style="border-left:2px solid {farbe};padding-left:6px">'
        f"**{sp.get('titel', '')}**{badge} "
        f'<small style="color:#888">{abstr} · {n} P.</small></span>',
        unsafe_allow_html=True,
    )
    st.markdown(sp.get("position", ""))
    if sp.get("setzt_voraus"):
        st.caption(f"↳ baut auf: {sp['setzt_voraus']}")

    current = _slider_wert(diskurs_id, f"S_{sp_id}")
    za = st.select_slider(
        "Einschätzung", options=ZA_OPTIONS, value=current,
        format_func=lambda x: ZA_LABELS[x],
        key=f"sl_S_{diskurs_id}_{sp_id}", label_visibility="collapsed",
    )
    st.session_state.s2_slider.setdefault(diskurs_id, {})[f"S_{sp_id}"] = za

    kommentar = _text_feld_mit_mikro(
        "Gib hier deine Ergänzungen, Bedingungen, Gegenargumente oder Kompromissvorschläge ein:",
        key=f"k_S_{diskurs_id}_{sp_id}",
        placeholder='z.B. "Ich könnte zustimmen, wenn..." oder "Das sehe ich anders, weil..."',
        farbe_stil="neutral", height=80,
    )
    st.session_state.s2_slider.setdefault(diskurs_id, {})[f"K_S_{sp_id}"] = kommentar

    eigenes_zitat = None
    if ist_eigen:
        for m in mitglieder:
            eigenes_zitat = m.get("zitat", "")[:150]
            break
    _diskutieren_btn(
        sp.get("titel", ""), sp.get("position", ""), eigenes_zitat,
        pid, alle_diskurse, eigene_diskurs_ids,
        participant_eigene_pos, unwidersprochen,
        f"btn_S_{diskurs_id}_{sp_id}"
    )


# ── Screens ────────────────────────────────────────────────────────────

def _screen_begruessung(pid):
    _auto_vorlesen("begruessung.mp3", "begruessung", autoplay_moeglich=True)
    st.markdown("## Willkommen zurück!")
    st.markdown(BEGRUESSUNG)
    if st.button("✅ Verstanden — Los geht's!", type="primary", use_container_width=True):
        st.session_state.s2_screen = "phase0"
        st.rerun()


def _screen_phase0(pid, unwidersprochen, alle_diskurse, eigene_diskurs_ids,
                   participant_eigene_pos):
    st.subheader("📋 Vorschläge mit Konsens-Potenzial")
    _auto_vorlesen("phase0_intro.mp3", "phase0_intro")
    st.markdown(PHASE0_INTRO_TEXT)

    echte = [u for u in unwidersprochen
             if "automatisch nachgetragen" not in u.get("titel", "").lower()
             and "automatisch nachgetragen" not in u.get("beschreibung", "").lower()]

    if not echte:
        st.info("Keine Einigkeitspunkte vorhanden.")
    else:
        for u in echte:
            u_id = u.get("id", "")
            pos = u.get("positionen", [])
            seen = set()
            pos_dedup = []
            for p in pos:
                p_pid = p.get("participant_id", "")
                if p_pid not in seen:
                    seen.add(p_pid)
                    pos_dedup.append(p)
            n = len(pos_dedup)

            with st.container():
                st.markdown(f"**{u.get('titel', '')}**")
                st.caption(f"Bisher keine direkten Gegenstimmen · {n} Person(en) aus Phase 1")
                st.markdown(u.get("beschreibung", ""))

                za = st.select_slider(
                    "Stimmst du damit überein, oder siehst du das anders?",
                    options=ZA_OPTIONS,
                    value=st.session_state.get(f"za_u_{u_id}", 0),
                    format_func=lambda x: ZA_LABELS[x],
                    key=f"za_u_{u_id}",
                )
                if za:
                    st.session_state.s2_bew.setdefault("konsens_bewertungen", {})[u_id] = za

                kommentar_u = _text_feld_mit_mikro(
                    "Gib hier deine Ergänzungen, Bedingungen, Gegenargumente oder Kompromissvorschläge ein:",
                    key=f"k_u_{u_id}",
                    placeholder="Einschränkung oder abweichende Meinung...",
                    farbe_stil="neutral", height=80,
                )
                if kommentar_u:
                    st.session_state.s2_bew.setdefault("konsens_kommentare", {})[u_id] = kommentar_u

                frage_u = _text_feld_mit_mikro(
                    f"Frage Sokra zu: {u.get('titel','')[:50]}",
                    key=f"frage_u_{u_id}",
                    placeholder="Deine Frage an Sokra...",
                    farbe_stil="sokra", height=68,
                )
                if frage_u and st.button("An Sokra senden", key=f"send_u_{u_id}"):
                    msg = (f"KONTEXT: {u.get('titel','')}\n"
                           f"Inhalt: {u.get('beschreibung','')}\n"
                           f"Frage: {frage_u}")
                    with st.spinner("Sokra..."):
                        _sokra_call(pid, msg, alle_diskurse, eigene_diskurs_ids,
                                   participant_eigene_pos, unwidersprochen)
                    st.session_state[f"_clear_frage_u_{u_id}"] = True
                    st.rerun()

                st.divider()

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Überspringen →"):
            st.session_state.s2_screen = "diskurs"
            st.rerun()
    with col2:
        if st.button("💾 Speichern & zu meinen Themen →", type="primary", use_container_width=True):
            if _BEW_OK:
                speichern(st.session_state.s2_bew)
                _sd_save(pid, "s2_bewertungen", st.session_state.s2_bew)
            st.session_state.s2_screen = "diskurs"
            st.rerun()


def _screen_diskurs(pid, diskurs, eigene_sp_ids, eigene_pos, stufe,
                    alle_diskurse, eigene_diskurs_ids,
                    participant_eigene_pos, unwidersprochen,
                    s1_ids, s2_ids):
    d_id = diskurs["id"]
    lager_list = diskurs.get("lager", [])

    ist_eigen = d_id in eigene_diskurs_ids
    ist_haupt = d_id in s2_ids
    badge = ("📍 Deine Debatte" if ist_eigen
             else ("⭐ Kernthema" if ist_haupt else "📋 Weiteres Thema"))
    st.markdown(f"**{badge}**")
    st.subheader(diskurs["titel"])

    _auto_vorlesen(f"diskurs_{d_id}.mp3", f"diskurs_{d_id}")
    st.markdown(f"*Streitfrage: {diskurs.get('streitfrage','')}*")
    st.markdown(diskurs.get("uebersicht", ""))

    if eigene_pos:
        lager_titel = eigene_pos[0].get("lager_titel", "")
        zitat = eigene_pos[0].get("zitat", "")
        st.info(
            f"**Deine Position aus Phase 1** (Sichtweise: *{lager_titel}*)\n\n"
            f'"{zitat}"'
        )

    st.markdown("---")
    st.markdown("#### Wie siehst du die verschiedenen Sichtweisen?")
    st.caption(
        "Bewerte den gemeinsamen Kern jeder Sichtweise. "
        "Darunter findest du Einzelpositionen für eine detailliertere Einschätzung."
    )

    n = len(lager_list)
    cols = st.columns(max(n, 1))
    for i, (col, lager) in enumerate(zip(cols, lager_list)):
        with col:
            _render_lager(
                d_id, lager, eigene_sp_ids, i,
                pid, alle_diskurse, eigene_diskurs_ids,
                participant_eigene_pos, unwidersprochen, stufe
            )

    st.markdown("---")
    alle_nav_ids = s1_ids + [d for d in s2_ids if d not in s1_ids]
    aktuell_idx = alle_nav_ids.index(d_id) if d_id in alle_nav_ids else -1
    naechster = (alle_nav_ids[aktuell_idx + 1]
                if 0 <= aktuell_idx < len(alle_nav_ids) - 1 else None)
    naechster_d = _diskurs_by_id(alle_diskurse, naechster) if naechster else None

    if naechster_d:
        label = f"Speichern & weiter: {naechster_d['titel'][:30]} →"
    else:
        label = "Speichern & Sitzung abschließen →"

    if st.button(label, type="primary", use_container_width=True, key=f"next_{d_id}"):
        _save_diskurs(pid, d_id, stufe)
        if naechster:
            st.session_state.s2_diskurs_id = naechster
            st.session_state.s2_screen = "diskurs"
        else:
            abschliessen(st.session_state.s2_bew)
            speichern(st.session_state.s2_bew)
            _sd_save(pid, "s2_bewertungen", st.session_state.s2_bew)
            st.session_state.s2_screen = "abschluss"
        st.rerun()


def _screen_abschluss():
    st.success("## Sitzung 2 abgeschlossen!")
    st.markdown(
        "Danke für deine Teilnahme. Deine Bewertungen und Kompromissvorschläge "
        "fließen in die Synthese ein. Sitzung 3 mit den Ergebnissen folgt in einigen Tagen."
    )
    st.balloons()


# ── Hauptrender ────────────────────────────────────────────────────────

def render(participant_id):
    try:
        data = _load_struktur()
    except FileNotFoundError:
        st.info(f"`{STRUCTURE_PATH}` noch nicht vorhanden (Pause 1 ausstehend).")
        return

    diskurse = data.get("diskurse", [])
    unwidersprochen = data.get("unwidersprochene_punkte", [])
    diskurse_aktiv = [d for d in diskurse if d.get("lager") and not d.get("error")]

    if not diskurse_aktiv:
        st.error("Keine gültige Diskursstruktur gefunden.")
        return

    _ensure_folders()
    _init_state(participant_id)

    s1_liste = stufe1_diskurse(diskurse_aktiv, participant_id) if _BEW_OK else []
    if _BEW_OK and st.session_state.s2_bew.get("hatte_s1_positionen") is None:
        markiere_s1_status(st.session_state.s2_bew, bool(s1_liste))
        speichern(st.session_state.s2_bew)
        _sd_save(participant_id, "s2_bewertungen", st.session_state.s2_bew)
    s1_ids = [x[0] for x in s1_liste]
    s2_ids = stufe2_diskurse(diskurse_aktiv, participant_id, anzahl=3) if _BEW_OK else []

    participant_eigene_pos = {}
    for d in diskurse_aktiv:
        if _BEW_OK:
            pos = eigene_positionen_finden(d, participant_id)
            if pos:
                participant_eigene_pos[d["id"]] = pos
    eigene_diskurs_ids = list(participant_eigene_pos.keys())

    if st.session_state.s2_screen == "diskurs" and st.session_state.s2_diskurs_id is None:
        st.session_state.s2_diskurs_id = s1_ids[0] if s1_ids else (
            s2_ids[0] if s2_ids else diskurse_aktiv[0]["id"]
        )

    # Sokra immer in der Sidebar, ab dem Moment nach der Begruessung
    if st.session_state.s2_screen != "begruessung":
        _render_sidebar(participant_id, diskurse_aktiv, eigene_diskurs_ids,
                        participant_eigene_pos, unwidersprochen)

    screen = st.session_state.s2_screen

    if screen == "begruessung":
        _screen_begruessung(participant_id)

    elif screen == "phase0":
        _render_topnav(participant_id, diskurse_aktiv, s1_ids, s2_ids, unwidersprochen)
        _screen_phase0(participant_id, unwidersprochen, diskurse_aktiv,
                       eigene_diskurs_ids, participant_eigene_pos)

    elif screen == "diskurs":
        _render_topnav(participant_id, diskurse_aktiv, s1_ids, s2_ids, unwidersprochen)
        d_id = st.session_state.s2_diskurs_id
        diskurs = _diskurs_by_id(diskurse_aktiv, d_id)
        if not diskurs:
            st.error(f"Debatte {d_id} nicht gefunden.")
            return

        ist_eigen = d_id in eigene_diskurs_ids
        stufe = 1 if ist_eigen else 2
        eigene_sp_ids = set()
        for _, _, sp_ids in [x for x in s1_liste if x[0] == d_id]:
            eigene_sp_ids.update(sp_ids)
        eigene_pos = participant_eigene_pos.get(d_id, [])

        try:
            _screen_diskurs(
                participant_id, diskurs, eigene_sp_ids, eigene_pos, stufe,
                diskurse_aktiv, eigene_diskurs_ids,
                participant_eigene_pos, unwidersprochen,
                s1_ids, s2_ids
            )
        except Exception as exc:
            _log_err(participant_id, f"screen_diskurs_{d_id}", exc)
            st.error(f"Fehler beim Laden der Debatte: {exc}")

    elif screen == "abschluss":
        _screen_abschluss()

    if st.session_state.get("_save_failed"):
        st.warning(
            "Letzte Speicherung fehlgeschlagen. Eingaben bleiben in dieser "
            "Sitzung erhalten, bitte Tab offen lassen."
        )

    st.caption(f"ID: {participant_id}")
