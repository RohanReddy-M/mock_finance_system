\# FinanceCore AI — Production Grade 6-Agent System



Multi-Agent AI system for enterprise financial query processing with human-in-the-loop governance.



\## Architecture



User → Streamlit UI → FastAPI → LangGraph Orchestrator

&#x20;                                     |

&#x20;        Planner → Retriever → Executor → Validator → Judge → Reporter

&#x20;                                                        |

&#x20;                                             score below 7 → retry Executor

&#x20;                                             high risk → Human Approval

&#x20;                                                        |

&#x20;                                             SQLite Audit + Prometheus Metrics



\## 6-Agent Pipeline



\- Planner: Breaks task into numbered steps

\- Retriever: Searches FAISS knowledge base using RAG

\- Executor: Does the analysis using plan and context

\- Validator: Checks output for harmful content

\- Judge: Scores quality 1-10, retries if below 7

\- Reporter: Formats final output with full audit trail



\## Production Features



\- Circuit Breaker: Groq API retries with exponential backoff

\- Pydantic Data Contracts: Every request validated automatically

\- Human-in-the-Loop: High-risk decisions pause for manager approval

\- SQLite Audit Database: Every decision stored permanently

\- Prometheus + Grafana: Live LLMOps monitoring dashboard

\- Proper Logging: Python logging to file for production debugging

\- Docker: Fully containerized with restart policy

\- recursion\_limit: Prevents infinite agent loops



\## Quick Start



1\. Clone the repo

2\. Add GROQ\_API\_KEY to .env file

3\. Add documents to documents/ folder

4\. Run: docker compose up --build



\## Access Points



\- Streamlit UI: http://localhost:8501

\- FastAPI Docs: http://localhost:8000/docs

\- Prometheus: http://localhost:9091

\- Grafana: http://localhost:3001



\## Tech Stack



\- LangGraph: Multi-agent orchestration

\- Groq LLaMA-3.3-70B: LLM backbone

\- LangChain + FAISS: RAG pipeline

\- FastAPI: Async REST API

\- Streamlit: Visual demo interface

\- Prometheus + Grafana: LLMOps observability

\- SQLite: Audit logging

\- Docker: Production deployment



\## AI Governance



Every agent decision is logged with timestamp, quality score, and human approval status.

High-risk decisions require explicit manager approval before delivery.

Full audit trail queryable at /audit endpoint.

