"""Grilla compartida por las dos carteras.

Este módulo no conoce ninguna regla de negocio ni ninguna fuente de datos: solo
sabe pintar una tabla. Vive aparte para que la cartera manual y la cartera
Siigo se vean idénticas sin que ninguna dependa de la otra. Cambiar aquí el
estilo cambia las dos a la vez, que es justamente lo que se busca: las vistas
se envían como imagen y deben reconocerse como el mismo documento.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode


GRID_CSS = {
    ".ag-root-wrapper": {
        "border": "1px solid #d6dfeb",
        "border-radius": "12px",
        "overflow": "hidden",
    },
    ".ag-header": {
        "background-color": "#1e3a8a !important",
        "border-bottom": "1px solid #1e40af",
    },
    ".ag-header-cell, .ag-header-cell-label, .ag-header-cell-text, .ag-header-icon": {
        "color": "#ffffff !important",
        "font-size": ".875rem",
        "font-weight": "700",
    },
    ".ag-row": {"border-color": "#e7edf5"},
    ".ag-cell": {"font-size": ".875rem", "line-height": "38px"},
}

# Las cinco primeras etiquetas son las de la cartera manual y no se tocan: ya
# están en las imágenes que el dueño envía. Las siguientes son los estados que
# solo existen en la lectura contable de Siigo.
STATUS_RENDERER = JsCode("""
class StatusBadge {
    init(params) {
        const colors = {
            Pagada: ["#fef9c3", "#854d0e"],
            Abonada: ["#ffedd5", "#9a3412"],
            Pendiente: ["#e2e8f0", "#475569"],
            Vencida: ["#fee2e2", "#b91c1c"],
            Anulada: ["#e2e8f0", "#475569"],
            "Pago parcial": ["#ffedd5", "#9a3412"],
            "Por vencer": ["#e2e8f0", "#475569"],
            "Sin vencimiento": ["#e2e8f0", "#475569"],
            "Por revisar": ["#fee2e2", "#b91c1c"],
            "Sin leer": ["#fee2e2", "#b91c1c"]
        };
        const palette = colors[params.value] || colors.Pendiente;
        this.element = document.createElement("span");
        this.element.textContent = params.value || "";
        Object.assign(this.element.style, {
            display: "inline-flex", alignItems: "center", lineHeight: "22px",
            padding: "0 10px", borderRadius: "999px", fontSize: "12px",
            fontWeight: "600", backgroundColor: palette[0], color: palette[1]
        });
    }
    getGui() { return this.element; }
}
""")

# Columnas de dinero, alineadas a la derecha. Incluye los nombres del cuadro
# general y los del estado de cuenta por cliente, en las dos carteras.
COLUMNAS_DERECHA = (
    "Subtotal",
    "IVA",
    "Retefuente",
    "ICA",
    "Abonos",
    "Descuento",
    "Saldo",
    "Sub valor factura",
    "Impuestos",
    "Retención",
    "Abono",
    "Saldo pendiente",
)


def render_grid(
    table: pd.DataFrame,
    *,
    key: str,
    edit_on_double_click: bool = False,
    on_row_event: JsCode | None = None,
    on_cell_click: JsCode | None = None,
    click_event_name: str | None = None,
    column_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Muestra una tabla de librería con cabecera azul y menú tipo Excel.

    ``on_row_event`` solo lo usa la cartera manual para abrir la edición con
    doble clic. La cartera Siigo nunca lo pasa: es de solo consulta.

    ``on_cell_click`` responde al clic sencillo (y a Enter) con el evento
    ``click_event_name``; lo usa la tabla de clientes para abrir el detalle.
    ``column_config`` ajusta columnas puntuales (anchos fijos, por ejemplo)
    sin que este módulo conozca ninguna regla de negocio.
    """

    builder = GridOptionsBuilder.from_dataframe(table)
    builder.configure_default_column(
        resizable=True,
        sortable=True,
        filter=True,
        minWidth=115,
    )
    if "Detalle del servicio" in table.columns:
        builder.configure_column("Detalle del servicio", minWidth=250)
    if "Cliente" in table.columns:
        builder.configure_column("Cliente", minWidth=210)
    if "_factura_id" in table.columns:
        builder.configure_column("_factura_id", hide=True, suppressColumnsToolPanel=True)
    if "Estado" in table.columns:
        builder.configure_column(
            "Estado", pinned="right", lockPinned=True, width=125, minWidth=125,
            cellRenderer=STATUS_RENDERER,
        )
    if "Días en cartera" in table.columns:
        builder.configure_column(
            "Días en cartera", pinned="right", lockPinned=True, width=145, minWidth=145,
            cellStyle={"textAlign": "right", "fontWeight": "700"},
        )
    for name in COLUMNAS_DERECHA:
        if name in table.columns:
            builder.configure_column(name, cellStyle={"textAlign": "right"})
    if column_config:
        # Después de las columnas comunes, para que el ajuste puntual gane.
        for nombre, config in column_config.items():
            if nombre in table.columns:
                builder.configure_column(nombre, **config)
    builder.configure_grid_options(
        animateRows=False,
        headerHeight=42,
        rowHeight=38,
        suppressCellFocus=not (edit_on_double_click or on_cell_click is not None),
        suppressMovableColumns=True,
    )
    if edit_on_double_click and on_row_event is not None:
        builder.configure_grid_options(
            getRowId=JsCode("function(params) { return String(params.data._factura_id); }"),
            onCellDoubleClicked=on_row_event,
            onCellKeyDown=on_row_event,
        )
    elif on_cell_click is not None:
        builder.configure_grid_options(
            onCellClicked=on_cell_click,
            onCellKeyDown=on_cell_click,
        )
    result = AgGrid(
        table,
        gridOptions=builder.build(),
        height=max(120, 50 + 38 * len(table)),
        fit_columns_on_grid_load=False,
        update_mode=GridUpdateMode.NO_UPDATE,
        update_on=(
            ["invoiceEditRequested"] if edit_on_double_click
            else [click_event_name] if click_event_name
            else []
        ),
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        theme="alpine",
        custom_css=GRID_CSS,
        key=key,
    )
    return result.event_data


__all__ = ["COLUMNAS_DERECHA", "GRID_CSS", "STATUS_RENDERER", "render_grid"]
