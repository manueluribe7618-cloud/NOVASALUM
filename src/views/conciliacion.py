"""Conciliación: cruza la cartera manual con la lectura de Siigo.

Es la única pantalla que mira las dos carteras a la vez, y lo hace a propósito:
compara factura por factura para encontrar diferencias. Las dos carteras siguen
siendo independientes; aquí solo se leen y se guarda una revisión interna, que
nunca modifica documentos en Siigo.
"""

from __future__ import annotations

from collections.abc import Mapping
import datetime as dt
import html
from typing import Any

import pandas as pd
import streamlit as st

from src import database as db
from src.cartera_siigo import normalizar_factura
from src.ui.components import (
    ESTADO_META,
    TODAS,
    as_integer,
    format_currency,
    render_kpi_card,
    render_section,
)
def _siigo_row_as_dict(
    row: pd.Series | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    return {key: (None if pd.isna(value) else value) for key, value in data.items()}


def _build_reconciliation(
    manual_invoices: list[dict[str, Any]],
    siigo_invoices: pd.DataFrame,
) -> list[dict[str, Any]]:
    manual_by_invoice = {
        (row["empresa_codigo"], normalizar_factura(row["factura"])): row
        for row in manual_invoices
    }
    siigo_by_invoice: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(siigo_invoices, pd.DataFrame) and not siigo_invoices.empty:
        for _, row in siigo_invoices.iterrows():
            company = str(row.get("empresa_codigo", "")).strip().upper()
            invoice_key = normalizar_factura(row.get("factura", ""))
            if company and invoice_key:
                siigo_by_invoice[(company, invoice_key)] = _siigo_row_as_dict(row) or {}
    result: list[dict[str, Any]] = []
    for company, invoice_key in sorted(set(manual_by_invoice) | set(siigo_by_invoice)):
        manual = manual_by_invoice.get((company, invoice_key))
        official = siigo_by_invoice.get((company, invoice_key))
        invoice = (manual or official or {}).get("factura", invoice_key)
        customer = (manual or official or {}).get("cliente", "")
        balance_difference = None
        iva_difference = None
        withholding_difference = None
        ica_difference = None
        if manual is None:
            status = "SOLO_SIIGO"
        elif official is None:
            status = "SOLO_MANUAL"
        else:
            balance_difference = as_integer(manual["saldo_cop"]) - as_integer(
                official.get("saldo_siigo")
            )
            iva_difference = as_integer(manual["iva_cop"]) - as_integer(
                official.get("iva_siigo")
            )
            withholding_difference = as_integer(manual["retefuente_cop"]) - as_integer(
                official.get("retefuente_siigo")
            )
            ica_difference = as_integer(manual["ica_cop"]) - as_integer(
                official.get("reteica_siigo")
            )
            if abs(balance_difference) <= 1 and all(
                abs(difference) <= 1
                for difference in (iva_difference, withholding_difference, ica_difference)
            ):
                status = "CUADRADO"
            elif abs(balance_difference) <= 1:
                status = "DIFERENCIA_IMPUESTOS"
            else:
                status = "DESCUADRE"
        result.append(
            {
                "empresa_codigo": company,
                "factura_clave": invoice_key,
                "factura": invoice,
                "cliente": customer,
                "estado": status,
                "manual": manual,
                "siigo": official,
                "dif_saldo": balance_difference,
                "dif_iva": iva_difference,
                "dif_retefuente": withholding_difference,
                "dif_ica": ica_difference,
            }
        )
    return result


def _format_difference(value: int | None) -> str:
    return "—" if value is None else format_currency(value)


def _visible_date(value: Any) -> str:
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return dt.date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(value)


def _render_comparison_side(
    title: str,
    kind: str,
    row: Mapping[str, Any] | None,
) -> None:
    if row is None:
        st.markdown(
            f'<div class="split-card {kind}"><div class="split-title">{html.escape(title)}</div>'
            '<div style="color:#94a3b8;padding-top:4rem;text-align:center">No existe esta factura en la fuente.</div></div>',
            unsafe_allow_html=True,
        )
        return
    is_siigo = kind == "siigo"
    fields = [
        ("Cliente", row.get("cliente", "—")),
        ("Fecha", _visible_date(row.get("fecha"))),
        ("Subtotal", format_currency(row.get("subtotal_siigo" if is_siigo else "subtotal_cop"))),
        ("IVA", format_currency(row.get("iva_siigo" if is_siigo else "iva_cop"))),
        (
            "Retefuente",
            format_currency(row.get("retefuente_siigo" if is_siigo else "retefuente_cop")),
        ),
        ("ICA", format_currency(row.get("reteica_siigo" if is_siigo else "ica_cop"))),
        ("Saldo", format_currency(row.get("saldo_siigo" if is_siigo else "saldo_cop"))),
    ]
    detail = row.get("descripcion_siigo", "") if is_siigo else row.get("descripcion", "")
    content = "".join(
        f'<div class="split-row"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>'
        for label, value in fields
    )
    st.markdown(
        f'<div class="split-card {kind}"><div class="split-title">{html.escape(title)}</div>'
        f'{content}<div style="margin-top:.8rem;color:#64748b;font-size:.82rem">{html.escape(str(detail or "Sin detalle"))}</div></div>',
        unsafe_allow_html=True,
    )


def _status_badge(status: str) -> str:
    label, tone = ESTADO_META.get(status, (status.replace("_", " ").title(), "gris"))
    return f'<span class="badge badge-{tone}">{html.escape(label)}</span>'


def render_reconciliation(company: str) -> None:
    """Renderiza el cruce de la cartera manual con la lectura de Siigo."""

    siigo_invoices = st.session_state.get("siigo_facturas", pd.DataFrame())
    if not isinstance(siigo_invoices, pd.DataFrame) or siigo_invoices.empty:
        st.markdown('<div class="surface">', unsafe_allow_html=True)
        render_section("Conciliación y auditoría", "Cruza las dos carteras factura por factura.")
        st.markdown(
            '<div class="empty-state"><strong>Primero consulta Siigo.</strong><br>'
            'Abre “Espejo Siigo” y carga datos reales o una muestra visual para comparar.</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return
    manual_invoices = db.listar_facturas(None if company == TODAS else company)
    filtered_siigo = siigo_invoices.copy()
    if company != TODAS and "empresa_codigo" in filtered_siigo.columns:
        filtered_siigo = filtered_siigo[
            filtered_siigo["empresa_codigo"].astype(str).str.upper().eq(company.upper())
        ].copy()
    # Una factura cuyo detalle no se leyó trae los impuestos en cero por
    # ausencia del dato, no porque valgan cero: compararla produciría
    # diferencias inventadas. Se excluye y se avisa cuántas quedaron fuera.
    sin_detalle = 0
    if "lectura_completa" in filtered_siigo.columns and not filtered_siigo.empty:
        completas = filtered_siigo["lectura_completa"].fillna(True).astype(bool)
        sin_detalle = int((~completas).sum())
        filtered_siigo = filtered_siigo[completas].copy()
    rows = _build_reconciliation(manual_invoices, filtered_siigo)
    if sin_detalle:
        st.info(
            f"{sin_detalle} factura(s) de Siigo quedan fuera de la comparación porque "
            "no se pudo leer su detalle. Vuelve a consultar para incluirlas."
        )

    st.markdown('<div class="surface">', unsafe_allow_html=True)
    render_section(
        "Conciliación y auditoría",
        "Cartera manual a la izquierda y lectura de Siigo a la derecha. Marcar una revisión no modifica Siigo.",
    )
    counts = {status: sum(1 for row in rows if row["estado"] == status) for status in ESTADO_META}
    kpis = st.columns(4)
    with kpis[0]:
        render_kpi_card("Cuadradas", str(counts["CUADRADO"]), "Saldo e impuestos coinciden")
    with kpis[1]:
        render_kpi_card(
            "Impuestos por revisar",
            str(counts["DIFERENCIA_IMPUESTOS"]),
            "El saldo coincide",
        )
    with kpis[2]:
        render_kpi_card(
            "Descuadres",
            str(counts["DESCUADRE"]),
            "Saldo diferente entre fuentes",
        )
    with kpis[3]:
        missing = counts["SOLO_MANUAL"] + counts["SOLO_SIIGO"]
        render_kpi_card(
            "Facturas faltantes",
            str(missing),
            "Solo presentes en una fuente",
            highlighted=True,
        )
    st.write("")
    table = pd.DataFrame(
        [
            {
                "Estado": ESTADO_META[row["estado"]][0],
                "Empresa": row["empresa_codigo"],
                "Factura": row["factura"],
                "Cliente": row["cliente"],
                "Saldo manual": format_currency(row["manual"]["saldo_cop"])
                if row["manual"]
                else "—",
                "Saldo Siigo": format_currency(row["siigo"].get("saldo_siigo"))
                if row["siigo"]
                else "—",
                "Dif. saldo": _format_difference(row["dif_saldo"]),
                "Dif. IVA": _format_difference(row["dif_iva"]),
                "Dif. retefuente": _format_difference(row["dif_retefuente"]),
                "Dif. ICA": _format_difference(row["dif_ica"]),
            }
            for row in rows
        ]
    )
    if not table.empty:
        st.dataframe(table, width="stretch", hide_index=True)
        by_option = {
            f"{row['empresa_codigo']} · {row['factura']} · {ESTADO_META[row['estado']][0]}": row
            for row in rows
        }
        selection = st.selectbox("Abrir comparación", list(by_option), key="conciliacion_factura")
        row = by_option[selection]
        st.write("")
        st.markdown(_status_badge(row["estado"]), unsafe_allow_html=True)
        left, right = st.columns(2)
        with left:
            _render_comparison_side("Cartera manual", "manual", row["manual"])
        with right:
            _render_comparison_side("Cartera Siigo", "siigo", row["siigo"])
        observation = st.text_area(
            "Observación de revisión",
            placeholder="Qué se verificó, qué falta por corregir o cuál es la siguiente acción.",
            key=f"observacion_{row['empresa_codigo']}_{row['factura_clave']}",
            max_chars=1500,
        )
        if st.button("Marcar revisión", type="primary"):
            try:
                db.guardar_revision_conciliacion(
                    empresa_codigo=row["empresa_codigo"],
                    factura_clave=row["factura_clave"],
                    estado=row["estado"],
                    observacion=observation,
                    manual=row["manual"],
                    siigo=row["siigo"],
                )
            except db.ErrorCartera as exc:
                st.error(str(exc))
            else:
                st.success("Revisión guardada en el historial interno.")
    else:
        st.markdown(
            '<div class="empty-state"><strong>No hay facturas para conciliar.</strong><br>'
            'Registra una factura manual o amplía la lectura de Siigo.</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


__all__ = ["render_reconciliation"]
