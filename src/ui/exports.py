"""Descargas bajo demanda: una instantánea de la vista sin escribir datos."""

import datetime as dt
from functools import partial

import streamlit as st

from src.exportacion import crear_excel


def render_excel_export(rows: list[dict], *, source: str, scope: str, source_note: str = "") -> None:
    st.download_button(
        "Descargar Excel por cliente",
        data=partial(crear_excel, [dict(r) for r in rows], origen=source,
                     fecha_corte=dt.date.today(), alcance=scope, fuente=source_note),
        file_name=f"NOVASALUM_{source}_{dt.date.today():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"exportar_{source}", on_click="ignore", disabled=not rows, width="stretch",
        help="Resumen y una hoja por cliente, con fórmulas y desglose por empresa.",
    )
