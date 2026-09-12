"""Estructura visual compartida de la aplicación.

Este módulo contiene únicamente la navegación y la cabecera. Las vistas y sus
reglas de negocio viven en módulos separados.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import streamlit as st

from src import database as db
from src.ui.components import activity_summary


ALL_COMPANIES = "TODAS"
VIEWS = ("Cartera manual", "Espejo Siigo", "Conciliación")


VISTA_MANUAL = "Cartera manual"


@dataclass(frozen=True)
class HeaderActions:
    """Acciones solicitadas desde los botones de la cabecera."""

    register_payment: bool = False
    register_invoice: bool = False


def render_sidebar(current_view: str) -> str:
    """Renderiza la navegación y devuelve la vista elegida."""

    selected_view = current_view if current_view in VIEWS else VIEWS[0]
    with st.sidebar:
        st.markdown(
            '<div class="brand"><span class="brand-mark">◈</span>NOVASALUM</div>',
            unsafe_allow_html=True,
        )
        st.caption("Cartera separada · operación y lectura contable")
        # El dueño debe saber de un vistazo dónde están guardadas sus facturas.
        st.caption(f"Datos: {db.descripcion_almacen()}")
        st.divider()
        selected_view = st.radio(
            "Navegación",
            VIEWS,
            index=VIEWS.index(selected_view),
            label_visibility="collapsed",
        )
        st.divider()
        activity = db.resumen_actividad()
        if activity:
            st.markdown("##### Actividad reciente")
            for event in activity[:4]:
                summary = activity_summary(event["detalle"])
                st.markdown(
                    f'<div class="activity"><strong>{html.escape(event["accion"].title())}</strong>'
                    f'<br><span style="color:#64748b">{html.escape(summary)}</span></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Todavía no hay movimientos manuales.")
    return selected_view


def active_company(scope: str = "manual") -> str:
    """Obtiene la empresa elegida dentro del filtro de la vista indicada.

    Cada cartera tiene su propio selector (``filtro_empresa_manual``,
    ``filtro_empresa_siigo``…) para que cambiar de empresa en una no mueva la
    otra. ``empresa_activa`` la escribe únicamente la cartera manual, porque es
    la preselección del diálogo de abono, que solo existe ahí.
    """

    company = st.session_state.get(f"filtro_empresa_{scope}", ALL_COMPANIES)
    if company not in {ALL_COMPANIES, *db.EMPRESAS}:
        company = ALL_COMPANIES
    if scope == "manual":
        st.session_state["empresa_activa"] = company
    return company


def render_page_header(*, view: str) -> HeaderActions:
    """Muestra la cabecera y concentra las acciones de cartera manual."""

    left, right = st.columns([4, 1.3], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="eyebrow">Finanzas · operación y verificación</div>'
            '<h1 style="margin:0">Cartera</h1>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="page-subtitle">Facturas, abonos y conciliación de las tres empresas.</div>',
            unsafe_allow_html=True,
        )
    with right:
        # Las dos acciones escriben en la cartera manual. Fuera de ella no se
        # dibujan: la cartera Siigo es de solo consulta y nadie la digita.
        register_invoice = False
        register_payment = False
        if view == VISTA_MANUAL:
            register_invoice = st.button(
                "＋ Registrar factura", type="primary", use_container_width=True
            )
            register_payment = st.button(
                "＋ Registrar abono", type="primary", use_container_width=True
            )

    return HeaderActions(
        register_payment=register_payment,
        register_invoice=register_invoice,
    )
