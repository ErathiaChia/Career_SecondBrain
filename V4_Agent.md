You are to plan the delta between the current Career_SecondBrain architecture that we have against this Career Intelligence Agent we are trying to build towards:
If unclear, feel free to ask before the start of the planning phase. You can break into multiple iterative phase to work your way towards the final goal with building and testing.

"""
# Career Intelligence Agent
'Final Architecture & Implementation Brief`

## Mission
Build a local-first Career Intelligence Agent that continuously ingests and understands my files on Synology, maintains a pre-computed knowledge layer, and answers complex career/work questions intelligently.
The system must not be a pure RAG chatbot and must not become an unbounded autonomous agent.

The target architecture is:
Pre-computed Knowledge Intelligence + Hybrid Retrieval + Bounded Agentic Investigation
The system should be optimized for a local Apple Silicon machine running Qwen 27B, where inference is significantly slower than cloud LLMs.
The design goal is:
• Fast answers for normal questions.
• Agentic retrieval when simple RAG is insufficient.
• Maximum ~3 investigation loops for a query.
• Heavy processing happens asynchronously during scheduled weekend indexing.
• Incremental processing only; never unnecessarily reprocess the entire corpus.
• Every important answer should be traceable back to source files.

⸻

1. Core Design Principles
1.1 Do NOT build a pure RAG system
Traditional:
Question
→ embedding
→ top-k chunks
→ LLM
→ answer
is insufficient for complex Career Intelligence queries.
The system must support:
Question
→ retrieve
→ reason
→ identify missing information
→ targeted tool/retrieval
→ reason
→ optionally verify
→ answer
However, this must be bounded.

⸻

2. Agent Loop Budget
The agent must have a strict investigation budget.
Default:
max_iterations: 3
max_tool_calls_per_iteration: 3
max_documents: 10
max_context_tokens: 20000
Expected behaviour:
Loop 1 — Discovery
Determine what information is relevant.
Example:
search knowledge
identify relevant projects/documents
Loop 2 — Investigation
Gather evidence or inspect relevant documents.
Example:
find evidence
read relevant sections
retrieve project history
Loop 3 — Verification / Synthesis
Only use this when necessary.
Example:
compare sources
resolve conflicting information
verify latest version
Then STOP and answer.
Never allow an uncontrolled:
search → think → search → think
20–30+ iteration loop.
If sufficient evidence is available, stop early.

⸻

3. Two Query Paths
The agent should support two execution paths.
Fast Path
For straightforward questions:
User Question
    ↓
Hybrid Retrieval
    ↓
Reranking
    ↓
Relevant Context
    ↓
Qwen 27B
    ↓
Answer
Target: approximately one main LLM inference.

⸻

Intelligence Path
For complex questions:
User Question
    ↓
Qwen 27B
    ↓
Tool / Retrieval
    ↓
Qwen 27B
    ↓
Tool / Retrieval
    ↓
Qwen 27B
    ↓
Answer
Maximum 3 investigation cycles.
The agent should decide whether the question actually requires agentic investigation.

⸻

4. Weekend Knowledge Preparation Pipeline
Create a scheduled/background pipeline that continuously prepares the knowledge base.
The goal is to move expensive work from query time to ingestion time.
Pipeline:
Synology Files
    ↓
Crawler
    ↓
Change Detection
    ↓
Parse
    ↓
Content Extraction
    ↓
Metadata Extraction
    ↓
LLM Intelligence Extraction
    ↓
Embedding
    ↓
Relationship Detection
    ↓
Knowledge Index
The pipeline should be runnable manually but also support scheduled weekly execution.

⸻

5. Incremental Processing
Do NOT reprocess every file every weekend.
Maintain document state such as:
path
filename
file_hash
size
modified_time
indexed_time
parser_version
embedding_model
embedding_version
intelligence_version
On every crawl:
new file
    → process

modified file
    → reprocess

unchanged file
    → skip

deleted file
    → mark/remove appropriately
Example:
10,000 files

9,700 unchanged → SKIP
250 modified    → REPROCESS
50 new          → PROCESS
The system must be designed around incremental updates.

⸻

6. Multi-Layer Knowledge Architecture
Do not rely solely on embeddings.
Maintain several complementary indexes.
Layer 1 — File Index
Store:
path
filename
file type
size
created date
modified date
hash
Purpose:
• Change detection
• Path-based retrieval
• File discovery

⸻

Layer 2 — Content Index
Extract searchable text from:
• PDF
• DOCX
• PPTX
• XLSX
• Markdown
• TXT
• source/code files where relevant
Support full-text/BM25-style retrieval.
Purpose:
Exact terminology and keyword retrieval.

⸻

Layer 3 — Semantic Index
Generate embeddings for useful document/chunk representations.
Store in the existing PostgreSQL + pgvector infrastructure where possible.
Purpose:
Semantic discovery when the user does not use the exact terminology found in the documents.

⸻

Layer 4 — Intelligence Index
Use Qwen 27B during offline/weekly processing to extract structured intelligence.
For each document, derive where applicable:
summary
keywords
topics
entities
projects
people
customers
products
dates
decisions
risks
actions
outcomes
references
document type
Example:
{
  "document": "IBF Commercial Proposal.pptx",
  "summary": "...",
  "topics": [
    "Genie Studio",
    "pricing",
    "AI agents",
    "IBF"
  ],
  "decisions": [
    "Initial implementation proposed at SGD 50,000"
  ],
  "entities": [
    "IBF",
    "Genie Studio",
    "Genie Tokens"
  ],
  "projects": [
    "IBF CPX"
  ]
}
This structured intelligence is extremely important for local inference performance.

⸻

7. Document Intelligence Cards
Create a compact representation of every important document.
Example:
{
  "document_id": "...",
  "title": "2026 Genie Studio Pricing Strategy",
  "path": "/Genie Studio/Commercial/2026 Pricing Strategy.docx",
  "summary": "Defines the transition from fixed-fee implementation pricing to usage-based Genie Token pricing.",
  "topics": [
    "pricing",
    "Genie Tokens",
    "pay-per-use"
  ],
  "projects": [
    "Genie Studio"
  ],
  "entities": [
    "IBF",
    "Genie Studio"
  ],
  "decisions": [],
  "dates": [],
  "related_documents": []
}
The agent should search these compact representations before loading large documents.

⸻

8. Hybrid Retrieval
Implement retrieval using multiple signals.
At minimum:
1. Path / filename search
2. Full-text / BM25 search
3. Vector similarity
4. Metadata filtering
5. Intelligence/entity/topic matching
Run retrieval methods in parallel where possible.
Combine the results using a ranking strategy.
Example:
Question
   ↓
 ┌─────────────┬─────────────┬──────────────┬─────────────┐
 │ BM25        │ Vector      │ Metadata     │ Intelligence│
 └─────────────┴─────────────┴──────────────┴─────────────┘
                     ↓
               Candidate Set
                     ↓
                  Reranker
                     ↓
                Top Sources
Do not make the LLM decide where to search for every simple question.
The retrieval system should handle most discovery mechanically.

⸻

9. Reranking
After broad retrieval, rerank the candidate documents/passages.
The purpose is:
20–50 candidates
       ↓
     rerank
       ↓
5–10 high-confidence sources
Only send the most relevant context to Qwen.
Avoid flooding Qwen with dozens of irrelevant chunks.

⸻

10. Context Construction
Do not blindly dump retrieved chunks into the context.
Prefer:
Document Intelligence Card
        ↓
Relevant sections
        ↓
Relevant passages
        ↓
Source metadata
The final context should be compact but evidence-rich.
Every source should retain:
document name
path
section/page
date
relevance
so that answers can cite or identify the evidence.

⸻

11. Agent Tools
Build an explicit tool layer.
At minimum, expose:
Knowledge Tools
search_knowledge()
search_documents()
search_by_project()
search_by_topic()
search_by_date()
Document Tools
get_document()
get_document_metadata()
read_file()
read_section()
Investigation Tools
find_evidence()
compare_documents()
find_conflicts()
trace_decision()
find_latest_version()
Career Intelligence Tools
get_project_history()
get_achievement()
get_kpi()
get_role_history()
build_timeline()
find_career_evidence()
The exact implementation can differ, but the conceptual capabilities must exist.

⸻

12. Career Intelligence Abstraction
The system should not expose only a generic “search my files” capability.
It should understand career/work concepts such as:
Projects
Roles
Responsibilities
Achievements
KPIs
Customers
Technologies
Products
Solutions
Business outcomes
Leadership
Architecture
Presales
Delivery
Product Management
AI initiatives
Decisions
Challenges
Lessons learned
The purpose is to answer questions such as:
What are my strongest examples of leading AI projects from opportunity through delivery?
Which projects demonstrate my product management capability?
What evidence do I have that I can lead enterprise AI transformation?
What did we actually achieve for this customer?
What were the major decisions made around Genie Studio?
Which projects best demonstrate my AI Solution Architect experience?
Build me STAR interview examples from my actual career evidence.

⸻

13. Project Intelligence
Create structured project-level knowledge where possible.
Example:
Project: Hong Leong Bank

Role:
AI Solution Architect

Stage:
Opportunity → POC → Architecture → Delivery

Business Problem:
Credit Risk Intelligence

Technologies:
Gemini
AvePoint
Appian

Evidence:
[linked documents]

Timeline:
[events]

Outcomes:
[linked documents]

Related Projects:
[links]
The agent should prefer project intelligence records for high-level questions and drill into source documents when evidence is required.

⸻

14. Relationship / Knowledge Graph
Do not introduce Neo4j unless necessary.
Initially, model relationships in PostgreSQL.
Useful relationships include:
Document → Project
Document → Person
Document → Customer
Document → Product
Document → Decision
Document → Meeting
Document → Topic

Project → Customer
Project → Technology
Project → Achievement
Project → Outcome
Project → Document

Decision → Source Document
Decision → Related Decision
Example:
Genie Studio Pricing Strategy
        │
        ├── IBF Proposal
        ├── Genie Token Pricing
        └── Product Strategy Meeting
This allows the agent to follow known relationships rather than rediscovering them through expensive inference.

⸻

15. Conflict and Recency Awareness
Career information can become stale.
The system should understand:
latest
current
previous
superseded
historical
conflicting
If two documents contain different information:
Document A: SGD 50k fixed fee
Document B: Token-based pricing
the system should not blindly merge them.
It should identify:
A = historical model
B = newer model
where supported by dates/version information.
If uncertain, tell the user that the sources conflict.

⸻

16. Weekend Change Intelligence
The weekly pipeline should not merely re-index.
It should produce a change summary.
Example:
CAREER INTELLIGENCE WEEKLY UPDATE

NEW FILES
──────────────
42

MODIFIED
──────────────
137

NEW PROJECT INFORMATION
──────────────
• Hong Leong Bank
• Genie Studio
• SFF

NEW DECISIONS
──────────────
• ...

NEW ACHIEVEMENTS
──────────────
• ...

CHANGED INFORMATION
──────────────
• Genie Studio pricing model

CONFLICTS
──────────────
• Two different versions of architecture

STALE INFORMATION
──────────────
• Old pricing document
This should be generated automatically after the weekly indexing run.

⸻

17. Performance Strategy for M1 + Qwen 27B
Optimize specifically for local inference.
Avoid unnecessary LLM calls.
Prefer:
filesystem operations
→ database queries
→ BM25
→ vector search
→ metadata filtering
→ reranking
before invoking Qwen.
Use Qwen 27B primarily for:
complex reasoning
document intelligence extraction
synthesis
comparison
final answers
Do not use Qwen to perform trivial routing or file discovery.

⸻

18. Agent Decision Policy
The agent should follow this conceptual policy:
1. Understand the question.

2. Check whether the existing intelligence index
   can answer it directly.

3. If yes:
      retrieve evidence
      answer

4. If no:
      perform targeted retrieval/investigation.

5. After every tool call:
      determine whether evidence is sufficient.

6. Stop immediately once sufficient evidence exists.

7. Never perform a search merely because another search
   might possibly reveal something.

8. Maximum 3 investigation iterations.

9. If evidence remains insufficient:
      clearly state what is known,
      what is uncertain,
and what evidence is missing.

⸻

19. Avoid Agentic Retrieval Anti-Pattern
Do NOT implement:
while not satisfied:
    ask LLM what to do
    search
    ask LLM what to do
    read
    ask LLM what to do
    search
    ...
without strict limits.
Instead:
FAST RETRIEVAL
      ↓
AGENT DECISION
      ↓
TARGETED TOOL
      ↓
AGENT DECISION
      ↓
OPTIONAL VERIFICATION
      ↓
ANSWER
Maximum three loops.

⸻

20. Architecture Goal
The final architecture should resemble:
                         SYNology
                            │
                            ▼
                    ┌───────────────┐
                    │ Weekly Crawler│
                    └───────┬───────┘
                            │
                      Change Detection
                            │
                            ▼
                  ┌────────────────────┐
                  │ Document Processor │
                  └─────────┬──────────┘
                            │
             ┌──────────────┼───────────────┐
             ▼              ▼               ▼
          Full Text      pgvector      Intelligence
           / BM25         Embeddings       Index
             │              │               │
             └──────────────┼───────────────┘
                            │
                            ▼
                  Career Knowledge Layer
                            │
                            ▼
                       User Question
                            │
                            ▼
                    ┌───────────────┐
                    │ Career Agent  │
                    │ Qwen 27B     │
                    └───────┬───────┘
                            │
                  ┌─────────┴─────────┐
                  │                   │
              Fast Path          Agentic Path
                  │                   │
             Hybrid Search       Tool / Search
                  │                   │
                  │              Max 3 loops
                  │                   │
                  └─────────┬─────────┘
                            │
                            ▼
                         Answer
                            │
                            ▼
                     Source Evidence

⸻

21. Implementation Guidance
Before changing code:
1. Inspect the existing repository.
2. Understand the current ingestion/indexing pipeline.
3. Understand existing PostgreSQL/pgvector schemas.
4. Understand existing MCP tools.
5. Identify what can be reused.
6. Do not unnecessarily replace working components.
7. Prefer incremental architectural improvements.
If the existing system already has:
crawler
indexer
embeddings
pgvector
MCP
OpenWebUI
Ollama
reuse them.
The objective is to evolve the current system into Career Intelligence, not rebuild everything from scratch.

⸻

22. Required Deliverables
Implement the system in stages.
Phase 1 — Foundation
• Incremental crawler
• File metadata/index
• Change detection
• Full-text search
• Existing pgvector integration
• Basic hybrid retrieval
Phase 2 — Intelligence Layer
• Document summaries
• Topics
• Entities
• Projects
• Decisions
• Outcomes
• Relationships
• Document intelligence records
Phase 3 — Agent
• Career Intelligence Agent
• Tool interface
• Fast path
• Agentic path
• Maximum 3 loops
• Early stopping
• Evidence-aware responses
Phase 4 — Weekly Intelligence
• Scheduled incremental pipeline
• Changed-document processing
• Knowledge refresh
• Relationship refresh
• Weekly change report
Phase 5 — Career Features
Implement higher-level tools for:
• Project history
• Achievement discovery
• KPI evidence
• Interview preparation
• STAR examples
• Career timeline
• Project comparison
• Skills/technology evidence
• Leadership evidence
• Product/architecture evidence

⸻

23. Quality Criteria
The system should optimize for:
Accuracy
Answers must be grounded in actual source material.
Traceability
Important claims should be traceable to source documents.
Freshness
Changed documents should be incorporated during the next scheduled indexing run.
Speed
Normal questions should not trigger unnecessary agent loops.
Intelligence
Complex questions should be able to investigate rather than relying solely on top-k RAG.
Boundedness
No query should enter an uncontrolled autonomous loop.
Local-first
The system should work effectively with local infrastructure and Qwen 27B.

⸻

24. Final Product Philosophy
The Career Intelligence Agent should behave less like:
“A chatbot with a vector database.”
and more like:
“A continuously maintained digital knowledge system about my professional career and work, with an agent capable of investigating that knowledge when necessary.”
The fundamental strategy is:
WEEKEND
──────────────
Do expensive thinking.
Build intelligence.
Build relationships.
Refresh embeddings.
Detect changes.
Prepare the knowledge base.

WEEKDAY
──────────────
Retrieve quickly.
Reason locally.
Investigate when necessary.
Maximum 3 loops.
Answer with evidence.
Do not sacrifice agentic retrieval merely to make the system faster.
Instead:
Use pre-computation to make agentic retrieval cheap enough that a local Qwen 27B can realistically use it.
That is the target architecture.
"""