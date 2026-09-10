"""Vistas de solo lectura para el espejo y la conciliación de Siigo.

La consulta a Siigo y la cartera digitada manualmente siguen separadas. Este
módulo únicamente muestra la primera y compara ambas fuentes; la única
escritura posible es guardar una revisión interna de conciliación.
"""

from __future__ import annotations

from collections.abc import Mapping
import datetime as dt
import html
import os
from typing import Any

import pandas as pd
import streamlit as st

from src import database as db
from src.cartera_siigo import (
    EMPRESAS_SIIGO,
    enriquecer_facturas_clientes,
    facturas_a_dataframe,
    normalizar_factura,
    recibos_a_dataframe,
)
from src.siigo import (
    ClienteSiigo,
    ConfiguracionSiigo,
    ErrorConfiguracionSiigo,
    ErrorSiigo,
)
from src.ui.components import (
    EMPRESAS,
    ESTADO_META,
    TODAS,
    as_integer,
    company_name,
    format_currency,
    render_kpi_card,
    render_section,
    short_text,
)


def _streamlit_secrets() -> Mapping[str, Any] | None:
    """Devuelve secretos de Streamlit cuando están disponibles."""

    try:
        secretos = st.secrets
        if isinstance(secretos, Mapping):
            return secretos
        return {clave: secretos[clave] for clave in secretos.keys()}
    except Exception:
        return None


def _siigo_configuration() -> tuple[ConfiguracionSiigo | None, dict[str, str]]:
    """Carga las credenciales disponibles sin exponer sus valores."""

    secretos = _streamlit_secrets()
    credenciales: dict[str, Any] = {}
    errores: dict[str, str] = {}
    for codigo in EMPRESAS_SIIGO:
        configurada = None
        if secretos is not None:
            try:
                parcial = ConfiguracionSiigo.desde_mapeo_secretos(secretos, {codigo: codigo})
                configurada = parcial.credenciales_para(codigo)
            except ErrorConfiguracionSiigo:
                pass
        if configurada is None:
            try:
                parcial = ConfiguracionSiigo.desde_entorno(
                    {codigo: codigo},
                    entorno=os.environ,
                )
                configurada = parcial.credenciales_para(codigo)
            except ErrorConfiguracionSiigo:
                errores[codigo] = "Sin credenciales configuradas"
        if configurada is not None:
            credenciales[codigo] = configurada
            errores.pop(codigo, None)
    if not credenciales:
        return None, errores
    return ConfiguracionSiigo(empresas=credenciales), errores


def _customer_without_name(invoice: Mapping[str, Any]) -> bool:
    customer = invoice.get("customer")
    return not isinstance(customer, Mapping) or not customer.get("name")


def _enrich_customers(
    siigo_client: ClienteSiigo,
    invoices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Completa nombres solo si Siigo no los incluyó en la factura."""

    if not invoices or not any(_customer_without_name(invoice) for invoice in invoices):
        return invoices
    ids = {
        str(invoice.get("customer", {}).get("id") or "").strip()
        for invoice in invoices
        if isinstance(invoice.get("customer"), Mapping)
        and _customer_without_name(invoice)
    }
    ids.discard("")
    if ids and len(ids) <= 25:
        catalog = [siigo_client.consultar_cliente(customer_id) for customer_id in sorted(ids)]
        return enriquecer_facturas_clientes(invoices, catalog)
    return enriquecer_facturas_clientes(invoices, siigo_client.listar_clientes(activo=True))


def _fetch_siigo(
    configuration: ConfiguracionSiigo,
    companies: list[str],
    start_date: dt.date,
    end_date: dt.date,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Consulta facturas y recibos de las empresas seleccionadas."""

    invoice_tables: list[pd.DataFrame] = []
    receipt_tables: list[pd.DataFrame] = []
    errors: dict[str, str] = {}
    for company in companies:
        try:
            client = ClienteSiigo(company, configuration)
            invoices = client.listar_facturas(start_date, end_date)
            invoices = _enrich_customers(client, invoices)
            invoice_tables.append(facturas_a_dataframe(company, invoices))
        except ErrorSiigo as exc:
            errors[company] = str(exc)
            continue
        except Exception as exc:
            errors[company] = f"No fue posible leer las facturas ({type(exc).__name__})."
            continue
        try:
            receipts = client.listar_recibos_caja(start_date, max(end_date, dt.date.today()))
            receipt_tables.append(recibos_a_dataframe(company, receipts))
        except ErrorSiigo as exc:
            errors[f"{company} · RECIBOS"] = str(exc)
        except Exception as exc:
            errors[f"{company} · RECIBOS"] = (
                f"No fue posible leer los recibos ({type(exc).__name__})."
            )
    invoices_df = (
        pd.concat(invoice_tables, ignore_index=True)
        if invoice_tables
        else facturas_a_dataframe("", [])
    )
    receipts_df = (
        pd.concat(receipt_tables, ignore_index=True)
        if receipt_tables
        else recibos_a_dataframe("", [])
    )
    return invoices_df, receipts_df, errors


def _siigo_sample(manual_invoices: list[dict[str, Any]]) -> pd.DataFrame:
    """Construye una muestra explícita para recorrer la interfaz sin credenciales."""

    rows: list[dict[str, Any]] = []
    if not manual_invoices:
        today = dt.date.today()
        manual_invoices = [
            {
                "empresa_codigo": "NOVASA",
                "factura": "FEBA1079",
                "fecha": today - dt.timedelta(days=55),
                "cliente": "Transportes Andinos SAS",
                "nit": "901.222.333-4",
                "descripcion": "Servicio Bogotá → Medellín · Manifiesto 47821",
                "subtotal_cop": 12_247_644,
                "iva_cop": 0,
                "retefuente_cop": 306_191,
                "ica_cop": 49_000,
                "total_cop": 11_892_453,
                "saldo_cop": 7_392_453,
                "estado": "VENCIDA",
            },
            {
                "empresa_codigo": "LUAC",
                "factura": "LUA208",
                "fecha": today - dt.timedelta(days=34),
                "cliente": "Comercializadora Central Ltda",
                "nit": "900.786.123-9",
                "descripcion": "Servicio Cali → Bogotá · Manifiesto 32018",
                "subtotal_cop": 7_850_000,
                "iva_cop": 0,
                "retefuente_cop": 196_250,
                "ica_cop": 31_400,
                "total_cop": 7_622_350,
                "saldo_cop": 7_622_350,
                "estado": "VENCIDA",
            },
        ]
    for index, manual in enumerate(manual_invoices[:8]):
        balance = as_integer(manual.get("saldo_cop"))
        iva = as_integer(manual.get("iva_cop"))
        withholding = as_integer(manual.get("retefuente_cop"))
        ica = as_integer(manual.get("ica_cop"))
        if index == 1:
            ica += 12_476
        if index == 2:
            balance += 38_000
        company = manual["empresa_codigo"]
        rows.append(
            {
                "empresa_codigo": company,
                "empresa": company_name(company) if company in EMPRESAS else company,
                "siigo_factura_id": f"muestra-{index + 1}",
                "factura": manual["factura"],
                "fecha": manual.get("fecha"),
                "cliente": manual.get("cliente", ""),
                "nit": manual.get("nit", ""),
                "moneda": "COP",
                "descripcion_siigo": manual.get("descripcion", ""),
                "subtotal_siigo": as_integer(manual.get("subtotal_cop")),
                "iva_siigo": iva,
                "retefuente_siigo": withholding,
                "reteica_siigo": ica,
                "total_siigo": as_integer(manual.get("total_cop")),
                "saldo_siigo": balance,
                "estado_siigo": manual.get("estado", "PENDIENTE"),
            }
        )
    if rows:
        extra = dict(rows[0])
        extra.update(
            {
                "siigo_factura_id": "muestra-solo-siigo",
                "factura": "FEBA1099",
                "cliente": "Cliente solo en Siigo SAS",
                "subtotal_siigo": 2_500_000,
                "total_siigo": 2_500_000,
                "saldo_siigo": 2_500_000,
            }
        )
        rows.append(extra)
    return pd.DataFrame(rows)


def _siigo_table(invoices: pd.DataFrame) -> pd.DataFrame:
    if invoices is None or invoices.empty:
        return pd.DataFrame()
    rows = []
    for _, invoice in invoices.iterrows():
        rows.append(
            {
                "Empresa": invoice.get("empresa_codigo", ""),
                "Factura": invoice.get("factura", ""),
                "Fecha": _visible_date(invoice.get("fecha")),
                "Cliente": invoice.get("cliente", ""),
                "Detalle": short_text(invoice.get("descripcion_siigo", "")),
                "Total": format_currency(invoice.get("total_siigo")),
                "Saldo Siigo": format_currency(invoice.get("saldo_siigo")),
                "Estado": str(invoice.get("estado_siigo", "")).replace("_", " ").title(),
            }
        )
    return pd.DataFrame(rows)


def render_siigo_mirror(company: str) -> None:
    """Renderiza la consulta de solo lectura a Siigo."""

    st.markdown('<div class="surface">', unsafe_allow_html=True)
    render_section(
        "Espejo contable de Siigo",
        "Lectura directa desde Siigo. Consultar o revisar esta pantalla no modifica ningún registro contable.",
    )
    configuration, credential_errors = _siigo_configuration()
    available = list(configuration.empresas.keys()) if configuration else []
    today = dt.date.today()
    preferred_company = [company] if company != TODAS and company in available else available
    with st.form("consulta_siigo"):
        column_1, column_2, column_3 = st.columns([1, 1, 1.4])
        with column_1:
            start_date = st.date_input("Desde", value=today.replace(day=1))
        with column_2:
            end_date = st.date_input("Hasta", value=today)
        with column_3:
            companies = st.multiselect(
                "Empresas a consultar",
                list(EMPRESAS),
                default=preferred_company,
                format_func=lambda code: f"{EMPRESAS[code]['prefijo']} · {code}",
            )
        query = st.form_submit_button("Consultar Siigo ahora", type="primary")
    actions = st.columns([1, 2.6])
    with actions[0]:
        sample = st.button("Cargar muestra visual", use_container_width=True)
    with actions[1]:
        if configuration is None:
            st.caption(
                "No hay credenciales disponibles todavía. La muestra visual permite recorrer el módulo sin conectarse a Siigo."
            )
        elif credential_errors:
            st.caption("Algunas empresas no tienen credenciales; las demás se pueden consultar.")

    if query:
        if not configuration:
            st.error(
                "No se encontraron credenciales de Siigo. Configúralas antes de consultar datos reales."
            )
        elif not companies:
            st.warning("Selecciona al menos una empresa.")
        elif start_date > end_date:
            st.warning("La fecha inicial no puede ser posterior a la final.")
        else:
            with st.spinner("Leyendo Siigo…"):
                invoices, receipts, errors = _fetch_siigo(
                    configuration, companies, start_date, end_date
                )
            st.session_state["siigo_facturas"] = invoices
            st.session_state["siigo_recibos"] = receipts
            st.session_state["siigo_errores"] = errors
            st.session_state["siigo_consultado_en"] = dt.datetime.now().astimezone()
            st.session_state["siigo_origen"] = "Lectura directa"
    if sample:
        manual_invoices = db.listar_facturas(None if company == TODAS else company)
        st.session_state["siigo_facturas"] = _siigo_sample(manual_invoices)
        st.session_state["siigo_recibos"] = pd.DataFrame()
        st.session_state["siigo_errores"] = {}
        st.session_state["siigo_consultado_en"] = dt.datetime.now().astimezone()
        st.session_state["siigo_origen"] = "Muestra visual"

    siigo_invoices = st.session_state.get("siigo_facturas", pd.DataFrame())
    siigo_receipts = st.session_state.get("siigo_recibos", pd.DataFrame())
    if isinstance(siigo_invoices, pd.DataFrame) and not siigo_invoices.empty:
        if company != TODAS and "empresa_codigo" in siigo_invoices.columns:
            siigo_invoices = siigo_invoices[
                siigo_invoices["empresa_codigo"].astype(str).eq(company)
            ].copy()
        checked_at = st.session_state.get("siigo_consultado_en")
        source = st.session_state.get("siigo_origen", "Lectura")
        if checked_at:
            st.caption(f"{source}: {checked_at:%d/%m/%Y %H:%M:%S %Z}")
        for key, message in st.session_state.get("siigo_errores", {}).items():
            st.warning(f"{key}: {message}")
        total = sum(as_integer(value) for value in siigo_invoices.get("total_siigo", []))
        balance = sum(as_integer(value) for value in siigo_invoices.get("saldo_siigo", []))
        receipts = sum(as_integer(value) for value in siigo_receipts.get("abonos_recibos", []))
        kpis = st.columns(3)
        with kpis[0]:
            render_kpi_card(
                "Facturado según Siigo",
                format_currency(total),
                f"{len(siigo_invoices)} documento(s)",
            )
        with kpis[1]:
            render_kpi_card(
                "Abonos visibles",
                format_currency(receipts),
                "Recibos de caja consultados",
            )
        with kpis[2]:
            render_kpi_card(
                "Saldo Siigo",
                format_currency(balance),
                "Saldo contable informado por Siigo",
                highlighted=True,
            )
        st.write("")
        st.dataframe(_siigo_table(siigo_invoices), width="stretch", hide_index=True)
    else:
        st.markdown(
            '<div class="empty-state"><strong>La lectura de Siigo aparecerá aquí.</strong><br>'
            'Usa las credenciales reales para consultarla o carga la muestra visual.</div>',
            unsafe_allow_html=True,
        )
    with st.expander("Cómo conectar Siigo"):
        st.code(
            '''SIIGO_PARTNER_ID = "NovaLogistics"
SIIGO_NOVASA_USERNAME = "usuario@empresa.com"
SIIGO_NOVASA_ACCESS_KEY = "..."
SIIGO_LUAC_USERNAME = "usuario@empresa.com"
SIIGO_LUAC_ACCESS_KEY = "..."
SIIGO_MSU_USERNAME = "usuario@empresa.com"
SIIGO_MSU_ACCESS_KEY = "..."''',
            language="toml",
        )
        st.caption(
            "Guarda estas claves en .streamlit/secrets.toml. No se muestran ni se almacenan en la aplicación."
        )
    st.markdown("</div>", unsafe_allow_html=True)


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
            filtered_siigo["empresa_codigo"].astype(str).eq(company)
        ].copy()
    rows = _build_reconciliation(manual_invoices, filtered_siigo)

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
            db.guardar_revision_conciliacion(
                empresa_codigo=row["empresa_codigo"],
                factura_clave=row["factura_clave"],
                estado=row["estado"],
                observacion=observation,
                manual=row["manual"],
                siigo=row["siigo"],
            )
            st.success("Revisión guardada en el historial interno.")
    else:
        st.markdown(
            '<div class="empty-state"><strong>No hay facturas para conciliar.</strong><br>'
            'Registra una factura manual o amplía la lectura de Siigo.</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


__all__ = ["render_reconciliation", "render_siigo_mirror"]
