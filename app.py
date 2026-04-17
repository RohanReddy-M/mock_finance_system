import streamlit as st
import requests

st.set_page_config(page_title="FinanceCore AI", page_icon="🏦", layout="wide")

with st.sidebar:
    st.title("System Status")
    try:
        r = requests.get("http://api:8000/health", timeout=3)
        data = r.json()
        st.success("All 6 Agents Ready")
        st.info(f"Knowledge base: {'Loaded' if data.get('knowledge_base') else 'Empty'}")
        st.caption("Pipeline: 6-agent orchestration active")
    except:
        st.error("Cannot connect to agents")
    st.divider()
    st.caption("Monitoring:")
    st.markdown("- [Grafana Dashboard](http://localhost:3001)")
    st.markdown("- [API Docs](http://localhost:8000/docs)")
    st.markdown("- [Metrics](http://localhost:8000/metrics)")
    if st.button("Clear Session"):
        st.session_state.history = []
        st.rerun()

st.title("FinanceCore AI — Production Grade 6-Agent System")
st.caption("Planner → Retriever → Executor → Validator → Judge → Reporter")
tab1, tab2, tab3 = st.tabs(["Run Agent Task", "Pending Approvals", "Audit Log"])

with tab1:
    task = st.text_area("Enter your query:",
        placeholder="Example: What is the refund policy for transactions above Rs 50,000?",
        height=100)
    col1, col2 = st.columns([1,3])
    with col1:
        user_id = st.text_input("User ID:", value="employee_001")
    with col2:
        priority = st.selectbox("Priority:", [1, 2, 3], index=0)

    if st.button("Run 6-Agent Pipeline", type="primary"):
        if task:
            with st.spinner("Planner → Retriever → Executor → Validator → Judge → Reporter"):
                try:
                    r = requests.post("http://api:8000/run-agent",
                        json={"task": task, "user_id": user_id, "priority": priority},
                        timeout=120)
                    data = r.json()
                    score = data.get("score", 0)
                    retries = data.get("retries", 0)
                    latency = data.get("latency_ms", 0)
                    needs_approval = data.get("needs_approval", False)
                    audit_id = data.get("audit_id")

                    if needs_approval:
                        st.warning(f"HIGH RISK DECISION — Human Approval Required (Audit ID: {audit_id})")
                    else:
                        st.success(f"Completed in {latency}ms | Quality: {score:.1f}/10 | Retries: {retries}")

                    st.subheader("Agent Reasoning Trail + Report")
                    st.text_area("", value=data.get("report",""), height=380, disabled=True)

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Quality Score", f"{score:.1f}/10")
                    c2.metric("Retries", retries)
                    c3.metric("Response Time", f"{latency}ms")
                    c4.metric("Risk Level", "HIGH" if needs_approval else "LOW")

                    if needs_approval:
                        st.divider()
                        st.subheader("Human Approval Required")
                        st.write("This response involves sensitive data. Manager must review:")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("APPROVE ✓", type="primary"):
                                requests.post("http://api:8000/approve",
                                    json={"audit_id": audit_id,
                                          "approved": True,
                                          "reviewer_id": user_id})
                                st.success("Approved and logged to audit trail")
                        with col_b:
                            if st.button("REJECT ✗"):
                                requests.post("http://api:8000/approve",
                                    json={"audit_id": audit_id,
                                          "approved": False,
                                          "reviewer_id": user_id})
                                st.error("Rejected and logged to audit trail")

                    if "history" not in st.session_state:
                        st.session_state.history = []
                    st.session_state.history.append({
                        "task": task, "score": score,
                        "latency": latency, "retries": retries,
                        "needs_approval": needs_approval
                    })

                except Exception as e:
                    st.error(f"Error: {e}")
        else:
            st.warning("Please enter a query")

with tab2:
    st.header("Pending Human Approvals")
    st.caption("High-risk decisions waiting for manager review")
    try:
        r = requests.get("http://api:8000/audit", timeout=5)
        logs = r.json().get("logs", [])
        pending = [l for l in logs if l["needs_approval"] and l["approved"] == -1]
        if pending:
            st.warning(f"{len(pending)} decision(s) awaiting approval")
            for log in pending:
                with st.expander(f"ID {log['id']} — Score: {log['score']}/10 — {log['task']}"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button(f"APPROVE", key=f"a{log['id']}", type="primary"):
                            requests.post("http://api:8000/approve",
                                json={"audit_id": log['id'],
                                      "approved": True,
                                      "reviewer_id": "manager"})
                            st.success("Approved")
                            st.rerun()
                    with col_b:
                        if st.button(f"REJECT", key=f"r{log['id']}"):
                            requests.post("http://api:8000/approve",
                                json={"audit_id": log['id'],
                                      "approved": False,
                                      "reviewer_id": "manager"})
                            st.error("Rejected")
                            st.rerun()
        else:
            st.success("No pending approvals")
    except:
        st.error("Cannot load approvals")

with tab3:
    st.header("Complete Audit Log")
    st.caption("Every agent decision — permanently stored and queryable")
    try:
        r = requests.get("http://api:8000/audit", timeout=5)
        logs = r.json().get("logs", [])
        hist = st.session_state.get("history", [])
        if hist:
            scores = [h["score"] for h in hist]
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total Queries", len(hist))
            c2.metric("Avg Quality", f"{sum(scores)/len(scores):.1f}/10")
            c3.metric("Below Threshold", sum(1 for s in scores if s < 7))
            c4.metric("High Risk", sum(1 for h in hist if h.get("needs_approval")))
            st.divider()
        if logs:
            for log in logs:
                if log["approved"] == -1:
                    status = "PENDING"
                    color = "orange"
                elif log["approved"] == 1:
                    status = "APPROVED"
                    color = "green"
                else:
                    status = "REJECTED"
                    color = "red"
                st.markdown(
                    f"**ID {log['id']}** | Score: {log['score']}/10 | "
                    f"Retries: {log['retries']} | :{color}[{status}] | {log['task']}"
                )
        else:
            st.info("No queries yet. Run something in Tab 1.")
    except:
        st.error("Cannot load audit log")