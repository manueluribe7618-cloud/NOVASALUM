"""Vista operativa de la cartera digitada manualmente.

Este módulo agrupa la interfaz de facturas y abonos de la cartera manual. La
persistencia y las reglas de integridad financiera permanecen en
``src.database``; aquí solo se compone la experiencia de Streamlit.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

from src import database as db
from src.ui.components import (
    EMPRESAS,
    ESTADO_META,
    TODAS,
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


BALANCE_FILTERS = ("Todos", "Con saldo pendiente", "Saldo en cero")
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


@dataclass(frozen=True)
class ManualFilters:
    """Criterios de lectura de la tabla de cartera, sin modificar los datos."""

    term: str
    customers: tuple[tuple[str, int], ...]
    states: tuple[str, ...]
    date_range: tuple[dt.date, dt.date] | None
    balance: str


def _render_kpis(company: str) -> None:
    """Muestra el resumen financiero de la cartera manual seleccionada."""

    summary = db.resumen_cartera(None if company == TODAS else company)
    columns = st.columns(3)
    with columns[0]:
        render_kpi_card(
            "Total facturado",
            format_currency(summary["total_facturado_cop"]),
            f"{summary['facturas_pendientes']} factura(s) con saldo",
        )
    with columns[1]:
        render_kpi_card(
            "Abonos recibidos",
            format_currency(summary["total_abonos_cop"]),
            "Pagos aplicados a facturas manuales",
        )
    with columns[2]:
        render_kpi_card(
            "Saldo pendiente",
            format_currency(summary["saldo_cartera_cop"]),
            f"{summary['facturas_vencidas']} factura(s) vencida(s)",
            highlighted=True,
        )


def _invoices_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convierte las facturas de persistencia al formato visible de la tabla."""

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "Factura": row["factura"],
                "Fecha": format_date(row["fecha"]),
                "Cliente": row["cliente"],
                "Detalle del servicio": short_text(row["descripcion"]),
                "Placas": str(row["placas"] or "—").replace(",", " ·"),
                "Subtotal": format_currency(row["subtotal_cop"]),
                "IVA": format_currency(row["iva_cop"]),
                "Retefuente": format_currency(row["retefuente_cop"]),
                "ICA": format_currency(row["ica_cop"]),
                "Abonos": format_currency(row["abonos_cop"]),
                "Saldo": format_currency(row["saldo_cop"]),
                "Estado": ESTADO_META[row["estado"]][0],
            }
        )
    return pd.DataFrame(output)


def _render_grid(table: pd.DataFrame, *, key: str) -> None:
    """Muestra una tabla de librería con cabecera azul y menú tipo Excel."""

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
    builder.configure_grid_options(
        animateRows=False,
        headerHeight=42,
        rowHeight=38,
        suppressCellFocus=True,
        suppressMovableColumns=True,
    )
    AgGrid(
        table,
        gridOptions=builder.build(),
        height=max(120, 50 + 38 * len(table)),
        fit_columns_on_grid_load=False,
        update_mode=GridUpdateMode.NO_UPDATE,
        enable_enterprise_modules=False,
        theme="alpine",
        custom_css=GRID_CSS,
        key=key,
    )


def _customer_options(
    invoices: list[dict[str, Any]],
) -> dict[str, tuple[str, int]]:
    """Prepara clientes registrados para el panel de filtros compacto."""

    options: dict[str, tuple[str, int]] = {}
    for invoice in invoices:
        company = str(invoice["empresa_codigo"])
        customer_id = int(invoice["cliente_id"])
        label = f"{invoice['cliente']} · {company}"
        options[label] = (company, customer_id)
    return dict(sorted(options.items(), key=lambda item: item[0].casefold()))


def _date_limits(invoices: list[dict[str, Any]]) -> tuple[dt.date, dt.date] | None:
    """Obtiene el rango completo de fechas disponible para el filtro."""

    dates = [dt.date.fromisoformat(str(row["fecha"])[:10]) for row in invoices]
    return (min(dates), max(dates)) if dates else None


def _clear_manual_filters() -> None:
    """Restablece los filtros de lectura sin tocar facturas ni abonos."""

    for key in (
        "filtro_facturas_manual",
        "filtro_clientes_manual",
        "filtro_estados_manual",
        "filtro_fechas_manual",
        "filtro_saldo_manual",
    ):
        st.session_state.pop(key, None)
    st.session_state["filtro_empresa_manual"] = TODAS


def _reset_customers_for_company() -> None:
    """Evita conservar clientes que pertenecen a otra empresa filtrada."""

    st.session_state["filtro_clientes_manual"] = []


def _filter_count(date_limits: tuple[dt.date, dt.date] | None) -> int:
    """Cuenta filtros activos para informar sin añadir ruido visual."""

    active = 0
    if st.session_state.get("filtro_empresa_manual", TODAS) != TODAS:
        active += 1
    if st.session_state.get("filtro_clientes_manual", []):
        active += 1
    if st.session_state.get("filtro_estados_manual", []):
        active += 1
    if st.session_state.get("filtro_saldo_manual", BALANCE_FILTERS[0]) != BALANCE_FILTERS[0]:
        active += 1
    selected_dates = st.session_state.get("filtro_fechas_manual")
    if date_limits and isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        active += tuple(selected_dates) != date_limits
    return active


def _render_compact_filters(
    invoices: list[dict[str, Any]],
    company: str,
) -> ManualFilters:
    """Muestra búsqueda y un único panel de filtros, inspirado en Excel."""

    customer_options = _customer_options(invoices)
    date_limits = _date_limits(invoices)
    state_options = tuple(
        state
        for state in ("PENDIENTE", "ABONADA", "VENCIDA", "PAGADA")
        if any(row["estado"] == state for row in invoices)
    )
    current_count = _filter_count(date_limits)
    search_column, filters_column = st.columns([3.8, 1])
    with search_column:
        term = st.text_input(
            "Buscar en la cartera",
            placeholder="Factura, cliente, placa o detalle",
            key="filtro_facturas_manual",
        )
    with filters_column:
        with st.popover(
            f"Filtros · {current_count}" if current_count else "Filtros",
            use_container_width=True,
        ):
            st.caption("Refina la tabla sin llenar la vista de segmentadores.")
            st.selectbox(
                "Empresa",
                [TODAS, *EMPRESAS],
                index=[TODAS, *EMPRESAS].index(company),
                format_func=company_label,
                key="filtro_empresa_manual",
                on_change=_reset_customers_for_company,
            )
            selected_labels = st.multiselect(
                "Clientes",
                list(customer_options),
                help="Puedes escribir para buscar uno o varios clientes registrados.",
                key="filtro_clientes_manual",
            )
            states = st.multiselect(
                "Estado",
                state_options,
                format_func=lambda state: ESTADO_META[state][0],
                key="filtro_estados_manual",
            )
            selected_dates: tuple[dt.date, dt.date] | None = None
            if date_limits:
                selected_date_value = st.date_input(
                    "Fecha de emisión",
                    value=date_limits,
                    min_value=date_limits[0],
                    max_value=date_limits[1],
                    key="filtro_fechas_manual",
                )
                if isinstance(selected_date_value, (tuple, list)) and len(selected_date_value) == 2:
                    selected_dates = (selected_date_value[0], selected_date_value[1])
            balance = st.selectbox(
                "Saldo",
                BALANCE_FILTERS,
                key="filtro_saldo_manual",
            )
            st.button(
                "Limpiar filtros",
                use_container_width=True,
                on_click=_clear_manual_filters,
            )

    return ManualFilters(
        term=term,
        customers=tuple(customer_options[label] for label in selected_labels),
        states=tuple(states),
        date_range=selected_dates,
        balance=balance,
    )


def _filter_rows(
    invoices: list[dict[str, Any]],
    filters: ManualFilters,
) -> list[dict[str, Any]]:
    """Aplica los criterios de la interfaz a una copia de lectura de facturas."""

    rows = filter_invoices(invoices, filters.term)
    if filters.customers:
        selected_customers = set(filters.customers)
        rows = [
            row
            for row in rows
            if (str(row["empresa_codigo"]), int(row["cliente_id"])) in selected_customers
        ]
    if filters.states:
        rows = [row for row in rows if row["estado"] in filters.states]
    if filters.date_range:
        start, end = filters.date_range
        rows = [
            row
            for row in rows
            if start <= dt.date.fromisoformat(str(row["fecha"])[:10]) <= end
        ]
    if filters.balance == "Con saldo pendiente":
        rows = [row for row in rows if int(row["saldo_cop"]) > 0]
    elif filters.balance == "Saldo en cero":
        rows = [row for row in rows if int(row["saldo_cop"]) == 0]
    return rows


def _filter_customers(
    invoices: list[dict[str, Any]],
    customers: tuple[tuple[str, int], ...],
) -> list[dict[str, Any]]:
    """Limita el resumen por cliente sin alterar el saldo total que debe."""

    if not customers:
        return invoices
    selected_customers = set(customers)
    return [
        invoice
        for invoice in invoices
        if (str(invoice["empresa_codigo"]), int(invoice["cliente_id"])) in selected_customers
    ]


def _customer_debt_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Agrupa el saldo pendiente por cliente, aun si debe a varias empresas."""

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if int(row["saldo_cop"]) <= 0:
            continue
        name = str(row["cliente"]).strip()
        key = name.casefold()
        customer = grouped.setdefault(
            key,
            {
                "Cliente": name,
                "Empresas": [],
                "Facturas con saldo": 0,
                "_saldo": 0,
            },
        )
        company = str(row["empresa_codigo"])
        if company not in customer["Empresas"]:
            customer["Empresas"].append(company)
        customer["Facturas con saldo"] += 1
        customer["_saldo"] += int(row["saldo_cop"])

    visible_rows = []
    for customer in grouped.values():
        visible_rows.append(
            {
                "Cliente": customer["Cliente"],
                "Saldo pendiente": format_currency(customer["_saldo"]),
                "Facturas con saldo": customer["Facturas con saldo"],
                "Empresas": " · ".join(sorted(customer["Empresas"])),
                "_saldo": customer["_saldo"],
            }
        )
    return pd.DataFrame(
        sorted(visible_rows, key=lambda row: (-int(row["_saldo"]), row["Cliente"].casefold()))
    )


def _company_scope(company: str) -> str:
    return "todas las empresas" if company == TODAS else company_name(company)


def _render_customer_debt(company: str, invoices: list[dict[str, Any]]) -> None:
    """Muestra una segunda tabla con el saldo que debe cada cliente."""

    table = _customer_debt_table(invoices)
    render_section(
        "Clientes y saldo pendiente",
        f"{len(table)} cliente(s) con deuda en {_company_scope(company)}.",
    )
    st.write("")
    if table.empty:
        st.markdown(
            '<div class="empty-state"><strong>No hay clientes con saldo pendiente.</strong><br>'
            'Elige otro cliente o registra una factura para comenzar.</div>',
            unsafe_allow_html=True,
        )
    else:
        _render_grid(table.drop(columns="_saldo"), key="tabla_clientes_manual")


def _render_invoice_form(active_company: str, *, use_expander: bool) -> None:
    """Renderiza y procesa el formulario de creación de una factura manual."""

    container = (
        st.expander("＋ Registrar nueva factura", expanded=False)
        if use_expander
        else st.container()
    )
    with container:
        render_section(
            "Nueva factura manual",
            "Los valores se guardan como pesos enteros, sin centavos.",
        )
        available_companies = (
            [active_company] if active_company != TODAS else list(EMPRESAS)
        )
        with st.form("formulario_nueva_factura", clear_on_submit=True):
            company = st.selectbox(
                "Empresa",
                available_companies,
                format_func=(
                    lambda code: f"{EMPRESAS[code]['prefijo']} · {EMPRESAS[code]['nombre']}"
                ),
            )
            column_a, column_b, column_c, column_d = st.columns(4)
            with column_a:
                prefix = st.text_input("Prefijo", value=EMPRESAS[company]["prefijo"]).upper()
            with column_b:
                number = st.text_input("Número de factura", placeholder="1079").upper()
            with column_c:
                issue_date = st.date_input("Fecha de emisión", value=dt.date.today())
            with column_d:
                due_date = st.date_input(
                    "Vencimiento",
                    value=dt.date.today() + dt.timedelta(days=30),
                )
            customer = st.text_input("Cliente", placeholder="Razón social o nombre")
            description = st.text_area(
                "Detalle del servicio",
                placeholder="Ruta, manifiesto, condición especial u observación operativa",
                max_chars=1000,
            )
            plates = st.text_input("Placas", placeholder="SOQ766, TAW897")
            amount_a, amount_b, amount_c, amount_d = st.columns(4)
            with amount_a:
                subtotal = st.number_input(
                    "Subtotal", min_value=0, step=1_000, value=0, format="%d"
                )
            with amount_b:
                iva = st.number_input("IVA", min_value=0, step=1_000, value=0, format="%d")
            with amount_c:
                retefuente = st.number_input(
                    "Retefuente", min_value=0, step=1_000, value=0, format="%d"
                )
            with amount_d:
                ica = st.number_input("ICA", min_value=0, step=1_000, value=0, format="%d")
            total = int(subtotal) + int(iva) - int(retefuente) - int(ica)
            st.caption(f"Total a cobrar: {format_currency(total)}")
            save = st.form_submit_button("Guardar factura", type="primary")
        if save:
            try:
                db.crear_factura(
                    {
                        "empresa_codigo": company,
                        "prefijo": prefix,
                        "numero": number,
                        "fecha": issue_date,
                        "vencimiento": due_date,
                        "cliente": customer,
                        "descripcion": description,
                        "placas": plates,
                        "subtotal_cop": subtotal,
                        "iva_cop": iva,
                        "retefuente_cop": retefuente,
                        "ica_cop": ica,
                    }
                )
            except db.ErrorCartera as exc:
                st.error(str(exc))
            else:
                st.success("Factura registrada.")
                st.rerun()


def _render_quick_edit(rows: list[dict[str, Any]], *, use_expander: bool) -> None:
    """Permite editar campos operativos o anular una factura existente."""

    if not rows:
        if not use_expander:
            st.info("No hay facturas disponibles para editar con este filtro.")
        return
    container = (
        st.expander("Editar factura en línea", expanded=False)
        if use_expander
        else st.container()
    )
    with container:
        render_section(
            "Ajustes rápidos",
            "Edita el detalle, las placas o los impuestos sin salir de la cartera.",
        )
        by_label = {invoice_label(row): row for row in rows}
        label = st.selectbox("Factura a editar", list(by_label), key="factura_edicion")
        invoice = by_label[label]
        columns = st.columns([1.55, 1.35])
        with columns[0]:
            st.markdown(
                f"""
                <div class="surface" style="margin-top:.25rem">
                  <div class="eyebrow">Factura seleccionada</div>
                  <div style="font-weight:800;font-size:1.1rem">{html.escape(invoice["factura"])}</div>
                  <div style="margin:.6rem 0">{status_badge(invoice["estado"])}</div>
                  <div style="font-size:.86rem;color:#64748b">{html.escape(invoice["cliente"])}</div>
                  <div style="margin-top:.65rem">{plates_html(invoice["placas"])}</div>
                  <div style="margin-top:.8rem;font-size:.86rem;color:#475569">{html.escape(invoice["descripcion"] or "Sin detalle")}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with columns[1]:
            editor_data = pd.DataFrame(
                [
                    {
                        "Detalle del servicio": invoice["descripcion"],
                        "Placas": invoice["placas"],
                        "Subtotal": int(invoice["subtotal_cop"]),
                        "IVA": int(invoice["iva_cop"]),
                        "Retefuente": int(invoice["retefuente_cop"]),
                        "ICA": int(invoice["ica_cop"]),
                    }
                ]
            )
            edited = st.data_editor(
                editor_data,
                hide_index=True,
                num_rows="fixed",
                key=f"editor_factura_{invoice['id']}",
                column_config={
                    "Detalle del servicio": st.column_config.TextColumn(width="large"),
                    "Placas": st.column_config.TextColumn(width="medium"),
                    "Subtotal": st.column_config.NumberColumn(min_value=0, step=1_000),
                    "IVA": st.column_config.NumberColumn(min_value=0, step=1_000),
                    "Retefuente": st.column_config.NumberColumn(min_value=0, step=1_000),
                    "ICA": st.column_config.NumberColumn(min_value=0, step=1_000),
                },
            )
            actions = st.columns([1, 1])
            with actions[0]:
                if st.button("Guardar cambios", type="primary", use_container_width=True):
                    edited_row = edited.iloc[0].to_dict()
                    try:
                        db.actualizar_campos_factura(
                            int(invoice["id"]),
                            {
                                "descripcion": edited_row["Detalle del servicio"],
                                "placas": edited_row["Placas"],
                                "subtotal_cop": edited_row["Subtotal"],
                                "iva_cop": edited_row["IVA"],
                                "retefuente_cop": edited_row["Retefuente"],
                                "ica_cop": edited_row["ICA"],
                            },
                        )
                    except db.ErrorCartera as exc:
                        st.error(str(exc))
                    else:
                        st.success("Cambios guardados.")
                        st.rerun()
            with actions[1]:
                if st.button("Anular factura", use_container_width=True):
                    try:
                        db.anular_factura(int(invoice["id"]))
                    except db.ErrorCartera as exc:
                        st.error(str(exc))
                    else:
                        st.success("Factura anulada. El registro continúa en auditoría.")
                        st.rerun()


def render_manual_portfolio(
    company: str,
    *,
    request_invoice: bool = False,
    request_edit: bool = False,
) -> None:
    """Renderiza la cartera manual para una empresa.

    Args:
        company: Código de empresa o ``TODAS``.
    """

    _render_kpis(company)
    st.write("")
    invoices = db.listar_facturas(None if company == TODAS else company)
    if request_invoice:
        show_invoice_dialog(company)
    if request_edit:
        show_edit_invoice_dialog(invoices)
    filters = _render_compact_filters(invoices, company)
    filtered = _filter_rows(invoices, filters)

    general_tab, customers_tab = st.tabs(["General", "Clientes y saldo pendiente"])
    with general_tab:
        render_section(
            f"Cartera manual · {company_name(company)}",
            f"{len(filtered)} factura(s) visible(s) · los saldos se actualizan al aplicar un abono.",
        )
        st.write("")
        if filtered:
            table = _invoices_table(filtered)
            _render_grid(table, key="tabla_cartera_general")
            st.caption(
                "Valores en pesos colombianos, sin centavos. Usa el menú de cada encabezado para ordenar o filtrar como en Excel."
            )
        else:
            st.markdown(
                '<div class="empty-state"><strong>No hay facturas para este filtro.</strong><br>'
                'Registra una factura nueva o carga una muestra para conocer el flujo.</div>',
                unsafe_allow_html=True,
            )
            if not db.hay_datos() and st.button("Cargar datos de demostración"):
                db.cargar_datos_demostracion()
                st.success("Muestra cargada. Puedes editarla, registrar abonos y revisar la conciliación.")
                st.rerun()
    with customers_tab:
        _render_customer_debt(company, _filter_customers(invoices, filters.customers))


@st.dialog("Registrar nueva factura", width="large")
def show_invoice_dialog(active_company: str) -> None:
    """Abre el registro de factura desde la cabecera, sin ocupar la tabla."""

    _render_invoice_form(active_company, use_expander=False)


@st.dialog("Editar factura", width="large")
def show_edit_invoice_dialog(invoices: list[dict[str, Any]]) -> None:
    """Abre la edición de una factura desde la cabecera."""

    _render_quick_edit(invoices, use_expander=False)


@st.dialog("Registrar abono", width="large")
def show_payment_dialog() -> None:
    """Abre el flujo de registro y aplicación de un abono manual.

    El pago puede distribuirse automáticamente por antigüedad (FIFO) o mediante
    importes digitados por factura. La operación final se valida y persiste en
    ``src.database``.
    """

    preferred_company = st.session_state.get("empresa_activa", TODAS)
    available_companies = (
        [preferred_company] if preferred_company != TODAS else list(EMPRESAS)
    )
    company = st.selectbox(
        "Empresa",
        available_companies,
        format_func=(
            lambda code: f"{EMPRESAS[code]['prefijo']} · {EMPRESAS[code]['nombre']}"
        ),
        key="abono_empresa",
    )
    customers = db.clientes_con_saldo(company)
    if not customers:
        st.info("Esta empresa no tiene facturas con saldo pendiente.")
        return
    customer_options = {
        f"{row['cliente']} · {format_currency(row['saldo_cop'])}": row
        for row in customers
    }
    customer_label = st.selectbox("Cliente", list(customer_options), key="abono_cliente")
    customer = customer_options[customer_label]
    information, payment = st.columns([1, 1])
    with information:
        date = st.date_input("Fecha del pago", value=dt.date.today(), key="abono_fecha")
        reference = st.text_input(
            "Referencia bancaria",
            placeholder="Recibo, transferencia o comprobante",
            key="abono_referencia",
        )
    with payment:
        amount = st.number_input(
            "Monto recibido",
            min_value=0,
            value=0,
            step=1_000,
            format="%d",
            key="abono_monto",
        )
        fifo = st.toggle(
            "Aplicar automáticamente a las facturas más antiguas (FIFO)",
            value=True,
            key="abono_fifo",
        )
    invoices = db.facturas_pendientes_cliente(company, int(customer["cliente_id"]))
    applications: list[dict[str, Any]]
    surplus = 0
    if fifo:
        applications, surplus = db.previsualizar_fifo(invoices, amount or 1)
    else:
        base = pd.DataFrame(
            [
                {
                    "Factura": invoice["factura"],
                    "Fecha": format_date(invoice["fecha"]),
                    "Saldo actual": format_currency(invoice["saldo_cop"]),
                    "Aplicar (COP)": 0,
                    "_id": int(invoice["id"]),
                }
                for invoice in invoices
            ]
        )
        edited = st.data_editor(
            base,
            hide_index=True,
            width="stretch",
            disabled=["Factura", "Fecha", "Saldo actual", "_id"],
            column_config={
                "Aplicar (COP)": st.column_config.NumberColumn(min_value=0, step=1_000),
                "_id": None,
            },
            key=f"abono_manual_{company}_{customer['cliente_id']}",
        )
        applications = [
            {"factura_id": int(row["_id"]), "monto_cop": as_integer(row["Aplicar (COP)"])}
            for _, row in edited.iterrows()
            if as_integer(row["Aplicar (COP)"]) > 0
        ]
        surplus = max(
            0,
            as_integer(amount) - sum(as_integer(application["monto_cop"]) for application in applications),
        )

    by_id = {int(invoice["id"]): invoice for invoice in invoices}
    preview_rows = []
    for application in applications:
        invoice = by_id[int(application["factura_id"])]
        applied = as_integer(application["monto_cop"])
        balance_after = as_integer(invoice["saldo_cop"]) - applied
        preview_rows.append(
            {
                "Factura": invoice["factura"],
                "Saldo antes": format_currency(invoice["saldo_cop"]),
                "Aplicar": format_currency(applied),
                "Saldo después": format_currency(balance_after),
                "Estado": "● Pagada" if balance_after == 0 else "● Abono parcial",
            }
        )
    st.markdown("##### Vista previa de aplicación")
    if preview_rows:
        st.dataframe(pd.DataFrame(preview_rows), width="stretch", hide_index=True)
    else:
        st.caption("Ingresa un monto para ver cómo se distribuirá el pago.")
    total_applied = sum(as_integer(application["monto_cop"]) for application in applications)
    payment_summary = st.columns(3)
    payment_summary[0].metric("Recibido", format_currency(amount))
    payment_summary[1].metric("Aplicado", format_currency(total_applied))
    payment_summary[2].metric("Saldo a favor", format_currency(surplus))
    if surplus:
        st.info(
            "El excedente queda registrado como saldo a favor del cliente para revisión posterior."
        )
    if st.button("Aplicar abono", type="primary", use_container_width=True):
        try:
            db.registrar_abono(
                empresa_codigo=company,
                cliente_id=int(customer["cliente_id"]),
                fecha=date,
                referencia=reference,
                monto_cop=amount,
                aplicaciones=applications,
            )
        except db.ErrorCartera as exc:
            st.error(str(exc))
        else:
            st.success("Abono aplicado y registrado en auditoría.")
            st.rerun()


__all__ = [
    "render_manual_portfolio",
    "show_edit_invoice_dialog",
    "show_invoice_dialog",
    "show_payment_dialog",
]
