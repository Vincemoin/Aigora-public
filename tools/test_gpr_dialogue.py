"""
test_gpr_dialogue.py

OFFLINE-Testskript: simuliert eine komplette GPR-Sitzung zwischen Sokra
(echter Claude-Aufruf ueber gpr_core.py, identischer Code-Pfad wie die App)
und einer simulierten Testperson (zweiter Claude-Aufruf mit eigener
Persona-Beschreibung). Kein Streamlit-Server noetig, laeuft rein im
Terminal -- Zweck: schnelle, wiederholbare Testlaeufe, ohne dass jede
Nachricht manuell eingetippt werden muss.

WICHTIG, ehrlich: das ersetzt echte menschliche Testlaeufe NICHT vollstaendig
-- eine simulierte Person ist immer noch eine KI ohne echte Unsicherheiten,
Tippfehler oder Emotionen. Gedacht als schnelles Zusatzwerkzeug zwischen
echten Testrunden, nicht als Ersatz dafuer.

Braucht eine lokale .env-Datei (git-ignoriert, siehe .gitignore) mit:
    ANTHROPIC_API_KEY=...
    OPENAI_API_KEY=...
(dieselben Werte wie in den Streamlit-Cloud-Secrets -- fuer search_corpus
wird zusaetzlich der bereits im Repo liegende chroma_db/-Ordner genutzt,
kein Extra-Setup noetig.)

Nutzung:
    python test_gpr_dialogue.py --turns 24 --persona skeptisch
    python test_gpr_dialogue.py --turns 30 --persona engagiert
    python test_gpr_dialogue.py --persona unentschlossen

Transkripte landen in test_runs/ (git-ignoriert, siehe .gitignore).
"""

import argparse
import datetime
import json
import os
import sys

# Windows-Konsolen-Codepage (cp1252) kann Emojis/Sonderzeichen nicht
# ausgeben -- ein Absturz HIER (reine Anzeige) darf niemals den ganzen
# Testlauf und damit das Transkript kosten (siehe Bug: erster Lauf brach
# bei einem Emoji in Sokras Abschiedsgruss ab, JSON wurde nie geschrieben,
# weil bisher nur am Ende gespeichert wurde -- jetzt zusaetzlich nach jedem
# Zug, siehe run()).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import truststore
    truststore.inject_into_ssl()  # nutzt den Windows/macOS-Zertifikatsspeicher
    # statt Pythons gebuendelter Zertifikatsliste -- hilft, wenn lokale
    # Antivirus-/Firewall-Software HTTPS-Verbindungen mit einem eigenen,
    # im Betriebssystem (aber nicht in certifi) vertrauten Zertifikat
    # spiegelt. Optional: nur lokal fuers Testskript relevant, betrifft die
    # eigentliche App (Streamlit Cloud) nicht.
except ImportError:
    pass

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic

from gpr_core import TOOLS, call_search_tool, get_system_block, with_cache_breakpoint, MODEL
from views.sitzung1_view import FIXED_WELCOME_FULL

client = Anthropic()

# Die simulierte Testperson braucht nicht Sonnet 5 -- sie spielt nur eine
# Rolle nach Skript, keine komplexe Aufgabe wie Sokra selbst. Haiku 4.5
# ist dafuer ausreichend und deutlich guenstiger. War bisher versehentlich
# auch auf MODEL (Sonnet 5) gesetzt -- vermutlich der Hauptkostentreiber
# der heutigen Testlaeufe, da JEDER zweite API-Call (die Persona-Seite)
# auf das teuerste Modell lief, ohne dass es das gebraucht haette.
PERSONA_MODEL = "claude-haiku-4-5-20251001"

PERSONAS = {
    "skeptisch": (
        "Du spielst eine Testperson (ca. 50, Eigenheimbesitzer:in auf dem Land) in einem Test-Chat "
        "zur deutschen Waermewende. Du bist eher skeptisch gegenueber staatlichen Vorgaben, hast Sorge "
        "um die Kosten einer neuen Heizung, aber bist nicht ideologisch dagegen -- du laesst dich von "
        "guten Argumenten durchaus bewegen. Du redest wie ein echter Mensch im Chat: mal kurz, mal etwas "
        "ausschweifend, gelegentlich ein Tippfehler, manchmal wechselst du das Thema oder wiederholst "
        "dich leicht, manchmal machst du auch mal eine Pause im Gedankengang mitten im Satz. Du bist "
        "KEIN Assistent -- antworte NUR als diese Person, ohne Meta-Kommentare, ohne zu erklaeren was du "
        "tust. Realistische Laenge, meist 1-4 Saetze, gelegentlich laenger wenn dir etwas wichtig ist."
    ),
    "engagiert": (
        "Du spielst eine Testperson (ca. 28, Mieterin in der Stadt, klimapolitisch engagiert) in einem "
        "Test-Chat zur deutschen Waermewende. Du bist grundsaetzlich fuer ambitionierten Klimaschutz, "
        "aber unsicher bei den konkreten Instrumenten (Foerderung vs. Verbote vs. CO2-Preis) und bei den "
        "Verteilungsfragen (wer zahlt). Du stellst gerne Rueckfragen und hinterfragst auch mal Quellen. "
        "Antworte wie ein echter Mensch im Chat, NICHT als Assistent -- keine Meta-Kommentare. "
        "Realistische Laenge, meist 1-4 Saetze."
    ),
    "unentschlossen": (
        "Du spielst eine Testperson (ca. 35, Angestellte, wohnt zur Miete, kein starkes Vorwissen zur "
        "Waermewende) in einem Test-Chat. Du hast noch keine gefestigte Meinung, laesst dich leicht von "
        "guten Argumenten in verschiedene Richtungen bewegen, fragst oft nach, wenn du einen Begriff "
        "nicht verstehst. Antworte wie ein echter Mensch im Chat, NICHT als Assistent -- keine "
        "Meta-Kommentare. Realistische Laenge, meist 1-3 Saetze, du bist eher wortkarg."
    ),
}


class Usage:
    """Sammelt Token-Verbrauch ueber den ganzen Lauf, getrennt nach Sokra
    (Sonnet 5) und Persona (Haiku), damit die tatsaechlichen Kostentreiber
    sichtbar werden statt geraten zu werden."""
    def __init__(self):
        self.sokra_in = self.sokra_out = self.sokra_cache_read = self.sokra_cache_write = 0
        self.persona_in = self.persona_out = 0

    def add_sokra(self, usage):
        self.sokra_in += getattr(usage, "input_tokens", 0)
        self.sokra_out += getattr(usage, "output_tokens", 0)
        self.sokra_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.sokra_cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def add_persona(self, usage):
        self.persona_in += getattr(usage, "input_tokens", 0)
        self.persona_out += getattr(usage, "output_tokens", 0)

    def report(self) -> str:
        return (
            f"Sokra (Sonnet 5): {self.sokra_in:,} Tokens in "
            f"(davon {self.sokra_cache_read:,} aus Cache gelesen, {self.sokra_cache_write:,} neu in Cache geschrieben), "
            f"{self.sokra_out:,} Tokens out\n"
            f"Persona (Haiku 4.5): {self.persona_in:,} Tokens in, {self.persona_out:,} Tokens out"
        )


usage = Usage()


def get_sokra_response(messages: list) -> str:
    """Identischer Ablauf wie _get_agent_response() in sitzung1_view.py,
    nur ohne Streamlit-UI (kein st.spinner, kein session_state) und mit
    derselben Text-Normalisierung wie dort (ein String statt Block-Liste,
    siehe CHANGELOG_SOKRA.md Punkt "zerschnipselte Antwort")."""
    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=get_system_block(), tools=TOOLS,
        messages=with_cache_breakpoint(messages),
    )
    usage.add_sokra(response.usage)
    while response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "search_corpus":
                try:
                    result_text = call_search_tool(block.input)
                except Exception as e:
                    result_text = f"Suche fehlgeschlagen ({e}). Bitte ohne dieses Suchergebnis antworten."
            else:
                result_text = "Unbekanntes Tool, keine Ausfuehrung moeglich."
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=get_system_block(), tools=TOOLS,
            messages=with_cache_breakpoint(messages),
        )
        usage.add_sokra(response.usage)
    final_text = "".join(
        getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"
    )
    messages.append({"role": "assistant", "content": final_text})
    return final_text


def get_persona_reply(persona_system: str, persona_messages: list) -> str:
    """Ruft die simulierte Testperson auf (Haiku 4.5, siehe PERSONA_MODEL)
    -- bekommt den Verlauf aus IHRER Sicht (was Sokra sagte = 'user' fuer
    die Persona, was sie selbst sagte = 'assistant')."""
    response = client.messages.create(
        model=PERSONA_MODEL, max_tokens=1024, system=persona_system, messages=persona_messages,
    )
    usage.add_persona(response.usage)
    return "".join(b.text for b in response.content if b.type == "text")


def run(turns: int, persona_key: str, out_path: str) -> None:
    persona_system = PERSONAS[persona_key]
    sokra_messages = [{"role": "assistant", "content": FIXED_WELCOME_FULL}]
    persona_messages = [{"role": "user", "content": FIXED_WELCOME_FULL}]
    transcript = [{"role": "sokra", "text": FIXED_WELCOME_FULL}]

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def _save():
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)

    farewell_streak = 0
    for turn in range(turns):
        persona_reply = get_persona_reply(persona_system, persona_messages)
        print(f"\n--- Person (Zug {turn + 1}) ---\n{persona_reply}")
        transcript.append({"role": "person", "text": persona_reply})
        persona_messages.append({"role": "assistant", "content": persona_reply})
        sokra_messages.append({"role": "user", "content": persona_reply})
        _save()  # nach JEDEM Zug speichern, nicht erst am Ende -- ein
        # spaeterer Absturz (z.B. reine Konsolen-Anzeigefehler) darf nicht
        # den ganzen bisherigen Testlauf kosten.

        sokra_reply = get_sokra_response(sokra_messages)
        print(f"\n--- Sokra (Zug {turn + 1}) ---\n{sokra_reply}")
        transcript.append({"role": "sokra", "text": sokra_reply})
        persona_messages.append({"role": "user", "content": sokra_reply})
        _save()

        # Fruehzeitig abbrechen, wenn das Gespraech erkennbar schon zu Ende
        # ist (Persona verabschiedet sich mehrfach kurz hintereinander) --
        # sonst laufen beide Seiten bis zum --turns-Limit nur noch "Tschuess"
        # hin und her (siehe Bug-Report: hat in allen drei Laeufen die
        # Wortzahl-Statistik verfaelscht und unnoetig API-Kosten verursacht).
        if len(persona_reply.split()) <= 4:
            farewell_streak += 1
        else:
            farewell_streak = 0
        if farewell_streak >= 2:
            print("\n(Gespraech wirkt beendet -- zwei kurze Abschieds-Zuege in Folge, breche frueher ab.)")
            break
        _save()

    print(f"\n\nTranskript vollstaendig gespeichert: {out_path}")
    print(f"\nToken-Verbrauch dieses Laufs:\n{usage.report()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=24, help="Anzahl Hin-und-Her-Zuege (Standard: 24)")
    parser.add_argument("--persona", choices=list(PERSONAS.keys()), default="skeptisch")
    args = parser.parse_args()

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"test_runs/test_run_{args.persona}_{timestamp}.json"
    run(args.turns, args.persona, output_path)
