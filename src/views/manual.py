"""Vista operativa de la cartera digitada manualmente.

Este módulo agrupa la interfaz de facturas y abonos de la cartera manual. La
persistencia y las reglas de integridad financiera permanecen en
``src.database``; aquí solo se compone la experiencia de Streamlit.
"""

from __future__ import annotations

import datetime as dt
import html
from typing import Any

import pandas as pd
import streamlit as st

from src import database as db
from src.ui.components import (
    EMPRESAS,
    ESTADO_META,
    TODAS,
    as_integer,
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


def _render_invoice_form(active_company: str) -> None:
    """Renderiza y procesa el formulario de creación de una factura manual."""

    with st.expander("＋ Registrar nueva factura", expanded=False):
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
            customer_column, tax_id_column = st.columns([2, 1])
            with customer_column:
                customer = st.text_input("Cliente", placeholder="Razón social o nombre")
            with tax_id_column:
                tax_id = st.text_input("NIT", placeholder="900.000.000-0")
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
                        "nit": tax_id,
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


def _render_quick_edit(rows: list[dict[str, Any]]) -> None:
    """Permite editar campos operativos o anular una factura existente."""

    if not rows:
        return
    with st.expander("Editar factura en línea", expanded=False):
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


def render_manual_portfolio(company: str, global_term: str) -> None:
    """Renderiza la cartera manual para una empresa y una búsqueda global.

    Args:
        company: Código de empresa o ``TODAS``.
        global_term: Texto seleccionado en el buscador global de la cabecera.
    """

    _render_kpis(company)
    st.write("")
    invoices = db.listar_facturas(None if company == TODAS else company)
    local_term = st.text_input(
        "Filtrar cartera",
        value=global_term,
        placeholder="Cliente, factura, NIT, ruta o placa",
    )
    filtered = filter_invoices(invoices, local_term)

    st.markdown('<div class="surface">', unsafe_allow_html=True)
    render_section(
        f"Cartera manual · {company_name(company)}",
        f"{len(filtered)} factura(s) visible(s) · los saldos se actualizan al aplicar un abono.",
    )
    st.write("")
    if filtered:
        table = _invoices_table(filtered)
        st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            height=min(540, 94 + 36 * len(table)),
            column_config={
                "Factura": st.column_config.TextColumn(width="small"),
                "Fecha": st.column_config.TextColumn(width="small"),
                "Cliente": st.column_config.TextColumn(width="medium"),
                "Detalle del servicio": st.column_config.TextColumn(width="large"),
                "Placas": st.column_config.TextColumn(width="medium"),
                "Estado": st.column_config.TextColumn(width="small"),
            },
        )
        st.caption(
            "Valores en pesos colombianos, sin centavos. Abre “Editar factura en línea” para cambiar impuestos o detalle."
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
    st.markdown("</div>", unsafe_allow_html=True)
    _render_invoice_form(company)
    _render_quick_edit(filtered)


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
        f"{row['cliente']} · {row['nit'] or 'Sin NIT'} · {format_currency(row['saldo_cop'])}": row
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


__all__ = ["render_manual_portfolio", "show_payment_dialog"]
