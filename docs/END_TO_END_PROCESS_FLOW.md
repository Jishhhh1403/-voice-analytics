# End-to-End Process Flow — Feedback Data to Problem–Backlog Gap Coverage

## 1. Value-stream flowchart

```mermaid
flowchart TD
    classDef source fill:#e8f1ff,stroke:#2f6fb2,color:#102a43
    classDef process fill:#f5f7fa,stroke:#7b8794,color:#102a43
    classDef novel fill:#e0f7fa,stroke:#00838f,stroke-width:2px,color:#043c3f
    classDef decision fill:#fff4d6,stroke:#c47f00,color:#432f00
    classDef output fill:#eaf7ea,stroke:#2e7d32,color:#123d14
    classDef guard fill:#f3e8ff,stroke:#6b21a8,color:#3b0764

    subgraph S0["0 · Inputs and controls"]
        A1["Feedback CSV / object store<br/>generation id + SHA-256 + size cap"]:::source
        A2["Backlog CSV<br/>title, description, acceptance criteria"]:::source
        A3["Taxonomy + config thresholds<br/>versioned, env-driven"]:::source
    end

    subgraph S1["1 · Feedback foundation — stage-ledged, idempotent"]
        B1{"Source valid and<br/>run already complete?"}:::decision
        B2["Parse, accept / quarantine<br/>PII redaction + quality manifest"]:::process
        B3["Duplicate detection<br/>linked, never discarded"]:::process
        B4["Insight extraction<br/>journey, intent, aspect, symptom, emotion, effort"]:::process
        B5["Clustering + canonicalisation<br/>embeddings, HDBSCAN, LLM consortium"]:::process
        B6["Canonical problems<br/>customer_problems + problem_evidence"]:::output
        B7["Taxonomy mapping<br/>journey nodes + proposals for unmapped"]:::process
        B8["Measurement + priority + MDS<br/>volume, trend, effort, priority, 2-D theme map"]:::process
        B1 -- "yes, fresh" --> B2
        B1 -- "no, reuse" --> B6
        B2 --> B3 --> B4 --> B5 --> B6 --> B7 --> B8
    end

    subgraph S2["2 · Backlog side"]
        C1["Backlog upload + profiling<br/>intent, feature, journey, AC text"]:::process
        C2["Validation run<br/>binds run + upload"]:::process
        C1 --> C2
    end

    subgraph S3["3 · Canonical problem to backlog coverage"]
        D1["BGE dense cosine, TF-IDF fallback<br/>similarity clipped to 0-1"]:::process
        D2["Closest backlog per problem<br/>argmax score"]:::process
        D3{"Coverage band"}:::decision
        D4["COVERED / MATCH"]:::output
        D5["NOT COVERED / MISMATCH"]:::output
        D6["GREY ZONE 0.60-0.75"]:::decision
        D7["LLM consortium<br/>3 specialist lenses + chair<br/>heuristic fallback if LLM unavailable"]:::process
        D8{"Chair decision"}:::decision
        D9["Matched group<br/>ADDRESSES"]:::output
        D10["Rejected grey zone<br/>NO_CLEAR_RELATIONSHIP"]:::output
        D1 --> D2 --> D3
        D3 -- ">= 0.75" --> D4
        D3 -- "< 0.60" --> D5
        D3 -- "grey" --> D6 --> D7 --> D8
        D8 -- MATCH --> D9
        D8 -- MISMATCH --> D10
    end

    subgraph S4["4 · NOVEL — whitespace lens discovery"]
        E1["3 families / 5 lenses<br/>GRAPH_BRIDGE, GRAPH_TEMPORAL<br/>SPATIAL_VOID<br/>COMBINATORIAL_LATTICE, COMBINATORIAL_NMF"]:::novel
        E2["Lens signals<br/>internal score + supporting feedbacks"]:::novel
        E3["Triangulate: merge by journey / intent / aspect<br/>or feedback overlap; single-family retained"]:::novel
        E4["Verified + merged whitespaces<br/>GET /whitespace"]:::novel
        E1 --> E2 --> E3 --> E4
    end

    subgraph S5["5 · NOVEL — lens-reinforced graduation"]
        F1{"Lens in GRAPH_BRIDGE or COMBINATORIAL_LATTICE<br/>and internal score > 0.6?"}:::decision
        F2["Associate to canonical problems<br/>0.6 x feedback overlap + 0.4 x label match"]:::novel
        F3["Best association per problem"]:::novel
        F4{"Grey zone + LLM MISMATCH<br/>and association > 0.5?"}:::decision
        F5["Promote to MATCH / COVERED<br/>rationale + scores stored as provenance"]:::novel
        F6["Keep LLM decision"]:::process
        F1 -- yes --> F2 --> F3 --> F4
        F1 -- no --> F6
        F4 -- yes --> F5
        F4 -- no --> F6
    end

    subgraph S6["6 · Decision report and human review"]
        G1["Report: canonical_coverage, findings,<br/>relationships, summary counts"]:::output
        G2["UI: lens badge, uncertainty note,<br/>method and limitations"]:::output
        G3["Product-owner review<br/>auditable decision"]:::guard
        G1 --> G2 --> G3
    end

    subgraph S7["Cross-cutting robustness"]
        H1["Deterministic IDs + stage ledger"]:::guard
        H2["Fallbacks: TF-IDF, LLM-off heuristic, safe failure"]:::guard
        H3["Configurable thresholds + limitations disclosure"]:::guard
    end

    A1 --> B1
    A2 --> C1
    A3 --> B5
    A3 --> D1
    B8 --> D1
    C2 --> D1
    D4 --> G1
    D5 --> G1
    D9 --> G1
    D10 --> F1
    D10 --> G1
    B6 --> E1
    C2 --> E1
    E2 --> F1
    F5 --> G1
    F6 --> G1
    H1 -.-> B1
    H2 -.-> D1
    H2 -.-> D7
    H3 -.-> F4
    H3 -.-> G2
```

## 2. Decision-sequence flowchart

```mermaid
sequenceDiagram
    autonumber
    actor PO as Product owner
    participant SRC as Feedback + backlog sources
    participant PIPE as Feedback pipeline
    participant CP as Canonical problem store
    participant COV as Coverage engine
    participant LLM as LLM consortium
    participant LENS as Whitespace lenses
    participant RPT as Report + UI

    PO->>SRC: Supply feedback CSV and backlog CSV
    SRC->>PIPE: Ingest by generation with checksum and size gate
    activate PIPE
    PIPE->>PIPE: Accept, quarantine, redact PII, link duplicates
    PIPE->>CP: Extract insights, cluster, canonicalise, map taxonomy
    CP-->>PIPE: Canonical problems, evidence, priority, MDS coordinates
    PIPE-->>RPT: Publish stage-ledged run summary
    deactivate PIPE

    RPT->>COV: Validate backlog against canonical problems
    activate COV
    COV->>COV: BGE cosine / TF-IDF fallback; closest backlog; band thresholds
    alt coverage >= 0.75
        COV-->>RPT: Covered + MATCH
    else coverage < 0.60
        COV-->>RPT: Not covered + MISMATCH
    else grey zone 0.60-0.75
        COV->>LLM: 3 specialist lenses + chair adjudicate
        LLM-->>COV: MATCH or MISMATCH with rationale
        COV-->>RPT: Grey-zone decision + provenance
    end

    Note over LENS,COV: NOVEL: lens signals re-inforce gaps the LLM did not match
    RPT->>LENS: Read same run and upload
    activate LENS
    LENS->>LENS: 5 lenses / 3 families emit scored signals
    LENS->>LENS: Shortlist GRAPH_BRIDGE + COMBINATORIAL_LATTICE with internal score > 0.6
    LENS->>CP: Associate via 0.6 feedback overlap + 0.4 label agreement
    CP-->>LENS: Best association per canonical problem
    alt grey zone + LLM MISMATCH + association > 0.5
        LENS-->>COV: Promote to MATCH / COVERED with provenance
    else below gate
        LENS-->>COV: Keep LLM decision
    end
    deactivate LENS
    deactivate COV

    COV-->>RPT: Findings, canonical coverage, summary, limitations
    RPT-->>PO: Lens badge, uncertainty note, method limitations
    PO->>RPT: Record product-owner review decision
    Note over PIPE,COV: Deterministic IDs · stage ledger · configurable thresholds · LLM fallbacks
```
