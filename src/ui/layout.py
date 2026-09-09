"""Estructura visual compartida de la aplicación.

Este módulo contiene únicamente la navegación y la cabecera. Las vistas y sus
reglas de negocio viven en módulos separados.
"""

from __future__ import annotations

import html

import streamlit as st

from src import database as db
from src.ui.components import activity_summary, company_label, invoice_label


ALL_COMPANIES = "TODAS"
VIEWS = ("Cartera manual", "Espejo Siigo", "Conciliación")


def render_sidebar(current_view: str) -> str:
    """Renderiza la navegación y devuelve la vista elegida."""

    selected_view = current_view if current_view in VIEWS else VIEWS[0]
    with st.sidebar:
        st.markdown(
            '<div class="brand"><span class="brand-mark">◈</span>NOVASALUM</div>',
            unsafe_allow_html=True,
        )
        st.caption("Cartera separada · operación y lectura contable")
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


def render_page_header() -> tuple[str, str, bool]:
    """Muestra cabecera global y retorna empresa, búsqueda y acción de abono."""

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
        request_payment = st.button(
            "＋ Registrar abono", type="primary", use_container_width=True
        )

    current_company = st.session_state.get("empresa_activa", ALL_COMPANIES)
    if current_company not in {ALL_COMPANIES, *db.EMPRESAS}:
        current_company = ALL_COMPANIES
    company = st.segmented_control(
        "Empresa",
        [ALL_COMPANIES, *db.EMPRESAS],
        default=current_company,
        format_func=company_label,
        key="selector_empresa_global",
        width="stretch",
        label_visibility="collapsed",
    )
    if company is None:
        company = current_company
    st.session_state["empresa_activa"] = company

    invoices = db.listar_facturas(None if company == ALL_COMPANIES else company)
    options = [""] + [invoice_label(invoice) for invoice in invoices]
    match = st.selectbox(
        "Buscar factura o cliente",
        options,
        index=0,
        placeholder="Buscar por factura, cliente, NIT o placa…",
        key="buscador_global",
        label_visibility="collapsed",
    )
    global_term = match.split(" · ", 1)[0] if match else ""
    return company, global_term, request_payment
