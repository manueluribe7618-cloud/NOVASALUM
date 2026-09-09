"""Aplicación Streamlit de NOVASALUM.

Ejecutar localmente:

    streamlit run app.py

La cartera manual se conserva en la base local configurada por NOVASALUM_DB.
Siigo se consulta en vivo y sus resultados solo permanecen en la sesión actual.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
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
from src.formato import fmt_cop
from src.siigo import (
    ClienteSiigo,
    ConfiguracionSiigo,
    ErrorConfiguracionSiigo,
    ErrorSiigo,
)


st.set_page_config(
    page_title="NOVASALUM · Cartera",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


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
    "SOLO_MANUAL": ("Solo manual", "rojo"),
    "SOLO_SIIGO": ("Solo Siigo", "rojo"),
}


def _estilos() -> None:
    st.markdown(
        """
        <style>
            :root {
                --ink: #172033;
                --muted: #65738a;
                --canvas: #f8fafc;
                --line: #e5eaf1;
                --blue: #2563eb;
                --blue-dark: #1e3a8a;
                --green: #16a34a;
                --amber: #d97706;
                --red: #dc2626;
                --violet: #7c3aed;
            }
            .stApp, [data-testid="stAppViewContainer"] {
                background: var(--canvas);
                color: var(--ink);
            }
            [data-testid="stHeader"] {
                background: rgba(248, 250, 252, .92);
            }
            [data-testid="stSidebar"] {
                background: #ffffff;
                border-right: 1px solid var(--line);
            }
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
                color: var(--muted);
            }
            .block-container {
                max-width: 1540px;
                padding-top: 2rem;
                padding-bottom: 3rem;
            }
            h1, h2, h3 {
                color: var(--ink) !important;
                letter-spacing: -0.025em;
            }
            .brand {
                display: flex;
                align-items: center;
                gap: .7rem;
                font-weight: 800;
                letter-spacing: -.03em;
                color: var(--ink);
                font-size: 1.2rem;
            }
            .brand-mark {
                display: inline-grid;
                width: 30px;
                height: 30px;
                place-items: center;
                border-radius: 9px;
                color: white;
                background: linear-gradient(135deg, #1e3a8a, #2563eb);
                box-shadow: 0 6px 14px rgba(37, 99, 235, .22);
            }
            .eyebrow {
                color: var(--muted);
                font-size: .78rem;
                font-weight: 700;
                letter-spacing: .09em;
                text-transform: uppercase;
                margin-bottom: .35rem;
            }
            .page-subtitle {
                color: var(--muted);
                margin-top: -.35rem;
                margin-bottom: 1.15rem;
                font-size: .95rem;
            }
            .kpi-card {
                min-height: 122px;
                padding: 1.05rem 1.15rem;
                border: 1px solid var(--line);
                border-radius: 16px;
                background: #fff;
                box-shadow: 0 6px 18px rgba(15, 23, 42, .045);
            }
            .kpi-label {
                color: var(--muted);
                font-size: .8rem;
                font-weight: 700;
                letter-spacing: .025em;
                text-transform: uppercase;
            }
            .kpi-value {
                margin-top: .5rem;
                color: var(--ink);
                font-size: 1.52rem;
                font-weight: 800;
                line-height: 1.15;
                letter-spacing: -.035em;
            }
            .kpi-detail {
                margin-top: .45rem;
                color: var(--muted);
                font-size: .82rem;
            }
            .kpi-card.saldo {
                border-color: rgba(37, 99, 235, .28);
                background: linear-gradient(135deg, #eff6ff, #ffffff 72%);
            }
            .kpi-card.saldo .kpi-value { color: var(--blue); }
            .surface {
                padding: 1.15rem;
                border: 1px solid var(--line);
                border-radius: 16px;
                background: #fff;
                box-shadow: 0 5px 16px rgba(15, 23, 42, .035);
            }
            .surface-title {
                color: var(--ink);
                font-weight: 800;
                font-size: 1rem;
                letter-spacing: -.015em;
            }
            .surface-subtitle {
                margin-top: .18rem;
                color: var(--muted);
                font-size: .83rem;
            }
            .badge {
                display: inline-flex;
                align-items: center;
                width: fit-content;
                padding: .27rem .55rem;
                border-radius: 999px;
                font-size: .75rem;
                font-weight: 800;
                white-space: nowrap;
            }
            .badge-verde { background: #dcfce7; color: #166534; }
            .badge-amarillo { background: #fef3c7; color: #92400e; }
            .badge-azul { background: #dbeafe; color: #1d4ed8; }
            .badge-rojo { background: #fee2e2; color: #b91c1c; }
            .badge-gris { background: #e2e8f0; color: #475569; }
            .plate {
                display: inline-block;
                margin: 0 .28rem .28rem 0;
                padding: .28rem .48rem;
                color: #334155;
                background: #f1f5f9;
                border: 1px solid #e2e8f0;
                border-radius: 7px;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: .78rem;
                font-weight: 700;
            }
            .split-card {
                min-height: 305px;
                padding: 1rem;
                background: #fff;
                border: 1px solid var(--line);
                border-radius: 14px;
            }
            .split-card.manual { border-top: 4px solid var(--blue); }
            .split-card.siigo { border-top: 4px solid var(--violet); }
            .split-title {
                margin: 0 0 .85rem;
                font-size: .92rem;
                font-weight: 800;
            }
            .split-row {
                display: flex;
                justify-content: space-between;
                gap: 1rem;
                padding: .52rem 0;
                border-bottom: 1px solid #f0f3f7;
                font-size: .86rem;
            }
            .split-row span { color: var(--muted); }
            .split-row strong { color: var(--ink); text-align: right; }
            .empty-state {
                padding: 2.2rem 1.2rem;
                border: 1px dashed #cbd5e1;
                border-radius: 16px;
                text-align: center;
                background: rgba(255,255,255,.55);
                color: var(--muted);
            }
            .activity {
                padding: .6rem 0;
                border-bottom: 1px solid #eef2f6;
                font-size: .82rem;
            }
            .activity:last-child { border-bottom: 0; }
            [data-testid="stDataFrame"] {
                border: 1px solid var(--line);
                border-radius: 12px;
                overflow: hidden;
            }
            [data-testid="stDataEditor"] {
                border: 1px solid var(--line);
                border-radius: 12px;
                overflow: hidden;
            }
            [data-testid="stButton"] > button {
                border-radius: 9px;
                font-weight: 700;
            }
            [data-testid="stSegmentedControl"] button {
                border-radius: 9px !important;
                font-weight: 700 !important;
            }
            @media (max-width: 760px) {
                .block-container { padding: 1rem .8rem 2rem; }
                .kpi-value { font-size: 1.25rem; }
                .kpi-card { min-height: 104px; padding: .85rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cop(valor: Any) -> str:
    return fmt_cop(valor, dash_zero=False)


def _entero(valor: Any) -> int:
    try:
        if pd.isna(valor):
            return 0
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return 0


def _fecha_visible(valor: Any) -> str:
    if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    try:
        return dt.date.fromisoformat(str(valor)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(valor)


def _texto_corto(valor: Any, limite: int = 48) -> str:
    texto = str(valor or "").strip()
    return texto if len(texto) <= limite else f"{texto[:limite - 1].rstrip()}…"


def _badge(estado: str) -> str:
    etiqueta, tono = ESTADO_META.get(estado, (estado.replace("_", " ").title(), "gris"))
    return f'<span class="badge badge-{tono}">{html.escape(etiqueta)}</span>'


def _placas_html(placas: Any) -> str:
    elementos = [parte.strip() for parte in str(placas or "").split(",") if parte.strip()]
    if not elementos:
        return '<span style="color:#94a3b8">Sin placas</span>'
    return "".join(f'<span class="plate">{html.escape(placa)}</span>' for placa in elementos)


def _empresa_nombre(codigo: str) -> str:
    if codigo == TODAS:
        return "Todas las empresas"
    return EMPRESAS[codigo]["nombre"]


def _empresa_etiqueta(codigo: str) -> str:
    if codigo == TODAS:
        return "◈ Todas"
    datos = EMPRESAS[codigo]
    return f"{datos['prefijo']} · {codigo}"


def _seccion(titulo: str, subtitulo: str | None = None) -> None:
    st.markdown(f'<div class="surface-title">{html.escape(titulo)}</div>', unsafe_allow_html=True)
    if subtitulo:
        st.markdown(
            f'<div class="surface-subtitle">{html.escape(subtitulo)}</div>',
            unsafe_allow_html=True,
        )


def _tarjeta_kpi(etiqueta: str, valor: str, detalle: str, *, destacada: bool = False) -> None:
    clase = " saldo" if destacada else ""
    st.markdown(
        f"""
        <div class="kpi-card{clase}">
          <div class="kpi-label">{html.escape(etiqueta)}</div>
          <div class="kpi-value">{html.escape(valor)}</div>
          <div class="kpi-detail">{html.escape(detalle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _factura_label(fila: Mapping[str, Any]) -> str:
    return f"{fila['factura']} · {fila['cliente']} · {_cop(fila['saldo_cop'])}"


def _aplicar_busqueda(filas: list[dict[str, Any]], termino: str) -> list[dict[str, Any]]:
    consulta = str(termino or "").strip().casefold()
    if not consulta:
        return filas
    campos = ("factura", "cliente", "nit", "descripcion", "placas")
    return [
        fila
        for fila in filas
        if consulta in " ".join(str(fila.get(campo, "")) for campo in campos).casefold()
    ]


def _secretos_streamlit() -> Mapping[str, Any] | None:
    try:
        secretos = st.secrets
        if isinstance(secretos, Mapping):
            return secretos
        return {clave: secretos[clave] for clave in secretos.keys()}
    except Exception:
        return None


def _configuracion_siigo() -> tuple[ConfiguracionSiigo | None, dict[str, str]]:
    secretos = _secretos_streamlit()
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


def _cliente_sin_nombre(factura: Mapping[str, Any]) -> bool:
    cliente = factura.get("customer")
    return not isinstance(cliente, Mapping) or not cliente.get("name")


def _enriquecer_clientes(
    cliente_siigo: ClienteSiigo,
    facturas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Completa nombres solo si Siigo no los incluyó en la factura."""

    if not facturas or not any(_cliente_sin_nombre(factura) for factura in facturas):
        return facturas
    ids = {
        str(factura.get("customer", {}).get("id") or "").strip()
        for factura in facturas
        if isinstance(factura.get("customer"), Mapping)
        and _cliente_sin_nombre(factura)
    }
    ids.discard("")
    if ids and len(ids) <= 25:
        catalogo = [cliente_siigo.consultar_cliente(cliente_id) for cliente_id in sorted(ids)]
        return enriquecer_facturas_clientes(facturas, catalogo)
    return enriquecer_facturas_clientes(facturas, cliente_siigo.listar_clientes(activo=True))


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
            errores[empresa] = f"No fue posible leer las facturas ({type(exc).__name__})."
            continue
        try:
            recibos = cliente.listar_recibos_caja(desde, max(hasta, dt.date.today()))
            tablas_recibos.append(recibos_a_dataframe(empresa, recibos))
        except ErrorSiigo as exc:
            errores[f"{empresa} · RECIBOS"] = str(exc)
        except Exception as exc:
            errores[f"{empresa} · RECIBOS"] = (
                f"No fue posible leer los recibos ({type(exc).__name__})."
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


def _muestra_siigo(facturas_manual: list[dict[str, Any]]) -> pd.DataFrame:
    """Construye una muestra explícita para recorrer la interfaz sin credenciales."""

    filas: list[dict[str, Any]] = []
    if not facturas_manual:
        hoy = dt.date.today()
        facturas_manual = [
            {
                "empresa_codigo": "NOVASA",
                "factura": "FEBA1079",
                "fecha": hoy - dt.timedelta(days=55),
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
                "fecha": hoy - dt.timedelta(days=34),
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
    for indice, manual in enumerate(facturas_manual[:8]):
        saldo = _entero(manual.get("saldo_cop"))
        iva = _entero(manual.get("iva_cop"))
        retefuente = _entero(manual.get("retefuente_cop"))
        reteica = _entero(manual.get("ica_cop"))
        if indice == 1:
            reteica += 12_476
        if indice == 2:
            saldo += 38_000
        filas.append(
            {
                "empresa_codigo": manual["empresa_codigo"],
                "empresa": EMPRESAS.get(manual["empresa_codigo"], {}).get(
                    "nombre", manual["empresa_codigo"]
                ),
                "siigo_factura_id": f"muestra-{indice + 1}",
                "factura": manual["factura"],
                "fecha": manual.get("fecha"),
                "cliente": manual.get("cliente", ""),
                "nit": manual.get("nit", ""),
                "moneda": "COP",
                "descripcion_siigo": manual.get("descripcion", ""),
                "subtotal_siigo": _entero(manual.get("subtotal_cop")),
                "iva_siigo": iva,
                "retefuente_siigo": retefuente,
                "reteica_siigo": reteica,
                "total_siigo": _entero(manual.get("total_cop")),
                "saldo_siigo": saldo,
                "estado_siigo": manual.get("estado", "PENDIENTE"),
            }
        )
    if filas:
        extra = dict(filas[0])
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
        filas.append(extra)
    return pd.DataFrame(filas)


def _render_cabecera() -> tuple[str, str]:
    izquierda, derecha = st.columns([4, 1.3], vertical_alignment="center")
    with izquierda:
        st.markdown(
            '<div class="eyebrow">Finanzas · operación y verificación</div>'
            '<h1 style="margin:0">Cartera</h1>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="page-subtitle">Facturas, abonos y conciliación de las tres empresas.</div>',
            unsafe_allow_html=True,
        )
    with derecha:
        if st.button("＋ Registrar abono", type="primary", use_container_width=True):
            _dialogo_registrar_abono()

    selector_actual = st.session_state.get("empresa_activa", TODAS)
    if selector_actual not in {TODAS, *EMPRESAS}:
        selector_actual = TODAS
    empresa = st.segmented_control(
        "Empresa",
        [TODAS, *EMPRESAS.keys()],
        default=selector_actual,
        format_func=_empresa_etiqueta,
        key="selector_empresa_global",
        width="stretch",
        label_visibility="collapsed",
    )
    if empresa is None:
        empresa = selector_actual
    st.session_state["empresa_activa"] = empresa

    facturas = db.listar_facturas(None if empresa == TODAS else empresa)
    opciones = [""] + [_factura_label(fila) for fila in facturas]
    coincidencia = st.selectbox(
        "Buscar factura o cliente",
        opciones,
        index=0,
        placeholder="Buscar por factura, cliente, NIT o placa…",
        key="buscador_global",
        label_visibility="collapsed",
    )
    termino = coincidencia.split(" · ", 1)[0] if coincidencia else ""
    return empresa, termino


def _render_sidebar(vista_actual: str) -> str:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><span class="brand-mark">◈</span>NOVASALUM</div>',
            unsafe_allow_html=True,
        )
        st.caption("Cartera separada · operación y lectura contable")
        st.divider()
        vista = st.radio(
            "Navegación",
            ["Cartera manual", "Espejo Siigo", "Conciliación"],
            index=["Cartera manual", "Espejo Siigo", "Conciliación"].index(vista_actual),
            label_visibility="collapsed",
        )
        st.divider()
        actividad = db.resumen_actividad()
        if actividad:
            st.markdown("##### Actividad reciente")
            for evento in actividad[:4]:
                detalle = json_resumen(evento["detalle"])
                st.markdown(
                    f'<div class="activity"><strong>{html.escape(evento["accion"].title())}</strong>'
                    f'<br><span style="color:#64748b">{html.escape(detalle)}</span></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Todavía no hay movimientos manuales.")
    return vista


def json_resumen(valor: Any) -> str:
    try:
        datos = pd.io.json.loads(valor)  # type: ignore[attr-defined]
    except Exception:
        try:
            import json

            datos = json.loads(valor)
        except Exception:
            return str(valor)[:85]
    if not isinstance(datos, Mapping):
        return str(datos)[:85]
    factura = datos.get("factura")
    monto = datos.get("monto_cop")
    if factura:
        return f"Factura {factura}"
    if monto:
        return f"Abono por {_cop(monto)}"
    return "Movimiento registrado"


def _render_kpis(empresa: str) -> None:
    resumen = db.resumen_cartera(None if empresa == TODAS else empresa)
    columnas = st.columns(3)
    with columnas[0]:
        _tarjeta_kpi(
            "Total facturado",
            _cop(resumen["total_facturado_cop"]),
            f"{resumen['facturas_pendientes']} factura(s) con saldo",
        )
    with columnas[1]:
        _tarjeta_kpi(
            "Abonos recibidos",
            _cop(resumen["total_abonos_cop"]),
            "Pagos aplicados a facturas manuales",
        )
    with columnas[2]:
        _tarjeta_kpi(
            "Saldo pendiente",
            _cop(resumen["saldo_cartera_cop"]),
            f"{resumen['facturas_vencidas']} factura(s) vencida(s)",
            destacada=True,
        )


def _tabla_facturas(filas: list[dict[str, Any]]) -> pd.DataFrame:
    salida: list[dict[str, Any]] = []
    for fila in filas:
        salida.append(
            {
                "Factura": fila["factura"],
                "Fecha": _fecha_visible(fila["fecha"]),
                "Cliente": fila["cliente"],
                "Detalle del servicio": _texto_corto(fila["descripcion"]),
                "Placas": str(fila["placas"] or "—").replace(",", " ·"),
                "Subtotal": _cop(fila["subtotal_cop"]),
                "IVA": _cop(fila["iva_cop"]),
                "Retefuente": _cop(fila["retefuente_cop"]),
                "ICA": _cop(fila["ica_cop"]),
                "Abonos": _cop(fila["abonos_cop"]),
                "Saldo": _cop(fila["saldo_cop"]),
                "Estado": ESTADO_META[fila["estado"]][0],
            }
        )
    return pd.DataFrame(salida)


def _render_formulario_factura(empresa_activa: str) -> None:
    with st.expander("＋ Registrar nueva factura", expanded=False):
        _seccion(
            "Nueva factura manual",
            "Los valores se guardan como pesos enteros, sin centavos.",
        )
        empresas_formulario = [empresa_activa] if empresa_activa != TODAS else list(EMPRESAS)
        with st.form("formulario_nueva_factura", clear_on_submit=True):
            empresa = st.selectbox(
                "Empresa",
                empresas_formulario,
                format_func=lambda codigo: f"{EMPRESAS[codigo]['prefijo']} · {EMPRESAS[codigo]['nombre']}",
            )
            columna_a, columna_b, columna_c, columna_d = st.columns(4)
            with columna_a:
                prefijo = st.text_input("Prefijo", value=EMPRESAS[empresa]["prefijo"]).upper()
            with columna_b:
                numero = st.text_input("Número de factura", placeholder="1079").upper()
            with columna_c:
                fecha = st.date_input("Fecha de emisión", value=dt.date.today())
            with columna_d:
                vencimiento = st.date_input(
                    "Vencimiento",
                    value=dt.date.today() + dt.timedelta(days=30),
                )
            columna_cliente, columna_nit = st.columns([2, 1])
            with columna_cliente:
                cliente = st.text_input("Cliente", placeholder="Razón social o nombre")
            with columna_nit:
                nit = st.text_input("NIT", placeholder="900.000.000-0")
            descripcion = st.text_area(
                "Detalle del servicio",
                placeholder="Ruta, manifiesto, condición especial u observación operativa",
                max_chars=1000,
            )
            placas = st.text_input("Placas", placeholder="SOQ766, TAW897")
            monto_a, monto_b, monto_c, monto_d = st.columns(4)
            with monto_a:
                subtotal = st.number_input(
                    "Subtotal", min_value=0, step=1_000, value=0, format="%d"
                )
            with monto_b:
                iva = st.number_input("IVA", min_value=0, step=1_000, value=0, format="%d")
            with monto_c:
                retefuente = st.number_input(
                    "Retefuente", min_value=0, step=1_000, value=0, format="%d"
                )
            with monto_d:
                ica = st.number_input("ICA", min_value=0, step=1_000, value=0, format="%d")
            total = int(subtotal) + int(iva) - int(retefuente) - int(ica)
            st.caption(f"Total a cobrar: {_cop(total)}")
            guardar = st.form_submit_button("Guardar factura", type="primary")
        if guardar:
            try:
                db.crear_factura(
                    {
                        "empresa_codigo": empresa,
                        "prefijo": prefijo,
                        "numero": numero,
                        "fecha": fecha,
                        "vencimiento": vencimiento,
                        "cliente": cliente,
                        "nit": nit,
                        "descripcion": descripcion,
                        "placas": placas,
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


def _render_edicion_rapida(filas: list[dict[str, Any]]) -> None:
    if not filas:
        return
    with st.expander("Editar factura en línea", expanded=False):
        _seccion(
            "Ajustes rápidos",
            "Edita el detalle, las placas o los impuestos sin salir de la cartera.",
        )
        por_etiqueta = {_factura_label(fila): fila for fila in filas}
        etiqueta = st.selectbox("Factura a editar", list(por_etiqueta), key="factura_edicion")
        factura = por_etiqueta[etiqueta]
        columnas = st.columns([1.55, 1.35])
        with columnas[0]:
            st.markdown(
                f"""
                <div class="surface" style="margin-top:.25rem">
                  <div class="eyebrow">Factura seleccionada</div>
                  <div style="font-weight:800;font-size:1.1rem">{html.escape(factura["factura"])}</div>
                  <div style="margin:.6rem 0">{_badge(factura["estado"])}</div>
                  <div style="font-size:.86rem;color:#64748b">{html.escape(factura["cliente"])}</div>
                  <div style="margin-top:.65rem">{_placas_html(factura["placas"])}</div>
                  <div style="margin-top:.8rem;font-size:.86rem;color:#475569">{html.escape(factura["descripcion"] or "Sin detalle")}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with columnas[1]:
            datos_editor = pd.DataFrame(
                [
                    {
                        "Detalle del servicio": factura["descripcion"],
                        "Placas": factura["placas"],
                        "Subtotal": int(factura["subtotal_cop"]),
                        "IVA": int(factura["iva_cop"]),
                        "Retefuente": int(factura["retefuente_cop"]),
                        "ICA": int(factura["ica_cop"]),
                    }
                ]
            )
            editado = st.data_editor(
                datos_editor,
                hide_index=True,
                num_rows="fixed",
                key=f"editor_factura_{factura['id']}",
                column_config={
                    "Detalle del servicio": st.column_config.TextColumn(width="large"),
                    "Placas": st.column_config.TextColumn(width="medium"),
                    "Subtotal": st.column_config.NumberColumn(min_value=0, step=1_000),
                    "IVA": st.column_config.NumberColumn(min_value=0, step=1_000),
                    "Retefuente": st.column_config.NumberColumn(min_value=0, step=1_000),
                    "ICA": st.column_config.NumberColumn(min_value=0, step=1_000),
                },
            )
            acciones = st.columns([1, 1])
            with acciones[0]:
                if st.button("Guardar cambios", type="primary", use_container_width=True):
                    fila_editada = editado.iloc[0].to_dict()
                    try:
                        db.actualizar_campos_factura(
                            int(factura["id"]),
                            {
                                "descripcion": fila_editada["Detalle del servicio"],
                                "placas": fila_editada["Placas"],
                                "subtotal_cop": fila_editada["Subtotal"],
                                "iva_cop": fila_editada["IVA"],
                                "retefuente_cop": fila_editada["Retefuente"],
                                "ica_cop": fila_editada["ICA"],
                            },
                        )
                    except db.ErrorCartera as exc:
                        st.error(str(exc))
                    else:
                        st.success("Cambios guardados.")
                        st.rerun()
            with acciones[1]:
                if st.button("Anular factura", use_container_width=True):
                    try:
                        db.anular_factura(int(factura["id"]))
                    except db.ErrorCartera as exc:
                        st.error(str(exc))
                    else:
                        st.success("Factura anulada. El registro continúa en auditoría.")
                        st.rerun()


def _render_cartera_manual(empresa: str, termino_global: str) -> None:
    _render_kpis(empresa)
    st.write("")
    facturas = db.listar_facturas(None if empresa == TODAS else empresa)
    busqueda_local = st.text_input(
        "Filtrar cartera",
        value=termino_global,
        placeholder="Cliente, factura, NIT, ruta o placa",
    )
    filtradas = _aplicar_busqueda(facturas, busqueda_local)

    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        f"Cartera manual · {_empresa_nombre(empresa)}",
        f"{len(filtradas)} factura(s) visible(s) · los saldos se actualizan al aplicar un abono.",
    )
    st.write("")
    if filtradas:
        tabla = _tabla_facturas(filtradas)
        st.dataframe(
            tabla,
            width="stretch",
            hide_index=True,
            height=min(540, 94 + 36 * len(tabla)),
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
    _render_formulario_factura(empresa)
    _render_edicion_rapida(filtradas)


@st.dialog("Registrar abono", width="large")
def _dialogo_registrar_abono() -> None:
    empresa_preferida = st.session_state.get("empresa_activa", TODAS)
    empresas_disponibles = [empresa_preferida] if empresa_preferida != TODAS else list(EMPRESAS)
    empresa = st.selectbox(
        "Empresa",
        empresas_disponibles,
        format_func=lambda codigo: f"{EMPRESAS[codigo]['prefijo']} · {EMPRESAS[codigo]['nombre']}",
        key="abono_empresa",
    )
    clientes = db.clientes_con_saldo(empresa)
    if not clientes:
        st.info("Esta empresa no tiene facturas con saldo pendiente.")
        return
    opciones_clientes = {
        f"{fila['cliente']} · {fila['nit'] or 'Sin NIT'} · {_cop(fila['saldo_cop'])}": fila
        for fila in clientes
    }
    etiqueta_cliente = st.selectbox("Cliente", list(opciones_clientes), key="abono_cliente")
    cliente = opciones_clientes[etiqueta_cliente]
    informacion, pago = st.columns([1, 1])
    with informacion:
        fecha = st.date_input("Fecha del pago", value=dt.date.today(), key="abono_fecha")
        referencia = st.text_input(
            "Referencia bancaria",
            placeholder="Recibo, transferencia o comprobante",
            key="abono_referencia",
        )
    with pago:
        monto = st.number_input(
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
    facturas = db.facturas_pendientes_cliente(empresa, int(cliente["cliente_id"]))
    aplicaciones: list[dict[str, Any]]
    sobrante = 0
    if fifo:
        aplicaciones, sobrante = db.previsualizar_fifo(facturas, monto or 1)
    else:
        base = pd.DataFrame(
            [
                {
                    "Factura": factura["factura"],
                    "Fecha": _fecha_visible(factura["fecha"]),
                    "Saldo actual": _cop(factura["saldo_cop"]),
                    "Aplicar (COP)": 0,
                    "_id": int(factura["id"]),
                }
                for factura in facturas
            ]
        )
        editado = st.data_editor(
            base,
            hide_index=True,
            width="stretch",
            disabled=["Factura", "Fecha", "Saldo actual", "_id"],
            column_config={
                "Aplicar (COP)": st.column_config.NumberColumn(min_value=0, step=1_000),
                "_id": None,
            },
            key=f"abono_manual_{empresa}_{cliente['cliente_id']}",
        )
        aplicaciones = [
            {"factura_id": int(fila["_id"]), "monto_cop": _entero(fila["Aplicar (COP)"])}
            for _, fila in editado.iterrows()
            if _entero(fila["Aplicar (COP)"]) > 0
        ]
        sobrante = max(0, _entero(monto) - sum(_entero(a["monto_cop"]) for a in aplicaciones))

    por_id = {int(factura["id"]): factura for factura in facturas}
    filas_preview = []
    for aplicacion in aplicaciones:
        factura = por_id[int(aplicacion["factura_id"])]
        aplicado = _entero(aplicacion["monto_cop"])
        saldo_despues = _entero(factura["saldo_cop"]) - aplicado
        filas_preview.append(
            {
                "Factura": factura["factura"],
                "Saldo antes": _cop(factura["saldo_cop"]),
                "Aplicar": _cop(aplicado),
                "Saldo después": _cop(saldo_despues),
                "Estado": "● Pagada" if saldo_despues == 0 else "● Abono parcial",
            }
        )
    st.markdown("##### Vista previa de aplicación")
    if filas_preview:
        st.dataframe(pd.DataFrame(filas_preview), width="stretch", hide_index=True)
    else:
        st.caption("Ingresa un monto para ver cómo se distribuirá el pago.")
    total_aplicado = sum(_entero(aplicacion["monto_cop"]) for aplicacion in aplicaciones)
    resumen_pago = st.columns(3)
    resumen_pago[0].metric("Recibido", _cop(monto))
    resumen_pago[1].metric("Aplicado", _cop(total_aplicado))
    resumen_pago[2].metric("Saldo a favor", _cop(sobrante))
    if sobrante:
        st.info(
            "El excedente queda registrado como saldo a favor del cliente para revisión posterior."
        )
    if st.button("Aplicar abono", type="primary", use_container_width=True):
        try:
            db.registrar_abono(
                empresa_codigo=empresa,
                cliente_id=int(cliente["cliente_id"]),
                fecha=fecha,
                referencia=referencia,
                monto_cop=monto,
                aplicaciones=aplicaciones,
            )
        except db.ErrorCartera as exc:
            st.error(str(exc))
        else:
            st.success("Abono aplicado y registrado en auditoría.")
            st.rerun()


def _tabla_siigo(facturas: pd.DataFrame) -> pd.DataFrame:
    if facturas is None or facturas.empty:
        return pd.DataFrame()
    filas = []
    for _, fila in facturas.iterrows():
        filas.append(
            {
                "Empresa": fila.get("empresa_codigo", ""),
                "Factura": fila.get("factura", ""),
                "Fecha": _fecha_visible(fila.get("fecha")),
                "Cliente": fila.get("cliente", ""),
                "Detalle": _texto_corto(fila.get("descripcion_siigo", "")),
                "Total": _cop(fila.get("total_siigo")),
                "Saldo Siigo": _cop(fila.get("saldo_siigo")),
                "Estado": str(fila.get("estado_siigo", "")).replace("_", " ").title(),
            }
        )
    return pd.DataFrame(filas)


def _render_siigo(empresa: str) -> None:
    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Espejo contable de Siigo",
        "Lectura directa desde Siigo. Consultar o revisar esta pantalla no modifica ningún registro contable.",
    )
    configuracion, errores_credenciales = _configuracion_siigo()
    disponibles = list(configuracion.empresas.keys()) if configuracion else []
    fecha_hoy = dt.date.today()
    empresa_preferida = [empresa] if empresa != TODAS and empresa in disponibles else disponibles
    with st.form("consulta_siigo"):
        c1, c2, c3 = st.columns([1, 1, 1.4])
        with c1:
            desde = st.date_input("Desde", value=fecha_hoy.replace(day=1))
        with c2:
            hasta = st.date_input("Hasta", value=fecha_hoy)
        with c3:
            empresas = st.multiselect(
                "Empresas a consultar",
                list(EMPRESAS),
                default=empresa_preferida,
                format_func=lambda codigo: f"{EMPRESAS[codigo]['prefijo']} · {codigo}",
            )
        consultar = st.form_submit_button("Consultar Siigo ahora", type="primary")
    acciones = st.columns([1, 2.6])
    with acciones[0]:
        muestra = st.button("Cargar muestra visual", use_container_width=True)
    with acciones[1]:
        if configuracion is None:
            st.caption(
                "No hay credenciales disponibles todavía. La muestra visual permite recorrer el módulo sin conectarse a Siigo."
            )
        elif errores_credenciales:
            st.caption(
                "Algunas empresas no tienen credenciales; las demás se pueden consultar."
            )

    if consultar:
        if not configuracion:
            st.error(
                "No se encontraron credenciales de Siigo. Configúralas antes de consultar datos reales."
            )
        elif not empresas:
            st.warning("Selecciona al menos una empresa.")
        elif desde > hasta:
            st.warning("La fecha inicial no puede ser posterior a la final.")
        else:
            with st.spinner("Leyendo Siigo…"):
                facturas, recibos, errores = _consultar_siigo(configuracion, empresas, desde, hasta)
            st.session_state["siigo_facturas"] = facturas
            st.session_state["siigo_recibos"] = recibos
            st.session_state["siigo_errores"] = errores
            st.session_state["siigo_consultado_en"] = dt.datetime.now().astimezone()
            st.session_state["siigo_origen"] = "Lectura directa"
    if muestra:
        manuales = db.listar_facturas(None if empresa == TODAS else empresa)
        st.session_state["siigo_facturas"] = _muestra_siigo(manuales)
        st.session_state["siigo_recibos"] = pd.DataFrame()
        st.session_state["siigo_errores"] = {}
        st.session_state["siigo_consultado_en"] = dt.datetime.now().astimezone()
        st.session_state["siigo_origen"] = "Muestra visual"

    facturas_siigo = st.session_state.get("siigo_facturas", pd.DataFrame())
    recibos_siigo = st.session_state.get("siigo_recibos", pd.DataFrame())
    if isinstance(facturas_siigo, pd.DataFrame) and not facturas_siigo.empty:
        if empresa != TODAS and "empresa_codigo" in facturas_siigo.columns:
            facturas_siigo = facturas_siigo[
                facturas_siigo["empresa_codigo"].astype(str).eq(empresa)
            ].copy()
        marca = st.session_state.get("siigo_consultado_en")
        origen = st.session_state.get("siigo_origen", "Lectura")
        if marca:
            st.caption(f"{origen}: {marca:%d/%m/%Y %H:%M:%S %Z}")
        for clave, mensaje in st.session_state.get("siigo_errores", {}).items():
            st.warning(f"{clave}: {mensaje}")
        total = sum(_entero(valor) for valor in facturas_siigo.get("total_siigo", []))
        saldo = sum(_entero(valor) for valor in facturas_siigo.get("saldo_siigo", []))
        recibos = sum(_entero(valor) for valor in recibos_siigo.get("abonos_recibos", []))
        siigo_kpis = st.columns(3)
        with siigo_kpis[0]:
            _tarjeta_kpi("Facturado según Siigo", _cop(total), f"{len(facturas_siigo)} documento(s)")
        with siigo_kpis[1]:
            _tarjeta_kpi("Abonos visibles", _cop(recibos), "Recibos de caja consultados")
        with siigo_kpis[2]:
            _tarjeta_kpi("Saldo Siigo", _cop(saldo), "Saldo contable informado por Siigo", destacada=True)
        st.write("")
        st.dataframe(_tabla_siigo(facturas_siigo), width="stretch", hide_index=True)
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


def _fila_siigo_dict(fila: pd.Series | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if fila is None:
        return None
    datos = dict(fila)
    return {clave: (None if pd.isna(valor) else valor) for clave, valor in datos.items()}


def _construir_conciliacion(
    manuales: list[dict[str, Any]],
    siigo: pd.DataFrame,
) -> list[dict[str, Any]]:
    por_manual = {
        (fila["empresa_codigo"], normalizar_factura(fila["factura"])): fila
        for fila in manuales
    }
    por_siigo: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(siigo, pd.DataFrame) and not siigo.empty:
        for _, fila in siigo.iterrows():
            empresa = str(fila.get("empresa_codigo", "")).strip().upper()
            clave = normalizar_factura(fila.get("factura", ""))
            if empresa and clave:
                por_siigo[(empresa, clave)] = _fila_siigo_dict(fila) or {}
    resultado: list[dict[str, Any]] = []
    for empresa, clave in sorted(set(por_manual) | set(por_siigo)):
        manual = por_manual.get((empresa, clave))
        oficial = por_siigo.get((empresa, clave))
        factura = (manual or oficial or {}).get("factura", clave)
        cliente = (manual or oficial or {}).get("cliente", "")
        dif_saldo = None
        dif_iva = None
        dif_retefuente = None
        dif_ica = None
        if manual is None:
            estado = "SOLO_SIIGO"
        elif oficial is None:
            estado = "SOLO_MANUAL"
        else:
            dif_saldo = _entero(manual["saldo_cop"]) - _entero(oficial.get("saldo_siigo"))
            dif_iva = _entero(manual["iva_cop"]) - _entero(oficial.get("iva_siigo"))
            dif_retefuente = _entero(manual["retefuente_cop"]) - _entero(
                oficial.get("retefuente_siigo")
            )
            dif_ica = _entero(manual["ica_cop"]) - _entero(oficial.get("reteica_siigo"))
            if abs(dif_saldo) <= 1 and all(
                abs(diferencia) <= 1
                for diferencia in (dif_iva, dif_retefuente, dif_ica)
            ):
                estado = "CUADRADO"
            elif abs(dif_saldo) <= 1:
                estado = "DIFERENCIA_IMPUESTOS"
            else:
                estado = "DESCUADRE"
        resultado.append(
            {
                "empresa_codigo": empresa,
                "factura_clave": clave,
                "factura": factura,
                "cliente": cliente,
                "estado": estado,
                "manual": manual,
                "siigo": oficial,
                "dif_saldo": dif_saldo,
                "dif_iva": dif_iva,
                "dif_retefuente": dif_retefuente,
                "dif_ica": dif_ica,
            }
        )
    return resultado


def _valor_diferencia(valor: int | None) -> str:
    return "—" if valor is None else _cop(valor)


def _render_lado(titulo: str, tipo: str, fila: Mapping[str, Any] | None) -> None:
    if fila is None:
        st.markdown(
            f'<div class="split-card {tipo}"><div class="split-title">{html.escape(titulo)}</div>'
            '<div style="color:#94a3b8;padding-top:4rem;text-align:center">No existe esta factura en la fuente.</div></div>',
            unsafe_allow_html=True,
        )
        return
    siigo = tipo == "siigo"
    campos = [
        ("Cliente", fila.get("cliente", "—")),
        ("Fecha", _fecha_visible(fila.get("fecha"))),
        ("Subtotal", _cop(fila.get("subtotal_siigo" if siigo else "subtotal_cop"))),
        ("IVA", _cop(fila.get("iva_siigo" if siigo else "iva_cop"))),
        ("Retefuente", _cop(fila.get("retefuente_siigo" if siigo else "retefuente_cop"))),
        ("ICA", _cop(fila.get("reteica_siigo" if siigo else "ica_cop"))),
        ("Saldo", _cop(fila.get("saldo_siigo" if siigo else "saldo_cop"))),
    ]
    if siigo:
        detalle = fila.get("descripcion_siigo", "")
    else:
        detalle = fila.get("descripcion", "")
    contenido = "".join(
        f'<div class="split-row"><span>{html.escape(etiqueta)}</span><strong>{html.escape(str(valor))}</strong></div>'
        for etiqueta, valor in campos
    )
    st.markdown(
        f'<div class="split-card {tipo}"><div class="split-title">{html.escape(titulo)}</div>'
        f'{contenido}<div style="margin-top:.8rem;color:#64748b;font-size:.82rem">{html.escape(str(detalle or "Sin detalle"))}</div></div>',
        unsafe_allow_html=True,
    )


def _render_conciliacion(empresa: str) -> None:
    facturas_siigo = st.session_state.get("siigo_facturas", pd.DataFrame())
    if not isinstance(facturas_siigo, pd.DataFrame) or facturas_siigo.empty:
        st.markdown('<div class="surface">', unsafe_allow_html=True)
        _seccion("Conciliación y auditoría", "Cruza las dos carteras factura por factura.")
        st.markdown(
            '<div class="empty-state"><strong>Primero consulta Siigo.</strong><br>'
            'Abre “Espejo Siigo” y carga datos reales o una muestra visual para comparar.</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return
    manuales = db.listar_facturas(None if empresa == TODAS else empresa)
    siigo_filtrado = facturas_siigo.copy()
    if empresa != TODAS and "empresa_codigo" in siigo_filtrado.columns:
        siigo_filtrado = siigo_filtrado[
            siigo_filtrado["empresa_codigo"].astype(str).eq(empresa)
        ].copy()
    filas = _construir_conciliacion(manuales, siigo_filtrado)

    st.markdown('<div class="surface">', unsafe_allow_html=True)
    _seccion(
        "Conciliación y auditoría",
        "Cartera manual a la izquierda y lectura de Siigo a la derecha. Marcar una revisión no modifica Siigo.",
    )
    conteos = {estado: sum(1 for fila in filas if fila["estado"] == estado) for estado in ESTADO_META}
    kpis = st.columns(4)
    with kpis[0]:
        _tarjeta_kpi("Cuadradas", str(conteos["CUADRADO"]), "Saldo e impuestos coinciden")
    with kpis[1]:
        _tarjeta_kpi(
            "Impuestos por revisar",
            str(conteos["DIFERENCIA_IMPUESTOS"]),
            "El saldo coincide",
        )
    with kpis[2]:
        _tarjeta_kpi("Descuadres", str(conteos["DESCUADRE"]), "Saldo diferente entre fuentes")
    with kpis[3]:
        faltantes = conteos["SOLO_MANUAL"] + conteos["SOLO_SIIGO"]
        _tarjeta_kpi("Facturas faltantes", str(faltantes), "Solo presentes en una fuente", destacada=True)
    st.write("")
    tabla = pd.DataFrame(
        [
            {
                "Estado": ESTADO_META[fila["estado"]][0],
                "Empresa": fila["empresa_codigo"],
                "Factura": fila["factura"],
                "Cliente": fila["cliente"],
                "Saldo manual": _cop(fila["manual"]["saldo_cop"]) if fila["manual"] else "—",
                "Saldo Siigo": _cop(fila["siigo"].get("saldo_siigo")) if fila["siigo"] else "—",
                "Dif. saldo": _valor_diferencia(fila["dif_saldo"]),
                "Dif. IVA": _valor_diferencia(fila["dif_iva"]),
                "Dif. retefuente": _valor_diferencia(fila["dif_retefuente"]),
                "Dif. ICA": _valor_diferencia(fila["dif_ica"]),
            }
            for fila in filas
        ]
    )
    if not tabla.empty:
        st.dataframe(tabla, width="stretch", hide_index=True)
        por_opcion = {
            f"{fila['empresa_codigo']} · {fila['factura']} · {ESTADO_META[fila['estado']][0]}": fila
            for fila in filas
        }
        seleccion = st.selectbox("Abrir comparación", list(por_opcion), key="conciliacion_factura")
        fila = por_opcion[seleccion]
        st.write("")
        st.markdown(_badge(fila["estado"]), unsafe_allow_html=True)
        izquierda, derecha = st.columns(2)
        with izquierda:
            _render_lado("Cartera manual", "manual", fila["manual"])
        with derecha:
            _render_lado("Cartera Siigo", "siigo", fila["siigo"])
        observacion = st.text_area(
            "Observación de revisión",
            placeholder="Qué se verificó, qué falta por corregir o cuál es la siguiente acción.",
            key=f"observacion_{fila['empresa_codigo']}_{fila['factura_clave']}",
            max_chars=1500,
        )
        if st.button("Marcar revisión", type="primary"):
            db.guardar_revision_conciliacion(
                empresa_codigo=fila["empresa_codigo"],
                factura_clave=fila["factura_clave"],
                estado=fila["estado"],
                observacion=observacion,
                manual=fila["manual"],
                siigo=fila["siigo"],
            )
            st.success("Revisión guardada en el historial interno.")
    else:
        st.markdown(
            '<div class="empty-state"><strong>No hay facturas para conciliar.</strong><br>'
            'Registra una factura manual o amplía la lectura de Siigo.</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    _estilos()
    db.inicializar()
    vista_actual = st.session_state.get("vista", "Cartera manual")
    vista = _render_sidebar(vista_actual)
    st.session_state["vista"] = vista
    empresa, termino_global = _render_cabecera()
    st.write("")
    if vista == "Cartera manual":
        _render_cartera_manual(empresa, termino_global)
    elif vista == "Espejo Siigo":
        _render_siigo(empresa)
    else:
        _render_conciliacion(empresa)


if __name__ == "__main__":
    main()
