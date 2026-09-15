"""Componentes de presentación compartidos por las vistas de cartera."""

from __future__ import annotations

import datetime as dt
import html
import json
from collections.abc import Mapping
from typing import Any

import pandas as pd
import streamlit as st

from src import database as db
from src.formato import fmt_cop


EMPRESAS = db.EMPRESAS
TODAS = "TODAS"
ESTADO_META = {
    "PAGADA": ("Pagada", "verde"),
    "ABONADA": ("Abonada", "amarillo"),
    "PENDIENTE": ("Pendiente", "azul"),
    "VENCIDA": ("Vencida", "rojo"),
    "ANULADA": ("Anulada", "gris"),
    "CUADRADO": ("Cuadrado", "verde"),
    "DIFERENCIA_IMPUESTOS": ("Diferencia impuestos", "amarillo"),
    "DESCUADRE": ("Descuadre", "rojo"),
    "DATO_INCOMPLETO": ("Falta dato de Siigo", "gris"),
    "SOLO_MANUAL": ("Solo manual", "rojo"),
    "SOLO_SIIGO": ("Solo Siigo", "rojo"),
}


def format_currency(value: Any) -> str:
    """Da formato a un importe COP igual que la interfaz existente."""

    return fmt_cop(value, dash_zero=False)


def as_integer(value: Any) -> int:
    """Convierte valores de interfaz a pesos enteros de forma tolerante."""

    try:
        if pd.isna(value):
            return 0
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def format_date(value: Any) -> str:
    """Muestra una fecha ISO como día/mes/año."""

    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return dt.date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(value)


def short_text(value: Any, limit: int = 48) -> str:
    """Acorta un texto para las tablas sin romper palabras visualmente."""

    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit - 1].rstrip()}…"


def status_badge(status: str) -> str:
    """Devuelve la etiqueta HTML del estado de una factura o conciliación."""

    label, tone = ESTADO_META.get(status, (status.replace("_", " ").title(), "gris"))
    return f'<span class="badge badge-{tone}">{html.escape(label)}</span>'


def plates_html(plates: Any) -> str:
    """Devuelve las placas como pequeñas etiquetas HTML."""

    items = [part.strip() for part in str(plates or "").split(",") if part.strip()]
    if not items:
        return '<span style="color:#94a3b8">Sin placas</span>'
    return "".join(f'<span class="plate">{html.escape(plate)}</span>' for plate in items)


def company_name(code: str) -> str:
    """Obtiene el nombre visible de una empresa, incluida la opción global."""

    if code == TODAS:
        return "Todas las empresas"
    return db.EMPRESAS[code]["nombre"]


def company_label(code: str) -> str:
    """Obtiene la etiqueta compacta usada por los selectores de empresa."""

    if code == TODAS:
        return "◈ Todas"
    data = db.EMPRESAS[code]
    return f"{data['prefijo']} · {code}"


def render_section(title: str, subtitle: str | None = None) -> None:
    """Renderiza el título y subtítulo de una superficie visual."""

    st.markdown(f'<div class="surface-title">{html.escape(title)}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(
            f'<div class="surface-subtitle">{html.escape(subtitle)}</div>',
            unsafe_allow_html=True,
        )


def render_kpi_card(
    label: str,
    value: str,
    detail: str,
    *,
    highlighted: bool = False,
) -> None:
    """Renderiza una tarjeta KPI con el mismo marcado visual de la app."""

    css_class = " saldo" if highlighted else ""
    st.markdown(
        f"""
        <div class="kpi-card{css_class}">
          <div class="kpi-label">{html.escape(label)}</div>
          <div class="kpi-value">{html.escape(value)}</div>
          <div class="kpi-detail">{html.escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def invoice_label(row: Mapping[str, Any]) -> str:
    """Construye la etiqueta de factura usada en los selectores."""

    return f"{row['factura']} · {row['cliente']} · {format_currency(row['saldo_cop'])}"


def filter_invoices(rows: list[dict[str, Any]], term: str) -> list[dict[str, Any]]:
    """Filtra facturas manuales por sus datos operativos visibles."""

    query = str(term or "").strip().casefold()
    if not query:
        return rows
    fields = ("factura", "cliente", "descripcion", "placas")
    return [
        row
        for row in rows
        if query in " ".join(str(row.get(field, "")) for field in fields).casefold()
    ]


def activity_summary(value: Any) -> str:
    """Resume el detalle JSON de un evento de auditoría para la barra lateral."""

    try:
        data = json.loads(value)
    except Exception:
        return str(value)[:85]
    if not isinstance(data, Mapping):
        return str(data)[:85]
    invoice = data.get("factura")
    amount = data.get("monto_cop")
    if invoice:
        return f"Factura {invoice}"
    if amount:
        return f"Abono por {format_currency(amount)}"
    return "Movimiento registrado"


__all__ = [
    "EMPRESAS",
    "ESTADO_META",
    "TODAS",
    "activity_summary",
    "as_integer",
    "company_label",
    "company_name",
    "filter_invoices",
    "format_currency",
    "format_date",
    "invoice_label",
    "plates_html",
    "render_kpi_card",
    "render_section",
    "short_text",
    "status_badge",
]
