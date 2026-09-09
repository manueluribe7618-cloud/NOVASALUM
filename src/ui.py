"""Interfaz de trabajo de NOVASALUM.

La interfaz privilegia la lectura rápida de cartera, pero mantiene los detalles
largos y las decisiones tributarias a un clic de distancia de la tabla principal.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
import html
import json
import os
from typing import Any

import altair as alt
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
from src.formato import fmt_cop
from src.siigo import (
    ClienteSiigo,
    ConfiguracionSiigo,
    ErrorConfiguracionSiigo,
    ErrorSiigo,
)


TODAS = "TODAS"
EMPRESAS = db.EMPRESAS
ESTADO_TONO = {
    "PAGADA": "verde",
    "ABONADA": "amarillo",
    "PENDIENTE": "azul",
    "VENCIDA": "rojo",
    "ANULADA": "gris",
    "CUADRADO": "verde",
    "DIFERENCIA_IMPUESTOS": "amarillo",
    "DESCUADRE": "rojo",
    "SOLO_MANUAL": "rojo",
    "SOLO_SIIGO": "rojo",
}
PLANTILLAS = {
    "Transporte estándar": {
        "descripcion": "IVA 0% · Retefuente 2,5% · ICA 0,4%",
        "iva": 0.0,
        "retefuente": 2.5,
        "ica": 0.4,
    },
    "Sin impuestos": {
        "descripcion": "IVA 0% · Retefuente 0% · ICA 0%",
        "iva": 0.0,
        "retefuente": 0.0,
        "ica": 0.0,
    },
}


def _estilos() -> None:
    st.markdown(
        """
        <style>
            :root {
                --ink: #172033;
                --muted: #64748b;
                --canvas: #f8fafc;
                --line: #e2e8f0;
                --blue: #2563eb;
                --blue-soft: #eff6ff;
                --green: #16a34a;
                --amber: #d97706;
                --red: #dc2626;
                --purple: #7c3aed;
            }
            .stApp, [data-testid="stAppViewContainer"] {
                background: var(--canvas);
                color: var(--ink);
            }
            [data-testid="stHeader"] {
                background: rgba(248, 250, 252, .94);
            }
            .block-container {
                max-width: 1540px;
                padding-top: 1.7rem;
                padding-bottom: 2.5rem;
            }
            h1, h2, h3 { color: var(--ink) !important; letter-spacing: -.025em; }
            .brand {
                display: flex;
                align-items: center;
                gap: .7rem;
                font-size: 1.15rem;
                font-weight: 800;
                letter-spacing: -.035em;
            }
            .brand-mark {
                display: inline-grid;
                width: 30px;
                height: 30px;
                place-items: center;
                color: white;
                background: linear-gradient(135deg, #1e3a8a, #2563eb);
                border-radius: 9px;
                box-shadow: 0 6px 14px rgba(37, 99, 235, .24);
            }
            .eyebrow {
                color: var(--muted);
                font-size: .74rem;
                font-weight: 800;
                letter-spacing: .1em;
                text-transform: uppercase;
            }
            .subtitle {
                color: var(--muted);
                margin-top: -.35rem;
                font-size: .94rem;
            }
            .surface {
                padding: 1.15rem;
                border: 1px solid var(--line);
                border-radius: 16px;
                background: white;
                box-shadow: 0 6px 20px rgba(15, 23, 42, .035);
            }
            .surface-title {
                font-size: 1rem;
                font-weight: 800;
                letter-spacing: -.02em;
            }
            .surface-caption {
                margin-top: .18rem;
                color: var(--muted);
                font-size: .84rem;
            }
            .kpi {
                min-height: 112px;
                padding: 1rem 1.08rem;
                border: 1px solid var(--line);
                border-radius: 15px;
                background: white;
                box-shadow: 0 5px 16px rgba(15, 23, 42, .035);
            }
            .kpi.primary {
                border-color: rgba(37, 99, 235, .3);
                background: linear-gradient(135deg, #eff6ff, #ffffff 78%);
            }
            .kpi-label {
                color: var(--muted);
                font-size: .76rem;
                font-weight: 800;
                letter-spacing: .06em;
                text-transform: uppercase;
            }
            .kpi-value {
                margin-top: .48rem;
                font-size: 1.48rem;
                line-height: 1.15;
                font-weight: 800;
                letter-spacing: -.04em;
            }
            .kpi.primary .kpi-value { color: var(--blue); }
            .kpi-detail {
                margin-top: .4rem;
                color: var(--muted);
                font-size: .8rem;
            }
            .company-balance {
                padding: .75rem .9rem;
                border: 1px solid var(--line);
                border-left-width: 4px;
                border-radius: 12px;
                background: white;
            }
            .company-balance strong {
                display: block;
                color: var(--ink);
                font-size: 1.04rem;
                letter-spacing: -.02em;
            }
            .company-balance span {
                color: var(--muted);
                font-size: .77rem;
            }
            .badge {
                display: inline-block;
                padding: .25rem .53rem;
                border-radius: 999px;
                font-size: .74rem;
                font-weight: 800;
                white-space: nowrap;
            }
            .badge-verde { color: #166534; background: #dcfce7; }
            .badge-amarillo { color: #92400e; background: #fef3c7; }
            .badge-azul { color: #1d4ed8; background: #dbeafe; }
            .badge-rojo { color: #b91c1c; background: #fee2e2; }
            .badge-gris { color: #475569; background: #e2e8f0; }
            .plate {
                display: inline-block;
                margin: 0 .3rem .28rem 0;
                padding: .27rem .48rem;
                border: 1px solid #dbe3ed;
                border-radius: 7px;
                color: #334155;
                background: #f8fafc;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: .77rem;
                font-weight: 700;
            }
            .detail-card {
                padding: 1rem 1.08rem;
                border: 1px solid #bfdbfe;
                border-radius: 14px;
                background: #f8fbff;
            }
            .detail-text {
                margin-top: .65rem;
                color: #334155;
                font-size: .92rem;
                line-height: 1.55;
                white-space: pre-wrap;
            }
            .invoice-list-head, .invoice-row {
                display: grid;
                grid-template-columns: 1.05fr 1.6fr 1.35fr 1.13fr 1.13fr 1.28fr .92fr;
                gap: .75rem;
                align-items: center;
            }
            .invoice-list-head {
                margin: .9rem .75rem .45rem;
                color: var(--muted);
                font-size: .7rem;
                font-weight: 800;
                letter-spacing: .075em;
                text-transform: uppercase;
            }
            .invoice-list-head .numeric { text-align: right; }
            .invoice-row {
                margin: 0 0 .55rem;
                padding: .9rem .95rem;
                border: 1px solid var(--line);
                border-radius: 14px;
                background: #fff;
                box-shadow: 0 3px 12px rgba(15, 23, 42, .025);
                transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease;
            }
            .invoice-row:hover {
                border-color: #bfdbfe;
                box-shadow: 0 8px 22px rgba(37, 99, 235, .09);
                transform: translateY(-1px);
            }
            .invoice-code {
                display: inline-flex;
                align-items: center;
                min-height: 29px;
                padding: .25rem .5rem;
                border-radius: 8px;
                color: #1e3a8a;
                background: #eff6ff;
                font-size: .78rem;
                font-weight: 850;
                letter-spacing: .015em;
            }
            .invoice-client strong {
                display: block;
                overflow: hidden;
                color: var(--ink);
                font-size: .86rem;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .invoice-sub {
                margin-top: .17rem;
                color: var(--muted);
                font-size: .75rem;
            }
            .invoice-money { text-align: right; }
            .invoice-money span {
                display: block;
                color: var(--muted);
                font-size: .67rem;
                font-weight: 700;
            }
            .invoice-money strong {
                display: block;
                margin-top: .08rem;
                color: var(--ink);
                font-size: .84rem;
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            .invoice-balance strong { color: var(--blue); }
            .invoice-extra {
                margin: -.18rem .35rem .72rem;
                padding: .58rem .75rem;
                border-radius: 10px;
                color: #475569;
                background: #f8fafc;
                font-size: .82rem;
                line-height: 1.45;
            }
            .invoice-extra .taxes {
                display: inline-block;
                margin-top: .3rem;
                color: #64748b;
                font-size: .75rem;
                font-variant-numeric: tabular-nums;
            }
            .empty {
                padding: 2.2rem 1rem;
                border: 1px dashed #cbd5e1;
                border-radius: 15px;
                color: var(--muted);
                text-align: center;
                background: rgba(255, 255, 255, .55);
            }
            [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
                border: 1px solid var(--line);
                border-radius: 12px;
                overflow: hidden;
            }
            [data-testid="stDataFrame"] [role="columnheader"] {
                background: #f1f5f9 !important;
            }
            [data-testid="stButton"] > button {
                border-radius: 9px;
                font-weight: 700;
            }
            [data-testid="stSegmentedControl"] button {
                border-radius: 9px !important;
                font-weight: 700 !important;
            }
            @media (max-width: 720px) {
                .block-container { padding: 1rem .75rem 2rem; }
                .kpi-value { font-size: 1.25rem; }
                .invoice-list-head { display: none; }
                .invoice-row {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: .75rem .55rem;
                }
                .invoice-money { text-align: left; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cop(valor: Any) -> str:
    return fmt_cop(valor, dash_zero=False)


def _numero(valor: Any) -> int:
    try:
        if valor is None or pd.isna(valor):
            return 0
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return 0


def _fecha(valor: Any) -> dt.date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    try:
        return dt.date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _fecha_visible(valor: Any) -> str:
    fecha = _fecha(valor)
    return fecha.strftime("%d/%m/%Y") if fecha else "—"


def _acortar(valor: Any, limite: int = 58) -> str:
    texto = str(valor or "").strip()
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def _badge(estado: str) -> str:
    etiquetas = {
        "DIFERENCIA_IMPUESTOS": "Diferencia impuestos",
        "SOLO_MANUAL": "Solo manual",
        "SOLO_SIIGO": "Solo Siigo",
    }
    etiqueta = etiquetas.get(estado, str(estado).replace("_", " ").title())
    tono = ESTADO_TONO.get(estado, "gris")
    return f'<span class="badge badge-{tono}">{html.escape(etiqueta)}</span>'


def _placas(placas: Any) -> str:
    items = [item.strip() for item in str(placas or "").split(",") if item.strip()]
    if not items:
        return '<span style="color:#94a3b8">Sin placas</span>'
    return "".join(f'<span class="plate">{html.escape(item)}</span>' for item in items)


def _seccion(titulo: str, subtitulo: str = "") -> None:
    st.markdown(
        f'<div class="surface-title">{html.escape(titulo)}</div>',
        unsafe_allow_html=True,
    )
    if subtitulo:
        st.markdown(
            f'<div class="surface-caption">{html.escape(subtitulo)}</div>',
            unsafe_allow_html=True,
        )


def _kpi(etiqueta: str, valor: str, detalle: str, principal: bool = False) -> None:
    clase = " primary" if principal else ""
    st.markdown(
        f"""
        <div class="kpi{clase}">
            <div class="kpi-label">{html.escape(etiqueta)}</div>
            <div class="kpi-value">{html.escape(valor)}</div>
            <div class="kpi-detail">{html.escape(detalle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _resumen(facturas: list[dict[str, Any]]) -> dict[str, int]:
    vigentes = [fila for fila in facturas if fila.get("estado") != "ANULADA"]
    return {
        "facturado": sum(_numero(fila.get("total_cop")) for fila in vigentes),
        "abonos": sum(_numero(fila.get("abonos_cop")) for fila in vigentes),
        "saldo": sum(_numero(fila.get("saldo_cop")) for fila in vigentes),
        "vencidas": sum(1 for fila in vigentes if fila.get("estado") == "VENCIDA"),
        "pendientes": sum(1 for fila in vigentes if _numero(fila.get("saldo_cop")) > 0),
    }


def _filtrar_facturas(
    facturas: list[dict[str, Any]],
    *,
    cliente: str,
    texto: str,
    desde: dt.date,
    hasta: dt.date,
) -> list[dict[str, Any]]:
    consulta = str(texto or "").strip().casefold()
    salida: list[dict[str, Any]] = []
    for factura in facturas:
        if cliente != "Todos los clientes" and factura.get("cliente") != cliente:
            continue
        fecha = _fecha(factura.get("fecha"))
        if fecha and not desde <= fecha <= hasta:
            continue
        if consulta:
            buscable = " ".join(
                str(factura.get(campo) or "")
                for campo in ("factura", "cliente", "descripcion", "placas")
            ).casefold()
            if consulta not in buscable:
                continue
        salida.append(factura)
    return salida


def _secretos() -> Mapping[str, Any] | None:
    try:
        secretos = st.secrets
        return {clave: secretos[clave] for clave in list(secretos.keys())}
    except Exception:
        return None


def _configuracion_siigo() -> tuple[ConfiguracionSiigo | None, dict[str, str]]:
    secretos = _secretos()
    credenciales: dict[str, Any] = {}
    errores: dict[str, str] = {}
    for codigo in EMPRESAS_SIIGO:
        parcial = None
        if secretos is not None:
            try:
                parcial = ConfiguracionSiigo.desde_mapeo_secretos(secretos, {codigo: codigo})
            except ErrorConfiguracionSiigo:
                pass
        if parcial is None:
            try:
                parcial = ConfiguracionSiigo.desde_entorno(
                    {codigo: codigo},
                    entorno=os.environ,
                )
            except ErrorConfiguracionSiigo:
                errores[codigo] = "Sin credenciales configuradas"
                continue
        credenciales[codigo] = parcial.credenciales_para(codigo)
    if not credenciales:
        return None, errores
    return ConfiguracionSiigo(empresas=credenciales), errores


def _cliente_sin_nombre(factura: Mapping[str, Any]) -> bool:
    cliente = factura.get("customer")
    return not isinstance(cliente, Mapping) or not cliente.get("name")


def _enriquecer_clientes(cliente_siigo: ClienteSiigo, facturas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not facturas or not any(_cliente_sin_nombre(factura) for factura in facturas):
        return facturas
    ids = {
        str(factura.get("customer", {}).get("id") or "").strip()
        for factura in facturas
        if isinstance(factura.get("customer"), Mapping) and _cliente_sin_nombre(factura)
    }
    ids.discard("")
    if ids and len(ids) <= 25:
        catalogo = [cliente_siigo.consultar_cliente(cliente_id) for cliente_id in sorted(ids)]
    else:
        catalogo = cliente_siigo.listar_clientes(activo=True)
    return enriquecer_facturas_clientes(facturas, catalogo)


def _consultar_siigo(
    configuracion: ConfiguracionSiigo,
    empresas: list[str],
    desde: dt.date,
    hasta: dt.date,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    tablas_facturas: list[pd.DataFrame] = []
    tablas_recibos: list[pd.DataFrame] = []
    errores: dict[str, str] = {}
    for empresa in empresas:
        try:
            cliente = ClienteSiigo(empresa, configuracion)
            facturas = cliente.listar_facturas(desde, hasta)
            facturas = _enriquecer_clientes(cliente, facturas)
            tablas_facturas.append(facturas_a_dataframe(empresa, facturas))
        except ErrorSiigo as exc:
            errores[empresa] = str(exc)
            continue
        except Exception as exc:
            errores[empresa] = f"No fue posible leer facturas ({type(exc).__name__})."
            continue
        try:
            recibos = cliente.listar_recibos_caja(desde, max(hasta, dt.date.today()))
            tablas_recibos.append(recibos_a_dataframe(empresa, recibos))
        except ErrorSiigo as exc:
            errores[f"{empresa} · recibos"] = str(exc)
        except Exception as exc:
            errores[f"{empresa} · recibos"] = (
                f"No fue posible leer recibos ({type(exc).__name__})."
            )
    facturas_df = (
        pd.concat(tablas_facturas, ignore_index=True)
        if tablas_facturas
        else facturas_a_dataframe("", [])
    )
    recibos_df = (
        pd.concat(tablas_recibos, ignore_index=True)
        if tablas_recibos
        else recibos_a_dataframe("", [])
    )
    return facturas_df, recibos_df, errores


def _muestra_siigo(manuales: list[dict[str, Any]]) -> pd.DataFrame:
    if not manuales:
        manuales = [
            {
                "empresa_codigo": "NOVASA",
                "factura": "FEBA-1079",
                "fecha": dt.date.today() - dt.timedelta(days=18),
                "cliente": "Cliente de ejemplo",
                "descripcion": "Servicio de transporte de demostración",
                "subtotal_cop": 4_000_000,
                "iva_cop": 0,
                "retefuente_cop": 100_000,
                "reteica_cop": 16_000,
                "total_cop": 3_884_000,
                "saldo_cop": 3_884_000,
                "estado": "PENDIENTE",
            }
        ]
    filas: list[dict[str, Any]] = []
    for indice, manual in enumerate(manuales[:8]):
        saldo = _numero(manual.get("saldo_cop"))
        ica = _numero(manual.get("ica_cop"))
        if indice == 1:
            ica += 12_476
        if indice == 2:
            saldo += 38_000
        filas.append(
            {
                "empresa_codigo": manual.get("empresa_codigo", "NOVASA"),
                "factura": manual.get("factura", ""),
                "fecha": manual.get("fecha"),
                "cliente": manual.get("cliente", ""),
                "descripcion_siigo": manual.get("descripcion", ""),
                "subtotal_siigo": _numero(manual.get("subtotal_cop")),
                "iva_siigo": _numero(manual.get("iva_cop")),
                "retefuente_siigo": _numero(manual.get("retefuente_cop")),
                "reteica_siigo": ica,
                "total_siigo": _numero(manual.get("total_cop")),
                "saldo_siigo": saldo,
                "estado_siigo": manual.get("estado", "PENDIENTE"),
                "moneda": "COP",
            }
        )
    return pd.DataFrame(filas)


def _render_cabecera() -> dict[str, Any]:
    st.markdown(
        '<div class="brand"><span class="brand-mark">◈</span>NOVASALUM</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="eyebrow" style="margin-top:1.25rem">Cartera y recaudo</div>', unsafe_allow_html=True)
    st.markdown("<h1 style='margin:.15rem 0'>Control de cartera</h1>", unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Consulta, registra y cobra sin perder de vista el saldo de cada empresa.</div>',
        unsafe_allow_html=True,
    )

    hoy = dt.date.today()
    opciones_empresa = [TODAS, *EMPRESAS]
    empresa = st.segmented_control(
        "Empresa",
        opciones_empresa,
        default=TODAS,
        format_func=lambda codigo: (
            "Todas las empresas"
            if codigo == TODAS
            else f"{EMPRESAS[codigo]['prefijo']} · {codigo}"
        ),
        key="filtro_empresa",
        width="stretch",
        label_visibility="collapsed",
    ) or TODAS
    empresa_consulta = None if empresa == TODAS else empresa
    clientes = db.listar_nombres_clientes(empresa_consulta)

    filtro_a, filtro_b, filtro_c, filtro_d = st.columns([1.55, 1.45, 1, 1])
    with filtro_a:
        cliente = st.selectbox(
            "Cliente",
            ["Todos los clientes", *clientes],
            index=0,
            key="filtro_cliente",
            placeholder="Selecciona o escribe un cliente",
            filter_mode="fuzzy",
        )
    with filtro_b:
        texto = st.text_input(
            "Buscar",
            placeholder="Factura, cliente, placa, ruta o manifiesto",
            key="filtro_texto",
        )
    with filtro_c:
        desde = st.date_input(
            "Desde",
            value=st.session_state.get("filtro_desde", hoy - dt.timedelta(days=90)),
            format="DD/MM/YYYY",
            key="filtro_desde",
        )
    with filtro_d:
        hasta = st.date_input(
            "Hasta",
            value=st.session_state.get("filtro_hasta", hoy),
            format="DD/MM/YYYY",
            key="filtro_hasta",
        )
    if desde > hasta:
        st.warning("La fecha inicial no puede ser posterior a la fecha final.")
        desde, hasta = hasta, desde

    return {
        "empresa": empresa,
        "empresa_consulta": empresa_consulta,
        "cliente": cliente,
        "texto": texto,
        "desde": desde,
        "hasta": hasta,
    }


def _render_resumen_general(
    facturas_visibles: list[dict[str, Any]],
    empresa: str,
) -> None:
    resumen = _resumen(facturas_visibles)
    porcentaje = (
        100 * resumen["abonos"] / resumen["facturado"]
        if resumen["facturado"] else 0
    )
    columnas = st.columns(4)
    with columnas[0]:
        _kpi(
            "Saldo pendiente",
            _cop(resumen["saldo"]),
            f"{resumen['pendientes']} factura(s) con saldo",
            principal=True,
        )
    with columnas[1]:
        _kpi("Total facturado", _cop(resumen["facturado"]), "Según los filtros activos")
    with columnas[2]:
        _kpi("Abonos recibidos", _cop(resumen["abonos"]), f"{porcentaje:.1f}% recaudado")
    with columnas[3]:
        _kpi("Facturas vencidas", str(resumen["vencidas"]), "Requieren seguimiento")

    st.caption(
        f"Avance de cobro del filtro: {porcentaje:.1f}% · {_cop(resumen['abonos'])} cobrados de {_cop(resumen['facturado'])} facturados."
    )
    st.progress(min(1.0, max(0.0, porcentaje / 100)))

    st.write("")
    _seccion("Saldo pendiente por empresa", "Este desglose permanece visible aunque filtres por una sola empresa.")
    saldos = db.resumen_saldos_por_empresa()
    empresa_columnas = st.columns(3)
    colores = {"NOVASA": "#2563EB", "LUAC": "#059669", "MSU": "#7C3AED"}
    for columna, codigo in zip(empresa_columnas, EMPRESAS):
        datos = saldos[codigo]
        with columna:
            st.markdown(
                f"""
                <div class="company-balance" style="border-left-color:{colores[codigo]}">
                    <span>{html.escape(EMPRESAS[codigo]["prefijo"])} · {html.escape(EMPRESAS[codigo]["nombre"])}</span>
                    <strong>{html.escape(_cop(datos["saldo_cop"]))}</strong>
                    <span>{datos["facturas_pendientes"]} factura(s) pendiente(s)</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _tabla_facturas(
    facturas: list[dict[str, Any]],
    *,
    mostrar_detalle: bool,
    mostrar_impuestos: bool,
) -> pd.DataFrame:
    filas: list[dict[str, Any]] = []
    for factura in facturas:
        fila = {
            "Factura": factura["factura"],
            "Emisión": _fecha_visible(factura.get("fecha")),
            "Cliente": factura.get("cliente", ""),
            "Placas": str(factura.get("placas") or "—").replace(",", " ·"),
            "Total": _cop(factura.get("total_cop")),
            "Abonos": _cop(factura.get("abonos_cop")),
            "Saldo pendiente": _cop(factura.get("saldo_cop")),
            "Estado": str(factura.get("estado", "")).replace("_", " ").title(),
        }
        if mostrar_impuestos:
            fila.update(
                {
                    "Subtotal": _cop(factura.get("subtotal_cop")),
                    "IVA": _cop(factura.get("iva_cop")),
                    "Retefuente": _cop(factura.get("retefuente_cop")),
                    "ICA": _cop(factura.get("ica_cop")),
                }
            )
        if mostrar_detalle:
            fila["Detalle del servicio"] = _acortar(factura.get("descripcion"), 88)
        filas.append(fila)
    return pd.DataFrame(filas)


def _seleccion_filas(evento: Any) -> list[int]:
    try:
        return list(evento.selection.rows)
    except (AttributeError, TypeError):
        return []


def _render_detalle_factura(factura: Mapping[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="detail-card">
            <div class="eyebrow">Factura seleccionada</div>
            <div style="display:flex;align-items:center;gap:.65rem;margin-top:.2rem">
                <strong style="font-size:1.15rem">{html.escape(str(factura["factura"]))}</strong>
                {_badge(str(factura["estado"]))}
            </div>
            <div style="margin-top:.45rem;color:#64748b;font-size:.88rem">{html.escape(str(factura["cliente"]))}</div>
            <div style="margin-top:.65rem">{_placas(factura.get("placas"))}</div>
            <div class="detail-text">{html.escape(str(factura.get("descripcion") or "Sin detalle del servicio"))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    acciones = st.columns([1, 1, 3])
    with acciones[0]:
        if st.button("Editar factura", key=f"editar_{factura['id']}", width="stretch"):
            st.session_state["factura_editando_id"] = int(factura["id"])
            st.info("La factura quedó lista en la pestaña Registrar / editar factura.")
    with acciones[1]:
        if st.button("Anular factura", key=f"anular_{factura['id']}", width="stretch"):
            try:
                db.anular_factura(int(factura["id"]))
            except db.ErrorCartera as exc:
                st.error(str(exc))
            else:
                st.success("Factura anulada. El movimiento sigue en auditoría.")
                st.rerun()


def _render_cartera(facturas: list[dict[str, Any]], contexto: Mapping[str, Any]) -> None:
    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Cartera operativa",
        "Selecciona una fila para abrir el detalle completo, editarla o anularla.",
    )
    controles_a, controles_b, controles_c = st.columns([1, 1, 3])
    with controles_a:
        mostrar_detalle = st.toggle(
            "Mostrar detalle en la tabla",
            value=False,
            key="tabla_mostrar_detalle",
        )
    with controles_b:
        mostrar_impuestos = st.toggle(
            "Mostrar impuestos",
            value=False,
            key="tabla_mostrar_impuestos",
        )
    with controles_c:
        st.caption(
            f"{len(facturas)} factura(s) visibles · los valores se muestran con puntos de miles y sin centavos."
        )

    if not facturas:
        st.markdown(
            '<div class="empty"><strong>No hay facturas para estos filtros.</strong><br>Registra una factura o carga una muestra para recorrer la aplicación.</div>',
            unsafe_allow_html=True,
        )
        if not db.hay_datos() and st.button("Cargar datos de demostración"):
            db.cargar_datos_demostracion()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    tabla = _tabla_facturas(
        facturas,
        mostrar_detalle=mostrar_detalle,
        mostrar_impuestos=mostrar_impuestos,
    )
    descarga = tabla.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Exportar vista CSV",
        data=descarga,
        file_name=f"cartera_{contexto['empresa']}_{dt.date.today().isoformat()}.csv",
        mime="text/csv",
    )
    st.markdown(
        """
        <div class="invoice-list-head">
            <span>Factura</span><span>Cliente y emisión</span><span>Placas</span>
            <span class="numeric">Total</span><span class="numeric">Abonos</span>
            <span class="numeric">Saldo pendiente</span><span>Estado</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for factura in facturas:
        estado = str(factura.get("estado") or "PENDIENTE")
        cliente = html.escape(str(factura.get("cliente") or "Sin cliente"))
        fecha = html.escape(_fecha_visible(factura.get("fecha")))
        st.markdown(
            f"""
            <div class="invoice-row">
                <div><span class="invoice-code">{html.escape(str(factura.get("factura") or ""))}</span></div>
                <div class="invoice-client"><strong>{cliente}</strong><div class="invoice-sub">Emisión {fecha}</div></div>
                <div>{_placas(factura.get("placas"))}</div>
                <div class="invoice-money"><span>Total</span><strong>{html.escape(_cop(factura.get("total_cop")))}</strong></div>
                <div class="invoice-money"><span>Abonos</span><strong>{html.escape(_cop(factura.get("abonos_cop")))}</strong></div>
                <div class="invoice-money invoice-balance"><span>Saldo</span><strong>{html.escape(_cop(factura.get("saldo_cop")))}</strong></div>
                <div>{_badge(estado)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        extras: list[str] = []
        if mostrar_detalle:
            extras.append(
                html.escape(_acortar(factura.get("descripcion"), 230))
            )
        if mostrar_impuestos:
            extras.append(
                "<span class=\"taxes\">"
                f"Subtotal {html.escape(_cop(factura.get('subtotal_cop')))} · "
                f"IVA {html.escape(_cop(factura.get('iva_cop')))} · "
                f"Retefuente {html.escape(_cop(factura.get('retefuente_cop')))} · "
                f"ICA {html.escape(_cop(factura.get('ica_cop')))}</span>"
            )
        if extras:
            st.markdown(
                f"<div class=\"invoice-extra\">{'<br>'.join(extras)}</div>",
                unsafe_allow_html=True,
            )
        with st.expander(
            f"Detalle completo · {factura.get('empresa_codigo')} · {factura.get('factura')}"
        ):
            _render_detalle_factura(factura)
    st.markdown("</div>", unsafe_allow_html=True)


def _asignar_valor_inicial(clave: str, valor: Any) -> None:
    if clave not in st.session_state:
        st.session_state[clave] = valor


def _sincronizar_prefijo(clave_empresa: str, clave_prefijo: str, clave_anterior: str) -> None:
    nueva = st.session_state[clave_empresa]
    anterior = st.session_state.get(clave_anterior)
    actual = str(st.session_state.get(clave_prefijo, "")).strip().upper()
    prefijo_anterior = EMPRESAS.get(str(anterior), {}).get("prefijo", "")
    if not actual or actual == prefijo_anterior:
        st.session_state[clave_prefijo] = EMPRESAS[nueva]["prefijo"]
    st.session_state[clave_anterior] = nueva


def _porcentaje(monto: Any, base: Any) -> float:
    base_numero = _numero(base)
    return round(100 * _numero(monto) / base_numero, 4) if base_numero else 0.0


def _plantilla_coincidente(
    subtotal: int,
    valores: Mapping[str, Any] | None,
) -> str | None:
    if not valores:
        return None
    for nombre, plantilla in PLANTILLAS.items():
        if (
            _numero(valores.get("iva_cop")) == int(round(subtotal * plantilla["iva"] / 100))
            and _numero(valores.get("retefuente_cop"))
            == int(round(subtotal * plantilla["retefuente"] / 100))
            and _numero(valores.get("ica_cop")) == int(round(subtotal * plantilla["ica"] / 100))
        ):
            return nombre
    return None


def _render_calculo_impuestos(
    *,
    token: str,
    subtotal: int,
    valores_actuales: Mapping[str, Any] | None,
) -> tuple[int, int, int, str]:
    actual = valores_actuales or {}
    clave_modo = f"{token}_modo_impuestos"
    plantilla_existente = _plantilla_coincidente(subtotal, valores_actuales)
    modo_inicial = (
        "Plantilla"
        if not valores_actuales or plantilla_existente
        else "Valores manuales"
    )
    _asignar_valor_inicial(clave_modo, modo_inicial)
    modo = st.segmented_control(
        "Forma de calcular impuestos",
        ["Plantilla", "Porcentajes", "Valores manuales"],
        key=clave_modo,
        width="stretch",
    ) or "Plantilla"
    columnas = st.columns(4)
    with columnas[0]:
        st.metric("Subtotal", _cop(subtotal))

    if modo == "Plantilla":
        clave_plantilla = f"{token}_plantilla"
        _asignar_valor_inicial(
            clave_plantilla,
            plantilla_existente or "Transporte estándar",
        )
        plantilla_nombre = st.selectbox(
            "Plantilla",
            list(PLANTILLAS),
            key=clave_plantilla,
            format_func=lambda clave: (
                f"{clave} · {PLANTILLAS[clave]['descripcion']}"
            ),
        )
        plantilla = PLANTILLAS[plantilla_nombre]
        iva = int(round(subtotal * plantilla["iva"] / 100))
        retefuente = int(round(subtotal * plantilla["retefuente"] / 100))
        ica = int(round(subtotal * plantilla["ica"] / 100))
        with columnas[1]:
            st.metric(f"IVA · {plantilla['iva']:g}%", _cop(iva))
        with columnas[2]:
            st.metric(f"Retefuente · {plantilla['retefuente']:g}%", _cop(retefuente))
        with columnas[3]:
            st.metric(f"ICA · {plantilla['ica']:g}%", _cop(ica))
        detalle = f"Plantilla: {plantilla_nombre}"
    elif modo == "Porcentajes":
        clave_iva = f"{token}_pct_iva"
        clave_rete = f"{token}_pct_rete"
        clave_ica = f"{token}_pct_ica"
        _asignar_valor_inicial(clave_iva, _porcentaje(actual.get("iva_cop"), subtotal))
        _asignar_valor_inicial(
            clave_rete,
            _porcentaje(actual.get("retefuente_cop"), subtotal),
        )
        _asignar_valor_inicial(clave_ica, _porcentaje(actual.get("ica_cop"), subtotal))
        with columnas[1]:
            porcentaje_iva = st.number_input(
                "% IVA",
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                key=clave_iva,
            )
        with columnas[2]:
            porcentaje_rete = st.number_input(
                "% Retefuente",
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                key=clave_rete,
            )
        with columnas[3]:
            porcentaje_ica = st.number_input(
                "% ICA",
                min_value=0.0,
                max_value=100.0,
                step=0.01,
                key=clave_ica,
            )
        iva = int(round(subtotal * porcentaje_iva / 100))
        retefuente = int(round(subtotal * porcentaje_rete / 100))
        ica = int(round(subtotal * porcentaje_ica / 100))
        st.caption(
            f"Resultado: IVA {_cop(iva)} · Retefuente {_cop(retefuente)} · ICA {_cop(ica)}"
        )
        detalle = "Cálculo por porcentajes"
    else:
        clave_iva = f"{token}_valor_iva"
        clave_rete = f"{token}_valor_rete"
        clave_ica = f"{token}_valor_ica"
        _asignar_valor_inicial(clave_iva, _numero(actual.get("iva_cop")))
        _asignar_valor_inicial(clave_rete, _numero(actual.get("retefuente_cop")))
        _asignar_valor_inicial(clave_ica, _numero(actual.get("ica_cop")))
        with columnas[1]:
            iva = int(
                st.number_input(
                    "IVA (COP)",
                    min_value=0,
                    step=1_000,
                    key=clave_iva,
                )
            )
            st.caption(_cop(iva))
        with columnas[2]:
            retefuente = int(
                st.number_input(
                    "Retefuente (COP)",
                    min_value=0,
                    step=1_000,
                    key=clave_rete,
                )
            )
            st.caption(_cop(retefuente))
        with columnas[3]:
            ica = int(
                st.number_input(
                    "ICA (COP)",
                    min_value=0,
                    step=1_000,
                    key=clave_ica,
                )
            )
            st.caption(_cop(ica))
        detalle = "Valores ingresados manualmente"
    return iva, retefuente, ica, detalle


def _render_registro_factura(contexto: Mapping[str, Any]) -> None:
    editando_id = st.session_state.get("factura_editando_id")
    factura = db.obtener_factura(editando_id) if editando_id else None
    token = f"editar_{editando_id}" if factura else "nueva_factura"
    creando = factura is None
    empresa_defecto = (
        str(factura["empresa_codigo"])
        if factura
        else (
            str(contexto["empresa"])
            if contexto["empresa"] != TODAS
            else "NOVASA"
        )
    )
    cliente_defecto = str(factura["cliente"]) if factura else ""
    subtotal_defecto = _numero(factura.get("subtotal_cop")) if factura else 0
    fecha_defecto = _fecha(factura.get("fecha")) if factura else dt.date.today()
    vencimiento_defecto = (
        _fecha(factura.get("vencimiento"))
        if factura and factura.get("vencimiento")
        else dt.date.today() + dt.timedelta(days=30)
    )

    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Registrar factura" if creando else f"Editar {factura['factura']}",
        "El prefijo se propone según la empresa, pero siempre puedes cambiarlo. El cliente se elige o se escribe una sola vez.",
    )
    if factura:
        aviso, cancelar = st.columns([4, 1])
        with aviso:
            st.info(
                "Los cambios de empresa o cliente están bloqueados si la factura ya tiene abonos aplicados."
            )
        with cancelar:
            if st.button("Cancelar edición", key=f"{token}_cancelar", width="stretch"):
                st.session_state["factura_editando_id"] = None
                st.rerun()

    clave_empresa = f"{token}_empresa"
    clave_prefijo = f"{token}_prefijo"
    clave_empresa_anterior = f"{token}_empresa_anterior"
    _asignar_valor_inicial(clave_empresa, empresa_defecto)
    _asignar_valor_inicial(clave_prefijo, str(factura["prefijo"]) if factura else EMPRESAS[empresa_defecto]["prefijo"])
    _asignar_valor_inicial(clave_empresa_anterior, empresa_defecto)
    _asignar_valor_inicial(f"{token}_numero", str(factura["numero"]) if factura else "")
    clave_cliente = f"{token}_cliente"
    if cliente_defecto:
        _asignar_valor_inicial(clave_cliente, cliente_defecto)
    elif st.session_state.get(clave_cliente) == "":
        # Un selectbox sin selección debe conservar None. Un texto vacío queda
        # fuera de las opciones cuando aparecen clientes y rompe la edición.
        del st.session_state[clave_cliente]
    _asignar_valor_inicial(f"{token}_fecha", fecha_defecto)
    _asignar_valor_inicial(f"{token}_vencimiento", vencimiento_defecto)
    _asignar_valor_inicial(f"{token}_placas", str(factura["placas"]) if factura else "")
    _asignar_valor_inicial(f"{token}_detalle", str(factura["descripcion"]) if factura else "")
    _asignar_valor_inicial(f"{token}_subtotal", subtotal_defecto)

    fila_a, fila_b, fila_c, fila_d = st.columns([1.05, .9, 1.05, 1.8])
    with fila_a:
        empresa = st.selectbox(
            "Empresa",
            list(EMPRESAS),
            key=clave_empresa,
            format_func=lambda codigo: f"{EMPRESAS[codigo]['prefijo']} · {EMPRESAS[codigo]['nombre']}",
            on_change=_sincronizar_prefijo,
            args=(clave_empresa, clave_prefijo, clave_empresa_anterior),
            disabled=bool(factura and _numero(factura.get("abonos_cop")) > 0),
        )
    with fila_b:
        prefijo = st.text_input(
            "Prefijo",
            max_chars=10,
            key=clave_prefijo,
            help="Se propone con la empresa, pero es completamente editable.",
        ).upper()
    with fila_c:
        numero = st.text_input(
            "Número de factura",
            max_chars=24,
            placeholder="Ejemplo: 1079",
            key=f"{token}_numero",
        ).upper()
    with fila_d:
        clientes = db.listar_nombres_clientes(empresa)
        cliente = st.selectbox(
            "Cliente",
            clientes,
            index=None,
            key=clave_cliente,
            placeholder="Selecciona o escribe un cliente nuevo",
            accept_new_options=True,
            filter_mode="fuzzy",
            disabled=bool(factura and _numero(factura.get("abonos_cop")) > 0),
        )

    fecha_col, vencimiento_col, placas_col = st.columns([1, 1, 2])
    with fecha_col:
        fecha = st.date_input(
            "Fecha de emisión",
            format="DD/MM/YYYY",
            key=f"{token}_fecha",
        )
    with vencimiento_col:
        vencimiento = st.date_input(
            "Fecha de vencimiento",
            format="DD/MM/YYYY",
            key=f"{token}_vencimiento",
        )
    with placas_col:
        placas = st.text_input(
            "Placas o equipos",
            placeholder="SOQ766, TAW897",
            key=f"{token}_placas",
        ).upper()
    detalle = st.text_area(
        "Detalle del servicio",
        placeholder="Ruta, manifiesto, orden de servicio u observación",
        height=108,
        key=f"{token}_detalle",
    )
    subtotal = int(
        st.number_input(
            "Subtotal (COP)",
            min_value=0,
            step=1_000,
            key=f"{token}_subtotal",
        )
    )
    st.caption(f"Subtotal digitado: {_cop(subtotal)}")
    iva, retefuente, ica, origen_calculo = _render_calculo_impuestos(
        token=token,
        subtotal=subtotal,
        valores_actuales=factura,
    )
    total = subtotal + iva - retefuente - ica
    st.markdown(
        f"""
        <div class="detail-card" style="margin-top:.8rem">
            <div class="eyebrow">{html.escape(origen_calculo)}</div>
            <div style="font-size:1.35rem;font-weight:800;color:#2563eb;margin-top:.25rem">Total de factura · {html.escape(_cop(total))}</div>
            <div style="font-size:.84rem;color:#64748b;margin-top:.35rem">Subtotal {_cop(subtotal)} + IVA {_cop(iva)} − Retefuente {_cop(retefuente)} − ICA {_cop(ica)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    etiqueta_guardar = "Guardar factura" if creando else "Actualizar factura"
    if st.button(etiqueta_guardar, type="primary", key=f"{token}_guardar", width="stretch"):
        if not str(cliente or "").strip():
            st.error("Selecciona o escribe un cliente.")
        elif not prefijo.strip() or not numero.strip():
            st.error("El prefijo y el número de factura son obligatorios.")
        elif total <= 0:
            st.error("El total de la factura debe ser mayor que cero.")
        else:
            datos = {
                "empresa_codigo": empresa,
                "prefijo": prefijo,
                "numero": numero,
                "cliente": str(cliente).strip(),
                "nit": "",
                "fecha": fecha,
                "vencimiento": vencimiento,
                "descripcion": detalle.strip(),
                "placas": placas.strip(),
                "subtotal_cop": subtotal,
                "iva_cop": iva,
                "retefuente_cop": retefuente,
                "ica_cop": ica,
            }
            try:
                if factura:
                    db.actualizar_campos_factura(int(factura["id"]), datos)
                    st.session_state["factura_editando_id"] = None
                    st.success("Factura actualizada.")
                else:
                    db.crear_factura(datos)
                    st.success("Factura registrada.")
                st.rerun()
            except db.ErrorCartera as exc:
                st.error(str(exc))
    st.markdown("</div>", unsafe_allow_html=True)


def _resumen_clientes(facturas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agrupados: dict[str, dict[str, Any]] = {}
    for factura in facturas:
        if factura.get("estado") == "ANULADA":
            continue
        cliente = str(factura.get("cliente") or "Sin cliente")
        fila = agrupados.setdefault(
            cliente,
            {
                "cliente": cliente,
                "facturas": 0,
                "pendientes": 0,
                "facturado": 0,
                "cobrado": 0,
                "saldo": 0,
            },
        )
        fila["facturas"] += 1
        fila["facturado"] += _numero(factura.get("total_cop"))
        fila["cobrado"] += _numero(factura.get("abonos_cop"))
        saldo = _numero(factura.get("saldo_cop"))
        fila["saldo"] += saldo
        if saldo > 0:
            fila["pendientes"] += 1
    return sorted(
        agrupados.values(),
        key=lambda fila: (fila["saldo"], str(fila["cliente"]).casefold()),
    )


def _render_clientes_recaudo(facturas: list[dict[str, Any]]) -> None:
    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Clientes y avance de recaudo",
        "La tabla está ordenada de menor a mayor saldo pendiente. El gráfico muestra cuánto se ha cobrado y qué falta por cobrar.",
    )
    resumen = _resumen_clientes(facturas)
    if not resumen:
        st.markdown(
            '<div class="empty"><strong>No hay clientes para estos filtros.</strong></div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    filas = [
        {
            "Cliente": fila["cliente"],
            "Facturas": fila["facturas"],
            "Pendientes": fila["pendientes"],
            "Facturado": _cop(fila["facturado"]),
            "Cobrado": _cop(fila["cobrado"]),
            "Saldo pendiente": _cop(fila["saldo"]),
            "Avance": f"{(100 * fila['cobrado'] / fila['facturado']) if fila['facturado'] else 0:.1f}%",
        }
        for fila in resumen
    ]
    st.dataframe(
        pd.DataFrame(filas),
        width="stretch",
        hide_index=True,
        column_config={
            "Cliente": st.column_config.TextColumn(width="large"),
            "Saldo pendiente": st.column_config.TextColumn(width="medium"),
        },
    )
    st.write("")
    grafico_base: list[dict[str, Any]] = []
    for fila in resumen:
        for estado, valor, color in (
            ("Cobrado", fila["cobrado"], "#16A34A"),
            ("Pendiente", fila["saldo"], "#2563EB"),
        ):
            grafico_base.append(
                {
                    "Cliente": fila["cliente"],
                    "Estado": estado,
                    "Valor": valor,
                    "Valor visible": _cop(valor),
                    "Color": color,
                }
            )
    datos_grafico = pd.DataFrame(grafico_base)
    orden = [fila["cliente"] for fila in reversed(resumen)]
    grafico = (
        alt.Chart(datos_grafico)
        .mark_bar(cornerRadiusEnd=5)
        .encode(
            y=alt.Y("Cliente:N", sort=orden, title=None),
            x=alt.X("Valor:Q", stack="zero", title="Pesos colombianos"),
            color=alt.Color(
                "Estado:N",
                scale=alt.Scale(
                    domain=["Cobrado", "Pendiente"],
                    range=["#16A34A", "#2563EB"],
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("Cliente:N"),
                alt.Tooltip("Estado:N"),
                alt.Tooltip("Valor visible:N", title="Valor"),
            ],
        )
        .properties(height=max(220, min(520, 42 * len(resumen))), title="Avance de cobro por cliente")
    )
    st.altair_chart(grafico, width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_abonos(contexto: Mapping[str, Any]) -> None:
    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Registrar abono",
        "El pago puede aplicarse automáticamente a las facturas más antiguas o repartirse manualmente.",
    )
    empresa = contexto["empresa_consulta"]
    clientes = db.clientes_con_saldo(empresa)
    if not clientes:
        st.markdown(
            '<div class="empty"><strong>No hay clientes con saldo pendiente.</strong></div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    opciones: dict[str, dict[str, Any]] = {}
    for cliente in clientes:
        etiqueta = (
            f"{cliente['cliente']} · {cliente['empresa_codigo']} · {_cop(cliente['saldo_cop'])}"
        )
        opciones[etiqueta] = cliente
    etiqueta_cliente = st.selectbox(
        "Cliente que realizó el pago",
        list(opciones),
        key="abono_cliente",
        filter_mode="fuzzy",
    )
    cliente = opciones[etiqueta_cliente]
    facturas = db.facturas_pendientes_cliente(
        cliente["empresa_codigo"],
        int(cliente["cliente_id"]),
    )
    cabecera_a, cabecera_b, cabecera_c = st.columns([1, 1, 1.35])
    with cabecera_a:
        monto = int(
            st.number_input(
                "Monto recibido (COP)",
                min_value=0,
                value=0,
                step=1_000,
                key="abono_monto",
            )
        )
        st.caption(_cop(monto))
    with cabecera_b:
        fecha = st.date_input(
            "Fecha de pago",
            value=dt.date.today(),
            format="DD/MM/YYYY",
            key="abono_fecha",
        )
    with cabecera_c:
        referencia = st.text_input(
            "Referencia bancaria",
            placeholder="Recibo, transferencia o comprobante",
            key="abono_referencia",
        )
    fifo = st.toggle(
        "Aplicar a las facturas más antiguas (FIFO)",
        value=True,
        key="abono_fifo",
    )

    aplicaciones: list[dict[str, Any]]
    sobrante = 0
    if fifo:
        aplicaciones, sobrante = (
            db.previsualizar_fifo(facturas, monto) if monto > 0 else ([], 0)
        )
    else:
        datos = pd.DataFrame(
            [
                {
                    "Factura": fila["factura"],
                    "Fecha": _fecha_visible(fila["fecha"]),
                    "Saldo actual": _cop(fila["saldo_cop"]),
                    "Aplicar (COP)": 0,
                    "_id": int(fila["id"]),
                }
                for fila in facturas
            ]
        )
        editado = st.data_editor(
            datos,
            width="stretch",
            hide_index=True,
            disabled=["Factura", "Fecha", "Saldo actual", "_id"],
            key=f"abono_manual_{cliente['empresa_codigo']}_{cliente['cliente_id']}",
            column_config={
                "Aplicar (COP)": st.column_config.NumberColumn(min_value=0, step=1_000),
                "_id": None,
            },
        )
        aplicaciones = [
            {"factura_id": int(fila["_id"]), "monto_cop": _numero(fila["Aplicar (COP)"])}
            for _, fila in editado.iterrows()
            if _numero(fila["Aplicar (COP)"]) > 0
        ]
        sobrante = max(0, monto - sum(_numero(fila["monto_cop"]) for fila in aplicaciones))

    por_id = {int(fila["id"]): fila for fila in facturas}
    previa = []
    for aplicacion in aplicaciones:
        factura = por_id[int(aplicacion["factura_id"])]
        aplicado = _numero(aplicacion["monto_cop"])
        saldo_nuevo = _numero(factura["saldo_cop"]) - aplicado
        previa.append(
            {
                "Factura": factura["factura"],
                "Saldo antes": _cop(factura["saldo_cop"]),
                "Aplicar": _cop(aplicado),
                "Saldo después": _cop(saldo_nuevo),
                "Resultado": "Pagada" if saldo_nuevo == 0 else "Abonada",
            }
        )
    st.markdown("##### Vista previa de aplicación")
    if previa:
        st.dataframe(pd.DataFrame(previa), width="stretch", hide_index=True)
    else:
        st.caption("Ingresa un monto para ver la distribución del abono.")
    aplicacion_total = sum(_numero(fila["monto_cop"]) for fila in aplicaciones)
    resumen = st.columns(3)
    resumen[0].metric("Recibido", _cop(monto))
    resumen[1].metric("Aplicado", _cop(aplicacion_total))
    resumen[2].metric("Saldo a favor", _cop(sobrante))
    if sobrante:
        st.info("El excedente se registrará como saldo a favor del cliente.")
    if st.button("Aplicar abono", type="primary", width="stretch"):
        try:
            db.registrar_abono(
                empresa_codigo=cliente["empresa_codigo"],
                cliente_id=int(cliente["cliente_id"]),
                fecha=fecha,
                referencia=referencia,
                monto_cop=monto,
                aplicaciones=aplicaciones,
            )
        except db.ErrorCartera as exc:
            st.error(str(exc))
        else:
            st.success("Abono aplicado correctamente.")
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _comparar_carteras(
    manuales: list[dict[str, Any]],
    siigo: pd.DataFrame,
) -> list[dict[str, Any]]:
    por_manual = {
        (str(fila["empresa_codigo"]), normalizar_factura(fila["factura"])): fila
        for fila in manuales
    }
    por_siigo: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(siigo, pd.DataFrame) and not siigo.empty:
        for _, fila in siigo.iterrows():
            empresa = str(fila.get("empresa_codigo") or "").upper()
            clave = normalizar_factura(fila.get("factura") or "")
            if empresa and clave:
                por_siigo[(empresa, clave)] = {
                    campo: (None if pd.isna(valor) else valor)
                    for campo, valor in dict(fila).items()
                }
    salida: list[dict[str, Any]] = []
    for empresa, clave in sorted(set(por_manual) | set(por_siigo)):
        manual = por_manual.get((empresa, clave))
        oficial = por_siigo.get((empresa, clave))
        diferencias: dict[str, int | None] = {
            "saldo": None,
            "iva": None,
            "retefuente": None,
            "ica": None,
        }
        if manual is None:
            estado = "SOLO_SIIGO"
        elif oficial is None:
            estado = "SOLO_MANUAL"
        else:
            diferencias = {
                "saldo": _numero(manual.get("saldo_cop")) - _numero(oficial.get("saldo_siigo")),
                "iva": _numero(manual.get("iva_cop")) - _numero(oficial.get("iva_siigo")),
                "retefuente": _numero(manual.get("retefuente_cop")) - _numero(oficial.get("retefuente_siigo")),
                "ica": _numero(manual.get("ica_cop")) - _numero(oficial.get("reteica_siigo")),
            }
            if all(abs(valor or 0) <= 1 for valor in diferencias.values()):
                estado = "CUADRADO"
            elif abs(diferencias["saldo"] or 0) <= 1:
                estado = "DIFERENCIA_IMPUESTOS"
            else:
                estado = "DESCUADRE"
        fuente = manual or oficial or {}
        salida.append(
            {
                "empresa": empresa,
                "clave": clave,
                "factura": fuente.get("factura", clave),
                "cliente": fuente.get("cliente", ""),
                "estado": estado,
                "manual": manual,
                "siigo": oficial,
                **diferencias,
            }
        )
    return salida


def _tabla_siigo(facturas: pd.DataFrame) -> pd.DataFrame:
    filas: list[dict[str, Any]] = []
    for _, fila in facturas.iterrows():
        filas.append(
            {
                "Empresa": fila.get("empresa_codigo", ""),
                "Factura": fila.get("factura", ""),
                "Fecha": _fecha_visible(fila.get("fecha")),
                "Cliente": fila.get("cliente", ""),
                "Detalle": _acortar(fila.get("descripcion_siigo", ""), 68),
                "Total": _cop(fila.get("total_siigo")),
                "Saldo Siigo": _cop(fila.get("saldo_siigo")),
                "Estado": str(fila.get("estado_siigo", "")).replace("_", " ").title(),
            }
        )
    return pd.DataFrame(filas)


def _render_lado_conciliacion(
    titulo: str,
    tipo: str,
    fila: Mapping[str, Any] | None,
) -> None:
    if fila is None:
        st.markdown(
            f'<div class="detail-card"><strong>{html.escape(titulo)}</strong><div class="detail-text">Esta factura no existe en esta fuente.</div></div>',
            unsafe_allow_html=True,
        )
        return
    es_siigo = tipo == "siigo"
    def campo(manual: str, oficial: str) -> str:
        return oficial if es_siigo else manual
    lineas = [
        ("Cliente", fila.get("cliente", "—")),
        ("Fecha", _fecha_visible(fila.get("fecha"))),
        ("Subtotal", _cop(fila.get(campo("subtotal_cop", "subtotal_siigo")))),
        ("IVA", _cop(fila.get(campo("iva_cop", "iva_siigo")))),
        ("Retefuente", _cop(fila.get(campo("retefuente_cop", "retefuente_siigo")))),
        ("ICA", _cop(fila.get(campo("ica_cop", "reteica_siigo")))),
        ("Saldo", _cop(fila.get(campo("saldo_cop", "saldo_siigo")))),
    ]
    lineas_html = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:.48rem 0;border-bottom:1px solid #e7edf5;font-size:.86rem"><span style="color:#64748b">{html.escape(etiqueta)}</span><strong>{html.escape(str(valor))}</strong></div>'
        for etiqueta, valor in lineas
    )
    detalle = fila.get("descripcion_siigo" if es_siigo else "descripcion", "")
    st.markdown(
        f"""
        <div class="detail-card">
            <strong>{html.escape(titulo)}</strong>
            <div style="margin-top:.55rem">{lineas_html}</div>
            <div class="detail-text">{html.escape(str(detalle or "Sin detalle"))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_conciliacion(manuales: list[dict[str, Any]], siigo: pd.DataFrame) -> None:
    filas = _comparar_carteras(manuales, siigo)
    if not filas:
        st.caption("No hay facturas para comparar.")
        return
    conteos = {estado: sum(1 for fila in filas if fila["estado"] == estado) for estado in ESTADO_TONO}
    columnas = st.columns(4)
    columnas[0].metric("Cuadradas", conteos["CUADRADO"])
    columnas[1].metric("Impuestos por revisar", conteos["DIFERENCIA_IMPUESTOS"])
    columnas[2].metric("Descuadres", conteos["DESCUADRE"])
    columnas[3].metric("Solo en una fuente", conteos["SOLO_MANUAL"] + conteos["SOLO_SIIGO"])
    tabla = pd.DataFrame(
        [
            {
                "Estado": str(fila["estado"]).replace("_", " ").title(),
                "Empresa": fila["empresa"],
                "Factura": fila["factura"],
                "Cliente": fila["cliente"],
                "Saldo manual": _cop(fila["manual"].get("saldo_cop")) if fila["manual"] else "—",
                "Saldo Siigo": _cop(fila["siigo"].get("saldo_siigo")) if fila["siigo"] else "—",
                "Diferencia": _cop(fila["saldo"]) if fila["saldo"] is not None else "—",
            }
            for fila in filas
        ]
    )
    evento = st.dataframe(
        tabla,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="tabla_conciliacion",
    )
    seleccion = _seleccion_filas(evento)
    if seleccion and 0 <= seleccion[0] < len(filas):
        fila = filas[seleccion[0]]
        st.write("")
        st.markdown(_badge(fila["estado"]), unsafe_allow_html=True)
        manual_col, siigo_col = st.columns(2)
        with manual_col:
            _render_lado_conciliacion("Cartera manual", "manual", fila["manual"])
        with siigo_col:
            _render_lado_conciliacion("Cartera Siigo", "siigo", fila["siigo"])
        nota = st.text_area(
            "Observación de revisión",
            placeholder="Qué se verificó o cuál es la siguiente acción.",
            max_chars=1_500,
            key=f"nota_{fila['empresa']}_{fila['clave']}",
        )
        if st.button("Guardar revisión", type="primary", key=f"revisar_{fila['empresa']}_{fila['clave']}"):
            db.guardar_revision_conciliacion(
                empresa_codigo=fila["empresa"],
                factura_clave=fila["clave"],
                estado=fila["estado"],
                observacion=nota,
                manual=fila["manual"],
                siigo=fila["siigo"],
            )
            st.success("Revisión guardada. Siigo no fue modificado.")


def _render_siigo(contexto: Mapping[str, Any], manuales: list[dict[str, Any]]) -> None:
    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Espejo de Siigo y conciliación",
        "La lectura de Siigo es oficial y de solo consulta. Los cambios de la cartera manual nunca se envían a Siigo.",
    )
    configuracion, errores_config = _configuracion_siigo()
    disponibles = list(configuracion.empresas.keys()) if configuracion else []
    empresa_preferida = (
        [contexto["empresa"]]
        if contexto["empresa"] != TODAS and contexto["empresa"] in disponibles
        else disponibles
    )
    controles_a, controles_b = st.columns([2, 1])
    with controles_a:
        empresas = st.multiselect(
            "Empresas para consultar",
            list(EMPRESAS),
            default=empresa_preferida,
            format_func=lambda codigo: f"{EMPRESAS[codigo]['prefijo']} · {codigo}",
            key="siigo_empresas",
        )
    with controles_b:
        consultar = st.button("Consultar Siigo", type="primary", width="stretch")
        muestra = st.button("Cargar muestra visual", width="stretch")
    if consultar:
        if not configuracion:
            st.error("No hay credenciales de Siigo configuradas.")
        elif not empresas:
            st.warning("Selecciona al menos una empresa.")
        else:
            with st.spinner("Leyendo datos de Siigo…"):
                facturas, recibos, errores = _consultar_siigo(
                    configuracion,
                    empresas,
                    contexto["desde"],
                    contexto["hasta"],
                )
            st.session_state["siigo_facturas"] = facturas
            st.session_state["siigo_recibos"] = recibos
            st.session_state["siigo_errores"] = errores
            st.session_state["siigo_origen"] = "Lectura directa"
            st.session_state["siigo_marca"] = dt.datetime.now().astimezone()
    if muestra:
        st.session_state["siigo_facturas"] = _muestra_siigo(manuales)
        st.session_state["siigo_recibos"] = pd.DataFrame()
        st.session_state["siigo_errores"] = {}
        st.session_state["siigo_origen"] = "Muestra visual"
        st.session_state["siigo_marca"] = dt.datetime.now().astimezone()

    if not configuracion:
        st.caption(
            "Puedes cargar una muestra visual mientras se configuran las credenciales de Siigo."
        )
    elif errores_config:
        st.caption("Algunas empresas no tienen credenciales; se puede consultar el resto.")
    facturas_siigo = st.session_state.get("siigo_facturas", pd.DataFrame())
    if isinstance(facturas_siigo, pd.DataFrame) and not facturas_siigo.empty:
        if contexto["empresa"] != TODAS and "empresa_codigo" in facturas_siigo.columns:
            facturas_siigo = facturas_siigo[
                facturas_siigo["empresa_codigo"].astype(str).eq(contexto["empresa"])
            ].copy()
        marca = st.session_state.get("siigo_marca")
        if marca:
            st.caption(f"{st.session_state.get('siigo_origen', 'Lectura')}: {marca:%d/%m/%Y %H:%M:%S %Z}")
        for nombre, error in st.session_state.get("siigo_errores", {}).items():
            st.warning(f"{nombre}: {error}")
        st.dataframe(_tabla_siigo(facturas_siigo), width="stretch", hide_index=True)
        st.write("")
        _seccion("Conciliación factura por factura", "Selecciona una fila para comparar manual y Siigo lado a lado.")
        _render_conciliacion(manuales, facturas_siigo)
    else:
        st.markdown(
            '<div class="empty"><strong>Aún no hay lectura de Siigo.</strong><br>Consulta datos reales o carga la muestra visual.</div>',
            unsafe_allow_html=True,
        )
    with st.expander("Configurar conexión Siigo"):
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
        st.caption("Estas claves se guardan en .streamlit/secrets.toml y nunca se muestran en pantalla.")
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    _estilos()
    db.inicializar()
    contexto = _render_cabecera()
    todas = db.listar_facturas(
        contexto["empresa_consulta"],
        incluir_anuladas=True,
    )
    visibles = _filtrar_facturas(
        todas,
        cliente=contexto["cliente"],
        texto=contexto["texto"],
        desde=contexto["desde"],
        hasta=contexto["hasta"],
    )
    st.write("")
    _render_resumen_general(visibles, contexto["empresa"])
    st.write("")
    cartera_tab, registro_tab, clientes_tab, abonos_tab, siigo_tab = st.tabs(
        [
            "Cartera",
            "Registrar / editar factura",
            "Clientes y recaudo",
            "Abonos FIFO",
            "Siigo y conciliación",
        ]
    )
    with cartera_tab:
        _render_cartera(visibles, contexto)
    with registro_tab:
        _render_registro_factura(contexto)
    with clientes_tab:
        _render_clientes_recaudo(visibles)
    with abonos_tab:
        _render_abonos(contexto)
    with siigo_tab:
        _render_siigo(contexto, visibles)
