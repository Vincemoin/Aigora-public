"""
synthese_dossiers.py

Schritt 1 der Pause-2-Synthese-Pipeline: baut aus der Diskursstruktur
(data/session2_diskurse.json) und den echten Sitzung-2-Bewertungen
(data/session2_bewertungen_live/, siehe synthese_download_bewertungen.py)
ein vollstaendiges Dossier pro Cashore-Howlett-Dimension. Reiner Code,
keine API-Kosten. Naechster Schritt (synthese_agent.py, LLM-Synthese
pro Dimension) baut auf der Ausgabe hier auf.

Dimensionen werden direkt als die deutschen `abstraktionsebene`-Strings
aus den echten Daten gefuehrt ("Uebergeordnete Ziele", "Konkrete Ziele",
"Zwischenziele", "Umsetzungslogik", "Instrumententyp",
"Feinausgestaltung") -- NICHT ueber die englischen Cashore-Howlett-Codes
(Goals/Objectives/...), deren deutsche Zuordnung zwischen
extract_ratified.py und der aktuellen Diskursstruktur widerspruechlich
ist (siehe DIMENSION_NAMES_DE dort vs. ABSTR_FARBEN in
views/sitzung2_view.py -- Objectives/Settings sind dort vertauscht).

Bekannte Dateneigenheiten, hier korrigiert/beruecksichtigt:

1. ID-Kollision: Lager-/Standpunkt-IDs sind im Rohformat IMMER mit
   "D1-..." praefigiert (Bug im Clustering-Schritt-2-Prompt, das
   Beispiel wurde woertlich uebernommen statt die echte Diskursnummer
   einzusetzen), unabhaengig vom tatsaechlichen Diskurs. Wird hier
   korrigiert: das "D1"-Praefix wird durch die echte diskurs_id ersetzt
   (roh_id bleibt zur Rueckverfolgung zusaetzlich erhalten).

2. Vererbungs-Speicherbug: standpunkt_bewertungen stehen in den echten
   Dateien fast durchgehend auf {"wert": 0, "quelle": "direkt"}, selbst
   wenn die Person nur das uebergeordnete Lager bewertet hat (Ursache:
   das Standpunkt-Widget wird bei jedem Rerun neu ausgewertet, auch im
   eingeklappten Expander, und ueberschreibt beim Speichern die eigent-
   lich korrekte Vererbung mit dem Default-Wert 0/"direkt"). Wird hier
   rekonstruiert statt aus den gespeicherten Dateien uebernommen: wert>0
   zaehlt als echte direkte Bewertung, sonst faellt der Wert auf die
   Lager-Bewertung zurueck ("vererbt_von_lager"), sonst "kein_urteil".

3. Mehrfachauftauchen NUR ueber Dimensionsgrenzen hinweg, nicht darunter:
   ein Lager-Kommentar, ein Diskurs-Kompromissvorschlag oder ein
   unwidersprochener Punkt kann mehrere Dimensionen beruehren, wenn seine
   Standpunkte/Positionen auf verschiedenen Abstraktionsebenen liegen --
   er wird dann bewusst in JEDES betroffene Dimensions-Dossier
   uebernommen (mit der Autor abgestimmt: Bewertungen zu einer Sichtweise
   betreffen wahrheitsgemaess alle ihre Unterebenen). INNERHALB einer
   Dimension darf ein Lager-Kommentar aber NICHT einfach in jeden dort
   liegenden Geschwister-Standpunkt kopiert werden -- das war ein Bug in
   einer frueheren Version (ein Lager mit 2 Standpunkten in derselben
   Dimension liess denselben Kommentar wortgleich zweimal auftauchen,
   ohne neuen Informationsgehalt). Lager-Kommentare stehen daher separat,
   EINMAL pro (diskurs_id, lager_id), nicht dupliziert pro Standpunkt.
   Ein Standpunkt traegt in seiner eigenen "kommentare"-Liste nur echte
   DIREKTE Standpunkt-Kommentare.

Nutzung:
    python synthese_dossiers.py
"""

import glob
import json
import os
from collections import defaultdict

STRUCTURE_PATH = "data/session2_diskurse.json"
BEWERTUNGEN_DIR = "data/session2_bewertungen_live"
OUTPUT_PATH = "data/synthese/dossiers.json"

# Test-Pseudonyme, die NIE als echte Teilnehmende in die Synthese einfliessen
# duerfen -- "Vince" war des Autors eigene Test-ID waehrend der Entwicklung,
# keine echten Studiendaten. Die zugehoerige Bewertungsdatei wurde bereits
# aus SurfDrive geloescht, aber die Zitate stecken noch als "mitglieder"-
# Eintraege in der Clustering-Struktur (session2_diskurse.json) selbst, aus
# der Zeit VOR der eigentlichen Studie -- werden hier konsequent
# herausgefiltert (Zitate, Herkunfts-Dimension, Personenzahl).
_TESTPERSONEN_AUSSCHLUSS = {"Vince"}


def _echte_mitglieder(sp):
    return [m for m in sp.get("mitglieder", [])
            if m.get("participant_id") not in _TESTPERSONEN_AUSSCHLUSS]


# ── Dimensions-Zuordnung ─────────────────────────────────────────────

def _herkunft_dimensionen(sp):
    """Welche(r) der sechs Cashore-Howlett-Dimension(en) dieser Standpunkt
    zugeordnet wird -- NICHT die vom Clustering-Modell freihaendig aus dem
    Standpunkt-Wortlaut geschaetzte 'abstraktionsebene' (unzuverlaessig,
    56% Abweichung von der echten S1-Herkunft in echten Laeufen gemessen),
    sondern die tatsaechliche, in Sitzung 1 von Sokra geprueften Herkunft
    der zugeordneten Personen. Ein Standpunkt buendelt fast immer Personen
    aus genau EINER Herkunfts-Dimension (57 von 63 in echten Daten) -- nur
    wenn das Clustering Personen aus zwei benachbarten Dimensionen
    zusammengefasst hat, erscheint der Standpunkt bewusst in BEIDEN
    betroffenen Dimensionen (kein Informationsverlust, mit der Autor
    abgestimmt)."""
    dims = {m.get("herkunft_dimension", "?") for m in _echte_mitglieder(sp)}
    dims.discard("?")
    return dims or {"?"}


# ── ID-Korrektur ─────────────────────────────────────────────────────

def _fix_id(raw_id, diskurs_id):
    """Ersetzt das kollidierende, immer gleiche 'D1'-Praefix durch die
    echte diskurs_id, z.B. 'D1-L1-S2' in Diskurs 'D3' -> 'D3-L1-S2'."""
    if raw_id.startswith("D1-"):
        return diskurs_id + raw_id[len("D1"):]
    return raw_id


# ── Laden ────────────────────────────────────────────────────────────

def _load_struktur():
    with open(STRUCTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_bewertungen(basis_dir=BEWERTUNGEN_DIR):
    alle = []
    for pfad in sorted(glob.glob(os.path.join(basis_dir, "*.json"))):
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        if daten.get("diskurse"):
            alle.append(daten)
    return alle


# ── Vererbungs-Rekonstruktion (siehe Moduldoc, Punkt 2) ────────────────

def _standpunkt_effektiv(diskurs_block, sp_raw_id, lager_raw_id):
    """Rekonstruiert NUR den Zustimmungswert (Zahl) mit Vererbung. Der
    Kommentar wird bewusst NICHT vom Lager mituebernommen -- der
    Lager-Kommentar gehoert an genau EINE Stelle (siehe
    `_lager_kommentare_liste`), nicht dupliziert in jeden Standpunkt
    darunter (frueherer Bug, siehe Moduldoc Punkt 3)."""
    sp_bew = diskurs_block.get("standpunkt_bewertungen", {}).get(sp_raw_id) or {}
    lager_bew = diskurs_block.get("lager_bewertungen", {}).get(lager_raw_id) or {}
    eigener_kommentar = sp_bew.get("kommentar", "")

    sp_wert = sp_bew.get("wert") or 0
    if sp_wert > 0:
        return {"wert": sp_wert, "quelle": "direkt", "eigener_kommentar": eigener_kommentar}

    lager_wert = lager_bew.get("wert") or 0
    if lager_wert > 0:
        return {"wert": lager_wert, "quelle": "vererbt_von_lager", "eigener_kommentar": eigener_kommentar}

    return {"wert": 0, "quelle": "kein_urteil", "eigener_kommentar": eigener_kommentar}


def _lager_kommentare_liste(bewertungen, d_id, l_raw):
    """EINMAL pro (diskurs_id, lager_id) berechnete Liste der Kommentare,
    die Personen direkt an der Sichtweise (nicht an einem Einzelstandpunkt)
    hinterlassen haben. Wird an alle Dimensionen angehaengt, die dieses
    Lager ueber seine Standpunkte beruehrt -- aber nur EINMAL pro
    Dimension, nicht pro Standpunkt darin."""
    liste = []
    for person in bewertungen:
        block = person.get("diskurse", {}).get(d_id)
        if not block or block.get("uebersprungen"):
            continue
        lb = block.get("lager_bewertungen", {}).get(l_raw) or {}
        kommentar = lb.get("kommentar", "")
        if kommentar:
            liste.append({
                "participant_id": person.get("participant_id"),
                "wert": lb.get("wert", 0),
                "kommentar": kommentar,
            })
    return liste


def _neues_profil():
    return {
        "n_bewertet": 0,
        "verteilung": {str(i): 0 for i in range(1, 6)},
        "mittelwert": None,
        "n_direkt": 0,
        "n_vererbt_von_lager": 0,
        "befuerwortung_4_5": 0,
        "ablehnung_1_2": 0,
        "bewertungen": [],
        "kommentare": [],
    }


# ── Dossier-Bau ──────────────────────────────────────────────────────

def build_dossiers():
    data = _load_struktur()
    diskurse = [d for d in data.get("diskurse", []) if d.get("lager") and not d.get("error")]
    bewertungen = _load_bewertungen()

    dossiers = defaultdict(lambda: {
        "standpunkte": [],
        "lager_kommentare": {},
        "diskurs_kompromissvorschlaege": defaultdict(list),
        "unwidersprochene_punkte": [],
    })

    for d in diskurse:
        d_id = d["id"]

        for lager in d.get("lager", []):
            l_raw = lager["id"]
            l_id = _fix_id(l_raw, d_id)

            dims_dieses_lagers = set()
            for sp in lager.get("standpunkte", []):
                if sp.get("mitglieder") and not _echte_mitglieder(sp):
                    continue  # nur Testpersonen, siehe Ausschluss weiter unten
                dims_dieses_lagers |= _herkunft_dimensionen(sp)
            lager_kommentare = _lager_kommentare_liste(bewertungen, d_id, l_raw)
            for dim in dims_dieses_lagers:
                dossiers[dim]["lager_kommentare"][l_id] = lager_kommentare

            for sp in lager.get("standpunkte", []):
                if sp.get("mitglieder") and not _echte_mitglieder(sp):
                    # Standpunkt besteht AUSSCHLIESSLICH aus Testpersonen
                    # (z.B. des Autors eigener "Vince"-Testlauf) -- kein
                    # einziger echter Teilnehmender dahinter, komplett
                    # ausschliessen statt mit leeren Zitaten aufzunehmen.
                    continue
                sp_raw = sp["id"]
                sp_id = _fix_id(sp_raw, d_id)
                sp_dimensionen = _herkunft_dimensionen(sp)

                profil = _neues_profil()
                for person in bewertungen:
                    pid = person.get("participant_id")
                    block = person.get("diskurse", {}).get(d_id)
                    if not block or block.get("uebersprungen"):
                        continue
                    eff = _standpunkt_effektiv(block, sp_raw, l_raw)

                    if eff["wert"] > 0:
                        profil["n_bewertet"] += 1
                        profil["verteilung"][str(eff["wert"])] += 1
                        profil["bewertungen"].append(
                            {"participant_id": pid, "wert": eff["wert"], "quelle": eff["quelle"]}
                        )
                        if eff["quelle"] == "direkt":
                            profil["n_direkt"] += 1
                        else:
                            profil["n_vererbt_von_lager"] += 1
                        if eff["wert"] >= 4:
                            profil["befuerwortung_4_5"] += 1
                        elif eff["wert"] <= 2:
                            profil["ablehnung_1_2"] += 1

                    if eff["eigener_kommentar"]:
                        profil["kommentare"].append(
                            {"participant_id": pid, "quelle": eff["quelle"],
                             "kommentar": eff["eigener_kommentar"]}
                        )

                if profil["n_bewertet"]:
                    profil["mittelwert"] = round(
                        sum(b["wert"] for b in profil["bewertungen"]) / profil["n_bewertet"], 2
                    )

                zitate, seen = [], set()
                for m in _echte_mitglieder(sp):
                    mpid = m.get("participant_id", "")
                    if mpid in seen:
                        continue
                    seen.add(mpid)
                    zitate.append({
                        "participant_id": mpid,
                        "herkunft_dimension": m.get("herkunft_dimension", "?"),
                        "zitat": m.get("zitat", ""),
                    })

                for dim in sp_dimensionen:
                    dossiers[dim]["standpunkte"].append({
                        "id": sp_id,
                        "roh_id": sp_raw,
                        "diskurs_id": d_id,
                        "diskurs_titel": d.get("titel", ""),
                        "streitfrage": d.get("streitfrage", ""),
                        "lager_id": l_id,
                        "lager_titel": lager.get("titel", ""),
                        "titel": sp.get("titel", ""),
                        "position": sp.get("position", ""),
                        "setzt_voraus": sp.get("setzt_voraus", ""),
                        "ursprungszitate": zitate,
                        "unterstuetzung": profil,
                        "abstraktionsebene_clustering": sp.get("abstraktionsebene", "?"),
                    })

        # Kompromissvorschlaege sind pro Diskurs (nicht pro Lager/Standpunkt)
        # gespeichert -- propagiert in jede Dimension, die im Diskurs vorkommt.
        dims_in_diskurs = set()
        for lager in d.get("lager", []):
            for sp in lager.get("standpunkte", []):
                if sp.get("mitglieder") and not _echte_mitglieder(sp):
                    continue
                dims_in_diskurs |= _herkunft_dimensionen(sp)
        for person in bewertungen:
            pid = person.get("participant_id")
            block = person.get("diskurse", {}).get(d_id)
            if not block:
                continue
            text = block.get("kompromissvorschlag", "")
            if not text:
                continue
            for dim in dims_in_diskurs:
                dossiers[dim]["diskurs_kompromissvorschlaege"][d_id].append(
                    {"participant_id": pid, "text": text}
                )

    # ── Unwidersprochene Punkte ──────────────────────────────────────
    konsens = defaultdict(lambda: {"werte": [], "kommentare": []})
    for person in bewertungen:
        pid = person.get("participant_id")
        for u_id, wert in (person.get("konsens_bewertungen") or {}).items():
            if wert:
                konsens[u_id]["werte"].append({"participant_id": pid, "wert": wert})
        for u_id, kommentar in (person.get("konsens_kommentare") or {}).items():
            if kommentar:
                konsens[u_id]["kommentare"].append({"participant_id": pid, "kommentar": kommentar})

    for u in data.get("unwidersprochene_punkte", []):
        u_id = u.get("id", "")
        dims = {p.get("herkunft_dimension", "?") for p in u.get("positionen", [])}
        agg = konsens.get(u_id, {"werte": [], "kommentare": []})
        werte = [w["wert"] for w in agg["werte"]]
        eintrag = {
            "id": u_id,
            "titel": u.get("titel", ""),
            "beschreibung": u.get("beschreibung", ""),
            "s1_positionen": u.get("positionen", []),
            "s2_bestaetigung": {
                "n": len(werte),
                "mittelwert": round(sum(werte) / len(werte), 2) if werte else None,
                "bewertungen": agg["werte"],
            },
            "abweichende_kommentare": agg["kommentare"],
        }
        for dim in dims:
            dossiers[dim]["unwidersprochene_punkte"].append(eintrag)

    ausgabe = {
        dim: {
            "standpunkte": inhalt["standpunkte"],
            "lager_kommentare": inhalt["lager_kommentare"],
            "diskurs_kompromissvorschlaege": dict(inhalt["diskurs_kompromissvorschlaege"]),
            "unwidersprochene_punkte": inhalt["unwidersprochene_punkte"],
        }
        for dim, inhalt in dossiers.items()
    }
    return ausgabe, len(bewertungen)


def main():
    dossiers, n_personen = build_dossiers()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dossiers, f, ensure_ascii=False, indent=2)

    print(f"Bewertungsdateien geladen: {n_personen} (aus {BEWERTUNGEN_DIR}/)")
    print(f"Dossiers geschrieben nach {OUTPUT_PATH}\n")
    for dim, inhalt in dossiers.items():
        n_sp = len(inhalt["standpunkte"])
        n_bewertet = sum(1 for sp in inhalt["standpunkte"] if sp["unterstuetzung"]["n_bewertet"] > 0)
        n_konsens = len(inhalt["unwidersprochene_punkte"])
        n_direkte_sp_kommentare = sum(len(sp["unterstuetzung"]["kommentare"]) for sp in inhalt["standpunkte"])
        n_lager_kommentare = sum(len(v) for v in inhalt["lager_kommentare"].values())
        n_kompromiss = sum(len(v) for v in inhalt["diskurs_kompromissvorschlaege"].values())
        print(f"{dim}: {n_sp} Standpunkte ({n_bewertet} mit >=1 Bewertung), "
              f"{n_konsens} Konsens-Fixpunkte, {n_direkte_sp_kommentare} direkte Standpunkt-Kommentare, "
              f"{n_lager_kommentare} Lager-Kommentare (je einmal), {n_kompromiss} Kompromissvorschlaege")


if __name__ == "__main__":
    main()
