"""Cartera Siigo: la misma vista de la cartera manual, leída del API.

Esta pantalla es independiente de la cartera manual. No lee ni escribe la base
de datos local, no comparte una sola clave de sesión con ella y nadie digita
nada aquí: la información se obtiene consultando Siigo factura por factura.

Lo único que comparte con la cartera manual es la apariencia —la grilla, las
tarjetas y el estado de cuenta— porque el dueño envía las dos vistas como
imagen y deben reconocerse como el mismo documento.
"""

from __future__ import annotations

from collections.abc import Mapping
import datetime as dt
import html
import os
from typing import Any

import pandas as pd
import streamlit as st

from src.cartera_siigo import EMPRESAS_SIIGO
from src.siigo import (
    ConfiguracionSiigo,
    ErrorConfiguracionSiigo,
)
from src.siigo_lectura import ParametrosLectura, Reporte, leer_cartera
from src.siigo_muestra import cargar_muestra
from src.siigo_vista import (
    COLUMNAS_CLIENTES,
    FILTROS_SALDO,
    SIIGO_ESTADO_META,
    buscar_filas,
    clave_cliente,
    es_cop,
    es_vigente,
    etiqueta_estado,
    filas_de_dataframe,
    filas_sumables,
    filtrar_saldo,
    money,
    money_kpi,
    nombre_cliente,
    ordenar_filas,
    suma_auditable,
    tabla_clientes,
    tabla_estado_cuenta,
    tabla_general,
)
from src.ui.components import (
    EMPRESAS,
    TODAS,
    company_label,
    company_name,
    render_kpi_card,
    render_section,
)
from src.ui.grid import render_grid


# Claves publicadas para la pantalla de conciliación, que cruza esta lectura
# con la cartera manual. Son el único punto de contacto entre las dos carteras.
CLAVE_REPORTE = "siigo_reporte"
CLAVE_FACTURAS = "siigo_facturas"
CLAVE_ERRORES = "siigo_errores"
CLAVE_CONSULTADO = "siigo_consultado_en"
CLAVE_ORIGEN = "siigo_origen"

# Tiempos propios de esta pantalla: más cortos que los del cliente por defecto
# porque aquí se encadenan muchas consultas y el dueño pidió que cargue rápido.
TIMEOUT_LECTURA = 10.0
REINTENTOS_LECTURA = 1


def _secretos() -> Mapping[str, Any] | None:
    """Devuelve los secretos de Streamlit cuando están disponibles.

    ``st.secrets`` se lee de forma perezosa: no falla al tocarlo sino al
    recorrerlo. Por eso aquí se copia a un diccionario dentro del ``try``, para
    que la ausencia de ``secrets.toml`` sea un «todavía no hay credenciales» y
    no una excepción que tumbe la pantalla.
    """

    try:
        return {clave: st.secrets[clave] for clave in st.secrets}
    except Exception:
        return None


def _configuracion() -> tuple[ConfiguracionSiigo | None, dict[str, str]]:
    """Carga las credenciales disponibles, empresa por empresa."""

    secretos = _secretos()
    credenciales: dict[str, Any] = {}
    faltantes: dict[str, str] = {}
    for codigo in EMPRESAS_SIIGO:
        configurada = None
        if secretos is not None:
            try:
                parcial = ConfiguracionSiigo.desde_mapeo_secretos(secretos, {codigo: codigo})
                configurada = parcial.credenciales_para(codigo)
            except ErrorConfiguracionSiigo:
                configurada = None
        if configurada is None:
            try:
                parcial = ConfiguracionSiigo.desde_entorno({codigo: codigo}, entorno=os.environ)
                configurada = parcial.credenciales_para(codigo)
            except ErrorConfiguracionSiigo:
                faltantes[codigo] = "Sin credenciales configuradas"
        if configurada is not None:
            credenciales[codigo] = configurada
            faltantes.pop(codigo, None)
    if not credenciales:
        return None, faltantes
    try:
        return (
            ConfiguracionSiigo(
                empresas=credenciales,
                timeout_s=TIMEOUT_LECTURA,
                reintentos=REINTENTOS_LECTURA,
            ),
            faltantes,
        )
    except ErrorConfiguracionSiigo as exc:
        faltantes["CONFIGURACIÓN"] = str(exc)
        return None, faltantes


def _publicar(reporte: Reporte) -> None:
    """Guarda la lectura para esta pantalla y para la de conciliación."""

    st.session_state[CLAVE_REPORTE] = reporte
    st.session_state[CLAVE_FACTURAS] = reporte.facturas
    st.session_state[CLAVE_ERRORES] = reporte.errores
    st.session_state[CLAVE_CONSULTADO] = reporte.leido_en
    st.session_state[CLAVE_ORIGEN] = reporte.origen


def _reporte_publicado() -> Reporte | None:
    reporte = st.session_state.get(CLAVE_REPORTE)
    return reporte if isinstance(reporte, Reporte) else None


def _formulario_consulta(
    configuracion: ConfiguracionSiigo | None,
    faltantes: Mapping[str, str],
) -> tuple[ParametrosLectura | None, bool]:
    """Panel de consulta. Devuelve los parámetros si se pidió leer Siigo."""

    disponibles = list(configuracion.empresas) if configuracion else []
    hoy = dt.date.today()
    with st.form("consulta_siigo"):
        columna_a, columna_b, columna_c = st.columns([1, 1, 1.6])
        with columna_a:
            desde = st.date_input(
                "Desde", value=hoy.replace(day=1), format="DD/MM/YYYY", key="siigo_desde"
            )
        with columna_b:
            hasta = st.date_input(
                "Hasta", value=hoy, format="DD/MM/YYYY", key="siigo_hasta"
            )
        with columna_c:
            empresas = st.multiselect(
                "Empresas a consultar",
                disponibles or list(EMPRESAS),
                default=disponibles,
                format_func=company_label,
                key="siigo_empresas",
            )
        consultar = st.form_submit_button(
            "Consultar Siigo ahora", type="primary", disabled=configuracion is None
        )
    muestra = st.button("Cargar muestra de demostración", key="siigo_muestra")

    if configuracion is None:
        st.info(
            "Todavía no hay credenciales de Siigo en el servidor. Puedes recorrer la "
            "pantalla con la muestra de demostración."
        )
        if faltantes.get("CONFIGURACIÓN"):
            st.error(faltantes["CONFIGURACIÓN"])
    elif faltantes:
        st.caption(
            "Sin credenciales: "
            + ", ".join(sorted(faltantes))
            + ". Las demás empresas se pueden consultar."
        )

    if not consultar:
        return None, muestra
    if not empresas:
        st.warning("Selecciona al menos una empresa.")
        return None, muestra
    if desde > hasta:
        st.warning("La fecha inicial no puede ser posterior a la final.")
        return None, muestra
    return ParametrosLectura(tuple(empresas), desde, hasta), muestra


def _ejecutar_lectura(
    configuracion: ConfiguracionSiigo,
    parametros: ParametrosLectura,
) -> Reporte:
    """Lee Siigo mostrando el avance, que es parte de la supervisión."""

    with st.status("Consultando Siigo factura por factura…", expanded=True) as estado:
        barra = st.progress(0.0)
        linea = st.empty()

        def progreso(empresa: str, hechas: int, total: int) -> None:
            barra.progress(min(1.0, hechas / total) if total else 1.0)
            linea.write(f"{company_name(empresa)} · {hechas} de {total} facturas")

        reporte = leer_cartera(configuracion, parametros, progreso=progreso)
        barra.progress(1.0)
        linea.empty()
        estado.update(
            label=(
                f"Lectura terminada: {reporte.total_facturas} factura(s) en "
                f"{reporte.segundos:.1f} s"
            ),
            state="complete",
            expanded=False,
        )
    return reporte


def _render_supervision(reporte: Reporte, empresa_filtro: str) -> None:
    """Todo lo que el usuario necesita para confiar (o no) en lo que ve.

    Se pinta siempre y antes que las cifras: una lectura en la que fallaron
    todas las empresas no puede verse igual que no haber consultado nunca.
    """

    marca = reporte.leido_en.strftime("%d/%m/%Y %H:%M:%S") if reporte.leido_en else "—"
    detalle_origen = f"{reporte.origen} · {marca}"
    if reporte.parametros:
        periodo = (
            f"{reporte.parametros.desde.strftime('%d/%m/%Y')} a "
            f"{reporte.parametros.hasta.strftime('%d/%m/%Y')}"
        )
        detalle_origen += f" · período {periodo}"
    st.caption(detalle_origen)

    for clave, mensaje in reporte.errores.items():
        st.warning(f"{clave}: {mensaje}. Los demás resultados siguen disponibles.")

    if reporte.sin_detalle:
        st.warning(
            f"{reporte.sin_detalle} factura(s) se muestran solo con lo que entregó el "
            "listado: su subtotal, impuestos y detalle aparecen con raya porque no se "
            "pudo leer su detalle individual. No se muestran como cero."
        )

    consultadas = set(reporte.parametros.empresas) if reporte.parametros else set()
    if empresa_filtro != TODAS and consultadas and empresa_filtro not in consultadas:
        st.info(
            f"{company_name(empresa_filtro)} no se consultó en esta lectura. "
            "Vuelve a consultar incluyéndola para ver su cartera."
        )

    if reporte.resumenes:
        with st.expander("Detalle de la lectura"):
            st.dataframe(
                pd.DataFrame([
                    {
                        "Empresa": company_name(r.empresa) if r.empresa in EMPRESAS else r.empresa,
                        "Facturas del período": r.facturas_en_periodo,
                        "Detalles leídos": r.detalles_leidos,
                        "Detalles fallidos": r.detalles_fallidos,
                        "Consultas al API": r.llamadas,
                        "Segundos": round(r.segundos, 1),
                    }
                    for r in reporte.resumenes
                ]),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Cada factura se consulta individualmente en Siigo: es la única forma "
                "de conocer su subtotal, sus impuestos y su saldo real."
            )


def _render_kpis(filas: list[dict[str, Any]]) -> None:
    """Tres tarjetas, en la misma posición que en la cartera manual."""

    sumables = filas_sumables(filas)
    facturado, sin_total = suma_auditable(sumables, "total_siigo")
    saldo, sin_saldo = suma_auditable(sumables, "saldo_siigo")
    con_saldo = sum(
        1 for f in sumables
        if f.get("saldo_siigo") is not None and float(f["saldo_siigo"]) > 0
    )
    vencidas = sum(1 for f in sumables if str(f.get("estado_siigo") or "") == "VENCIDA")

    detalle_facturado = f"{con_saldo} factura(s) con saldo"
    if sin_total:
        detalle_facturado += f" · {sin_total} sin total leído"
    detalle_saldo = f"{vencidas} factura(s) vencida(s)"
    if sin_saldo:
        detalle_saldo += f" · {sin_saldo} sin saldo leído"

    columnas = st.columns(3)
    with columnas[0]:
        render_kpi_card(
            "Total facturado",
            money_kpi(facturado) if sumables else "—",
            detalle_facturado,
        )
    with columnas[1]:
        render_kpi_card(
            "Abonos recibidos",
            "—",
            "Siigo no informa el abono de cada factura",
        )
    with columnas[2]:
        render_kpi_card(
            "Saldo pendiente",
            money_kpi(saldo) if sumables else "—",
            detalle_saldo,
            highlighted=True,
        )


def _contar_filtros() -> int:
    activos = 0
    if st.session_state.get("filtro_empresa_siigo", TODAS) != TODAS:
        activos += 1
    for clave in ("filtro_clientes_siigo", "filtro_estados_siigo"):
        if st.session_state.get(clave):
            activos += 1
    if st.session_state.get("filtro_saldo_siigo", FILTROS_SALDO[0]) != FILTROS_SALDO[0]:
        activos += 1
    return activos


def _limpiar_filtros() -> None:
    st.session_state["filtro_facturas_siigo"] = ""
    st.session_state["filtro_empresa_siigo"] = TODAS
    st.session_state["filtro_clientes_siigo"] = []
    st.session_state["filtro_estados_siigo"] = []
    st.session_state["filtro_saldo_siigo"] = FILTROS_SALDO[0]


def _render_filtros(filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Buscador y panel de filtros, con el mismo aspecto que la cartera manual."""

    clientes = {}
    for fila in filas:
        clientes.setdefault(clave_cliente(fila), []).append(fila)
    opciones_cliente = {
        nombre_cliente(grupo): clave for clave, grupo in clientes.items()
    }
    opciones_cliente = dict(sorted(opciones_cliente.items(), key=lambda p: p[0].casefold()))
    estados_presentes = [
        codigo for codigo in SIIGO_ESTADO_META
        if any(etiqueta_estado(f) == SIIGO_ESTADO_META[codigo] for f in filas)
    ]

    columna_busqueda, columna_filtros = st.columns([3.8, 1], vertical_alignment="bottom")
    with columna_busqueda:
        termino = st.text_input(
            "Buscar en la cartera",
            placeholder="Factura, cliente, NIT o detalle del servicio",
            key="filtro_facturas_siigo",
        )
    with columna_filtros:
        activos = _contar_filtros()
        with st.popover(
            f"Filtros · {activos}" if activos else "Filtros",
            use_container_width=True,
        ):
            st.caption("Filtran lo ya leído; para cambiar el período, vuelve a consultar.")
            st.selectbox(
                "Empresa",
                [TODAS, *EMPRESAS],
                format_func=company_label,
                key="filtro_empresa_siigo",
            )
            guardados = st.session_state.get("filtro_clientes_siigo") or []
            validos = [c for c in guardados if c in opciones_cliente]
            if len(validos) != len(guardados):
                st.session_state["filtro_clientes_siigo"] = validos
            seleccion_clientes = st.multiselect(
                "Clientes",
                list(opciones_cliente),
                help="Busca por razón social; se muestra su cartera en todas las empresas.",
                placeholder="Selecciona clientes",
                key="filtro_clientes_siigo",
            )
            estados = st.multiselect(
                "Estado",
                estados_presentes,
                format_func=lambda codigo: SIIGO_ESTADO_META[codigo],
                placeholder="Selecciona estados",
                key="filtro_estados_siigo",
            )
            saldo = st.selectbox("Saldo", FILTROS_SALDO, key="filtro_saldo_siigo")
            st.button(
                "Limpiar filtros",
                use_container_width=True,
                on_click=_limpiar_filtros,
            )
    return {
        "termino": termino,
        "empresa": st.session_state.get("filtro_empresa_siigo", TODAS),
        "clientes": tuple(opciones_cliente[nombre] for nombre in seleccion_clientes),
        "estados": tuple(estados),
        "saldo": saldo,
    }


def _aplicar_filtros(
    filas: list[dict[str, Any]],
    filtros: Mapping[str, Any],
) -> list[dict[str, Any]]:
    salida = buscar_filas(filas, filtros["termino"])
    if filtros["empresa"] != TODAS:
        salida = [f for f in salida if str(f.get("empresa_codigo")) == filtros["empresa"]]
    if filtros["clientes"]:
        elegidos = set(filtros["clientes"])
        salida = [f for f in salida if clave_cliente(f) in elegidos]
    if filtros["estados"]:
        etiquetas = {SIIGO_ESTADO_META[c] for c in filtros["estados"]}
        salida = [f for f in salida if etiqueta_estado(f) in etiquetas]
    return filtrar_saldo(salida, filtros["saldo"])


def _render_estado_cuenta(filas: list[dict[str, Any]]) -> None:
    """Estado de cuenta de un cliente, separado por empresa, como el manual."""

    grupos: dict[str, list[dict[str, Any]]] = {}
    for fila in filas:
        grupos.setdefault(clave_cliente(fila), []).append(fila)
    opciones = {nombre_cliente(grupo): clave for clave, grupo in grupos.items()}
    opciones = dict(sorted(opciones.items(), key=lambda p: p[0].casefold()))

    render_section(
        "Detalle del cliente",
        "El total combina las tres empresas; el desglose muestra dónde vive cada factura.",
    )
    if not opciones:
        st.caption("Todavía no hay clientes en esta lectura.")
        return
    if st.session_state.get("detalle_cliente_siigo") not in opciones:
        st.session_state.pop("detalle_cliente_siigo", None)
    etiqueta = st.selectbox(
        "Cliente",
        list(opciones),
        index=None,
        placeholder="Escribe o elige la razón social",
        key="detalle_cliente_siigo",
        label_visibility="collapsed",
    )
    if not etiqueta:
        st.caption("Elige un cliente para ver su cartera separada por empresa.")
        return

    del_cliente = grupos[opciones[etiqueta]]
    sumables = filas_sumables(del_cliente)
    facturado, _ = suma_auditable(sumables, "total_siigo")
    saldo, sin_saldo = suma_auditable(sumables, "saldo_siigo")
    anuladas = sum(1 for f in del_cliente if not es_vigente(f))
    otra_moneda = sum(1 for f in del_cliente if not es_cop(f))

    por_empresa: dict[str, list[dict[str, Any]]] = {}
    for fila in del_cliente:
        por_empresa.setdefault(str(fila.get("empresa_codigo") or ""), []).append(fila)
    ordenadas = [c for c in EMPRESAS if c in por_empresa]
    ordenadas += [c for c in por_empresa if c not in EMPRESAS]

    st.caption(
        f"{len(del_cliente)} factura(s) en {len(ordenadas)} empresa(s) según Siigo. "
        "Esta cartera es de solo consulta: nadie la digita."
    )
    for codigo in ordenadas:
        del_empresa = por_empresa[codigo]
        saldo_empresa, _ = suma_auditable(filas_sumables(del_empresa), "saldo_siigo")
        titulo = company_name(codigo) if codigo in EMPRESAS else (codigo or "Sin empresa")
        st.markdown(f"**{etiqueta} · {titulo}**")
        render_grid(
            tabla_estado_cuenta(ordenar_filas(del_empresa)),
            key=f"tabla_detalle_cliente_siigo_{codigo or 'sin'}",
        )
        st.markdown(
            f'<div class="statement-company-total">Saldo pendiente '
            f'{html.escape(titulo)}: {money(saldo_empresa)}</div>',
            unsafe_allow_html=True,
        )
        st.write("")

    avisos = []
    if anuladas:
        avisos.append(f"{anuladas} anulada(s)")
    if sin_saldo:
        avisos.append(f"{sin_saldo} sin saldo leído")
    if otra_moneda:
        avisos.append(f"{otra_moneda} en otra moneda")
    nota = f" · No incluye {', '.join(avisos)}" if avisos else ""
    st.markdown(
        '<div class="statement-total-row">'
        f'<span class="statement-total-context">Facturado {money(facturado)}{html.escape(nota)}'
        '</span>'
        f'<span class="statement-total-badge">SALDO EN CARTERA&nbsp;&nbsp;{money(saldo)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def _render_sin_lectura(reporte: Reporte | None) -> None:
    """Distingue «nunca consultaste» de «consultaste y no había nada»."""

    if reporte is None:
        mensaje = (
            "<strong>Todavía no has consultado Siigo.</strong><br>"
            "Elige el período y pulsa «Consultar Siigo ahora», o carga la muestra "
            "de demostración para recorrer la pantalla."
        )
    else:
        periodo = ""
        if reporte.parametros:
            periodo = (
                f" del {reporte.parametros.desde.strftime('%d/%m/%Y')} al "
                f"{reporte.parametros.hasta.strftime('%d/%m/%Y')}"
            )
        mensaje = (
            f"<strong>La lectura{periodo} no encontró facturas.</strong><br>"
            "Amplía el período o revisa las advertencias de arriba."
        )
    st.markdown(f'<div class="empty-state">{mensaje}</div>', unsafe_allow_html=True)


def render_siigo_portfolio(company: str) -> None:
    """Renderiza la cartera Siigo: consulta, supervisión y las mismas tablas."""

    render_section(
        "Cartera Siigo",
        "Lectura de solo consulta, factura por factura. Esta pantalla nunca modifica "
        "documentos en Siigo ni toca la cartera manual.",
    )
    st.write("")
    configuracion, faltantes = _configuracion()
    parametros, pidio_muestra = _formulario_consulta(configuracion, faltantes)

    if parametros is not None and configuracion is not None:
        _publicar(_ejecutar_lectura(configuracion, parametros))
    elif pidio_muestra:
        _publicar(cargar_muestra())

    reporte = _reporte_publicado()
    st.write("")
    if reporte is None:
        _render_sin_lectura(None)
        return

    _render_supervision(reporte, company)
    filas = ordenar_filas(filas_de_dataframe(reporte.facturas))
    if not filas:
        _render_sin_lectura(reporte)
        return

    # Las tarjetas siguen arriba, como en la cartera manual, pero se pintan
    # con las facturas que el filtro dejó visibles. Antes sumaban TODAS, así
    # que el indicador y la tabla de abajo mostraban cifras distintas en la
    # misma pantalla; y estas vistas se envían como imagen, de modo que la
    # contradicción viajaba con ellas. El contenedor reserva el sitio para
    # dibujarlas después de conocer el filtro, sin mover nada de lugar.
    tarjetas = st.container()
    filtros = _render_filtros(filas)
    visibles = _aplicar_filtros(filas, filtros)
    with tarjetas:
        _render_kpis(visibles)
        st.write("")
    vigentes = [f for f in visibles if es_vigente(f)]
    anuladas = [f for f in visibles if not es_vigente(f)]

    general, clientes = st.tabs(["General", "Clientes y saldo pendiente"])
    with general:
        empresa_titulo = company_name(filtros["empresa"])
        render_section(
            f"Cartera Siigo · {empresa_titulo}",
            f"{len(vigentes)} factura(s) visible(s) · valores oficiales informados por Siigo.",
        )
        st.write("")
        if vigentes:
            render_grid(tabla_general(vigentes), key="tabla_cartera_siigo")
            st.caption(
                "Valores en pesos colombianos, sin centavos. Una raya significa que "
                "Siigo no entregó ese dato, no que valga cero."
            )
        else:
            st.markdown(
                '<div class="empty-state"><strong>No hay facturas para este filtro.</strong><br>'
                "Limpia los filtros o amplía el período de la consulta.</div>",
                unsafe_allow_html=True,
            )
        if anuladas:
            with st.expander(f"Anuladas ({len(anuladas)})"):
                render_grid(tabla_general(anuladas), key="tabla_anuladas_siigo")
                st.caption("No suman en los totales ni en el saldo de cartera.")
    with clientes:
        tabla = tabla_clientes(visibles)
        render_section(
            "Clientes y saldo pendiente",
            f"{len(tabla)} cliente(s) con saldo según Siigo.",
        )
        st.write("")
        if tabla.empty:
            st.markdown(
                '<div class="empty-state"><strong>No hay clientes con saldo pendiente.</strong><br>'
                "Puede que todas las facturas del período estén pagadas.</div>",
                unsafe_allow_html=True,
            )
        else:
            render_grid(tabla[list(COLUMNAS_CLIENTES)], key="tabla_clientes_siigo")
        st.write("")
        _render_estado_cuenta(visibles)


__all__ = ["render_siigo_portfolio"]
