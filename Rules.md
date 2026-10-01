# Engineering & AI Operating Rules

## Project: **Motif**
> *Strict behavioral boundaries, technical constraints, and quality guardrails for hackathon evaluation and production readiness.*

---

## 1. Core System Axioms (Non-Negotiable)

### 1.1 The Zero-Hallucination & Quote Verification Rule
* **Rule:** An LLM may **never** synthesize a customer claim, feature request, or bug without attaching the exact verbatim source quote and customer ID from the ingested dataset.
* **Enforcement:**
  - Every theme payload must include `cited_quotes: List[str]`.
  - A deterministic validation filter executes before any theme is persisted or displayed:
    ```python
    def verify_quote(quote: str, raw_feedback_pool: List[str]) -> bool:
        return any(quote.strip() in item for item in raw_feedback_pool)
    ```
  - If a single quote fails verbatim substring matching, the cluster labeling discards the citation or triggers fallback to exact passage extraction. Faith-based LLM summaries are strictly forbidden.

### 1.2 No Predefined Categories (Emergent Discovery Only)
* **Rule:** Developers, prompt engineers, and backend scripts are strictly prohibited from hardcoding or guiding taxonomy categories (e.g., "UI/UX", "Billing", "Performance", "Authentication").
* **Enforcement:**
  - Clustering must be unsupervised, executed via **HDBSCAN** on dense semantic embeddings (`all-MiniLM-L6-v2`).
  - Clusters must reflect mathematical density in vector space.
  - Points with distance metrics exceeding cluster density thresholds must be assigned label `-1` (`Noise`) and discarded from theme generation. Under no circumstances should an outlier be forced into an artificial bucket.

### 1.3 Strict Human-in-the-Loop PM Approval Gate (No Auto-Shipping)
* **Rule:** The AI proposes; the human PM decides. Under no conditions shall the system automatically dispatch a PRD or create a GitHub issue without explicit PM interaction.
* **Enforcement:**
  - The backend GitHub dispatcher endpoint (`POST /api/v1/themes/{id}/approve`) requires an active PM approval signature and audit log entry.
  - Automated pipelines may only run up to the "Pending PM Review" state.
  - The UI requires the PM to physically review the quotes and click "Approve & Ship" (or edit/reject).

### 1.4 Revenue-First Ranking with Account Deduplication (Value Over Volume)
* **Rule:** Raw feedback frequency/count must never be the primary sort key when revenue data is present. Furthermore, repeat complaints from the same enterprise customer must never artificially multiply their ARR.
* **Enforcement:**
  - Themes must be ranked by **Revenue at Risk**, where each distinct customer account's ARR is credited at most once per discovered theme:
    $$\text{Revenue at Risk} = \sum_{a \in \text{Unique Accounts}} \text{ARR}_a \times \max_{i \in \text{Items}_a}(\text{Churn Multiplier}_i)$$
  - A single enterprise account ($100k+ ARR) threatening churn must mathematically outrank 50 free-tier users requesting minor visual changes.

### 1.5 Strict Privacy & Opt-In Scoping
* **Rule:** Connectors must enforce an explicit opt-in boundary.
* **Enforcement:**
  - Personal DMs, unapproved private channels, and unselected folder trees must be blocked at the ingestion layer.
  - Unapproved inputs are discarded immediately in-memory and never written to PostgreSQL or vector storage.

---

## 2. Technical Stack Constraints

All development must strictly adhere to the defined technologies. Substituting these tools without formal architectural amendment is prohibited.

| Layer | Mandated Technology | Allowed Fallbacks | Forbidden Alternatives |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | **FastAPI (Python 3.11+)** | None | ❌ Flask, Django, Express.js |
| **Database & Vectors** | **PostgreSQL 16 + pgvector** | Hosted Supabase (with pgvector) | ❌ Pinecone, Weaviate, Milvus, Chroma, SQLite |
| **Embedding Engine** | **Sentence-Transformers (`all-MiniLM-L6-v2`)** | None (runs locally on CPU) | ❌ OpenAI `text-embedding-3`, Cohere |
| **Clustering Engine** | **HDBSCAN (`scikit-learn`)** | None (offloaded to thread pool) | ❌ K-Means (fixed $k$), DBSCAN (fixed epsilon), LDA |
| **Primary LLM** | **Groq LLaMA 3.3-70B (`llama-3.3-70b-versatile`)** | Google Gemini 2.0 Flash / OpenAI GPT-4o-mini / **Deterministic Offline Labeler** | ❌ Unstructured completions without Pydantic schema |
| **Document Ingestion** | **Microsoft MarkItDown** | Built-in Python CSV/JSON/TXT parsers | ❌ Unchecked raw binary ingestion |
| **Frontend UI** | **Next.js 16 (App Router) + React 19** | None | ❌ Create-React-App, Vue, Svelte, Angular |
| **Styling** | **Tailwind CSS 4** | Vanilla CSS custom tokens | ❌ Ad-hoc inline CSS frameworks |
| **Target Integration** | **GitHub REST API (v3)** | Offline PRD compilation (when no token set) | ❌ Auto-shipping without human approval |

---

## 3. Data Integrity & Verification Checklist

Before any release or hackathon demonstration:
- [x] All 300 benchmark items in `corpus_300.json` generate reproducible clusters without errors.
- [x] Every cited quote in the UI matches word-for-word against its underlying database record (`citation_validity == 100%`).
- [x] Offline mode functions end-to-end without network calls when `GROQ_API_KEY` is omitted.
- [x] GitHub issues are generated only upon human PM approval and never during autonomous background pipeline runs.
