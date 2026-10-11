import json
import os
from datetime import datetime
from typing import Any, Dict

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Production Re-Planner Under Disruption",
    page_icon="🏭",
    layout="wide",
)

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
SAMPLE_DATA_PATH = os.path.join(os.path.dirname(__file__), "sample_response.json")


def load_sample_response() -> Dict[str, Any]:
    """Load sample response fixture for testing when API is offline."""
    if os.path.exists(SAMPLE_DATA_PATH):
        with open(SAMPLE_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def check_api_health() -> bool:
    """Check connectivity to backend health endpoint."""
    for path in ["/health", "/api/health"]:
        try:
            r = httpx.get(f"{API_URL}{path}", timeout=1.5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
    return False


def call_analyze_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call backend POST /analyze endpoint, falling back to sample fixture if unavailable."""
    for path in ["/analyze", "/api/analyze"]:
        try:
            r = httpx.post(f"{API_URL}{path}", json=payload, timeout=12.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return {}


# --- Sidebar: Controls & Scenarios ---
st.sidebar.title("🏭 Re-Planner Controls")

# API Health Status
is_healthy = check_api_health()
if is_healthy:
    st.sidebar.success(f"● Backend Connected ({API_URL})")
else:
    st.sidebar.warning(f"○ Backend Offline ({API_URL}) — Using Demo Fixture")

st.sidebar.markdown("---")
st.sidebar.subheader("Objective Weights (R6)")
weight_late = st.sidebar.slider("Late Order Penalty", min_value=0.0, max_value=50.0, value=10.0, step=1.0)
weight_overtime = st.sidebar.slider("Overtime Penalty", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
weight_changeover = st.sidebar.slider("Changeover Penalty", min_value=0.0, max_value=10.0, value=1.0, step=0.5)

avoid_overtime = st.sidebar.checkbox("Avoid Overtime (Strict Shift End)", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("Disruption Configuration")
disruption_type = st.sidebar.selectbox("Scenario", ["None (Base Schedule)", "Machine Breakdown (CNC-1)", "Rush Order"])

payload_disruption = None
if disruption_type == "Machine Breakdown (CNC-1)":
    payload_disruption = {
        "event_id": "D-1",
        "kind": "breakdown",
        "at": "2026-10-12T08:00:00",
        "target": "CNC-1",
        "duration_h": 2.0,
    }
elif disruption_type == "Rush Order":
    payload_disruption = {
        "event_id": "D-2",
        "kind": "rush_order",
        "at": "2026-10-12T08:30:00",
        "target": "O-RUSH",
        "product": "P-A",
        "qty": 15,
        "due": "2026-10-12T14:00:00",
        "priority": 1,
        "customer": "VIP Client",
    }


# --- Main Dashboard ---
st.title("🏭 Production Re-Planner Under Disruption")
st.caption("Real-time constraint-validated schedule replanning with explainability and KPI optimization")

# Quick Action Buttons
col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
action_prompt = None

if col_btn1.button("📅 Build Today's Schedule", use_container_width=True):
    action_prompt = "Build today's schedule from base orders."
if col_btn2.button("⚡ Load Disruption & Re-plan", use_container_width=True):
    action_prompt = "Load machine disruption on CNC-1 and re-plan schedule."
    payload_disruption = {
        "event_id": "D-1",
        "kind": "breakdown",
        "at": "2026-10-12T08:00:00",
        "target": "CNC-1",
        "duration_h": 2.0,
    }
if col_btn3.button("⏰ What If We Avoid Overtime?", use_container_width=True):
    action_prompt = "Replan schedule strictly avoiding operator overtime."
    avoid_overtime = True
if col_btn4.button("❓ Why Did Order O-101 Move?", use_container_width=True):
    action_prompt = "Explain why order O-101 moved from its original machine."

# Text prompt input
user_query = st.text_input("Ask a question or enter replanning instruction:", value=action_prompt or "")

execute_btn = st.button("🚀 Run Analysis / Re-plan", type="primary")

# Execute or Load Response
if "analysis_result" not in st.session_state or execute_btn or action_prompt:
    request_body = {
        "message": user_query or "Re-plan schedule under current constraints.",
        "weights": {
            "late": weight_late,
            "overtime": weight_overtime,
            "changeover": weight_changeover,
        },
        "avoid_overtime": avoid_overtime,
        "disruption": payload_disruption,
    }

    with st.spinner("Analyzing schedule and solving constraints..."):
        api_result = call_analyze_api(request_body) if is_healthy else {}
        if api_result:
            st.session_state["analysis_result"] = api_result
            st.session_state["source"] = "Live Backend API"
        else:
            st.session_state["analysis_result"] = load_sample_response()
            st.session_state["source"] = "Saved Sample Response (Offline Demo Mode)"

data = st.session_state.get("analysis_result", {})
source_label = st.session_state.get("source", "Demo Fixture")

if source_label.startswith("Saved Sample"):
    st.info(f"ℹ️ **Data Source:** {source_label}. Backend `/analyze` endpoint was unreachable; showing verified demonstration plan.")
else:
    st.success(f"✅ **Data Source:** {source_label} (Run ID: `{data.get('run_id', 'N/A')}`)")


# 1. Plain-Language Explanation Callout
explanation = data.get("explanation", "No explanation available.")
st.subheader("📢 Plant Manager Briefing")
st.info(explanation)


# 2. Key Performance Indicators (KPIs)
st.subheader("📊 Key Performance Indicators (KPIs)")
kpis = data.get("kpis", {})
kpi_cols = st.columns(5)
kpi_cols[0].metric("Late Orders", kpis.get("late_orders", 0))
kpi_cols[1].metric("Total Lateness", f"{kpis.get('total_lateness_h', 0.0):.1f} hrs")
kpi_cols[2].metric("Overtime", f"{kpis.get('overtime_h', 0.0):.1f} hrs")
kpi_cols[3].metric("Changeovers", kpis.get("changeovers", 0))
kpi_cols[4].metric("Moved Jobs", kpis.get("moved_jobs", 0))


# 3. Gantt Chart (Plotly Timeline with Changed Jobs & Breakdowns)
st.subheader("📅 Schedule Gantt Chart (R10)")
jobs = data.get("jobs", [])
blocked = data.get("blocked", [])

if jobs:
    records = []
    for j in jobs:
        status_label = "⚠️ Changed Job" if j.get("changed", False) else "Standard Job"
        records.append({
            "Machine": j.get("machine"),
            "Start": j.get("start"),
            "Finish": j.get("end"),
            "Order": f"{j.get('order_id')} (S{j.get('step')})",
            "Product": j.get("product"),
            "Operator": j.get("operator"),
            "Status": status_label,
        })

    # Add breakdown windows to timeline for clear visual shading
    for b in blocked:
        records.append({
            "Machine": b.get("machine"),
            "Start": b.get("start"),
            "Finish": b.get("end"),
            "Order": "🛑 BREAKDOWN",
            "Product": "N/A",
            "Operator": "None",
            "Status": "🛑 Machine Breakdown",
        })

    df_jobs = pd.DataFrame(records)
    df_jobs["Start"] = pd.to_datetime(df_jobs["Start"])
    df_jobs["Finish"] = pd.to_datetime(df_jobs["Finish"])

    color_map = {
        "Standard Job": "#1f77b4",
        "⚠️ Changed Job": "#ff7f0e",
        "🛑 Machine Breakdown": "#d62728",
    }

    fig = px.timeline(
        df_jobs,
        x_start="Start",
        x_end="Finish",
        y="Machine",
        color="Status",
        color_discrete_map=color_map,
        hover_data=["Order", "Product", "Operator", "Start", "Finish"],
        title="Machine Schedule Timeline",
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("No scheduled jobs to display.")


# 4. Schedule Changes & Constraint Checks (Side-by-Side)
col_changes, col_validation = st.columns([1, 1])

with col_changes:
    st.subheader("🔄 Schedule Changes")
    changes = data.get("changes", [])
    if changes:
        ch_rows = []
        for ch in changes:
            ch_rows.append({
                "Order": ch.get("order_id"),
                "Step": ch.get("step"),
                "From": ch.get("from") or ch.get("from_"),
                "To": ch.get("to"),
                "Reason": ch.get("reason_code"),
            })
        st.dataframe(pd.DataFrame(ch_rows), use_container_width=True, hide_index=True)
    else:
        st.write("No schedule modifications compared to original plan.")

with col_validation:
    st.subheader("🛡️ Constraint Validation Status")
    check = data.get("check", {})
    rules = [
        ("Machine Capacity (No Overlap)", check.get("capacity_ok", True)),
        ("Operator Skills", check.get("skill_ok", True)),
        ("Changeover Gaps", check.get("changeover_ok", True)),
        ("Routing Precedence", check.get("precedence_ok", True)),
        ("Machine Eligibility & Duration", check.get("eligibility_ok", True)),
        ("Shift Bounds & Overtime", check.get("shift_ok", True)),
        ("WIP & Fixed Jobs", check.get("wip_ok", True)),
        ("Breakdown Avoidance", check.get("breakdown_ok", True)),
    ]

    for label, is_ok in rules:
        if is_ok:
            st.markdown(f"✅ **{label}**: Passed")
        else:
            st.markdown(f"❌ **{label}**: Failed")

    violations = check.get("violations", [])
    if violations:
        with st.expander("⚠️ View Constraint Violations"):
            for v in violations:
                st.write(f"- {v}")


# 5. Pipeline Trace & Raw Response Expander
st.markdown("---")
with st.expander("🔍 Trace & Raw JSON Inspection"):
    st.markdown(f"**Run ID:** `{data.get('run_id', 'N/A')}`")
    st.markdown("**Pipeline Trace:**")
    st.json(data.get("trace", {}))
    st.markdown("**Full Response:**")
    st.json(data)

