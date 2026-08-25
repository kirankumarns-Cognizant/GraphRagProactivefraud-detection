"""Risk dashboard component — displays scoring results and Tier 2 explanations.

Shows:
- Decision banner (APPROVE/REVIEW/REJECT with color)
- Risk score gauge
- Rules breakdown table
- On-demand Tier 2 "Explain with AI" button
- Tier 1 vs Tier 2 comparison (for technical audience)
"""

import streamlit as st

from streamlit_app.engine.explainer import explain_entity


# Decision color mapping
_DECISION_COLORS = {
    "APPROVE": ("#28a745", "green", "✅"),   # Green
    "REVIEW": ("#ffc107", "orange", "⚠️"),    # Amber
    "REJECT": ("#dc3545", "red", "🚫"),       # Red
}


def render_dashboard() -> None:
    """Render the risk assessment dashboard for the last transaction.

    Reads st.session_state.last_result and displays the full breakdown.
    """
    result = st.session_state.get("last_result")
    if not result:
        return

    st.divider()
    st.subheader("Risk Assessment Result")

    decision = result.get("decision", "?")
    score = result.get("risk_score", 0)
    hex_color, st_color, icon = _DECISION_COLORS.get(decision, ("#6c757d", "gray", "❓"))

    # --- Decision Banner ---
    st.markdown(
        f"""
        <div style="
            background-color: {hex_color}20;
            border-left: 6px solid {hex_color};
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 16px;
        ">
            <h2 style="color: {hex_color}; margin: 0;">
                {icon} {decision}
            </h2>
            <p style="margin: 4px 0 0 0; font-size: 1.1em;">
                Transaction {result.get('transaction_id', 'N/A')} —
                ${result.get('amount', 0):.2f} on {result.get('account_id', '?')}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Metrics Row ---
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Risk Score", f"{score}/130")
    with m2:
        st.metric("Rules Triggered", result.get("rule_count", 0))
    with m3:
        st.metric("Latency", f"{result.get('latency_ms', 0):.0f}ms")
    with m4:
        st.metric("Tier", "1 — Graph Rules")

    # --- Risk Score Bar ---
    score_pct = min(score / 130.0, 1.0)
    st.progress(score_pct, text=f"Risk Score: {score} "
                f"(APPROVE ≤29 | REVIEW 30-59 | REJECT ≥60)")

    # --- Warnings ---
    if result.get("warnings"):
        for warning in result["warnings"]:
            st.warning(warning)

    # --- Rules Breakdown ---
    rules = result.get("rules_triggered", [])
    if rules:
        st.subheader("Rules Breakdown")
        for rule in rules:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                rule.get("severity", ""), "⚪"
            )
            st.markdown(
                f"{severity_icon} **{rule['rule']}** — {rule['detail']}"
            )
    else:
        st.info("No rules triggered — transaction appears clean")

    # --- SNS Notification Status ---
    if result.get("sns_result"):
        sns = result["sns_result"]
        if sns.get("sent"):
            st.success(f"SNS notification sent (ID: {sns['message_id'][:12]}...)")
        elif sns.get("error"):
            st.warning(f"SNS notification failed: {sns['error']}")

    # --- Tier 2: Explain with AI (on-demand) ---
    if decision in ("REVIEW", "REJECT"):
        st.divider()
        _render_tier2_section(result)


def _render_tier2_section(result: dict) -> None:
    """Render the on-demand Tier 2 LLM explanation section.

    Args:
        result: The Tier 1 scoring result.
    """
    st.subheader("Tier 2: AI-Powered Explanation")
    st.caption("Click below to get a detailed LLM-generated analysis "
               "(typically 5-15 seconds)")

    if st.button("🔍 Explain with AI", use_container_width=True):
        with st.spinner("Gathering evidence and generating explanation..."):
            tier2 = explain_entity(result.get("account_id", ""), max_hops=2)
            st.session_state.tier2_result = tier2

    tier2 = st.session_state.get("tier2_result")
    if tier2:
        # Source indicator
        source_label = "🤖 Claude Sonnet 4" if tier2["source"] == "llm" else "📋 Template"
        st.caption(f"Source: {source_label} | Latency: {tier2['latency_s']:.1f}s")

        if tier2.get("warning"):
            st.warning(tier2["warning"])

        # Explanation text
        st.markdown(tier2["explanation"])

        # Evidence details (expandable for technical audience)
        evidence = tier2.get("evidence", {})
        findings = evidence.get("findings", [])
        if findings:
            with st.expander(f"📊 Raw Evidence ({len(findings)} findings)", expanded=False):
                for f in findings:
                    severity_icon = {"high": "🔴", "medium": "🟡",
                                     "low": "🟢", "info": "ℹ️"}.get(
                        f.get("severity", ""), "⚪"
                    )
                    st.markdown(
                        f"{severity_icon} **{f['type']}**: {f['detail']}"
                    )

        # Tier 1 vs Tier 2 comparison (technical audience)
        with st.expander("⚖️ Tier 1 vs Tier 2 Comparison", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### Tier 1: Graph Rules")
                st.markdown(f"- **Score**: {result.get('risk_score', 0)}/130")
                st.markdown(f"- **Decision**: {result.get('decision', '?')}")
                st.markdown(f"- **Latency**: {result.get('latency_ms', 0):.0f}ms")
                st.markdown(f"- **Rules**: {result.get('rule_count', 0)} triggered")
                st.markdown("- **Approach**: Deterministic graph traversal")
            with col2:
                st.markdown("### Tier 2: LLM Analysis")
                risk_line = "See explanation above"
                for line in tier2["explanation"].split("\n"):
                    if "risk level" in line.lower() or "risk:" in line.lower():
                        risk_line = line.strip()
                        break
                st.markdown(f"- **Risk Assessment**: {risk_line}")
                st.markdown(f"- **Latency**: {tier2['latency_s']:.1f}s")
                st.markdown(f"- **Source**: {source_label}")
                st.markdown(f"- **Evidence**: {len(findings)} findings")
                st.markdown("- **Approach**: Graph evidence + LLM reasoning")
