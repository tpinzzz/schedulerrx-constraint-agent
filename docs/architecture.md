# Architecture diagram

Required submission artifact. Two renderings below: a Mermaid diagram (renders inline
on GitHub) and an ASCII version. For a PNG to attach on Devpost, paste the Mermaid
source into <https://mermaid.live> and export, or screenshot the GitHub render.

## Mermaid

```mermaid
flowchart TB
    IN([Infeasible scheduling scenario]) --> ORCH

    subgraph ORCH["Orchestrator — perceive → decide → act (one fixed cycle)"]
      direction TB
      L1["<b>Layer 1 · Symbolic Diagnostic</b><br/>MCP tool: diagnose_schedule<br/>• run CP-SAT → INFEASIBLE<br/>• parse log for reported #N<br/>• proto-scan for all-false bool_or (ground truth)<br/>• map literals → semantic var names + reasons"]
      L2["<b>Layer 2 · Gemini (single call)</b><br/>• translate report → plain English<br/>• rank the CLOSED candidate set by ID<br/>• advisory only · cannot invent actions"]
      L3["<b>Layer 3 · Symbolic Verify</b><br/>MCP tool: verify_relaxation<br/>• apply each candidate BY ID<br/>• re-solve EVERY candidate<br/>• badge ✓ feasible / ✗ infeasible"]
      L1 -- "structured report +<br/>closed candidate set" --> L2
      L2 -- "ranked candidate IDs +<br/>English explanation" --> L3
    end

    SOLVER[("OR-Tools CP-SAT<br/>(deterministic ground truth)")]
    L1 -. solve / inspect proto .-> SOLVER
    L3 -. re-solve each candidate .-> SOLVER

    ORCH --> OUT([Only re-verified fixes + resulting schedule])

    style L1 fill:#11314a,stroke:#5b9dff,color:#fff
    style L2 fill:#2a2140,stroke:#7c5cff,color:#fff
    style L3 fill:#0f2b16,stroke:#3fb950,color:#fff
    style SOLVER fill:#1c2330,stroke:#8b97a7,color:#fff
```

## ASCII

```
            Infeasible scheduling scenario
                          │
        ┌─────────────────▼─────────────────────────────────────┐
        │  ORCHESTRATOR  (perceive → decide → act, one cycle)     │
        │                                                         │
        │  ┌───────────────────────────────────────────────┐     │
        │  │ L1  SYMBOLIC DIAGNOSTIC   [MCP diagnose_schedule]│    │     run / inspect
        │  │  run CP-SAT → INFEASIBLE                         │────┼────────────────────┐
        │  │  parse log #N  +  proto-scan all-false bool_or   │    │                    │
        │  │  literals → semantic names + block reasons       │    │                    ▼
        │  └───────────────────┬──────────────────────────────┘   │           ┌──────────────────┐
        │      report + CLOSED candidate set                       │           │  OR-Tools CP-SAT │
        │  ┌───────────────────▼──────────────────────────────┐   │           │  (ground truth)  │
        │  │ L2  GEMINI  (single call)                         │   │           └──────────────────┘
        │  │  English explanation + rank candidate IDs         │   │                    ▲
        │  │  advisory · bounded to the closed set             │   │                    │
        │  └───────────────────┬──────────────────────────────┘   │                    │
        │      ranked IDs + explanation                            │     re-solve each  │
        │  ┌───────────────────▼──────────────────────────────┐   │                    │
        │  │ L3  SYMBOLIC VERIFY      [MCP verify_relaxation]   │───┼────────────────────┘
        │  │  apply each candidate BY ID · re-solve EVERY one   │   │
        │  │  badge ✓ feasible / ✗ infeasible                   │   │
        │  └───────────────────┬──────────────────────────────┘   │
        └────────────────────── │ ────────────────────────────────┘
                                ▼
              Only re-verified fixes + resulting schedule
```

**Key property:** the LLM (L2) sits *between* two symbolic layers. L1 bounds what it can
talk about (a closed candidate set with stable IDs); L3 re-solves whatever it ranks
before anything reaches the user. Hallucination cannot escape the sandwich.
