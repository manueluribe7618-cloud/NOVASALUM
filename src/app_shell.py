"""Composición de NOVASALUM.

La configuración de Streamlit, la inicialización de la base y el enrutamiento
de vistas se mantienen aquí para que ``app.py`` sea solo el punto de entrada.
"""

from __future__ import annotations

import streamlit as st

from src import database as db
from src.ui.layout import active_company, render_page_header, render_sidebar
from src.ui.styles import apply_global_styles
from src.views.manual import render_manual_portfolio, show_payment_dialog
from src.views.siigo import render_reconciliation, render_siigo_mirror


def run_application() -> None:
    """Inicializa la aplicación y muestra la vista seleccionada."""

    st.set_page_config(
        page_title="NOVASALUM · Cartera",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_global_styles()
    db.inicializar()

    current_view = st.session_state.get("vista", "Cartera manual")
    view = render_sidebar(current_view)
    st.session_state["vista"] = view
    request_payment = render_page_header()
    company = active_company()
    st.write("")

    if request_payment:
        show_payment_dialog()

    if view == "Cartera manual":
        render_manual_portfolio(company)
    elif view == "Espejo Siigo":
        render_siigo_mirror(company)
    else:
        render_reconciliation(company)
