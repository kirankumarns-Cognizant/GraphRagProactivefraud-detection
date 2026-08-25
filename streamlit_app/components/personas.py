"""Persona selector component — three demo customer profiles.

Renders persona cards with profile info, expected behavior,
and selection buttons. Manages persona state in session_state.
"""

import streamlit as st

from streamlit_app.config.settings import PERSONAS


def render_persona_selector() -> None:
    """Render the three persona cards and handle selection.

    Updates st.session_state.selected_persona on selection.
    """
    st.subheader("Select a Customer Persona")

    cols = st.columns(3)
    for i, (key, persona) in enumerate(PERSONAS.items()):
        with cols[i]:
            band_color = {
                "APPROVE": "green",
                "REVIEW": "orange",
                "REJECT": "red",
            }.get(persona["expected_band"], "gray")

            selected = st.session_state.get("selected_persona") == key

            st.markdown(
                f"### {persona['avatar']} {persona['name']}\n"
                f"**Account:** `{persona['account_id']}`\n\n"
                f"{persona['description']}\n\n"
                f"Expected: :{band_color}[**{persona['expected_band']}**]"
            )

            if st.button(
                f"Select {persona['name']}",
                key=f"select_{key}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state.selected_persona = key
                st.session_state.last_result = None
                st.session_state.tier2_result = None
                # Clear form widget keys so new persona defaults take effect
                # (Streamlit ignores the value= param if a key already exists)
                for form_key in ("txn_amount", "txn_merchant",
                                 "txn_description", "txn_account"):
                    st.session_state.pop(form_key, None)
                st.rerun()
