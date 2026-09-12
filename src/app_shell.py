"""Composición de NOVASALUM.

La configuración de Streamlit, la inicialización de la base y el enrutamiento
de vistas se mantienen aquí para que ``app.py`` sea solo el punto de entrada.

Cada cartera elige su propia empresa (``filtro_empresa_manual``,
``filtro_empresa_siigo``…) para que cambiar de empresa en una no mueva la otra.
"""

from __future__ import annotations

import os

import streamlit as st

from src import database as db
from src.ui.layout import VISTA_MANUAL, active_company, render_page_header, render_sidebar
from src.ui.styles import apply_global_styles
from src.views.conciliacion import render_reconciliation
from src.views.manual import render_manual_portfolio, show_payment_dialog
from src.ui.ingreso import render_ingreso, render_seguridad, usuario_actual
from src.views.siigo import render_siigo_portfolio


VISTA_SIIGO = "Espejo Siigo"
VISTA_SEGURIDAD = "Seguridad"


def run_application() -> None:
    """Inicializa la aplicación y muestra la vista seleccionada."""

    st.set_page_config(
        page_title="NOVASALUM · Cartera",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_global_styles()

    # Puente de secretos: si hay una URL de Supabase configurada, la cartera
    # manual se guarda allá. src.database no importa Streamlit, así que la
    # llave viaja por el entorno del proceso.
    try:
        url_nube = str(st.secrets.get("SUPABASE_DB_URL", "")).strip()
    except Exception:
        url_nube = ""
    if url_nube:
        os.environ["SUPABASE_DB_URL"] = url_nube

    try:
        db.inicializar()
    except Exception as exc:
        st.error(
            "No fue posible conectar con la base de datos "
            f"({db.descripcion_almacen()}). Detalle: {exc}"
        )
        st.info(
            "Revisa la llave SUPABASE_DB_URL en los secretos, o retírala para "
            "trabajar con la base local mientras tanto. Ninguna factura se "
            "pierde por este aviso: simplemente no se puede leer ni guardar "
            "hasta restablecer la conexión."
        )
        st.stop()

    # Puerta de acceso: nada de la cartera se muestra sin ingresar. Va antes
    # que cualquier lectura de datos, no solo antes de dibujarlos.
    if usuario_actual() is None:
        render_ingreso()
        st.stop()

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
    elif view == VISTA_SEGURIDAD:
        render_seguridad()
    else:
        render_reconciliation(active_company("conciliacion"))
