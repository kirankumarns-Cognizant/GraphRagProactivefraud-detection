"""Notification and review panel components.

Displays in-app notifications for flagged transactions and provides
approve/reject buttons for REVIEW decisions.
"""

import time

import streamlit as st


def render_notification_panel() -> None:
    """Render the notification panel and approve/reject flow.

    Shows pending REVIEW transactions with approve/reject buttons.
    Displays notification history.
    """
    pending = st.session_state.get("pending_review")
    notifications = st.session_state.get("notifications", [])

    if not pending and not notifications:
        return

    st.divider()

    # --- Pending Review (approve/reject) ---
    if pending and pending.get("decision") == "REVIEW":
        _render_review_panel(pending)

    # --- Notification History ---
    if notifications:
        with st.expander(f"🔔 Notifications ({len(notifications)})", expanded=False):
            for notif in reversed(notifications[-10:]):
                icon = {"review": "⚠️", "approved": "✅", "rejected": "🚫"}.get(
                    notif.get("type", ""), "ℹ️"
                )
                st.markdown(
                    f"{icon} **{notif['timestamp']}** — {notif['message']}"
                )


def _render_review_panel(pending: dict) -> None:
    """Render the approve/reject panel for a pending REVIEW transaction.

    Args:
        pending: The pending transaction result dict.
    """
    st.subheader("⚠️ Transaction Requires Your Decision")

    st.markdown(
        f"""
        <div style="
            background-color: #ffc10720;
            border-left: 6px solid #ffc107;
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 16px;
        ">
            <p style="margin: 0;">
                <strong>Transaction:</strong> {pending.get('transaction_id', 'N/A')}<br>
                <strong>Amount:</strong> ${pending.get('amount', 0):.2f}<br>
                <strong>Merchant:</strong> {pending.get('merchant_id', 'N/A')}<br>
                <strong>Risk Score:</strong> {pending.get('risk_score', 0)} (REVIEW band: 30-59)<br>
                <strong>Rules:</strong> {', '.join(r['rule'] for r in pending.get('rules_triggered', []))}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅ Approve Transaction", use_container_width=True, type="primary"):
            _resolve_review(pending, "APPROVED")
            st.rerun()

    with col2:
        if st.button("🚫 Reject Transaction", use_container_width=True):
            _resolve_review(pending, "REJECTED")
            st.rerun()


def _resolve_review(pending: dict, resolution: str) -> None:
    """Resolve a pending REVIEW transaction.

    Args:
        pending: The pending transaction result dict.
        resolution: Either 'APPROVED' or 'REJECTED'.
    """
    txn_id = pending.get("transaction_id", "N/A")

    # Update the transaction in history
    for txn in st.session_state.transaction_history:
        if txn.get("transaction_id") == txn_id:
            txn["decision"] = resolution
            txn["resolved_by"] = "customer"
            txn["resolved_at"] = time.strftime("%H:%M:%S")
            break

    # Add notification
    icon_word = "approved" if resolution == "APPROVED" else "rejected"
    st.session_state.notifications.append({
        "type": icon_word,
        "txn_id": txn_id,
        "message": f"Transaction {txn_id} {icon_word} by customer",
        "timestamp": time.strftime("%H:%M:%S"),
    })

    # Clear pending review
    st.session_state.pending_review = None
