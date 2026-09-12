"""Composición de NOVASALUM.

La configuración de Streamlit, la inicialización de la base y el enrutamiento
de vistas se mantienen aquí para que ``app.py`` sea solo el punto de entrada.

Cada cartera elige su propia empresa (``filtro_empresa_manual``,
``filtro_empresa_siigo``…) para que cambiar de empresa en una no mueva la otra.
"""

from __future__ import annotations

import streamlit as st

from src import database as db
from src.ui.layout import VISTA_MANUAL, active_company, render_page_header, render_sidebar
from src.ui.styles import apply_global_styles
from src.views.conciliacion import render_reconciliation
from src.views.manual import render_manual_portfolio, show_payment_dialog
from src.views.siigo import render_siigo_portfolio


VISTA_SIIGO = "Espejo Siigo"


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

    current_view = st.session_state.get("vista", VISTA_MANUAL)
    view = render_sidebar(current_view)
    st.session_state["vista"] = view
    actions = render_page_header(view=view)
    st.write("")

    if view == VISTA_MANUAL:
        if actions.register_payment:
            show_payment_dialog()
        render_manual_portfolio(
            active_company("manual"),
            request_invoice=actions.register_invoice,
        )
    elif view == VISTA_SIIGO:
        render_siigo_portfolio(active_company("siigo"))
    else:
        render_reconciliation(active_company("conciliacion"))
