# Security & Privacy Notes

## What is intentionally NOT in this repository

This is a public export of the Aigora **system and code**, prepared
separately from the private development repository used during the actual
study. The following categories were deliberately excluded and never
committed to this repo's history:

- **All participant data.** No chat logs, ratings, discourse clusters,
  thematic-analysis output, or synthesised recommendations generated from
  real study sessions. These were collected under an ethics approval scoped
  to academic/thesis use, not public redistribution — even pseudonymised,
  small-sample qualitative data carries a meaningful re-identification risk
  and is not released here.
- **Secrets of any kind.** API keys, SurfDrive credentials, participant
  access codes. `.streamlit/secrets.toml.VORLAGE` is a *template* with
  placeholder values only (`HIER_..._EINTRAGEN`) — fill in your own values
  locally or in your deployment platform's secret manager, never in a
  committed file.
- **Private participant-to-access-code mappings.**

If you are extending this project: keep this separation. Real participant
data belongs in a separate, access-controlled location (e.g. the
institutional SurfDrive/WebDAV store this code already talks to), never in
the git history of a repo you intend to make public.

## What IS in this repository

- Application code, AI agent system prompts, and the full offline synthesis
  pipeline.
- The RAG corpus (`chroma_db/`) — curated policy documents and reports used
  for retrieval, not participant-generated content. If any underlying
  document has its own redistribution restrictions, check that before
  treating this corpus as freely reusable.
- UI assets (logos, graphics, and a handful of pre-generated audio clips of
  the app's own fixed narration text — not participant recordings).

## Handling secrets if you deploy this

1. Never commit `.env` or `.streamlit/secrets.toml` — both are gitignored
   here; keep them that way.
2. Use your deployment platform's secret manager (e.g. Streamlit Cloud's
   Settings → Secrets) for all real credentials.
3. Rotate any credential that was ever pasted into a chat, ticket, or
   non-secret-manager location, even briefly.

## Reporting an issue

This is an academic prototype, not a maintained production system. If you
spot something concerning (e.g. a secret accidentally left in a commit, or a
way the app could leak participant data in a future fork), please open an
issue or contact the repository owner directly rather than a public
disclosure, out of respect for any participants in studies run with
derivatives of this code.
