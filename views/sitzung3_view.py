"""
views/sitzung3_view.py

Sitzung 3: Ergebnisse & Abstimmung. Zeigt das synthetisierte
Empfehlungsdokument (data/synthese/empfehlung_final.json, siehe
synthese_final_synthese.py) und laesst jede Empfehlung mit Ja/Nein
bewerten -- kein Mehrfachvergleich mehr (Ueberwaeltigungsproblem aus S2
vermeiden), sondern punktweise Ratifikation des bereits gefilterten
Ergebnisses. Sokra begleitet wie in S1/S2 dauerhaft in der Seitenleiste.

Gleiches Architekturprinzip wie S2: fehlende Datei/Assets duerfen nie die
ganze App crashen lassen, nur diese Sitzung (siehe render()-Try/Except).
"""

import json
import os
import re

import streamlit as st

try:
    from sokra_s3_prompt import (
        SOKRA_S3_SYSTEM_PROMPT,
        build_global_context,
        get_rag_context,
    )
    _SOKRA_OK = True
except ImportError:
    _SOKRA_OK = False

try:
    from session3_bewertungen import (
        laden, speichern, bewerten, konflikt_entscheiden, abschliessen, fortschritt,
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

EMPFEHLUNG_PATH = "data/synthese/empfehlung_final.json"
DOSSIERS_PATH = "data/synthese/dossiers.json"
LOG_FOLDER = "aigora_logs_s3"
_SUBFOLDERS = ["s3_bewertungen", "s3_chat", "errorlog"]

DIM_FARBEN = {
    "Übergeordnete Ziele": "#1a6b3c", "Konkrete Ziele": "#2d7d9a",
    "Zwischenziele": "#5c6bc0", "Umsetzungslogik": "#7b5ea7",
    "Instrumententyp": "#b06a20", "Feinausgestaltung": "#9e3030",
}
DIM_REIHENFOLGE = list(DIM_FARBEN.keys())

BEGRUESSUNG = """Willkommen zur dritten und letzten Sitzung!

In dieser Sitzung siehst du die Ergebnisse aus Sitzung 1 und 2 und entscheidest bei jedem Punkt, ob du ihn mittragen oder ablehnen möchtest.

Zur Einordnung: In Sitzung 1 hast du deine eigene Position entwickelt, in Sitzung 2 habt ihr euch mit den unterschiedlichen Sichtweisen der Gruppe auseinandergesetzt. Aus euren Positionen, Bewertungen und Kompromissvorschlägen haben wir mehrheitsfähige Empfehlungen herausgefiltert und zu einem Abschlussdokument zusammengestellt — gegliedert nach den sechs Politik-Dimensionen von Cashore & Howlett, dem Ordnungsrahmen dieser Studie: von übergeordneten Zielen bis zu konkreten Ausgestaltungsdetails.

Die Punkte sind bereits auf breite, mehrheitsfähige Zustimmung geprüft. Die Frage bei jedem Punkt lautet daher nicht, ob er exakt deiner Wunschposition entspricht, sondern ob du ihn mittragen kannst — auch wenn er nicht deine erste Präferenz ist. Stimme zu, wenn das der Fall ist. Lehne ab, wenn du den Punkt inhaltlich nicht mittragen kannst.

Zu jedem Punkt kannst du zusätzlich einen Kommentar hinterlassen und einsehen, auf welchen Aussagen aus Sitzung 1 und 2 die Empfehlung beruht.

Sokra steht dir dabei in der Seitenleiste jederzeit für Rückfragen zur Verfügung.

Bereit? Dann geht's los."""


# ── SurfDrive ─────────────────────────────────────────────────────────

@st.cache_resource
def _ensure_folders():
    sd.ensure_folder(LOG_FOLDER)
    for sub in _SUBFOLDERS:
        sd.ensure_folder(f"{LOG_FOLDER}/{sub}")
    return True

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


# ── Daten laden ──────────────────────────────────────────────────────

@st.cache_resource
def _load_empfehlung():
    with open(EMPFEHLUNG_PATH, encoding="utf-8") as f:
        return json.load(f)

@st.cache_resource
def _load_dossiers():
    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _eigene_positionen(dossiers, empfehlung, participant_id):
    """kandidat_id -> Liste eigener Zitate dieser Person, wenn sie unter den
    Standpunkten steht, auf die sich diese Empfehlung stuetzt."""
    sp_lookup = {}
    for dim, inhalt in dossiers.items():
        for sp in inhalt["standpunkte"]:
            sp_lookup[(dim, sp["id"])] = sp

    ergebnis = {}
    for dim, inhalt in empfehlung["dimensionen"].items():
        for x in inhalt["eintraege"]:
            sp_ids = (x.get("stuetzt_sich_auf") or {}).get("standpunkte", [])
            treffer = []
            for sid in sp_ids:
                sp = sp_lookup.get((dim, sid))
                if not sp:
                    continue
                for z in sp.get("ursprungszitate", []):
                    if z["participant_id"] == participant_id:
                        treffer.append({"zitat": z["zitat"], "sp_id": sid})
            if treffer:
                ergebnis[x["id"]] = treffer
    return ergebnis


# ── Text+Mikro-Feld (gleiches Muster wie S1/S2) ──────────────────────

def _text_feld_mit_mikro(label, key, placeholder, farbe_stil="neutral", height=80):
    icon = "🗨️" if farbe_stil == "sokra" else "📝"
    if st.session_state.pop(f"_clear_{key}", False):
        st.session_state[key] = ""
    elif key not in st.session_state:
        st.session_state[key] = ""

    with st.container(border=True):
        st.caption(f"{icon} {label}")
        col_txt, col_mic = st.columns([10, 1])
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

def _sokra_call(pid, user_msg, empfehlung, eigene_pos, aktuelle_bewertungen):
    if not _SOKRA_OK:
        return "*(Sokra nicht verfügbar)*"

    kontext = build_global_context(empfehlung, eigene_pos, aktuelle_bewertungen)
    messages = st.session_state.s3_chat + [{"role": "user", "content": user_msg}]
    system_blocks = [
        {"type": "text", "text": SOKRA_S3_SYSTEM_PROMPT},
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
            model=get_model_name(), max_tokens=1024,
            system=system_blocks, messages=messages,
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        text = re.sub(r"<ui_action>.*?</ui_action>", "", raw, flags=re.DOTALL).strip()
        st.session_state.s3_chat.append({"role": "user", "content": user_msg})
        st.session_state.s3_chat.append({"role": "assistant", "content": text})
        _sd_save(pid, "s3_chat", st.session_state.s3_chat)
        return text
    except Exception as exc:
        return f"*(Fehler: {exc})*"


def _berechne_fortschritt(empfehlung):
    konfliktgruppen = empfehlung.get("konfliktgruppen", [])
    konflikt_je_kandidat = {(opt["dim"], opt["id"]) for kg in konfliktgruppen for opt in kg["optionen"]}
    alle_ids = [
        x["id"] for dim, inhalt in empfehlung["dimensionen"].items() for x in inhalt["eintraege"]
        if (dim, x["id"]) not in konflikt_je_kandidat
    ]
    return fortschritt(st.session_state.s3_bew, alle_ids, len(konfliktgruppen))


def _render_sidebar(pid, empfehlung, eigene_pos):
    with st.sidebar:
        fs = _berechne_fortschritt(empfehlung)
        st.progress(fs["bewertet"] / fs["gesamt"] if fs["gesamt"] else 0)
        st.caption(f"{fs['bewertet']} von {fs['gesamt']} Entscheidungen getroffen")
        st.divider()
        st.markdown("### 🤖 Sokra")
        st.caption("Dein Assistent für alle Fragen, immer erreichbar")
        st.checkbox("🔊 Nachrichten automatisch vorlesen", value=True, key="s3_autoplay")
        st.divider()

        chat_container = st.container(height=420)
        with chat_container:
            if not st.session_state.s3_chat:
                with st.chat_message("assistant", avatar=AGENT_AVATAR):
                    st.markdown(
                        "Ich bin dabei und helfe dir bei den Empfehlungen. Stell mir "
                        "Fragen, per Text oder Mikro, oder nutze die 'Frage Sokra'-Felder "
                        "bei den einzelnen Empfehlungen."
                    )
            else:
                for idx, msg in enumerate(st.session_state.s3_chat[-10:]):
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
                _sokra_call(pid, user_input, empfehlung, eigene_pos, st.session_state.s3_bew["bewertungen"])
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
                            _sokra_call(pid, text, empfehlung, eigene_pos, st.session_state.s3_bew["bewertungen"])
                        st.rerun()


# ── Screens ──────────────────────────────────────────────────────────

def _screen_begruessung():
    if _TTS_OK:
        pfad = "assets/audio_s3/begruessung.mp3"
        if os.path.exists(pfad):
            autoplay = st.session_state.get("s3_autoplay", True) and \
                       st.session_state.get("_s3_audio_ident") != "begruessung"
            with open(pfad, "rb") as f:
                st.audio(f.read(), format="audio/mp3", autoplay=autoplay)
            st.session_state["_s3_audio_ident"] = "begruessung"
    st.markdown("## Willkommen zur Abstimmung!")
    st.markdown(BEGRUESSUNG)
    if st.button("✅ Verstanden — Los geht's!", type="primary", use_container_width=True):
        st.session_state.s3_screen = "bewertung"
        st.rerun()


def _render_empfehlung(pid, dim, x, farbe, dossiers, empfehlung, eigene_pos, nr=None):
    kid = x["id"]
    bew = st.session_state.s3_bew["bewertungen"].get(kid, {})
    aktueller_wert = bew.get("wert")

    minderheit_hinweis = ""
    sp_ids = (x.get("stuetzt_sich_auf") or {}).get("standpunkte", [])
    sp_lookup_dim = {sp["id"]: sp for sp in dossiers.get(dim, {}).get("standpunkte", [])}
    if any(sp_lookup_dim.get(sid, {}).get("minderheitsposition") for sid in sp_ids):
        minderheit_hinweis = (
            ' <span title="Dieser Punkt hat einen echten, aber kleineren Widerspruch '
            'überstanden und ist bewusst als Minderheitsposition markiert.">🔶</span>'
        )

    nr_praefix = f"<strong>{nr}.</strong> " if nr is not None else ""
    st.markdown(
        f'<div style="border-left:4px solid {farbe};padding:6px 10px;margin:4px 0 2px;'
        f'background:{farbe}0d">{nr_praefix}{x["aussage_final"]}{minderheit_hinweis}</div>',
        unsafe_allow_html=True,
    )

    eigene = eigene_pos.get(kid)
    if eigene:
        st.caption(f'📍 Beruht u.a. auf deiner eigenen Position: "{eigene[0]["zitat"][:150]}"')

    col1, col2, col3 = st.columns([1.1, 1.4, 3.5])
    with col1:
        if st.button("Stimme zu", key=f"ja_{kid}",
                    type="primary" if aktueller_wert == "ja" else "secondary",
                    use_container_width=True):
            bewerten(st.session_state.s3_bew, kid, "ja")
            st.rerun()
    with col2:
        if st.button("Stimme nicht zu", key=f"nein_{kid}",
                    type="primary" if aktueller_wert == "nein" else "secondary",
                    use_container_width=True):
            bewerten(st.session_state.s3_bew, kid, "nein")
            st.rerun()
    with col3:
        kommentar = st.text_input(
            "Kommentar", key=f"k_{kid}", value=bew.get("kommentar", ""),
            placeholder="Kommentar (optional)", label_visibility="collapsed",
        )
        if kommentar != bew.get("kommentar", ""):
            bewerten(st.session_state.s3_bew, kid, aktueller_wert, kommentar)

    detail_cols = st.columns([1, 1])
    with detail_cols[0]:
        if x.get("nutzer_erklaerung"):
            with st.expander("Wie ist dieser Punkt entstanden?"):
                st.caption(x["nutzer_erklaerung"])
    with detail_cols[1]:
        if sp_ids:
            with st.expander("Ursprünglicher Standpunkt"):
                for sid in sp_ids:
                    sp = sp_lookup_dim.get(sid)
                    if sp:
                        st.caption(f"**{sid}**: {sp['position']} "
                                  f"(n={sp['unterstuetzung']['n_bewertet']}, "
                                  f"Ø={sp['unterstuetzung']['mittelwert']})")
    st.markdown('<hr style="margin:6px 0;border-color:#eee">', unsafe_allow_html=True)


def _render_konfliktgruppe(pid, idx, kg, alle_eintraege, empfehlung, eigene_pos, nr=None):
    """Echte Entweder-Oder-Wahl: gemeinsamer Kern einmal, dann Optionen
    NEBENEINANDER mit je einem Klick waehlbar -- kein unabhaengiges
    Ja/Nein pro Option (siehe der Autor: 'man braucht nur auf das eine
    oder andere zu klicken')."""
    bestehend = st.session_state.s3_bew.get("konflikt_entscheidungen", {}).get(str(idx), {})
    gewaehlt = bestehend.get("gewaehlte_option")

    numerisch = kg["typ"] == "numerisch"
    with st.container(border=True):
        typ_label = "🔢 Zahlenwert wählen" if numerisch else "⚖️ Grundsätzliche Wahl"
        nr_praefix = f"{nr}. " if nr is not None else ""
        st.markdown(f"**{nr_praefix}{typ_label}**")
        st.markdown(f"✓ **Gemeinsam:** {kg.get('gemeinsamer_kern','')}")
        st.caption("Welcher Wert soll gelten?" if numerisch else "Unterschied — wähle eine Option:")

        cols = st.columns(len(kg["optionen"]))
        for col, opt in zip(cols, kg["optionen"]):
            opt_id = opt["id"]
            with col:
                aktiv = gewaehlt == opt_id
                titel = opt.get("unterschied_text") or opt.get("kurzlabel", "")
                beschreibung = opt.get("kurzlabel", "") if opt.get("unterschied_text") else ""
                marker = "●" if aktiv else "○"
                label = f"{marker} **{titel}**"
                if beschreibung:
                    label += f"\n\n{beschreibung}"
                if st.button(
                    label,
                    key=f"konflikt_{idx}_{opt_id}",
                    type="primary" if aktiv else "secondary",
                    use_container_width=True,
                ):
                    konflikt_entscheiden(st.session_state.s3_bew, idx, opt_id)
                    st.rerun()

        kommentar = st.text_input(
            "Kommentar", key=f"k_konflikt_{idx}", value=bestehend.get("kommentar", ""),
            placeholder="Kommentar (optional)", label_visibility="collapsed",
        )
        if kommentar != bestehend.get("kommentar", ""):
            konflikt_entscheiden(st.session_state.s3_bew, idx, gewaehlt, kommentar)


def _render_cashore_tabelle(empfehlung):
    """Kompakte Cashore-Howlett-Uebersicht: 2 Spalten (Zweck/Mittel) x 3
    Zeilen (Hoch/Mittel/Niedrig), je Zelle Dimension + Anzahl Kandidaten,
    farblich markiert, Klick springt zur jeweiligen Dimension."""
    zeilen = [
        ("Hoch", "Übergeordnete Ziele", "Umsetzungslogik"),
        ("Mittel", "Konkrete Ziele", "Instrumententyp"),
        ("Niedrig", "Zwischenziele", "Feinausgestaltung"),
    ]
    def zelle(dim):
        n = len(empfehlung["dimensionen"].get(dim, {}).get("eintraege", []))
        farbe = DIM_FARBEN[dim]
        return (f'<a href="#dim-{dim.replace(" ","-")}" style="text-decoration:none;color:inherit">'
                f'<div style="background:{farbe}1a;border-left:3px solid {farbe};border-radius:4px;'
                f'padding:5px 8px;margin:2px 0;font-size:.8rem">'
                f'<strong style="color:{farbe}">{dim}</strong> · {n}</div></a>')
    zeilen_html = "".join(
        f'<div style="display:grid;grid-template-columns:70px 1fr 1fr;gap:6px;align-items:center;margin:2px 0">'
        f'<span style="font-size:.7rem;color:#999">{label}</span>{zelle(zweck)}{zelle(mittel)}</div>'
        for label, zweck, mittel in zeilen
    )
    st.markdown(
        '<div style="display:grid;grid-template-columns:70px 1fr 1fr;gap:6px;font-size:.72rem;'
        'font-weight:700;color:#888;margin-bottom:2px"><span></span>'
        '<span>🎯 ZWECK</span><span>⚙️ MITTEL</span></div>' + zeilen_html,
        unsafe_allow_html=True,
    )


def _primaere_dim(kg):
    """Ordnet eine Konfliktgruppe der Dimension zu, in der sie inline angezeigt
    wird: bei dimensionsübergreifenden Konflikten die höher-abstrakte (erste in
    DIM_REIHENFOLGE), damit sie im Kontext der jeweiligen Cashore-Howlett-Ebene
    steht statt pauschal ganz oben (siehe der Autor: 'richtig eingeordnet in den
    Kontext')."""
    dims_der_optionen = {opt["dim"] for opt in kg["optionen"]}
    for dim in DIM_REIHENFOLGE:
        if dim in dims_der_optionen:
            return dim
    return kg["optionen"][0]["dim"]


def _screen_bewertung(pid, empfehlung, dossiers, eigene_pos):
    konfliktgruppen = empfehlung.get("konfliktgruppen", [])
    alle_eintraege = {
        (dim, x["id"]): x
        for dim, inhalt in empfehlung["dimensionen"].items()
        for x in inhalt["eintraege"]
    }
    konflikt_je_kandidat = set()
    konfliktgruppen_je_dim = {}
    for idx, kg in enumerate(konfliktgruppen):
        for opt in kg["optionen"]:
            konflikt_je_kandidat.add((opt["dim"], opt["id"]))
        konfliktgruppen_je_dim.setdefault(_primaere_dim(kg), []).append((idx, kg))

    st.markdown(
        "Hier siehst du alle Kandidaten für das Empfehlungspapier, gegliedert nach den sechs "
        "Politik-Dimensionen. Bitte bewerte nacheinander jeden Punkt — bei manchen musst du "
        "zwischen mehreren Optionen wählen, statt zuzustimmen oder abzulehnen."
    )
    _render_cashore_tabelle(empfehlung)
    st.markdown("<br>", unsafe_allow_html=True)

    for dim in DIM_REIHENFOLGE:
        inhalt = empfehlung["dimensionen"].get(dim)
        if not inhalt:
            continue
        eintraege_dim = [x for x in inhalt["eintraege"] if (dim, x["id"]) not in konflikt_je_kandidat]
        kg_dim = konfliktgruppen_je_dim.get(dim, [])
        if not eintraege_dim and not kg_dim:
            continue
        farbe = DIM_FARBEN[dim]
        n_dim_bew = sum(1 for x in eintraege_dim
                        if st.session_state.s3_bew["bewertungen"].get(x["id"], {}).get("wert"))
        n_dim_bew += sum(
            1 for idx, _ in kg_dim
            if st.session_state.s3_bew.get("konflikt_entscheidungen", {}).get(str(idx), {}).get("gewaehlte_option")
        )
        n_dim_gesamt = len(eintraege_dim) + len(kg_dim)
        st.markdown(f'<div id="dim-{dim.replace(" ","-")}"></div>', unsafe_allow_html=True)
        with st.expander(f"{dim} ({n_dim_bew}/{n_dim_gesamt})", expanded=True):
            # dissens_notiz nur zeigen, wenn er auch tatsaechlich zu einer
            # Entscheidungsmoeglichkeit fuehrt -- sonst tote Information
            # (siehe der Autor: "wozu das da steht, wenn keine Handlungsoption
            # daraus resultiert").
            if kg_dim and inhalt.get("dissens_notiz"):
                st.info(inhalt["dissens_notiz"])
            nr = 1
            for idx, kg in kg_dim:
                _render_konfliktgruppe(pid, idx, kg, alle_eintraege, empfehlung, eigene_pos, nr=nr)
                nr += 1
            for x in eintraege_dim:
                _render_empfehlung(pid, dim, x, farbe, dossiers, empfehlung, eigene_pos, nr=nr)
                nr += 1

    st.divider()
    if st.button("💾 Speichern & abschließen →", type="primary", use_container_width=True):
        speichern(st.session_state.s3_bew)
        _sd_save(pid, "s3_bewertungen", st.session_state.s3_bew)
        abschliessen(st.session_state.s3_bew)
        speichern(st.session_state.s3_bew)
        _sd_save(pid, "s3_bewertungen", st.session_state.s3_bew)
        st.session_state.s3_screen = "abschluss"
        st.rerun()


def _screen_abschluss():
    st.success("## Danke für deine Teilnahme!")
    st.markdown(
        "Du hast alle drei Sitzungen der Aigora-Studie zur Wärmewende abgeschlossen. "
        "Deine Bewertungen fließen in den Abschlussbericht ein."
    )
    st.balloons()
    st.divider()
    if st.button("✏️ Eingaben anpassen", use_container_width=True):
        st.session_state.s3_screen = "bewertung"
        st.rerun()


# ── Hauptrender ──────────────────────────────────────────────────────

def render(participant_id):
    try:
        empfehlung = _load_empfehlung()
    except FileNotFoundError:
        st.info(f"`{EMPFEHLUNG_PATH}` noch nicht vorhanden. Sitzung 3 ist noch nicht bereit.")
        return
    try:
        dossiers = _load_dossiers()
    except FileNotFoundError:
        dossiers = {}

    if not _BEW_OK:
        st.error("Bewertungsmodul (session3_bewertungen.py) fehlt.")
        return

    _ensure_folders()

    if "s3_init" not in st.session_state:
        st.session_state.s3_bew = _sd_load(participant_id, "s3_bewertungen") or laden(participant_id)
        st.session_state.s3_chat = _sd_load(participant_id, "s3_chat") or []
        st.session_state.s3_screen = "begruessung"
        st.session_state.s3_init = True

    eigene_pos = _eigene_positionen(dossiers, empfehlung, participant_id) if dossiers else {}

    if st.session_state.s3_screen != "begruessung":
        _render_sidebar(participant_id, empfehlung, eigene_pos)

    try:
        if st.session_state.s3_screen == "begruessung":
            _screen_begruessung()
        elif st.session_state.s3_screen == "bewertung":
            _screen_bewertung(participant_id, empfehlung, dossiers, eigene_pos)
        elif st.session_state.s3_screen == "abschluss":
            _screen_abschluss()
    except Exception as exc:
        st.error(f"Fehler in Sitzung 3: {exc}")

    if st.session_state.get("_save_failed"):
        st.warning("Letzte Speicherung fehlgeschlagen. Eingaben bleiben in dieser Sitzung erhalten, "
                   "bitte Tab offen lassen.")

    st.caption(f"ID: {participant_id}")
