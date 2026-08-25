"""GraphRAG Fraud Detection — Streamlit Demo Application.

Main entry point for the fraud detection demo UI.
Demonstrates three customer personas (genuine, fraud, borderline)
processed through the Tier 1 graph-based + Tier 2 LLM fraud pipeline.

Launch:
    cd fraud-detection
    streamlit run streamlit_app/app.py
"""

import sys
import os

import streamlit as st

# Ensure project root is on the import path so we can import lambdas/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from streamlit_app.config.settings import PAGE_ICON, PAGE_TITLE, PERSONAS
from streamlit_app.components.health_check import run_all_checks
from streamlit_app.components.warmup import warmup_all_personas
from streamlit_app.components.personas import render_persona_selector
from streamlit_app.components.transaction_form import render_transaction_form
from streamlit_app.components.dashboard import render_dashboard
from streamlit_app.components.notifications import render_notification_panel


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
if "initialized" not in st.session_state:
    st.session_state.initialized = False
    st.session_state.health_status = {}
    st.session_state.warmup_results = {}
    st.session_state.selected_persona = None
    st.session_state.transaction_history = []
    st.session_state.pending_review = None
    st.session_state.notifications = []
    st.session_state.tier2_result = None
    st.session_state.last_result = None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title(f"{PAGE_ICON} Fraud Detection")
    st.caption("GraphRAG-powered POC Demo")

    st.divider()

    # --- Health Check ---
    st.subheader("System Health")

    if st.button("Run Health Check", use_container_width=True):
        with st.spinner("Checking AWS services..."):
            st.session_state.health_status = run_all_checks()
            st.session_state.initialized = True

    if st.session_state.health_status:
        for service, (status, detail) in st.session_state.health_status.items():
            icon = {"green": "🟢", "amber": "🟡", "red": "🔴"}.get(status, "⚪")
            st.markdown(f"{icon} **{service}**")
            st.caption(detail)
    else:
        st.info("Click 'Run Health Check' to verify services")

    st.divider()

    # --- Persona Warmup ---
    st.subheader("Persona Warmup")

    if st.button("Verify Personas", use_container_width=True):
        with st.spinner("Verifying persona accounts in Neptune..."):
            st.session_state.warmup_results = warmup_all_personas()

    if st.session_state.warmup_results:
        for key, result in st.session_state.warmup_results.items():
            icon = "✅" if result["exists"] else "❌"
            persona = PERSONAS[key]
            st.markdown(f"{icon} **{persona['name']}** ({persona['account_id']})")
            st.caption(result["detail"])

    st.divider()

    # --- Transaction History ---
    st.subheader("Transaction History")
    if st.session_state.transaction_history:
        for txn in reversed(st.session_state.transaction_history[-10:]):
            decision = txn.get("decision", "?")
            color = {
                "APPROVE": "green", "APPROVED": "green",
                "REVIEW": "orange",
                "REJECT": "red", "REJECTED": "red",
            }.get(decision, "gray")
            st.markdown(
                f":{color}[**{decision}**] ${txn.get('amount', 0):.2f} — "
                f"{txn.get('account_id', '?')}"
            )
    else:
        st.caption("No transactions yet")


# ---------------------------------------------------------------------------
# Main Area
# ---------------------------------------------------------------------------
st.title(PAGE_TITLE)

# 1. Persona Selector
render_persona_selector()

# 2. Transaction Form (shown when persona selected)
if st.session_state.selected_persona:
    render_transaction_form()

    # 3. Risk Dashboard (shown after transaction submitted)
    render_dashboard()

    # 4. Notification / Review Panel
    render_notification_panel()

else:
    st.divider()
    st.info("Select a customer persona above to begin a transaction")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "GraphRAG Fraud Detection POC | "
    "Tier 1: Graph Rules (Neptune) | "
    "Tier 2: LLM Explanation (Bedrock Claude) | "
    "Built with Streamlit"
)
