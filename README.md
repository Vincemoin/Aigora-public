# Aigora

Aigora is a prototype platform for AI-assisted citizen deliberation, built as
part of an MPP thesis. It explores whether and how AI can support
deliberative mini-publics across three stages:

1. **Session 1 — Positions**: a citizen develops their own position on a
   policy topic (here: the German *Wärmewende*/heating transition) through a
   guided, Socratic dialogue with an AI facilitator ("Sokra"), grounded in a
   curated evidence corpus via retrieval-augmented generation.
2. **Session 2 — Discourse**: positions from all participants are clustered
   into discourses, camps and standpoints; participants review where
   agreement and disagreement actually lie and can propose compromises.
3. **Session 3 — Ratification**: a synthesised set of policy recommendations,
   built from a staged "No-Objection" filtering process (not simple majority
   voting), is presented back to participants for a final Yes/No per point.

This repository contains the **system and code only**: the Streamlit app,
the AI agent system prompts, and the full offline synthesis pipeline. It
deliberately does **not** contain any participant data, study results, or
anything generated from real sessions — see [SECURITY.md](SECURITY.md) for
why, and what that means if you want to run this yourself.

## Architecture

```
streamlit_app.py        Entry point: login + phase overview (3 tiles)
bootstrap_secrets.py     Copies Streamlit secrets into environment variables
access_control.py        Access-code login (one code per participant)
phasen.py                Per-session date windows + manual testing override
model_config.py           Provider switch: Anthropic <-> DeepSeek
surfdrive_storage.py      Minimal WebDAV client (participant data storage)
branding.py                Asset paths with graceful fallback
gpr_core.py                 Session 1 core: the "Sokra" system prompt, tools,
                             intervention taxonomy, ratification mechanism
retrieve.py                  RAG retrieval (ChromaDB + embeddings)
survey_gate.py                Pre-/post-survey link buttons per session
session_progress.py            Auto-detects whether a session is already done
session2_bewertungen.py         Session 2 data model (discourse ratings)
session3_bewertungen.py         Session 3 data model (ratification)
sokra_s2_prompt.py / sokra_s3_prompt.py   Session 2/3 assistant prompts
voice_io.py                     Speech input/output
views/                           The three session UIs
pipeline_session2/                Offline: position clustering into discourses
pipeline_synthese/                 Offline: the full synthesis pipeline
  synthese_dossiers.py              1. build per-dimension dossiers
  synthese_standpunkt_filter.py     2. No-Objection filter, Stage A
  synthese_stufe_b.py               3. No-Objection filter, Stage B
  synthese_stufe_c.py               4. No-Objection filter, Stage C
  synthese_agent.py                 (helper module, per-dimension phrasing)
  synthese_final_synthese.py        5. final synthesis + coherence +
                                        deterministic conflict-plausibility check
  synthese_abschluss_check.py       6. grammar/wording QA pass
  synthese_policy_brief.py          7. renders the final HTML policy brief
  synthese_download_bewertungen.py  downloads raw Session 2 ratings
  synthese_vererbung_check.py       checks rating-inheritance legitimacy
tools/                              Local, non-deployed helper scripts
docs/                                 Supplementary documentation
```

## The "No-Objection" synthesis method

Rather than filtering recommendations by majority vote, each standpoint is
kept unless there is real, *proportionate* objection against it — silence or
a lone dissenting voice does not remove a point. This is implemented as a
staged, increasingly expensive check (cheap deterministic rule → targeted LLM
check → substantive comment review), so only genuinely contested points reach
the most expensive step. See `pipeline_synthese/synthese_standpunkt_filter.py`,
`synthese_stufe_b.py` and `synthese_stufe_c.py` for the exact criteria at each
stage.

AI-proposed either/or conflicts between recommendations are additionally
verified against real participant support data before being presented as a
forced choice — see `verifiziere_konfliktgruppen` in
`synthese_final_synthese.py`.

## Running this yourself

This code expects:
- Anthropic (and optionally OpenAI/DeepSeek) API keys, see
  `.streamlit/secrets.toml.VORLAGE` for the exact secrets structure.
- SurfDrive (or another WebDAV-compatible host) for participant data storage.
- A populated `chroma_db/` corpus for retrieval (included in this repo —
  curated policy documents, not participant data).
- Your own `data/` directory, created at runtime — intentionally not part of
  this repository (see SECURITY.md).

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## License / citation

[Add your preferred license here before publishing, e.g. MIT for the code.
If you want others to be able to reuse this but require attribution in
academic contexts, consider adding a citation note pointing to your thesis.]
