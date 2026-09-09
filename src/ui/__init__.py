"""Primitivas de presentación reutilizables de NOVASALUM.

Este paquete no contiene reglas contables ni acceso a datos. Reúne los estilos
y pequeños componentes que comparten las vistas de la aplicación.
"""

from .components import (
    EMPRESAS,
    ESTADO_META,
    TODAS,
    activity_summary,
    as_integer,
    company_label,
    company_name,
    filter_invoices,
    format_currency,
    format_date,
    invoice_label,
    plates_html,
    render_kpi_card,
    render_section,
    short_text,
    status_badge,
)
from .styles import apply_global_styles

__all__ = [
    "EMPRESAS",
    "ESTADO_META",
    "TODAS",
    "activity_summary",
    "apply_global_styles",
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
