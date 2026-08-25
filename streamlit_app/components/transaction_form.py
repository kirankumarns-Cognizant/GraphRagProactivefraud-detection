"""Transaction form component — submit transactions for risk assessment.

Pre-fills fields from the selected persona's defaults. On submit,
calls the scoring engine and stores results in session_state.
"""

import time
import uuid

import streamlit as st

from streamlit_app.config.settings import PERSONAS
from streamlit_app.engine.scoring import score_transaction
from streamlit_app.engine.notifier import send_review_notification


def render_transaction_form() -> None:
    """Render the transaction input form and handle submission.

    Requires st.session_state.selected_persona to be set.
    Updates st.session_state.last_result and transaction_history on submit.
    """
    persona_key = st.session_state.get("selected_persona")
    if not persona_key:
        return

    persona = PERSONAS[persona_key]

    st.divider()
    st.subheader(f"Submit Transaction as {persona['avatar']} {persona['name']}")

    # Use persona-specific widget keys so each persona has independent form state.
    # Switching personas renders different keys → Streamlit uses value= defaults.
    pk = persona_key

    form_col1, form_col2 = st.columns(2)
    with form_col1:
        amount = st.number_input(
            "Transaction Amount ($)",
            min_value=1.0,
            max_value=50000.0,
            value=persona["default_amount"],
            step=10.0,
            key=f"txn_amount_{pk}",
        )
        merchant_id = st.text_input(
            "Merchant ID",
            value=persona["default_merchant"],
            key=f"txn_merchant_{pk}",
        )

    with form_col2:
        description = st.text_input(
            "Description (optional)",
            value=persona["default_description"],
            key=f"txn_description_{pk}",
        )
        account_id = st.text_input(
            "Account ID",
            value=persona["account_id"],
            disabled=True,
            key=f"txn_account_{pk}",
        )

    if st.button("Submit Transaction", type="primary", use_container_width=True):
        txn_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"

        with st.spinner("Running Tier 1 risk assessment..."):
            result = score_transaction(
                account_id=persona["account_id"],
                merchant_id=merchant_id,
                amount=amount,
                transaction_id=txn_id,
            )

        # Add metadata
        result["description"] = description
        result["persona"] = persona_key
        result["timestamp"] = time.strftime("%H:%M:%S")

        # Store result
        st.session_state.last_result = result
        st.session_state.tier2_result = None  # Reset Tier 2

        # Add to history
        st.session_state.transaction_history.append(result)

        # If REVIEW, set as pending and send notification
        if result["decision"] == "REVIEW":
            st.session_state.pending_review = result

            # Send SNS notification (non-blocking)
            sns_result = send_review_notification(result)
            result["sns_result"] = sns_result

            # Add in-app notification
            st.session_state.notifications.append({
                "type": "review",
                "txn_id": txn_id,
                "message": f"Transaction {txn_id} flagged for review — "
                          f"${amount:.2f} on {persona['account_id']}",
                "timestamp": time.strftime("%H:%M:%S"),
            })

        st.rerun()
