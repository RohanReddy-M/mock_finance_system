import os, time, json, logging, sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import FakeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from dotenv import load_dotenv
from groq import Groq
from langgraph.graph import StateGraph, END
from typing import TypedDict, List
from pydantic import BaseModel
import pandas as pd

load_dotenv()
app = FastAPI(title="FinanceCore AI - Production Grade Multi-Agent System")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
vectorstore = None
DB_PATH = "/tmp/audit.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/tmp/financecore.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            task TEXT,
            score REAL,
            retries INTEGER,
            needs_approval INTEGER DEFAULT 0,
            approved INTEGER DEFAULT -1,
            report TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Audit database initialized")

init_db()

REQUESTS = Counter("agent_requests_total", "Total requests", ["status"])
LATENCY  = Histogram("agent_latency_seconds", "Response time", ["endpoint"])
QUALITY  = Histogram("agent_quality_score", "Judge scores")
RETRIES  = Counter("agent_retries_total", "Retry count")

class TaskRequest(BaseModel):
    task: str
    priority: int = 1
    user_id: str = "anonymous"

class ApprovalRequest(BaseModel):
    audit_id: int
    approved: bool
    reviewer_id: str = "anonymous"

def call_groq(messages, temperature=0.1):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=temperature
            )
        except Exception as e:
            logger.warning("Groq attempt %d failed: %s", attempt+1, str(e))
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    logger.error("Circuit open — all Groq retries exhausted")
    return None

class State(TypedDict):
    task: str
    plan: List[str]
    context: str
    result: str
    safe: bool
    score: float
    feedback: str
    retries: int
    report: str
    trace: List[str]
    needs_approval: bool

def planner(state):
    logger.info("PLANNER starting")
    resp = call_groq([{"role":"user","content":
        f"Break this task into 3-5 numbered steps. Return ONLY a JSON array of strings.\nTask: {state['task']}"}])
    if resp is None:
        state["plan"] = ["Analyze query", "Find relevant information", "Provide answer"]
    else:
        try:
            content = resp.choices[0].message.content
            start = content.find("["); end = content.rfind("]") + 1
            state["plan"] = json.loads(content[start:end])
        except:
            state["plan"] = ["Analyze query", "Find relevant information", "Provide answer"]
    state["trace"].append(f"PLANNER: Created {len(state['plan'])}-step plan")
    return state

def retriever(state):
    logger.info("RETRIEVER searching knowledge base")
    if vectorstore:
        docs = vectorstore.similarity_search(state["task"], k=3)
        state["context"] = "\n\n".join([d.page_content for d in docs])
        state["trace"].append(f"RETRIEVER: Found {len(docs)} relevant chunks")
    else:
        state["context"] = "No knowledge base loaded"
        state["trace"].append("RETRIEVER: No knowledge base available")
    return state

def executor(state):
    attempt = state["retries"] + 1
    logger.info("EXECUTOR attempt %d", attempt)
    feedback = f"\nIMPROVE BASED ON: {state['feedback']}" if state["feedback"] else ""
    context = state["context"][:1500] if len(state["context"]) > 1500 else state["context"]
    resp = call_groq([{"role":"user","content":
        f"Answer using ONLY the context provided. Be specific.\nTask: {state['task']}\nPlan: {state['plan']}\nContext: {context}{feedback}"}],
        temperature=0.2)
    if resp is None:
        state["result"] = "Unable to process — AI service temporarily unavailable."
    else:
        state["result"] = resp.choices[0].message.content
    state["trace"].append(f"EXECUTOR: Analysis complete (attempt {attempt})")
    return state

def validator(state):
    logger.info("VALIDATOR checking safety")
    harmful = ["hack the system", "steal money", "bypass security", "launder money", "exploit vulnerability"]
    state["safe"] = not any(kw in state["result"].lower() for kw in harmful)
    if state["safe"]:
        state["trace"].append("VALIDATOR: Content passed safety check")
    else:
        state["result"] = "Response flagged for safety review."
        state["trace"].append("VALIDATOR: FLAGGED — harmful content detected")
    return state

def judge(state):
    logger.info("JUDGE evaluating quality")
    resp = call_groq([{"role":"user","content":
        f"""Rate this answer. Return ONLY valid JSON:
{{"accuracy":0,"completeness":0,"clarity":0,"groundedness":0,"overall":0,"feedback":"","high_risk":false}}
Set high_risk=true if involves large amounts, legal compliance, or sensitive data.
Task: {state['task']}
Answer: {state['result']}"""}])
    if resp is None:
        state["score"] = 7.0; state["needs_approval"] = False
    else:
        try:
            content = resp.choices[0].message.content
            start = content.find("{"); end = content.rfind("}") + 1
            scores = json.loads(content[start:end])
            state["score"] = scores["overall"]
            state["feedback"] = scores.get("feedback", "")
            state["needs_approval"] = scores.get("high_risk", False)
            QUALITY.observe(state["score"])
        except:
            state["score"] = 7.0; state["needs_approval"] = False
    state["trace"].append(f"JUDGE: {state['score']}/10 | High risk: {state['needs_approval']}")
    return state

def reporter(state):
    logger.info("REPORTER formatting output")
    trace_text = "\n".join([f"  {i+1}. {t}" for i,t in enumerate(state["trace"])])
    approval = "\nSTATUS: AWAITING HUMAN APPROVAL" if state["needs_approval"] else "\nSTATUS: AUTO-APPROVED"
    state["report"] = f"""TASK: {state['task']}

AGENT REASONING TRAIL:
{trace_text}

FINAL ANSWER:
{state['result']}

QUALITY SCORE: {state['score']}/10
RETRIES: {state['retries']}{approval}"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO audit_log (timestamp,task,score,retries,needs_approval,report) VALUES (?,?,?,?,?,?)",
            (str(time.time()), state["task"], state["score"],
             state["retries"], 1 if state["needs_approval"] else 0, state["report"]))
        conn.commit(); conn.close()
        state["trace"].append("REPORTER: Saved to audit database")
    except Exception as e:
        logger.error("Audit save failed: %s", str(e))
    return state

def should_retry(state):
    if not state["safe"]: return "reporter"
    if state["score"] < 7 and state["retries"] < 2:
        state["retries"] += 1; RETRIES.inc(); return "executor"
    return "reporter"

def build_graph():
    wf = StateGraph(State)
    wf.add_node("planner", planner)
    wf.add_node("retriever", retriever)
    wf.add_node("executor", executor)
    wf.add_node("validator", validator)
    wf.add_node("judge", judge)
    wf.add_node("reporter", reporter)
    wf.set_entry_point("planner")
    wf.add_edge("planner", "retriever")
    wf.add_edge("retriever", "executor")
    wf.add_edge("executor", "validator")
    wf.add_edge("validator", "judge")
    wf.add_conditional_edges("judge", should_retry)
    wf.add_edge("reporter", END)
    return wf.compile()

agent_app = build_graph()

@app.on_event("startup")
async def startup():
    global vectorstore
    docs = []
    if os.path.exists("documents/"):
        for f in os.listdir("documents/"):
            path = f"documents/{f}"
            try:
                if f.endswith(".pdf"):
                    d = PyPDFLoader(path).load()
                elif f.endswith(".txt"):
                    d = TextLoader(path).load()
                elif f.endswith(".csv"):
                    df = pd.read_csv(path)
                    from langchain.schema import Document
                    docs.append(Document(
                        page_content=df.to_string(),
                        metadata={"source": f}))
                    continue
                else:
                    continue
                for doc in d: doc.metadata["source"] = f
                docs.extend(d)
            except Exception as e:
                logger.error("Failed loading %s: %s", f, str(e))
    if docs:
        chunks = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50).split_documents(docs)
        vectorstore = FAISS.from_documents(chunks, FakeEmbeddings(size=384))
        logger.info("Knowledge base: %d chunks", len(chunks))

@app.post("/run-agent")
async def run_agent(request: TaskRequest):
    start = time.time()
    logger.info("Task from %s: %s", request.user_id, request.task[:50])
    try:
        result = agent_app.invoke(
            {"task":request.task, "plan":[], "context":"", "result":"",
             "safe":True, "score":0.0, "feedback":"", "retries":0,
             "report":"", "trace":[], "needs_approval":False},
            config={"recursion_limit": 10}
        )
        latency = time.time() - start
        LATENCY.labels("run-agent").observe(latency)
        REQUESTS.labels("success").inc()
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT id FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return {
            "task": request.task,
            "report": result["report"],
            "score": result["score"],
            "retries": result["retries"],
            "needs_approval": result["needs_approval"],
            "audit_id": row[0] if row else None,
            "latency_ms": round(latency * 1000)
        }
    except Exception as e:
        REQUESTS.labels("error").inc()
        logger.error("Pipeline failed: %s", str(e))
        return JSONResponse(500, {"error": str(e)})

@app.post("/approve")
async def approve(request: ApprovalRequest):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE audit_log SET approved=? WHERE id=?",
                 (1 if request.approved else 0, request.audit_id))
    conn.commit(); conn.close()
    logger.info("Audit %d: %s by %s", request.audit_id,
                "APPROVED" if request.approved else "REJECTED", request.reviewer_id)
    return {"status": "approved" if request.approved else "rejected",
            "audit_id": request.audit_id}

@app.get("/audit")
async def get_audit():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id,timestamp,task,score,retries,needs_approval,approved FROM audit_log ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return {"logs": [{"id":r[0],"timestamp":r[1],"task":r[2][:60],
                      "score":r[3],"retries":r[4],
                      "needs_approval":bool(r[5]),"approved":r[6]} for r in rows]}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
async def health():
    return {"status":"ok","knowledge_base":vectorstore is not None,
            "pipeline":"6-agent orchestration active"}