"""
voice_io.py

STT + TTS fuer Sitzung 1, komplett ueber Azure AI Speech (Microsoft) --
gewaehlt wegen Zero Data Retention als Standardverhalten fuer ALLE Kunden,
ohne Enterprise-Vereinbarung (siehe Chatverlauf, Primaerquelle:
https://learn.microsoft.com/.../text-to-speech/data-privacy-security --
"Microsoft doesn't retain or store the text ... doesn't store audio ...
generated with the real-time synthesis API").

Braucht in st.secrets:
    [azure_speech]
    key = "..."
    region = "..."         # z.B. "swedencentral" -- fuer TTS (regionsbasiert)
    resource_name = "..."  # der Name der Speech-Ressource im Azure-Portal
                            # (Ressourcen-Uebersichtsseite) -- fuer STT ueber
                            # die Fast-Transcription-API (ressourcennamen-
                            # basierter Endpoint "*.cognitiveservices.azure.com")

Endpoints:
    STT: https://{resource_name}.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe
         -- Fast Transcription API, NICHT die "Kurz-Audio"-Schnittstelle.
         GEWECHSELT (siehe CHANGELOG_SOKRA.md): die alte Kurz-Audio-API war
         hart auf 60 Sekunden UND EINE einzelne Aeusserung begrenzt -- bei
         einer Denkpause im Gespraech wurde der Rest der Aufnahme schlicht
         ignoriert ("nur der erste Teil transkribiert"). Fast Transcription
         verarbeitet komplette Aufnahmen mit mehreren Aeusserungen/Pausen
         (bis 5 Stunden), synchron in einem Request, kein Polling noetig.
    TTS: https://{region}.tts.speech.microsoft.com/cognitiveservices/v1
         (regionsbasiert, unveraendert -- fuer TTS reicht die einfachere
         Schnittstelle, dort gibt es keine Pausen-/Laengenproblematik).

Technischer Hinweis: _resample_to_16k_mono existiert noch aus der alten
Kurz-Audio-Anbindung (dort strikt verlangt) -- fuer Fast Transcription nicht
zwingend noetig, aber unschaedlich und bewusst drin gelassen (schadet der
Erkennungsqualitaet nicht, spart eine Sonderbehandlung).

Datenschutz: trotz der oben zitierten Standardzusage vor Studienstart mit
der Datenschutz-/Ethikstelle der Uni gegenchecken, nicht allein auf diesen
Code-Kommentar verlassen.
"""

import io
import json
import wave
from xml.sax.saxutils import escape

import numpy as np
import requests
import streamlit as st

STT_LANGUAGE = "de-DE"
TTS_OUTPUT_FORMAT = "audio-24khz-96kbitrate-mono-mp3"

DEFAULT_TTS_VOICE = "de-DE-Florian:DragonHDLatestNeural"
DEFAULT_TTS_RATE = "+0%"

# "Aigora" wird von der TTS-Stimme ohne Hilfe uneinheitlich ausgesprochen
# (z.B. wie ein englischer Name) -- per IPA-Phonem fest auf kurzes "ai"
# (Diphthong wie in "Mai") + langes "o" (wie in "Rose") verankert.
AIGORA_PHONEME = "<phoneme alphabet='ipa' ph='aɪɡoːʁa'>Aigora</phoneme>"

# Kuratierte Auswahl fuer ein Stimm-Dropdown im Interface -- vollstaendige
# Liste (15+ Standard- plus Multilingual-/HD-Stimmen) waere zu unuebersicht-
# lich, das hier deckt Geschlecht/Charakter-Varianz ab. Anzeigename -> Azure-
# Stimmenname. Florian/Seraphina "Dragon HD" zuerst gesetzt (des Autors Test:
# GA-Status in swedencentral, kontextbewusst -- klingt laut Microsofts
# eigener Beschreibung deutlich lebendiger/weniger monoton als die aelteren
# Multilingual-/Standard-Neural-Stimmen, die vorher Standard waren).
GERMAN_VOICES = {
    "Florian (männlich, HD, lebendig)": "de-DE-Florian:DragonHDLatestNeural",
    "Seraphina (weiblich, HD, lebendig)": "de-DE-Seraphina:DragonHDLatestNeural",
    "Florian (männlich, klassisch)": "de-DE-FlorianMultilingualNeural",
    "Seraphina (weiblich, klassisch)": "de-DE-SeraphinaMultilingualNeural",
    "Katja (weiblich, klassisch)": "de-DE-KatjaNeural",
    "Conrad (männlich, klassisch)": "de-DE-ConradNeural",
}

# Fuer ein Geschwindigkeits-Dropdown -- SSML-Prosody-Rate-Werte als Prozent-
# Abweichung von der Normalgeschwindigkeit der jeweiligen Stimme.
TTS_RATES = {
    "Langsamer": "-20%",
    "Etwas langsamer": "-10%",
    "Normal": "+0%",
    "Etwas schneller": "+10%",
    "Schneller": "+20%",
}


def _region() -> str:
    return st.secrets["azure_speech"]["region"]


def _resource_host() -> str:
    return f"https://{st.secrets['azure_speech']['resource_name']}.cognitiveservices.azure.com"


def _auth_header() -> dict:
    return {"Ocp-Apim-Subscription-Key": st.secrets["azure_speech"]["key"]}


def list_voices():
    """Fragt bei Azure die Liste aller fuer diese Ressource/Region tatsaech-
    lich freigeschalteten Stimmen ab -- u.a. um zu pruefen, ob eine Preview-
    Stimme (z.B. OpenAI-Stimmen in Azure Speech) verfuegbar ist, ohne dafuer
    ein Terminal/curl zu brauchen. Gibt bei Fehlern eine Liste mit einem
    einzigen Fehler-Eintrag zurueck, statt zu crashen."""
    try:
        response = requests.get(
            f"https://{_region()}.tts.speech.microsoft.com/cognitiveservices/voices/list",
            headers=_auth_header(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return [{"Fehler": str(e)}]


def _resample_to_16k_mono(wav_bytes: bytes) -> bytes:
    """Wandelt eine beliebige WAV-Aufnahme in 16kHz/Mono/16-Bit-PCM um, wie
    von Azures Kurz-Audio-REST-Schnittstelle strikt verlangt. Einfache
    lineare Interpolation reicht fuer Spracherkennung aus, keine
    Studioqualitaet noetig."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        return wav_bytes  # kein 16-Bit-PCM -- unveraendert durchreichen

    audio = np.frombuffer(frames, dtype=np.int16)
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1).astype(np.int16)

    if framerate != 16000 and len(audio) > 1:
        duration = len(audio) / framerate
        target_len = max(int(duration * 16000), 1)
        old_indices = np.linspace(0, len(audio) - 1, num=len(audio))
        new_indices = np.linspace(0, len(audio) - 1, num=target_len)
        audio = np.interp(new_indices, old_indices, audio).astype(np.int16)

    out = io.BytesIO()
    with wave.open(out, "wb") as wf_out:
        wf_out.setnchannels(1)
        wf_out.setsampwidth(2)
        wf_out.setframerate(16000)
        wf_out.writeframes(audio.tobytes())
    return out.getvalue()


def transcribe_audio(audio_bytes: bytes, content_type: str = "audio/wav") -> str:
    """Wandelt eine Sprachaufnahme in Text um (Azure Fast Transcription API).
    Gibt bei Fehlern einen leeren String zurueck -- der Aufrufer behandelt
    das wie "nichts eingegeben", statt die Sitzung mit einer Exception
    abzubrechen. `profanityFilterMode: None` bewusst gesetzt -- Azures
    Standard ("Masked") wuerde z.B. Kraftausdruecke der Person durch
    Sternchen ersetzen, das verfaelscht die eigentliche Aussage."""
    try:
        audio_16k = _resample_to_16k_mono(audio_bytes)
        definition = {"locales": [STT_LANGUAGE], "profanityFilterMode": "None"}
        response = requests.post(
            f"{_resource_host()}/speechtotext/transcriptions:transcribe",
            params={"api-version": "2025-10-15"},
            headers=_auth_header(),
            files={
                "audio": ("audio.wav", audio_16k, "audio/wav"),
                "definition": (None, json.dumps(definition), "application/json"),
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        phrases = result.get("combinedPhrases") or []
        if not phrases:
            st.session_state["_s1_last_voice_error"] = "Keine Sprache erkannt (leere Antwort)."
            return ""
        return phrases[0].get("text", "").strip()
    except Exception as e:
        st.session_state["_s1_last_voice_error"] = f"STT-Fehler: {e}"
        return ""


def synthesize_speech(text: str, voice: str = DEFAULT_TTS_VOICE, rate: str = DEFAULT_TTS_RATE):
    """Erzeugt eine MP3-Sprachausgabe fuer den gegebenen Text (Azure
    Text-to-Speech). `voice` und `rate` steuern Stimme und Geschwindigkeit
    (siehe GERMAN_VOICES/TTS_RATES fuer sinnvolle Werte). Gibt None zurueck
    bei leerem Text oder Fehlern -- der Aufrufer zeigt dann einfach keine
    Audiospur an, der Text bleibt trotzdem normal sichtbar."""
    if not text.strip():
        return None
    escaped_text = escape(text).replace("Aigora", AIGORA_PHONEME)
    ssml = (
        f"<speak version='1.0' xml:lang='de-DE'>"
        f"<voice xml:lang='de-DE' name='{voice}'>"
        f"<prosody rate='{rate}'>{escaped_text}</prosody>"
        f"</voice></speak>"
    )
    try:
        response = requests.post(
            f"https://{_region()}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                **_auth_header(),
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": TTS_OUTPUT_FORMAT,
                "User-Agent": "Aigora-Sokra",
            },
            data=ssml.encode("utf-8"),
            timeout=30,
        )
        response.raise_for_status()
        return response.content
    except Exception as e:
        st.session_state["_s1_last_voice_error"] = f"TTS-Fehler: {e}"
        return None
