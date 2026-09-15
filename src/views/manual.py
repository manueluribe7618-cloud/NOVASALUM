"""Vista operativa de la cartera digitada manualmente.

Este módulo agrupa la interfaz de facturas y abonos de la cartera manual. La
persistencia y las reglas de integridad financiera permanecen en
``src.database``; aquí solo se compone la experiencia de Streamlit.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from src import database as db
from src.formato import parse_cop
from src.taxes import TAX_COMPONENTS, TAX_DEFAULTS, calculate_tax
from src.ui.grid import render_grid
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
MONTH_LABELS = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}
REQUEST_INVOICE_EDIT = JsCode("""
function(params) {
    if (params.type === "cellKeyDown" && params.event.key !== "Enter") return;
    if (!params.data || !params.data._factura_id) return;
    params.api.dispatchEvent({
        type: "invoiceEditRequested",
        data: {
            invoice_id: params.data._factura_id,
            request_id: crypto.randomUUID()
        }
    });
}
""")


@dataclass(frozen=True)
class ManualFilters:
    """Criterios de lectura de la tabla de cartera, sin modificar los datos."""

    term: str
    customers: tuple[str, ...]
    states: tuple[str, ...]
    year: int | None
    month: int | None
    balance: str


def _render_kpis(invoices: list[dict[str, Any]]) -> None:
    """Muestra el resumen financiero de la cartera manual seleccionada."""

    summary = {
        "total_facturado_cop": sum(int(row["total_cop"]) for row in invoices),
        "total_abonos_cop": sum(int(row["abonos_cop"]) for row in invoices),
        "saldo_cartera_cop": sum(int(row["saldo_cop"]) for row in invoices),
        "facturas_pendientes": sum(int(row["saldo_cop"]) > 0 for row in invoices),
        "facturas_vencidas": sum(row["estado"] == "VENCIDA" for row in invoices),
    }
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
                "_factura_id": int(row["id"]),
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
                "Descuento": (
                    format_currency(row["descuento_cop"])
                    if int(row.get("descuento_cop", 0) or 0) else ""
                ),
                "Saldo": format_currency(row["saldo_cop"]),
                "Estado": ESTADO_META[row["estado"]][0],
            }
        )
    return pd.DataFrame(output)


def _render_grid(
    table: pd.DataFrame, *, key: str, edit_on_double_click: bool = False
) -> dict[str, Any] | None:
    """Muestra la tabla compartida; el doble clic para editar es solo manual."""

    return render_grid(
        table,
        key=key,
        edit_on_double_click=edit_on_double_click,
        on_row_event=REQUEST_INVOICE_EDIT if edit_on_double_click else None,
    )


def _consume_invoice_edit_event(
    event: dict[str, Any] | None, invoices: list[dict[str, Any]]
) -> int | None:
    """Consume cada gesto una vez y busca por ID, nunca por posición de fila."""

    if not event or event.get("type") != "invoiceEditRequested":
        return None
    data = event.get("data") or {}
    request_id = data.get("request_id")
    if not request_id or request_id == st.session_state.get("ultima_edicion_grilla"):
        return None
    st.session_state["ultima_edicion_grilla"] = request_id
    try:
        invoice_id = int(data["invoice_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if not any(int(row["id"]) == invoice_id for row in invoices):
        return None
    # Cada apertura comienza con los valores guardados, incluso si se cerró
    # previamente un borrador sin guardar de esta misma factura.
    for key in list(st.session_state):
        if key.startswith(f"editar_factura_{invoice_id}_") or key == f"editor_factura_{invoice_id}":
            del st.session_state[key]
    return invoice_id


def _customer_options(
    invoices: list[dict[str, Any]],
) -> dict[str, str]:
    """Prepara razones sociales únicas para el panel de filtros compacto.

    El mismo cliente puede existir en las tres empresas con registros
    separados. Aquí se agrupa por razón social para que, al buscarlo, se vea
    su cartera completa sin importar cuál empresa emitió cada factura.
    """

    options: dict[str, str] = {}
    seen: set[str] = set()
    for invoice in invoices:
        name = str(invoice["cliente"]).strip()
        key = name.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        options[name] = key
    return dict(sorted(options.items(), key=lambda item: item[0].casefold()))


def _invoice_date(invoice: dict[str, Any]) -> dt.date:
    """Convierte una fecha de persistencia a un objeto fecha de interfaz."""

    return dt.date.fromisoformat(str(invoice["fecha"])[:10])


def _available_years(invoices: list[dict[str, Any]]) -> tuple[int, ...]:
    """Devuelve los años facturados, de más reciente a más antiguo."""

    return tuple(sorted({_invoice_date(invoice).year for invoice in invoices}, reverse=True))


def _selected_period() -> tuple[int | None, int | None]:
    """Lee el período actual antes de dibujar los indicadores."""

    year = st.session_state.get("filtro_anio_manual")
    month = st.session_state.get("filtro_mes_manual")
    return (
        year if isinstance(year, int) else None,
        month if isinstance(month, int) and month in MONTH_LABELS else None,
    )


def _filter_period(
    invoices: list[dict[str, Any]],
    year: int | None,
    month: int | None,
) -> list[dict[str, Any]]:
    """Limita facturas por año y mes sin modificar ningún saldo."""

    return [
        invoice
        for invoice in invoices
        if (year is None or _invoice_date(invoice).year == year)
        and (month is None or _invoice_date(invoice).month == month)
    ]


def _clear_manual_filters() -> None:
    """Restablece los filtros de lectura sin tocar facturas ni abonos."""

    for key in (
        "filtro_facturas_manual",
        "filtro_clientes_manual",
        "filtro_estados_manual",
        "filtro_anio_manual",
        "filtro_mes_manual",
        "filtro_saldo_manual",
    ):
        st.session_state.pop(key, None)
    st.session_state["filtro_empresa_manual"] = TODAS


def _reset_customers_for_company() -> None:
    """Evita conservar clientes que pertenecen a otra empresa filtrada."""

    st.session_state["filtro_clientes_manual"] = []


def _filter_count() -> int:
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
    if st.session_state.get("filtro_anio_manual") is not None:
        active += 1
    if st.session_state.get("filtro_mes_manual") is not None:
        active += 1
    return active


def _render_compact_filters(
    invoices: list[dict[str, Any]],
    company: str,
) -> ManualFilters:
    """Muestra búsqueda y un único panel de filtros, inspirado en Excel."""

    customer_options = _customer_options(invoices)
    years = _available_years(invoices)
    state_options = tuple(
        state
        for state in ("PENDIENTE", "ABONADA", "VENCIDA", "PAGADA")
        if any(row["estado"] == state for row in invoices)
    )
    current_count = _filter_count()
    search_column, filters_column = st.columns([3.8, 1], vertical_alignment="bottom")
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
            stored_customers = st.session_state.get("filtro_clientes_manual")
            if stored_customers:
                # Descarta selecciones que ya no existen en el alcance actual
                # (o guardadas con el formato anterior "Cliente · EMPRESA").
                valid_customers = [
                    label for label in stored_customers if label in customer_options
                ]
                if len(valid_customers) != len(stored_customers):
                    st.session_state["filtro_clientes_manual"] = valid_customers
            selected_labels = st.multiselect(
                "Clientes",
                list(customer_options),
                help="Busca por razón social; se muestra su cartera en todas las empresas.",
                placeholder="Selecciona clientes",
                key="filtro_clientes_manual",
            )
            states = st.multiselect(
                "Estado",
                state_options,
                format_func=lambda state: ESTADO_META[state][0],
                placeholder="Selecciona estados",
                key="filtro_estados_manual",
            )
            year = st.selectbox(
                "Año de facturación",
                [None, *years],
                format_func=lambda value: "Todos los años" if value is None else str(value),
                key="filtro_anio_manual",
            )
            month = st.selectbox(
                "Mes de facturación",
                [None, *MONTH_LABELS],
                format_func=lambda value: "Todos los meses"
                if value is None
                else MONTH_LABELS[value],
                key="filtro_mes_manual",
            )
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
        year=year,
        month=month,
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
            if str(row["cliente"]).strip().casefold() in selected_customers
        ]
    if filters.states:
        rows = [row for row in rows if row["estado"] in filters.states]
    rows = _filter_period(rows, filters.year, filters.month)
    if filters.balance == "Con saldo pendiente":
        rows = [row for row in rows if int(row["saldo_cop"]) > 0]
    elif filters.balance == "Saldo en cero":
        rows = [row for row in rows if int(row["saldo_cop"]) == 0]
    return rows


def _filter_customers(
    invoices: list[dict[str, Any]],
    customers: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Limita el resumen por cliente sin alterar el saldo total que debe."""

    if not customers:
        return invoices
    selected_customers = set(customers)
    return [
        invoice
        for invoice in invoices
        if str(invoice["cliente"]).strip().casefold() in selected_customers
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


def _statement_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Refleja el estado de cuenta que Finanzas envía en Excel, fila por fila.

    Mismas columnas y nombres de la hoja: los conceptos en cero quedan en
    blanco (como las celdas vacías del Excel) y el detalle va completo.
    """

    def _monto(valor: Any) -> str:
        return format_currency(valor) if int(valor) else ""

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "_factura_id": int(row["id"]),
                "Factura": row["factura"],
                "Fecha": format_date(row["fecha"]),
                "Detalle del servicio": str(row["descripcion"] or "").strip(),
                "Placas": str(row["placas"] or "—").replace(",", " ·"),
                "Sub valor factura": format_currency(row["subtotal_cop"]),
                "Impuestos": _monto(row["iva_cop"]),
                "Retención": _monto(row["retefuente_cop"]),
                "ICA": _monto(row["ica_cop"]),
                "Abono": _monto(row["abonos_cop"]),
                "Descuento": _monto(row.get("descuento_cop", 0) or 0),
                "Saldo pendiente": format_currency(row["saldo_cop"]),
            }
        )
    return pd.DataFrame(output)


def _request_payment_for(company: str, cliente_id: int) -> None:
    """Deja preseleccionados empresa y cliente para el diálogo de abono."""

    st.session_state["abono_preseleccion"] = {
        "empresa": str(company),
        "cliente_id": int(cliente_id),
    }
    # Se limpia el estado previo del diálogo para que la preselección mande.
    for key in ("abono_empresa", "abono_cliente"):
        st.session_state.pop(key, None)


def _render_customer_detail(
    invoices: list[dict[str, Any]],
    filters: ManualFilters,
) -> bool:
    """Muestra la cartera completa de un cliente, separada por empresa.

    El total combinado responde "cuánto me debe este cliente"; el desglose por
    empresa responde "dónde registro el abono y a cuáles facturas puede ir",
    porque cada abono pertenece a una sola empresa.

    Devuelve ``True`` si se pidió registrar un abono desde el detalle.
    """

    options = _customer_options(invoices)
    render_section(
        "Detalle del cliente",
        "El total combina las tres empresas; el desglose muestra dónde vive cada factura.",
    )
    if not options:
        st.caption("Todavía no hay clientes registrados en este alcance.")
        return False
    picker_key = "detalle_cliente_manual"
    labels = list(options)
    if st.session_state.get(picker_key) not in labels:
        st.session_state.pop(picker_key, None)
    default_index = None
    if picker_key not in st.session_state and len(filters.customers) == 1:
        selected_name = filters.customers[0]
        default_index = next(
            (position for position, label in enumerate(labels)
             if options[label] == selected_name),
            None,
        )
    selected_label = st.selectbox(
        "Cliente",
        labels,
        index=default_index,
        placeholder="Escribe o elige la razón social",
        key=picker_key,
        label_visibility="collapsed",
    )
    if not selected_label:
        st.caption("Elige un cliente para ver su cartera separada por empresa.")
        return False

    selected_name = options[selected_label]
    rows = [
        row for row in invoices
        if str(row["cliente"]).strip().casefold() == selected_name
    ]
    by_company: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_company.setdefault(str(row["empresa_codigo"]), []).append(row)
    ordered_companies = [code for code in EMPRESAS if code in by_company]
    ordered_companies += [code for code in by_company if code not in EMPRESAS]

    total_invoiced = sum(int(row["total_cop"]) for row in rows)
    total_paid = sum(int(row["abonos_cop"]) for row in rows)
    total_balance = sum(int(row["saldo_cop"]) for row in rows)
    st.caption(
        f"{len(rows)} factura(s) en {len(ordered_companies)} empresa(s). "
        "Cada abono se registra en una sola empresa y aplica solo a sus facturas."
    )

    payment_requested = False
    for code in ordered_companies:
        company_rows = by_company[code]
        company_balance = sum(int(row["saldo_cop"]) for row in company_rows)
        company_title = EMPRESAS[code]["nombre"] if code in EMPRESAS else code
        header_column, action_column = st.columns([3.2, 1], vertical_alignment="center")
        with header_column:
            st.markdown(f"**{selected_label} · {company_title}**")
        with action_column:
            if company_balance > 0 and st.button(
                "＋ Abono aquí",
                key=f"abono_detalle_{code}",
                use_container_width=True,
            ):
                _request_payment_for(code, int(company_rows[0]["cliente_id"]))
                payment_requested = True
        _render_grid(_statement_table(company_rows), key=f"tabla_detalle_cliente_{code}")
        st.markdown(
            f'<div class="statement-company-total">Saldo pendiente '
            f'{html.escape(company_title)}: {format_currency(company_balance)}</div>',
            unsafe_allow_html=True,
        )
        st.write("")
    st.markdown(
        '<div class="statement-total-row">'
        f'<span class="statement-total-context">Facturado {format_currency(total_invoiced)}'
        f' · Abonado {format_currency(total_paid)}</span>'
        f'<span class="statement-total-badge">SALDO EN CARTERA&nbsp;&nbsp;'
        f'{format_currency(total_balance)}</span></div>',
        unsafe_allow_html=True,
    )
    return payment_requested


def _render_tax_control(
    component: str,
    subtotal: int,
    *,
    key_prefix: str = "factura",
    existing_amount: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Configura un concepto tributario sin obligarlo para cada factura."""

    label = TAX_COMPONENTS[component]
    defaults = TAX_DEFAULTS[component]
    # Al editar, conservar el importe exacto hasta que se elija otra regla.
    default_mode = "VALOR_FIJO" if existing_amount else str(defaults["mode"])
    entry_modes = ("PORCENTAJE", "VALOR_FIJO", "NO_APLICA")
    entry_labels = {
        "PORCENTAJE": "Porcentaje (%)",
        "VALOR_FIJO": "Valor en pesos ($)",
        "NO_APLICA": "No aplica",
    }
    mode = st.radio(
        f"{label} · Forma de ingreso",
        entry_modes,
        index=entry_modes.index(default_mode),
        format_func=entry_labels.__getitem__,
        key=f"{key_prefix}_{component}_modo",
    )
    configured_value: float | int = 0
    if mode == "PORCENTAJE":
        percentage_key = f"{key_prefix}_{component}_porcentaje"
        # El porcentaje usado debe coincidir con los dos decimales visibles,
        # incluso si se pegó una tasa con mayor precisión.
        st.session_state[percentage_key] = float(
            Decimal(str(st.session_state.get(percentage_key, defaults["value"])))
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        configured_value = st.number_input(
            f"{label} (%)",
            min_value=0.0,
            max_value=100.0,
            step=0.01,
            format="%.2f",
            help="Escribe solo el número: por ejemplo, 19 equivale a 19 % del subtotal. Se usan dos decimales.",
            key=percentage_key,
        )
    elif mode == "VALOR_FIJO":
        configured_value = st.number_input(
            f"{label} (COP)",
            min_value=0,
            value=existing_amount if existing_amount is not None else int(defaults["value"]),
            step=1_000,
            format="%d",
            key=f"{key_prefix}_{component}_valor",
        )
    calculation = calculate_tax(subtotal, mode, configured_value)
    if mode == "PORCENTAJE":
        percentage_label = f"{configured_value:.2f}".replace(".", ",")
        st.caption(f"{percentage_label} % del subtotal = {format_currency(calculation.amount_cop)}")
    elif mode == "VALOR_FIJO":
        st.caption(f"Importe: {format_currency(calculation.amount_cop)}")
    else:
        st.caption("Este concepto no se aplica a la factura.")
    return calculation.amount_cop, {
        "modo": calculation.mode,
        "valor_configurado": str(calculation.configured_value),
        "monto_calculado_cop": calculation.amount_cop,
    }


def _format_subtotal_input(key: str) -> None:
    """Agrupa los miles al confirmar el campo, sin alterar texto inválido."""

    try:
        amount = parse_cop(str(st.session_state[key]))
    except ValueError:
        return
    st.session_state[key] = f"{amount:,}".replace(",", ".")


def _render_subtotal_input(
    key: str,
    initial: int = 0,
    *,
    label: str = "Subtotal (COP)",
    placeholder: str = "1.500.000",
) -> int | None:
    """Muestra un importe colombiano y devuelve pesos enteros validados."""

    if key not in st.session_state:
        st.session_state[key] = f"{initial:,}".replace(",", ".")
    elif isinstance(st.session_state[key], int):
        # Conserva un borrador que seguía abierto con el antiguo campo numérico.
        st.session_state[key] = f"{st.session_state[key]:,}".replace(",", ".")
    raw = st.text_input(
        label,
        key=key,
        placeholder=placeholder,
        help="Escribe con o sin puntos de miles. Al pulsar Enter o salir del campo se aplican los separadores automáticamente.",
        on_change=_format_subtotal_input,
        args=(key,),
    )
    try:
        return parse_cop(raw)
    except ValueError as exc:
        st.error(str(exc))
        return None


def _sync_invoice_company() -> None:
    """Propone el nuevo prefijo sin sustituir un prefijo personalizado."""

    company = st.session_state["factura_empresa"]
    previous = st.session_state.get("factura_empresa_anterior", company)
    prefix = str(st.session_state.get("factura_prefijo", "")).strip().upper()
    if not prefix or prefix == EMPRESAS[previous]["prefijo"]:
        st.session_state["factura_prefijo"] = EMPRESAS[company]["prefijo"]
    st.session_state["factura_empresa_anterior"] = company


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
        # Los controles deben recalcular antes de guardar. st.form retiene sus
        # cambios hasta el envío e impide abrir las casillas de porcentaje.
        with st.container():
            company = st.selectbox(
                "Empresa",
                available_companies,
                format_func=(
                    lambda code: f"{EMPRESAS[code]['prefijo']} · {EMPRESAS[code]['nombre']}"
                ),
                key="factura_empresa",
                on_change=_sync_invoice_company,
            )
            st.session_state["factura_empresa_anterior"] = company
            st.session_state.setdefault("factura_prefijo", EMPRESAS[company]["prefijo"])
            column_a, column_b, column_c, column_d = st.columns(4)
            with column_a:
                prefix = st.text_input("Prefijo", key="factura_prefijo").upper()
            with column_b:
                number = st.text_input(
                    "Número de factura", placeholder="1079", key="factura_numero"
                ).upper()
            with column_c:
                issue_date = st.date_input(
                    "Fecha de emisión", value=dt.date.today(), key="factura_fecha"
                )
            with column_d:
                due_date = st.date_input(
                    "Vencimiento",
                    value=dt.date.today() + dt.timedelta(days=30),
                    key="factura_vencimiento",
                )
            customer = st.selectbox(
                "Cliente · Razón social",
                db.listar_nombres_clientes(),
                index=None,
                placeholder="Escribe para buscar o agregar una razón social",
                accept_new_options=True,
                filter_mode="fuzzy",
                help="Las coincidencias aparecen mientras escribes. Selecciona una o pulsa Enter para agregar un cliente nuevo.",
                key="factura_cliente",
            )
            description = st.text_area(
                "Detalle del servicio",
                placeholder="Ruta, manifiesto, condición especial u observación operativa",
                max_chars=1000,
                key="factura_detalle",
            )
            plates = st.text_input("Placas", placeholder="SOQ766, TAW897", key="factura_placas")
            subtotal_value = _render_subtotal_input("factura_subtotal")
            subtotal = subtotal_value or 0
            descuento_value = _render_subtotal_input(
                "factura_descuento",
                label="Descuento (COP)",
                placeholder="0",
            )
            descuento = descuento_value or 0
            if descuento_value is not None and descuento > subtotal:
                st.warning("El descuento no puede ser mayor que el subtotal.")
            st.markdown("##### Impuestos y retenciones")
            st.caption(
                f"Base: {format_currency(subtotal)}. Elige porcentaje, valor en pesos o no aplica para cada concepto."
                if subtotal_value is not None else "Corrige el subtotal para calcular los impuestos."
            )
            iva_column, withholding_column, ica_column = st.columns(3)
            with iva_column:
                iva, iva_config = _render_tax_control("iva", int(subtotal))
            with withholding_column:
                retefuente, retefuente_config = _render_tax_control(
                    "retefuente", int(subtotal)
                )
            with ica_column:
                ica, ica_config = _render_tax_control("ica", int(subtotal))
            total = int(subtotal) + int(iva) - int(retefuente) - int(ica) - int(descuento)
            st.metric(
                "Total a cobrar",
                format_currency(total)
                if subtotal_value is not None and descuento_value is not None
                else "—",
            )
            if descuento:
                st.caption(
                    f"Incluye un descuento de {format_currency(descuento)}. "
                    "Los impuestos se calculan sobre el subtotal, como en la hoja de Finanzas."
                )
            save = st.button(
                "Guardar factura", type="primary", key="factura_guardar",
                disabled=subtotal_value is None or descuento_value is None,
            )
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
                        "descuento_cop": descuento,
                        "impuestos_config": {
                            "iva": iva_config,
                            "retefuente": retefuente_config,
                            "ica": ica_config,
                        },
                    }
                )
            except db.ErrorCartera as exc:
                st.error(str(exc))
            else:
                st.success("Factura registrada.")
                st.rerun()


def _render_quick_edit(
    rows: list[dict[str, Any]], *, use_expander: bool, invoice_id: int | None = None
) -> None:
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
            "Corrige el número, las fechas, el detalle, las placas o los impuestos "
            "sin salir de la cartera.",
        )
        if invoice_id is None:
            by_label = {invoice_label(row): row for row in rows}
            label = st.selectbox("Factura a editar", list(by_label), key="factura_edicion")
            invoice = by_label[label]
        else:
            invoice = next((row for row in rows if int(row["id"]) == invoice_id), None)
            if invoice is None:
                st.info("Esta factura ya no está disponible en la vista actual.")
                return
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
            identity_columns = st.columns([1.1, 1, 1])
            with identity_columns[0]:
                number_value = st.text_input(
                    "Número de factura",
                    value=str(invoice["numero"]),
                    key=f"editar_factura_{invoice['id']}_numero",
                    help=(
                        f"El prefijo {invoice['prefijo']} se conserva; "
                        "corrige solo el número si hubo un error de digitación."
                    ),
                ).upper()
            with identity_columns[1]:
                issue_value = st.date_input(
                    "Fecha de emisión",
                    value=dt.date.fromisoformat(invoice["fecha"]),
                    key=f"editar_factura_{invoice['id']}_fecha",
                )
            with identity_columns[2]:
                due_value = st.date_input(
                    "Vencimiento",
                    value=(
                        dt.date.fromisoformat(invoice["vencimiento"])
                        if invoice["vencimiento"] else None
                    ),
                    key=f"editar_factura_{invoice['id']}_vencimiento",
                )
            editor_data = pd.DataFrame(
                [
                    {
                        "Detalle del servicio": invoice["descripcion"],
                        "Placas": invoice["placas"],
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
                },
            )
            subtotal_value = _render_subtotal_input(
                f"editar_factura_{invoice['id']}_subtotal", int(invoice["subtotal_cop"])
            )
            descuento_value = _render_subtotal_input(
                f"editar_factura_{invoice['id']}_descuento",
                int(invoice["descuento_cop"]),
                label="Descuento (COP)",
                placeholder="0",
            )
        edited_row = edited.iloc[0].to_dict()
        subtotal = subtotal_value or 0
        descuento = descuento_value or 0
        if descuento_value is not None and descuento > subtotal:
            st.warning("El descuento no puede ser mayor que el subtotal.")
        st.markdown("##### Impuestos y retenciones")
        st.caption(
            f"Base de cálculo: {format_currency(subtotal)}. Puedes conservar el importe o indicar un porcentaje."
            if subtotal_value is not None else "Corrige el subtotal para calcular los impuestos."
        )
        amounts: dict[str, int] = {}
        configurations: dict[str, dict[str, Any]] = {}
        for column, component in zip(st.columns(3), TAX_COMPONENTS):
            with column:
                amounts[component], configurations[component] = _render_tax_control(
                    component,
                    subtotal,
                    key_prefix=f"editar_factura_{invoice['id']}",
                    existing_amount=int(invoice[f"{component}_cop"]),
                )
        total = (
            subtotal + amounts["iva"] - amounts["retefuente"] - amounts["ica"] - descuento
        )
        st.metric(
            "Total a cobrar",
            format_currency(total)
            if subtotal_value is not None and descuento_value is not None
            else "—",
        )
        actions = st.columns([1, 1])
        with actions[0]:
            if st.button(
                "Guardar cambios", type="primary", width="stretch",
                disabled=subtotal_value is None or descuento_value is None,
            ):
                try:
                    db.actualizar_campos_factura(
                        int(invoice["id"]),
                        {
                            "numero": number_value,
                            "fecha": issue_value,
                            "vencimiento": due_value,
                            "descripcion": edited_row["Detalle del servicio"],
                            "placas": edited_row["Placas"],
                            "subtotal_cop": subtotal,
                            "descuento_cop": descuento,
                            **{f"{component}_cop": amount for component, amount in amounts.items()},
                            "impuestos_config": configurations,
                        },
                    )
                except db.ErrorCartera as exc:
                    st.error(str(exc))
                else:
                    st.success("Cambios guardados.")
                    st.rerun()
        with actions[1]:
            if st.button("Anular factura", width="stretch"):
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
) -> None:
    """Renderiza la cartera manual para una empresa.

    Args:
        company: Código de empresa o ``TODAS``.
    """

    invoices = db.listar_facturas(None if company == TODAS else company)
    selected_year, selected_month = _selected_period()
    _render_kpis(_filter_period(invoices, selected_year, selected_month))
    st.write("")
    if request_invoice:
        show_invoice_dialog(company)
    filters = _render_compact_filters(invoices, company)
    filtered = _filter_rows(invoices, filters)

    edit_invoice_id = None
    general_tab, customers_tab = st.tabs(["General", "Clientes y saldo pendiente"])
    with general_tab:
        render_section(
            f"Cartera manual · {company_name(company)}",
            f"{len(filtered)} factura(s) visible(s) · los saldos se actualizan al aplicar un abono.",
        )
        st.write("")
        if filtered:
            table = _invoices_table(filtered)
            event = _render_grid(
                table, key="tabla_cartera_general", edit_on_double_click=True
            )
            edit_invoice_id = _consume_invoice_edit_event(event, filtered)
            st.caption(
                "Doble clic sobre una factura para editarla, o selecciona una celda y pulsa Enter. "
                "Valores en pesos colombianos, sin centavos."
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
        st.write("")
        payment_from_detail = _render_customer_detail(invoices, filters)
    if edit_invoice_id is not None:
        show_edit_invoice_dialog(filtered, edit_invoice_id)
    if payment_from_detail:
        show_payment_dialog()


@st.dialog("Registrar nueva factura", width="large")
def show_invoice_dialog(active_company: str) -> None:
    """Abre el registro de factura desde la cabecera, sin ocupar la tabla."""

    _render_invoice_form(active_company, use_expander=False)


@st.dialog("Editar factura", width="large")
def show_edit_invoice_dialog(invoices: list[dict[str, Any]], invoice_id: int) -> None:
    """Abre directamente la factura sobre la que se hizo doble clic."""

    _render_quick_edit(invoices, use_expander=False, invoice_id=invoice_id)


@st.dialog("Registrar abono", width="large")
def show_payment_dialog() -> None:
    """Abre el flujo de registro y aplicación de un abono manual.

    El pago puede distribuirse automáticamente por antigüedad (FIFO) o mediante
    importes digitados por factura. La operación final se valida y persiste en
    ``src.database``.
    """

    # Preselección desde el detalle del cliente: empresa y cliente ya elegidos.
    preselection = st.session_state.pop("abono_preseleccion", None)
    preferred_company = st.session_state.get("empresa_activa", TODAS)
    available_companies = (
        [preferred_company] if preferred_company != TODAS else list(EMPRESAS)
    )
    company_index = 0
    if preselection and preselection.get("empresa") in available_companies:
        company_index = available_companies.index(preselection["empresa"])
    company = st.selectbox(
        "Empresa",
        available_companies,
        index=company_index,
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
    customer_index = 0
    if preselection:
        customer_index = next(
            (position for position, row in enumerate(customers)
             if int(row["cliente_id"]) == int(preselection.get("cliente_id", -1))),
            0,
        )
    customer_label = st.selectbox(
        "Cliente", list(customer_options), index=customer_index, key="abono_cliente"
    )
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
