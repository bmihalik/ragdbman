# Vision

ragdbman is not another RAG wrapper. It is a **document intelligence system** —
a tool for people who care about their books, documents and source files, who
want to understand and control how their knowledge base is built, and who
refuse to let a machine black-box the process.

## The problem

Most RAG and vector database tools today treat your files as garbage in, garbage
out. You point them at a folder, they chunk everything uniformly (a 400-page
textbook gets the same treatment as a 3-line config file), they dump the results
into an opaque vector store, and the original document structure is lost
forever. You cannot see what was chunked, how it was chunked, or why a search
returned what it did. You cannot say "this is a textbook, chunk by chapter and
section" or "this is a code file, chunk by function." The system maintainer is
reduced to hoping the machine got it right.

This is chaos. It works for quick prototypes. It fails for anyone who needs to
maintain, debug, curate, or trust their knowledge base.

## What ragdbman should be

A document intelligence system that gives the system maintainer **real control
and real visibility** into every stage of the pipeline — from source file to
indexed, searchable knowledge. Not a black box. A glass box.

### Inspectable sources

Every source file — PDF, DOCX, EPUB, HTML, source code — is converted into a
real, readable Markdown file before chunking and embedding ever run. You can
open it, read it, fix it, and see exactly what the indexer sees. The converted
text is not hidden inside a database blob; it lives in a sidecar directory you
can browse with any file manager.

### Structured chunking

Chunking should respect document structure, not ignore it. A textbook should be
chunked by chapter and section. A research paper by its abstract, methods, and
results. A code file by function and class. The chunking strategy is a
first-class, configurable decision — not a fixed pipeline that treats every file
the same.

**Section-based chunking** is a planned feature: ragdbman will understand
document hierarchy (Markdown headings, PDF sections, code blocks) and cut along
structural boundaries, producing chunks that carry their section path as
metadata. A search result won't just say "page 47" — it will say "Chapter 3 >
Section 3.2 > Methods."

### Knowledge Cards (KC / KCDB)

Knowledge Cards are curated, structured knowledge objects — not raw chunks, but
synthesized units of understanding that a human or AI has reviewed, refined, and
marked as trustworthy. They live in a **Knowledge Card Database (KCDB)** that
sits alongside the vector index and the full-text index as a first-class data
source.

A search across ragdbman should be able to return:

- Raw chunks (what the indexer produced from the source files)
- Knowledge Cards (what someone has curated and verified)
- Structured facts (numeric, date, keyword metadata extracted at index time)

This three-layer model — raw, curated, structured — gives the system maintainer
a clear picture of what the knowledge base *knows* and how confident it is in
each piece.

### Multiple indexing engines

ragdbman should support multiple indexing strategies and let the maintainer
choose:

- **Full-text search** (FTS5, BM25 ranking) — fast, exact, interpretable.
- **Vector similarity** (dense embeddings) — semantic, fuzzy, language-agnostic.
- **Hybrid** (rank fusion) — the best of both.
- **Structured queries** (numeric, date, keyword filters) — precise, composable.

And the maintainer should be able to see which engine produced which result, and
why. Search should not be a magic box that returns answers; it should be a
transparent process with a visible chain of evidence.

### The SQLite advantage

Everything — chunks, vectors, full-text index, metadata, audit logs — lives in a
plain SQLite database file per collection. No server to install, no credentials
to manage, no cloud account to create. You can open it with `sqlite3`, inspect
it, query it, back it up, or edit it directly. This is the same philosophy as
Hermes-Agent's approach to AI memory: the system's internal state should be
readable and editable by the human who maintains it.

## The philosophy: glass box, not black box

In Hermes-Agent, you can look at the SKILL file structure and see what happened
inside "the mind of the AI." You can watch memory enrichment happen in a SQLite
database and edit it when it goes wrong. The system's intelligence is not hidden
behind an API — it is laid out in files and tables you can inspect.

ragdbman should bring the same philosophy to document indexing:

- **See the converted source** — Markdown files in a sidecar directory.
- **See the chunks** — their boundaries, their overlap, their section paths.
- **See the index** — a SQLite database you can open and query.
- **See the search** — which engine matched, with what score, from what source.
- **See the Knowledge Cards** — curated, verified, distinct from raw chunks.

Every stage of the pipeline should be inspectable, debuggable, and overridable.

## Who it's for

- **System maintainers** who manage document libraries and need control over how
  files are indexed, chunked, and served — not just "dump everything and hope."
- **Researchers and professionals** with specialized document collections
  (medical, legal, technical) where chunking quality matters and
  one-size-fits-all RAG fails.
- **Hermes-Agent users and developers** who want a structured, controllable
  knowledge base accessible through MCP, integrated with their AI ecosystem.
- **Anyone who has looked at a vector database and thought: "I have no idea
  what's actually in there, and I should."**

## Community

ragdbman is being developed in the open, alongside the Hermes-Agent ecosystem.
The goal is not just to ship a tool, but to build a community around the idea
that document intelligence should be transparent, controllable, and structured —
not opaque, automatic, and chaotic.

From the community, we hope for:

- **Feedback** — what works, what breaks, what's missing.
- **Inspiration** — use cases and workflows we haven't thought of.
- **Network building** — connecting with people who care about structured
  knowledge management.
- **Co-development** — contributions, ideas, and collaboration on the features
  described in this vision.

## Implementation direction

ragdbman is implemented in **Python**, to align with the Hermes-Agent
ecosystem and the broader AI tooling community.

The primary integration surface is the **MCP server**: language-agnostic,
accessible from any AI agent or ecosystem that speaks Model Context Protocol. A
thin HTTP REST API runs alongside it for direct programmatic access from any
language.

Dependencies will be managed with **`uv`** and virtual environments — the
accepted, low-friction approach for the target audience of system maintainers
and AI ecosystem developers.

## The short version

Don't dump your files into a black box and hope. Convert them, inspect them,
chunk them with structure, curate what matters, index with the right engine for
the job, and keep the whole thing in a database you can open and read. That is
document intelligence.
