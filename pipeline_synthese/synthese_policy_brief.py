"""
synthese_policy_brief.py

Das eigentliche Endprodukt: ein lesbares Empfehlungsdokument aus
data/synthese/empfehlung_final.json.

Aufbau folgt jetzt der Cashore-Howlett-Trichterlogik: zwei Spalten (ZWECK /
MITTEL), je drei Zeilen (Hoch/Makro -> Niedrig/Mikro), visuell nach unten
schmaler werdend -- von abstrakten Zielen zu konkreter Feinausgestaltung.

Echte Entweder-Oder-Konflikte (siehe "konfliktgruppen" in
synthese_final_synthese.py) werden PROMINENT als offene Entscheidung
angezeigt, nicht als zwei unabhaengige Empfehlungen nebeneinander.

Erklaerungen sind zweigeteilt: "nutzer_erklaerung" (IDs-frei, fuer
Teilnehmende, standardmaessig eingeklappt) vs. "begruendung" (intern, mit
IDs/Fachjargon, nur in der Rueckverfolgbarkeit).

Nutzung:
    python synthese_policy_brief.py
Erzeugt: data/synthese/policy_brief.html
"""

import json
import re
from html import escape as e

EMPFEHLUNG_PATH = "data/synthese/empfehlung_final.json"
FILTER_PATH = "data/synthese/standpunkt_filter.json"
DOSSIERS_PATH = "data/synthese/dossiers.json"
OUTPUT_PATH = "data/synthese/policy_brief.html"

DIM_FARBEN = {
    "Übergeordnete Ziele": "#1a6b3c", "Konkrete Ziele": "#2d7d9a",
    "Zwischenziele": "#5c6bc0", "Umsetzungslogik": "#7b5ea7",
    "Instrumententyp": "#b06a20", "Feinausgestaltung": "#9e3030",
}

# Cashore-Howlett-Matrix: (Zweck-Dimension, Mittel-Dimension) je Abstraktionsstufe
FUNNEL_ZEILEN = [
    ("Hoch (Makro)", "Übergeordnete Ziele", "Umsetzungslogik"),
    ("Mittel (Meso)", "Konkrete Ziele", "Instrumententyp"),
    ("Niedrig (Mikro)", "Zwischenziele", "Feinausgestaltung"),
]
FUNNEL_BREITEN = ["100%", "88%", "76%"]  # Trichter-Effekt: abstrakt -> konkret


def badge(text, color="#555"):
    return (f'<span style="background:{color};color:#fff;border-radius:3px;'
            f'padding:1px 6px;font-size:.72rem;font-weight:600;white-space:nowrap">'
            f'{e(str(text))}</span>')


def _clean(text):
    """Entfernt rohe Token-Reste (E0, E12 ...), falls das Modell versehentlich
    eins statt der echten ID im Beschreibungstext gelassen hat."""
    if not text:
        return text
    return re.sub(r"\bE\d+\b", "", text)


def main():
    with open(EMPFEHLUNG_PATH, encoding="utf-8") as f:
        empfehlung = json.load(f)
    with open(FILTER_PATH, encoding="utf-8") as f:
        filterdaten = json.load(f)
    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        dossiers = json.load(f)

    sp_lookup = {}
    for dim, inhalt in dossiers.items():
        for sp in inhalt["standpunkte"]:
            sp_lookup[(dim, sp["id"])] = sp

    alle_eintraege = {
        (dim, x["id"]): x
        for dim, inhalt in empfehlung["dimensionen"].items()
        for x in inhalt["eintraege"]
    }
    konfliktgruppen = empfehlung.get("konfliktgruppen", [])
    konflikt_je_kandidat = {}
    for i, kg in enumerate(konfliktgruppen):
        for opt in kg["optionen"]:
            konflikt_je_kandidat.setdefault((opt["dim"], opt["id"]), []).append(i)

    n_gesamt = sum(len(inhalt["eintraege"]) for inhalt in empfehlung["dimensionen"].values())
    n_angepasst = sum(1 for inhalt in empfehlung["dimensionen"].values()
                       for x in inhalt["eintraege"] if x["kohaerenz_angepasst"])
    n_zusammengefuehrt = sum(1 for inhalt in empfehlung["dimensionen"].values()
                              for x in inhalt["eintraege"] if x.get("zusammengefuehrt_aus"))
    a = filterdaten["zusammenfassung"]

    summary = (
        f'<div class="meta">'
        f'<span><strong>Empfehlungen gesamt:</strong> {n_gesamt}</span>'
        f'<span><strong>Geprüfte Standpunkte:</strong> {a["n_gesamt"]}</span>'
        f'<span><strong>Ausgeschlossen (echter Widerspruch):</strong> '
        f'{sum(1 for v in filterdaten.get("stufe_c",{}).values() if v["verdikt"]=="ausschliessen") + a["n_ausgeschlossen"]}</span>'
        f'<span><strong>Offene Entweder-Oder-Entscheidungen:</strong> {len(konfliktgruppen)}</span>'
        f'<span><strong>Wegen Kohärenz angepasst:</strong> {n_angepasst}</span>'
        f'<span><strong>Redundanzen zusammengeführt:</strong> {n_zusammengefuehrt}</span>'
        f'</div>'
        f'<div style="font-size:.85rem;color:#555;margin:10px 0 20px;max-width:760px">'
        f'Verfahren: <strong>No-Objection statt Mehrheitsschwelle</strong> — jeder Punkt hier hat entweder '
        f'breite Zustimmung, passt widerspruchsfrei zur im jeweiligen Diskurs meistgetragenen Sichtweise, '
        f'oder hat einen echten, aber nicht überproportionalen Widerspruch überstanden. Die Anordnung folgt '
        f'der Cashore-Howlett-Trichterlogik: links der ZWECK-Strang (was erreicht werden soll), rechts der '
        f'MITTEL-Strang (wie), jeweils von abstrakt (oben) zu konkret (unten).</div>'
    )

    # ── Konfliktgruppen-Uebersicht: gemeinsamer Kern EINMAL, dann nur die
    #    kompakten Unterschiede als klickbare Optionen (nicht die vollen,
    #    sich stark ueberschneidenden Aussagen nebeneinander) ─────────────
    konflikt_html = ""
    if konfliktgruppen:
        gruppen_karten = []
        for kg in konfliktgruppen:
            typ_label = "🔢 Zahlen-Spanne" if kg["typ"] == "numerisch" else "⚖️ Grundsätzliche Wahl"
            options_html = []
            for opt in kg["optionen"]:
                dim = opt["dim"]
                options_html.append(
                    f'<div style="flex:1;min-width:180px;border:1.5px solid #e67e22;border-radius:8px;'
                    f'padding:10px 12px;background:#fff">'
                    f'<div style="font-weight:700;font-size:.88rem;color:#7a4a00">{e(opt.get("kurzlabel") or "")}</div>'
                    + (f'<div style="font-size:.78rem;color:#555;margin-top:4px">{e(opt["unterschied_text"])}</div>'
                       if opt.get("unterschied_text") else "")
                    + f'<div style="font-size:.68rem;color:#aaa;margin-top:6px">{e(dim)}</div>'
                    + '</div>'
                )
            gruppen_karten.append(
                f'<div style="border:2px solid #e67e22;border-radius:10px;padding:14px 18px;margin:14px 0;background:#fff8f0">'
                f'<div style="display:flex;gap:8px;align-items:center">{badge(typ_label, "#e67e22")}'
                + (badge(f'{kg.get("min","")}–{kg.get("max","")} {kg.get("einheit","")}', "#e67e22")
                   if kg["typ"] == "numerisch" else "")
                + '</div>'
                f'<div style="font-size:.9rem;color:#333;margin:8px 0;font-weight:500">'
                f'✓ Gemeinsam: {e(_clean(kg.get("gemeinsamer_kern","")))}</div>'
                f'<div style="font-size:.78rem;color:#7a4a00;margin:6px 0 4px">Unterschied — wähle:</div>'
                f'<div style="display:flex;gap:10px;flex-wrap:wrap">{"".join(options_html)}</div>'
                f'</div>'
            )
        konflikt_html = (
            '<section style="margin:24px 0">'
            '<h2 style="color:#e67e22;border-bottom:2px solid #e67e22">Offene Entweder-Oder-Entscheidungen</h2>'
            '<p style="font-size:.85rem;color:#666;max-width:700px">Diese Punkte schließen sich gegenseitig aus. '
            'Was beide Seiten teilen, steht einmal fest — nur der wirkliche Unterschied muss entschieden werden.</p>'
            + "".join(gruppen_karten) + '</section>'
        )

    def render_karte(dim, x, farbe):
        sp_ids = (x.get("stuetzt_sich_auf") or {}).get("standpunkte", [])
        quellen_html = []
        for sid in sp_ids:
            sp = sp_lookup.get((dim, sid))
            if not sp:
                continue
            minderheit_flag = " · Minderheitsposition" if sp.get("minderheitsposition") else ""
            quellen_html.append(
                f'<div style="margin:4px 0;padding:6px 8px;background:#fafafa;border-radius:4px;'
                f'font-size:.75rem"><strong>{e(sid)}</strong>{e(minderheit_flag)}: {e(sp["position"])}'
                f'<div style="color:#888;margin-top:2px">Unterstützung: n={sp["unterstuetzung"]["n_bewertet"]}, '
                f'Ø={sp["unterstuetzung"]["mittelwert"]}</div></div>'
            )

        angepasst_html = ""
        if x["kohaerenz_angepasst"]:
            angepasst_html = (
                f'<div style="font-size:.72rem;color:#a04000;margin-top:6px;padding:4px 8px;'
                f'background:#fff3e0;border-radius:4px">⚠ Formulierung wegen Kohärenz mit anderer '
                f'Dimension präzisiert.</div>'
            )
        merge_html = ""
        if x.get("zusammengefuehrt_aus"):
            merge_html = (
                f'<div style="font-size:.72rem;color:#7b1fa2;margin-top:4px">🔗 Zusammengeführte, '
                f'kompatible Begründungen (echte Redundanz erkannt)</div>'
            )
        konflikt_indices = konflikt_je_kandidat.get((dim, x["id"]))
        konflikt_badge = badge("⚖️ Teil einer Entweder-Oder-Wahl, siehe oben ↑", "#e67e22") if konflikt_indices else ""

        nutzer_html = ""
        if x.get("nutzer_erklaerung"):
            nutzer_html = (
                f'<details style="margin-top:8px"><summary style="cursor:pointer;color:#2d7d9a;'
                f'font-size:.8rem">💬 Wie ist dieser Punkt entstanden?</summary>'
                f'<div style="font-size:.82rem;color:#444;margin-top:6px;line-height:1.5">'
                f'{e(x["nutzer_erklaerung"])}</div></details>'
            )

        # Bei Konfliktgruppen steht die volle Aussage schon oben kompakt
        # gegenuebergestellt -- hier NICHT nochmal wiederholen, nur kurz
        # auf den gemeinsamen Kern + Wahlmoeglichkeit verweisen.
        if konflikt_indices:
            haupttext = (
                f'<div style="font-size:.88rem;color:#7a4a00;font-style:italic">'
                f'Teil einer Entweder-Oder-Entscheidung — Details und Auswahl oben im Abschnitt '
                f'"Offene Entweder-Oder-Entscheidungen".</div>'
            )
        else:
            haupttext = f'<div style="font-size:.95rem;font-weight:600;line-height:1.5">{e(x["aussage_final"])}</div>'

        return (
            f'<div style="border:1px solid {farbe};border-radius:10px;padding:12px 16px;'
            f'margin:10px 0;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            f'<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:4px">'
            f'<span style="font-size:.72rem;font-weight:700;color:{farbe}">{e(x["id"])}</span>{konflikt_badge}</div>'
            + haupttext
            + angepasst_html + merge_html + nutzer_html
            + (f'<details style="margin-top:6px"><summary style="cursor:pointer;color:#aaa;font-size:.72rem">'
               f'Rückverfolgbarkeit (technisch)</summary>{"".join(quellen_html)}</details>'
               if quellen_html else "")
            + '</div>'
        )

    def render_dimension(dim):
        inhalt = empfehlung["dimensionen"].get(dim)
        farbe = DIM_FARBEN[dim]
        if not inhalt or not inhalt["eintraege"]:
            return (f'<div style="padding:10px 14px"><h3 style="color:{farbe};font-size:.95rem;margin:0">'
                    f'{e(dim)}</h3><p style="font-size:.8rem;color:#999">Keine Empfehlungen.</p></div>')
        karten = "".join(render_karte(dim, x, farbe) for x in inhalt["eintraege"])
        return (
            f'<div style="padding:10px 14px">'
            f'<h3 style="color:{farbe};font-size:.95rem;margin:0 0 6px;border-bottom:1px solid {farbe}44">{e(dim)}</h3>'
            + (f'<div style="font-size:.78rem;color:#888;margin-bottom:6px">{e(inhalt["dissens_notiz"][:200])}</div>'
               if inhalt.get("dissens_notiz") else "")
            + karten + '</div>'
        )

    trichter_zeilen = []
    for i, (label, zweck_dim, mittel_dim) in enumerate(FUNNEL_ZEILEN):
        breite = FUNNEL_BREITEN[i]
        trichter_zeilen.append(
            f'<div style="max-width:{breite};margin:0 auto 18px;">'
            f'<div style="text-align:center;font-size:.72rem;color:#999;letter-spacing:.05em;'
            f'text-transform:uppercase;margin-bottom:6px">{e(label)}</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;'
            f'border:1px dashed #ddd;border-radius:14px;padding:6px">'
            f'{render_dimension(zweck_dim)}{render_dimension(mittel_dim)}'
            f'</div></div>'
        )

    trichter_html = (
        '<section style="margin:20px 0">'
        '<div style="display:grid;grid-template-columns:1fr 1fr;max-width:100%;margin:0 auto 4px;'
        'font-weight:800;font-size:.85rem;text-align:center">'
        '<div style="color:#1a3a5c">🎯 ZWECK — was erreicht werden soll</div>'
        '<div style="color:#7b5ea7">⚙️ MITTEL — wie es erreicht wird</div>'
        '</div>'
        + "".join(trichter_zeilen) + '</section>'
    )

    anhang = empfehlung.get("anhang_minderheitspositionen", {})
    anhang_html = ""
    if any(anhang.values()):
        anhang_bloecke = []
        for dim, sps in anhang.items():
            if not sps:
                continue
            eintraege_html = "".join(
                f'<div style="border-left:3px solid #999;padding:8px 12px;margin:8px 0;background:#fafafa">'
                f'<strong style="font-size:.85rem">{e(sp["titel"])}</strong> '
                f'<span style="font-size:.75rem;color:#888">(Sichtweise: {e(sp["lager_titel"])}, '
                f'n={sp["unterstuetzung"]["n_bewertet"]}, Ø={sp["unterstuetzung"]["mittelwert"]}, '
                f'{sp["unterstuetzung"]["befuerwortung_4_5"]} Befürwortung vs. '
                f'{sp["unterstuetzung"]["ablehnung_1_2"]} Ablehnung)</span>'
                f'<div style="font-size:.85rem;color:#444;margin-top:4px">{e(sp["position"])}</div>'
                f'</div>'
                for sp in sps
            )
            anhang_bloecke.append(f'<h3 style="font-size:1rem;color:{DIM_FARBEN.get(dim,"#555")}">{e(dim)}</h3>{eintraege_html}')
        anhang_html = (
            '<section style="margin:36px 0;padding-top:16px;border-top:2px dashed #ccc">'
            '<h2 style="color:#666">Anhang: dokumentierte Minderheitspositionen</h2>'
            '<p style="font-size:.85rem;color:#666;max-width:700px">Diese Positionen haben einen echten '
            'Widerspruch nicht überstanden — die jeweilige Sichtweise wurde in ihrem Diskurs bereits '
            'mehrheitlich zugunsten einer anderen Sichtweise entschieden. Sie stehen hier zur '
            'Vollständigkeit dokumentiert, nicht als gleichrangige Empfehlung.</p>'
            + "".join(anhang_bloecke) + '</section>'
        )

    html = (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Aigora Empfehlungsdokument</title>'
        '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
        'max-width:1100px;margin:0 auto;padding:24px 16px;line-height:1.5;color:#1a1a1a;background:#fbfbfb}'
        'summary::marker{display:none}summary::-webkit-details-marker{display:none}'
        'h1{font-size:1.6rem;color:#1a3a5c}h2{font-size:1.25rem;padding-bottom:4px;margin-top:8px}'
        '.meta{background:#fff;border-radius:8px;padding:12px 16px;font-size:.82rem;color:#555;'
        'display:flex;gap:16px;flex-wrap:wrap;box-shadow:0 1px 2px rgba(0,0,0,.06)}'
        '@media (max-width:700px){div[style*="grid-template-columns:1fr 1fr"]{grid-template-columns:1fr !important}}'
        '</style></head><body>'
        '<h1>Wärmewende-Bürgerbeteiligung — Empfehlungsdokument</h1>'
        '<p style="color:#555;font-size:.92rem">Synthese aus Sitzung 1 (Positionsfindung) und '
        'Sitzung 2 (Diskurs) — Pause 2, Aigora-Studie.</p>'
        f'{summary}{konflikt_html}{trichter_html}{anhang_html}'
        '</body></html>'
    )
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Geschrieben: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
