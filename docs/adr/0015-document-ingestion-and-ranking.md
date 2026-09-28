# ADR-0015: Company document ingestion (Docling) and relevance ranking (TypeSafe Jev)

- **Status:** proposed
- **Date:** 2026-09-28
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0005, ADR-0014, ADR-0016

## Context and problem

Companies already have their knowledge in documents: policies, procedures,
contracts, price lists, org handbooks — as PDF, DOCX, XLSX, PPTX and HTML. To
spread AI across every department (ADR-0014), agents must answer from these
documents, with two hard requirements:

1. **Small context.** Only the few passages that actually matter go to the model
   — cheaper, faster, fewer hallucinations, and it works with small local models.
2. **Access control.** A person (and their agent) only ever sees passages from
   documents their company / department / role is allowed to see.

Today `services/rag_service.py` embeds agent memories, sessions and task history
into pgvector; company documents are not ingested at all, and there is no
ranking step beyond vector similarity.

## Options considered

**Parsing**

- **A — Docling (IBM, MIT).** Converts PDF (incl. layout, tables, OCR), DOCX,
  XLSX, PPTX, HTML into a structured document model / Markdown, and ships a
  structure-aware chunker (HybridChunker).
- **B — Unstructured / plain text extraction.** Weaker on tables and layout.

**Ranking**

- **C — vector similarity only** (current).
- **D — hybrid retrieval + a local cross-encoder reranker.**
- **E — hybrid retrieval + TypeSafe Jev.** Jev is a "System One" decision model:
  instead of generating text it answers typed questions (boolean / choice /
  score) about a text with calibrated probabilities, via `POST /v1/systemone`,
  billed per input token (output is free).

## Decision

**A + E, with D as the local fallback.**

Pipeline:

1. **Ingest** — documents are uploaded in the web UI, synced from a folder / Git
   / SharePoint-like source during installation (ADR-0016), or dropped into a
   workspace. Docling converts them; HybridChunker splits them along headings and
   tables.
2. **Store** — each chunk goes into Postgres with its embedding (pgvector), a
   `tsvector` for keyword search, the source document + version, and an **ACL**
   (company, department ids, roles, classification). Re-ingest is idempotent per
   document hash; superseded versions are hidden, not deleted.
3. **Retrieve** — candidates = keyword (Postgres full-text) ∪ vector search,
   **filtered by the caller's ACL in SQL** before anything is ranked.
4. **Rank** — Jev scores each candidate with a typed question ("How relevant is
   this passage to the request?", score / probability). Keep the top-k above a
   calibrated threshold; if nothing clears it, say so instead of guessing.
5. **Answer** — only the kept passages, with citations (document, section,
   version), go into the model context.

Jev is also a fit for other cheap typed decisions later — routing a task to a
department or skill (choice), "does this request touch a restricted policy?"
(boolean) — but this ADR only commits to ranking.

Behind one `Ranker` interface with two implementations:

- `JevRanker` — TypeSafe API (cloud). Default when the install allows cloud
  processing.
- `LocalRanker` — a local cross-encoder reranker (e.g. a BGE reranker) for
  installs that must keep documents on premises.

## Consequences

- **Positive:** Company documents become usable by every agent with small,
  cited contexts. ACL filtering happens before ranking, so a ranking bug cannot
  leak a passage. Calibrated scores give a principled "I don't know".
- **Negative / cost:** Docling brings heavy dependencies (PyTorch, OCR models) —
  run it as a separate ingestion worker image, not inside the API process. Jev is
  a paid external API and not OpenAI-compatible — a dedicated client is needed.
- **Accepted residual risk:** With `JevRanker`, candidate passages are sent to
  TypeSafe. This is an explicit per-install setting (ADR-0016), shown in the
  admin UI and recorded in the audit log.
- **Follow-ups:**
  1. Spike: Jev request/response format, latency and cost for ~50 candidates per
     query; calibrate the threshold on a sample policy set.
  2. `ingest` worker (Docling) + `DocumentChunk` table with ACL + migration.
  3. Retrieval API used by the MCP server, the web chat and the TUI.
  4. Extend `rag_service` to share the retrieval + ranking path.
