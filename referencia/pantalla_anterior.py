"""Vista de supervisión de cartera en vivo desde Siigo."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from typing import Any

import pandas as pd
import streamlit as st

from src import database as db
from src.cartera_siigo import (
    EMPRESAS_SIIGO,
    ESTADOS_CONTABLES,
    ESTADOS_REVISION,
    conciliar_cartera,
    construir_operacion_local,
    enriquecer_facturas_clientes,
    facturas_a_dataframe,
    hash_fuente_siigo,
    normalizar_factura,
    recibos_a_dataframe,
)
from src.siigo import (
    ClienteSiigo,
    ConfiguracionSiigo,
    ErrorConfiguracionSiigo,
    ErrorSiigo,
)
from src.ui.componentes import fmt_cop


API_VERSION = "2026.08.21.1"
_CLAVE_SNAPSHOT = "_cartera_siigo_snapshot"
_EDAD_MAXIMA_APROBACION = dt.timedelta(minutes=5)


def _secretos_streamlit() -> Mapping[str, Any] | None:
    try:
        secretos = st.secrets
        claves = list(secretos.keys())
        if isinstance(secretos, Mapping):
            return secretos
        return {clave: secretos[clave] for clave in claves}
    except Exception:
        return None


def configuracion_siigo_disponible() -> tuple[ConfiguracionSiigo | None, dict[str, str]]:
    """Carga cada empresa por separado para permitir una activación gradual."""

    secretos = _secretos_streamlit()
    credenciales = {}
    errores: dict[str, str] = {}
    for codigo in EMPRESAS_SIIGO:
        configurada = None
        if secretos is not None:
            try:
                parcial = ConfiguracionSiigo.desde_mapeo_secretos(
                    secretos, {codigo: codigo}
                )
                configurada = parcial.credenciales_para(codigo)
            except ErrorConfiguracionSiigo:
                configurada = None
        if configurada is None:
            try:
                parcial = ConfiguracionSiigo.desde_entorno(
                    {codigo: codigo}, entorno=os.environ
                )
                configurada = parcial.credenciales_para(codigo)
            except ErrorConfiguracionSiigo:
                errores[codigo] = "Sin credenciales configuradas"
        if configurada is not None:
            credenciales[codigo] = configurada
            errores.pop(codigo, None)
    if not credenciales:
        return None, errores
    try:
        return ConfiguracionSiigo(empresas=credenciales), errores
    except ErrorConfiguracionSiigo as exc:
        errores["CONFIGURACION"] = str(exc)
        return None, errores


def _cliente_sin_nombre(factura: Mapping[str, Any]) -> bool:
    cliente = factura.get("customer")
    return not isinstance(cliente, Mapping) or not cliente.get("name")


def _enriquecer_clientes_relevantes(
    cliente: ClienteSiigo,
    facturas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Consulta solo terceros presentes; usa catálogos si el lote es grande."""

    if not facturas or not any(_cliente_sin_nombre(f) for f in facturas):
        return facturas
    ids = {
        str(f.get("customer", {}).get("id") or "").strip()
        for f in facturas
        if isinstance(f.get("customer"), Mapping) and _cliente_sin_nombre(f)
    }
    ids.discard("")
    sin_id = any(
        _cliente_sin_nombre(f)
        and (
            not isinstance(f.get("customer"), Mapping)
            or not str(f["customer"].get("id") or "").strip()
        )
        for f in facturas
        if isinstance(f, Mapping)
    )
    if ids and len(ids) <= 25 and not sin_id:
        catalogo = [cliente.consultar_cliente(cliente_id) for cliente_id in sorted(ids)]
        return enriquecer_facturas_clientes(facturas, catalogo)

    catalogo = cliente.listar_clientes(activo=True)
    enriquecidas = enriquecer_facturas_clientes(facturas, catalogo)
    if any(_cliente_sin_nombre(f) for f in enriquecidas):
        # ``active`` es true por defecto en Siigo; la segunda consulta evita perder
        # nombres de clientes inactivos presentes en facturas históricas.
        catalogo += cliente.listar_clientes(activo=False)
        enriquecidas = enriquecer_facturas_clientes(facturas, catalogo)
    return enriquecidas


def _consultar_siigo(
    configuracion: ConfiguracionSiigo,
    empresas: list[str],
    fecha_inicio: dt.date,
    fecha_fin: dt.date,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[tuple[str, str], dict], dict[str, str]]:
    tablas_facturas: list[pd.DataFrame] = []
    tablas_recibos: list[pd.DataFrame] = []
    detalle: dict[tuple[str, str], dict] = {}
    errores: dict[str, str] = {}
    fin_recibos = max(fecha_fin, dt.date.today())
    for codigo in empresas:
        try:
            cliente = ClienteSiigo(codigo, configuracion)
            facturas = cliente.listar_facturas(fecha_inicio, fecha_fin)
        except ErrorSiigo as exc:
            errores[codigo] = str(exc)
            continue
        except Exception as exc:
            errores[codigo] = f"No fue posible consultar esta empresa ({type(exc).__name__})."
            continue
        if not facturas:
            tablas_facturas.append(facturas_a_dataframe(codigo, []))
            continue
        try:
            facturas = _enriquecer_clientes_relevantes(cliente, facturas)
        except ErrorSiigo as exc:
            errores[f"{codigo} · CLIENTES"] = str(exc)
        except Exception as exc:
            errores[f"{codigo} · CLIENTES"] = (
                f"No fue posible consultar nombres de clientes ({type(exc).__name__})"
            )
        try:
            tablas_facturas.append(facturas_a_dataframe(codigo, facturas))
            for factura in facturas:
                factura_id = str(factura.get("id") or "").strip()
                if factura_id:
                    detalle[(codigo, factura_id)] = dict(factura)
        except Exception as exc:
            errores[codigo] = f"Siigo entregó facturas no válidas ({type(exc).__name__})."
            continue
        try:
            recibos = cliente.listar_recibos_caja(fecha_inicio, fin_recibos)
            tablas_recibos.append(recibos_a_dataframe(codigo, recibos))
        except ErrorSiigo as exc:
            errores[f"{codigo} · RECIBOS"] = str(exc)
        except Exception as exc:
            errores[f"{codigo} · RECIBOS"] = (
                f"No fue posible consultar abonos ({type(exc).__name__})"
            )
    facturas_df = (
        pd.concat(tablas_facturas, ignore_index=True)
        if tablas_facturas else facturas_a_dataframe("", [])
    )
    recibos_df = (
        pd.concat(tablas_recibos, ignore_index=True)
        if tablas_recibos else recibos_a_dataframe("", [])
    )
    return facturas_df, recibos_df, detalle, errores


def _aplicar_periodo_visible(
    facturas: pd.DataFrame,
    desde: dt.date,
    hasta: dt.date,
    incluir_anteriores: bool,
) -> pd.DataFrame:
    if facturas.empty:
        return facturas.copy()
    fechas = pd.to_datetime(facturas["fecha"], errors="coerce").dt.date
    en_periodo = fechas.ge(desde) & fechas.le(hasta)
    if incluir_anteriores:
        saldo = pd.to_numeric(facturas["saldo_siigo"], errors="coerce")
        # Un balance nulo es un dato incompleto, no una factura pagada; se conserva
        # para revisión en vez de desaparecer del histórico.
        en_periodo = en_periodo | (fechas.lt(desde) & (saldo.gt(0.5) | saldo.isna()))
    return facturas[en_periodo].reset_index(drop=True)


def _filtrar_fuente_por_fecha(
    datos: pd.DataFrame,
    columna: str,
    desde: dt.date,
    hasta: dt.date,
) -> pd.DataFrame:
    if datos.empty or columna not in datos.columns:
        return datos.iloc[0:0].copy()
    fechas = pd.to_datetime(datos[columna], errors="coerce").dt.date
    return datos[fechas.ge(desde) & fechas.le(hasta)].copy()


def _operacion_para_consulta(
    vehiculos: pd.DataFrame,
    gruas: pd.DataFrame,
    viajes: pd.DataFrame,
    facturas_visibles: pd.DataFrame,
    desde: dt.date,
    hasta: dt.date,
    empresas_consultadas: list[str] | tuple[str, ...] | set[str],
) -> pd.DataFrame:
    """Cruza históricos, pero limita los faltantes locales al rango consultado."""

    empresas_validas = {str(codigo).strip().upper() for codigo in empresas_consultadas}
    completa = construir_operacion_local(vehiculos, gruas, viajes)
    if not completa.empty:
        completa = completa[completa["empresa_codigo"].isin(empresas_validas)].copy()
    claves_siigo = {
        (str(fila.get("empresa_codigo") or ""), normalizar_factura(fila.get("factura")))
        for _, fila in facturas_visibles.iterrows()
    }
    coincidentes = completa[
        completa.apply(
            lambda fila: (
                str(fila.get("empresa_codigo") or ""),
                str(fila.get("factura_clave") or ""),
            ) in claves_siigo,
            axis=1,
        )
    ] if not completa.empty else completa

    periodo = construir_operacion_local(
        _filtrar_fuente_por_fecha(vehiculos, "fecha", desde, hasta),
        _filtrar_fuente_por_fecha(gruas, "fecha_inicio", desde, hasta),
        _filtrar_fuente_por_fecha(viajes, "fecha", desde, hasta),
    )
    if not periodo.empty:
        periodo = periodo[periodo["empresa_codigo"].isin(empresas_validas)].copy()
    salida = pd.concat([coincidentes, periodo], ignore_index=True)
    if salida.empty:
        return salida
    return salida.drop_duplicates(
        subset=["empresa_codigo", "factura_clave"], keep="first"
    ).reset_index(drop=True)


def _guardar_snapshot(
    facturas: pd.DataFrame,
    recibos: pd.DataFrame,
    operacion: pd.DataFrame,
    detalle: dict,
    errores: dict[str, str],
    parametros: dict[str, Any],
    *,
    facturas_consultadas: pd.DataFrame | None = None,
) -> None:
    st.session_state[_CLAVE_SNAPSHOT] = {
        "facturas": facturas,
        # Conserva el lote completo de Siigo antes del filtro de cartera visible.
        # Es la fuente del resumen histórico e incluye también facturas ya pagadas.
        "facturas_consultadas": (
            facturas.copy()
            if facturas_consultadas is None
            else facturas_consultadas.copy()
        ),
        "recibos": recibos,
        "operacion": operacion,
        "detalle": detalle,
        "errores": errores,
        "parametros": parametros,
        "consultado_en": dt.datetime.now().astimezone(),
    }


def _asegurar_campos_ui_siigo(facturas: pd.DataFrame) -> pd.DataFrame:
    """Compatibilidad para snapshots previos sin recalcular valores de Siigo."""

    salida = facturas.copy()
    if "descripcion_siigo" not in salida.columns:
        salida["descripcion_siigo"] = ""
    for columna in ("subtotal_siigo", "descuento_siigo"):
        if columna not in salida.columns:
            salida[columna] = None
    return salida


def _filtrar_texto_siigo(cartera: pd.DataFrame, busqueda: str) -> pd.DataFrame:
    termino = str(busqueda or "").strip().casefold()
    if not termino or cartera.empty:
        return cartera.copy()
    texto = pd.Series("", index=cartera.index, dtype="object")
    for columna in ("factura", "cliente", "nit", "descripcion_siigo"):
        valores = cartera.get(
            columna, pd.Series("", index=cartera.index, dtype="object")
        )
        texto = texto + " " + valores.fillna("").astype(str)
    return cartera[texto.str.casefold().str.contains(termino, regex=False)].copy()


def _suma_auditable(valores: pd.Series) -> float:
    numeros = pd.to_numeric(valores, errors="coerce")
    if numeros.isna().any():
        return float("nan")
    return float(numeros.sum())


def _resumen_historico_clientes(
    facturas_consultadas: pd.DataFrame,
    recibos: pd.DataFrame | None = None,
    empresas_recibos_no_disponibles: set[str] | None = None,
) -> pd.DataFrame:
    """Resume solo valores Siigo del lote completo, separados por moneda."""

    columnas = [
        "EMPRESA", "CLIENTE", "NIT", "MONEDA", "PRIMERA FACTURA",
        "ÚLTIMA FACTURA", "FACTURAS", "TOTAL FACTURADO",
        "DESCUENTOS SIIGO", "ANTICIPOS SIIGO",
        "ABONOS (RECIBOS CONSULTADOS)", "SALDO SIIGO",
        "VALOR CUBIERTO (TOTAL - SALDO)",
    ]
    if facturas_consultadas is None or facturas_consultadas.empty:
        return pd.DataFrame(columns=columnas)

    base = _cartera_vigente(facturas_consultadas).copy()
    if base.empty:
        return pd.DataFrame(columns=columnas)
    for columna, predeterminado in {
        "empresa_codigo": "", "empresa": "", "cliente": "", "nit": "",
        "moneda": "COP",
        "siigo_factura_id": "", "factura": "", "fecha": None,
        "total_siigo": None, "descuento_siigo": None,
        "anticipo_aplicado": 0.0, "saldo_siigo": None,
    }.items():
        if columna not in base.columns:
            base[columna] = predeterminado

    base["factura_clave"] = base["factura"].map(normalizar_factura)
    empresas_sin_recibos = {
        str(empresa or "").strip().upper()
        for empresa in (empresas_recibos_no_disponibles or set())
    }
    recibos_base = recibos.copy() if recibos is not None else pd.DataFrame()
    if not recibos_base.empty:
        columnas_recibo = [
            columna for columna in (
                "empresa_codigo", "factura_clave", "abonos_recibos"
            ) if columna in recibos_base.columns
        ]
        if len(columnas_recibo) == 3:
            recibos_base = recibos_base[columnas_recibo].drop_duplicates(
                ["empresa_codigo", "factura_clave"], keep="last"
            )
            base = base.merge(
                recibos_base,
                on=["empresa_codigo", "factura_clave"],
                how="left",
            )
    if "abonos_recibos" not in base.columns:
        base["abonos_recibos"] = 0.0
    base["abonos_recibos"] = pd.to_numeric(
        base["abonos_recibos"], errors="coerce"
    ).fillna(0.0).astype(float)
    if empresas_sin_recibos:
        codigos = base["empresa_codigo"].fillna("").astype(str).str.upper()
        base.loc[codigos.isin(empresas_sin_recibos), "abonos_recibos"] = float("nan")
    total = pd.to_numeric(base["total_siigo"], errors="coerce")
    saldo = pd.to_numeric(base["saldo_siigo"], errors="coerce")
    base["valor_cubierto"] = (total - saldo).where(total.notna() & saldo.notna())
    base["fecha_resumen"] = pd.to_datetime(base["fecha"], errors="coerce")
    base["factura_resumen"] = base["siigo_factura_id"].fillna("").astype(str)
    sin_id = base["factura_resumen"].eq("")
    base.loc[sin_id, "factura_resumen"] = base.loc[sin_id, "factura"].astype(str)

    agrupado = (
        base.groupby(["empresa", "cliente", "nit", "moneda"], dropna=False)
        .agg(
            primera_factura=("fecha_resumen", "min"),
            ultima_factura=("fecha_resumen", "max"),
            facturas=("factura_resumen", "nunique"),
            total_facturado=("total_siigo", _suma_auditable),
            descuentos=("descuento_siigo", _suma_auditable),
            anticipos=("anticipo_aplicado", _suma_auditable),
            abonos=("abonos_recibos", _suma_auditable),
            saldo=("saldo_siigo", _suma_auditable),
            valor_cubierto=("valor_cubierto", _suma_auditable),
        )
        .reset_index()
    )
    for columna in ("primera_factura", "ultima_factura"):
        agrupado[columna] = agrupado[columna].dt.date
    agrupado = agrupado.rename(columns={
        "empresa": "EMPRESA",
        "cliente": "CLIENTE",
        "nit": "NIT",
        "moneda": "MONEDA",
        "primera_factura": "PRIMERA FACTURA",
        "ultima_factura": "ÚLTIMA FACTURA",
        "facturas": "FACTURAS",
        "total_facturado": "TOTAL FACTURADO",
        "descuentos": "DESCUENTOS SIIGO",
        "anticipos": "ANTICIPOS SIIGO",
        "abonos": "ABONOS (RECIBOS CONSULTADOS)",
        "saldo": "SALDO SIIGO",
        "valor_cubierto": "VALOR CUBIERTO (TOTAL - SALDO)",
    })
    return agrupado[columnas].sort_values(
        ["EMPRESA", "MONEDA", "SALDO SIIGO"],
        ascending=[True, True, False],
        na_position="last",
    ).reset_index(drop=True)


def _tabla_visible(cartera: pd.DataFrame) -> pd.DataFrame:
    columnas = {
        "empresa": "EMPRESA",
        "factura": "FACTURA",
        "descripcion_siigo": "DESCRIPCIÓN SIIGO",
        "fecha": "FECHA",
        "cliente": "CLIENTE",
        "nit": "NIT",
        "sucursal": "SUCURSAL",
        "moneda": "MONEDA",
        "tasa_cambio": "TASA CAMBIO",
        "subtotal_siigo": "SUBTOTAL SIIGO",
        "descuento_siigo": "DESCUENTO SIIGO",
        "base_siigo": "BASE NETA SIIGO",
        "iva_siigo": "IVA",
        "otros_impuestos_siigo": "OTROS IMPUESTOS",
        "retefuente_siigo": "RETEFUENTE",
        "reteica_siigo": "RETEICA",
        "reteiva_siigo": "RETEIVA",
        "otras_retenciones_siigo": "OTRAS RETENCIONES",
        "total_siigo": "TOTAL SIIGO",
        "saldo_siigo": "SALDO SIIGO",
        "anticipo_aplicado": "ANTICIPO APLICADO",
        "abonos_recibos": "ABONOS (RECIBOS)",
        "cuotas_abonadas": "CUOTAS ABONADAS",
        "otros_ajustes": "OTROS AJUSTES / NOTAS",
        "vencimiento_inicial": "PRIMER VENCIMIENTO",
        "vencimiento": "VENCIMIENTO",
        "cuotas": "CUOTAS",
        "dias_mora": "DÍAS MORA",
        "antiguedad": "ANTIGÜEDAD",
        "estado_siigo": "ESTADO SIIGO",
        "valor_base_local": "BASE OPERATIVA",
        "standby_local": "STANDBY LOCAL",
        "diferencia_base": "DIFERENCIA SUBTOTAL VS BASE OPERATIVA",
        "origen_local": "ORIGEN LOCAL",
        "placas": "PLACAS/EQUIPOS",
        "manifiestos": "MANIFIESTOS/ÓRDENES",
        "resultado_conciliacion": "CONCILIACIÓN",
        "estado_revision": "SUPERVISIÓN",
        "observacion": "OBSERVACIÓN",
        "observaciones_siigo": "OBSERVACIONES SIIGO",
    }
    existentes = [columna for columna in columnas if columna in cartera.columns]
    return cartera[existentes].rename(columns=columnas)


def _filtrar_vista(cartera: pd.DataFrame) -> pd.DataFrame:
    if cartera.empty:
        return cartera
    a, b, c = st.columns([1.2, 1, 1])
    busqueda = a.text_input(
        "Cliente, NIT, factura o descripción Siigo",
        key="siigo_filtro_texto",
        placeholder="Buscar…",
    ).strip().casefold()
    estados = b.multiselect(
        "Estado Siigo", ESTADOS_CONTABLES, key="siigo_filtro_estado"
    )
    revisiones = c.multiselect(
        "Supervisión",
        list(ESTADOS_REVISION) + [
            "EN_REVISION_CAMBIO_DATOS", "EN_REVISION_CAMBIO_SIIGO",
        ],
        key="siigo_filtro_revision",
    )
    salida = cartera.copy()
    if busqueda:
        salida = _filtrar_texto_siigo(salida, busqueda)
    if estados:
        salida = salida[salida["estado_siigo"].isin(estados)]
    if revisiones:
        salida = salida[salida["estado_revision"].isin(revisiones)]
    return salida.reset_index(drop=True)


def _cartera_vigente(cartera: pd.DataFrame) -> pd.DataFrame:
    """Conserva anuladas en el detalle, pero no en agregados financieros."""

    if cartera.empty:
        return cartera.copy()
    estados = cartera.get(
        "estado_siigo", pd.Series("", index=cartera.index, dtype="object")
    )
    return cartera[~estados.fillna("").astype(str).eq("ANULADA")].copy()


def _neutralizar_formula_csv(valor: Any) -> Any:
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def _csv_seguro(vista: pd.DataFrame) -> bytes:
    """Genera CSV legible por Excel sin ejecutar texto externo como fórmula."""

    salida = vista.copy()
    for columna in salida.columns:
        if pd.api.types.is_object_dtype(salida[columna]) \
                or pd.api.types.is_string_dtype(salida[columna]):
            salida[columna] = salida[columna].map(_neutralizar_formula_csv)
    return salida.to_csv(index=False).encode("utf-8-sig")


def _metricas(cartera: pd.DataFrame, faltantes: pd.DataFrame) -> None:
    vigentes = _cartera_vigente(cartera)
    anuladas = len(cartera) - len(vigentes)
    monedas = vigentes.get(
        "moneda", pd.Series(dtype="object")
    ).fillna("COP").astype(str).str.upper()
    no_cop = monedas.ne("COP")
    if bool(no_cop.any()):
        st.warning(
            f"Hay {int(no_cop.sum())} factura(s) en moneda distinta de COP. "
            "No se mezclan en los totales monetarios."
        )
    cartera_cop = vigentes[~no_cop] if not vigentes.empty else vigentes
    total_serie = pd.to_numeric(cartera_cop.get("total_siigo"), errors="coerce")
    saldo_serie = pd.to_numeric(cartera_cop.get("saldo_siigo"), errors="coerce")
    total = total_serie.sum(min_count=1)
    saldo = saldo_serie.sum(min_count=1)
    incompletas = int(pd.to_numeric(
        vigentes.get("saldo_siigo", pd.Series(dtype="float64")), errors="coerce"
    ).isna().sum())
    vencido = pd.to_numeric(
        cartera_cop.loc[cartera_cop.get("estado_siigo").eq("VENCIDA"), "saldo_siigo"],
        errors="coerce",
    ).sum(min_count=1) if not cartera_cop.empty else 0
    en_revision = int(cartera.get("estado_revision", pd.Series(dtype="object")).astype(str).str.startswith("EN_REVISION").sum())
    columnas = st.columns(6)
    columnas[0].metric("Facturado", fmt_cop(total, dash_zero=False))
    columnas[1].metric("Saldo conocido", fmt_cop(saldo, dash_zero=False))
    columnas[2].metric("Saldo vencido", fmt_cop(vencido, dash_zero=False))
    columnas[3].metric("En revisión", f"{en_revision:,}".replace(",", "."))
    columnas[4].metric("Saldo incompleto", f"{incompletas:,}".replace(",", "."))
    columnas[5].metric("Locales sin Siigo", f"{len(faltantes):,}".replace(",", "."))
    if anuladas:
        st.caption(
            f"{anuladas} factura(s) anulada(s) permanecen en el detalle, "
            "pero no se suman en Facturado, Saldo ni los totales por cliente."
        )


def _validar_aprobacion_fresca(
    configuracion: ConfiguracionSiigo,
    fila: Mapping[str, Any],
    consultado_en: dt.datetime,
    *,
    ahora: dt.datetime | None = None,
) -> None:
    """Impide aprobar una lectura vieja o una factura que ya cambió en Siigo."""

    ahora = ahora or dt.datetime.now().astimezone()
    marca = consultado_en
    if marca.tzinfo is None:
        marca = marca.replace(tzinfo=ahora.tzinfo)
    if ahora - marca > _EDAD_MAXIMA_APROBACION:
        raise RuntimeError(
            "La lectura tiene más de 5 minutos. Consulta Siigo de nuevo antes de aprobar."
        )
    empresa = str(fila.get("empresa_codigo") or "")
    factura_id = str(fila.get("siigo_factura_id") or "")
    actual = ClienteSiigo(empresa, configuracion).consultar_factura(factura_id)
    if hash_fuente_siigo(actual) != str(fila.get("fuente_hash") or ""):
        raise RuntimeError(
            "La factura cambió en Siigo después de esta lectura. Consulta de nuevo."
        )


def _validar_fuentes_para_aprobar(
    fila: Mapping[str, Any],
    errores: Mapping[str, str],
) -> None:
    """Una lectura parcial puede verse, pero nunca aprobarse como completa."""

    empresa = str(fila.get("empresa_codigo") or "")
    relevantes = [
        clave for clave in errores
        if clave == "OPERACION_LOCAL" or clave == empresa or clave.startswith(empresa + " ")
    ]
    if relevantes:
        raise RuntimeError(
            "No se puede aprobar porque faltó una fuente de esta lectura ("
            + ", ".join(relevantes)
            + "). Consulta de nuevo cuando esté disponible."
        )
    if str(fila.get("estado_siigo") or "") == "DATO_INCOMPLETO":
        raise RuntimeError(
            "No se puede aprobar mientras Siigo entregue saldo o cuotas incompletas."
        )


def _formulario_revision(
    cartera: pd.DataFrame,
    configuracion: ConfiguracionSiigo,
    consultado_en: dt.datetime,
    errores: Mapping[str, str],
) -> None:
    if cartera.empty:
        return
    st.markdown("#### Supervisar una factura")
    opciones = {}
    for indice, fila in cartera.iterrows():
        etiqueta = f"{fila.get('empresa_codigo')} · {fila.get('factura')} · {fila.get('cliente')}"
        opciones.setdefault(etiqueta, indice)
    seleccion = st.selectbox(
        "Factura", list(opciones), key="siigo_revision_factura"
    )
    fila = cartera.loc[opciones[seleccion]]
    factura_id = str(fila.get("siigo_factura_id") or "")
    clave_form = f"siigo_revision_{fila.get('empresa_codigo')}_{factura_id}"
    estado_actual = str(fila.get("estado") or "EN_REVISION")
    if estado_actual not in ESTADOS_REVISION:
        estado_actual = "EN_REVISION"
    with st.form(clave_form):
        estado = st.selectbox(
            "Estado interno",
            ESTADOS_REVISION,
            index=ESTADOS_REVISION.index(estado_actual),
        )
        observacion = st.text_area(
            "Observación de Finanzas",
            value=str(fila.get("observacion") or ""),
            max_chars=4000,
        )
        guardar = st.form_submit_button("Guardar revisión", type="primary")
    if guardar:
        version = fila.get("version")
        version_esperada = 0 if pd.isna(version) or version is None else int(version)
        try:
            if estado == "APROBADA":
                _validar_fuentes_para_aprobar(fila, errores)
                _validar_aprobacion_fresca(
                    configuracion, fila, consultado_en
                )
            db.guardar_revision_siigo(
                str(fila["empresa_codigo"]),
                factura_id,
                estado,
                observacion,
                str(fila["huella_revision"]),
                st.session_state.rol,
                version_esperada=version_esperada,
            )
        except (ValueError, PermissionError, RuntimeError, ErrorSiigo) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(
                "No se pudo guardar la revisión central "
                f"({type(exc).__name__}). La factura de Siigo no fue modificada."
            )
        else:
            st.session_state["_flash"] = "Revisión de Siigo guardada."
            st.rerun()


def _detalle_factura(cartera: pd.DataFrame, detalle: dict) -> None:
    if cartera.empty:
        return
    st.markdown("#### Detalle contable y operativo")
    opciones = {
        f"{fila.get('empresa_codigo')} · {fila.get('factura')} · {fila.get('cliente')}": indice
        for indice, fila in cartera.iterrows()
    }
    etiqueta = st.selectbox("Ver detalle de", list(opciones), key="siigo_detalle_factura")
    fila = cartera.loc[opciones[etiqueta]]
    raw = detalle.get((str(fila.get("empresa_codigo")), str(fila.get("siigo_factura_id"))), {})
    izquierda, derecha = st.columns(2, gap="large")
    with izquierda:
        st.markdown("##### Siigo · fuente contable oficial")
        st.write(f"**Factura:** {fila.get('factura') or '—'}")
        st.write(
            f"**Descripción Siigo:** {fila.get('descripcion_siigo') or '—'}"
        )
        st.write(f"**Cliente:** {fila.get('cliente') or '—'} · {fila.get('nit') or '—'}")
        st.write(f"**Sucursal:** {fila.get('sucursal') or '0'}")
        st.write(
            f"**Subtotal bruto:** {fmt_cop(fila.get('subtotal_siigo'), dash_zero=False)}"
        )
        st.write(f"**Descuento Siigo:** {fmt_cop(fila.get('descuento_siigo'))}")
        st.write(f"**Base neta:** {fmt_cop(fila.get('base_siigo'), dash_zero=False)}")
        st.write(f"**IVA:** {fmt_cop(fila.get('iva_siigo'))}")
        st.write(
            "**Retenciones (fuente / ICA / IVA):** "
            f"{fmt_cop(fila.get('retefuente_siigo'))} / "
            f"{fmt_cop(fila.get('reteica_siigo'))} / "
            f"{fmt_cop(fila.get('reteiva_siigo'))}"
        )
        st.write(f"**Total:** {fmt_cop(fila.get('total_siigo'), dash_zero=False)}")
        st.write(f"**Saldo oficial:** {fmt_cop(fila.get('saldo_siigo'), dash_zero=False)}")
        st.write(f"**Anticipo aplicado:** {fmt_cop(fila.get('anticipo_aplicado'))}")
        st.write(f"**Recibos de caja:** {fila.get('recibos_caja') or '—'}")
        items = raw.get("items") if isinstance(raw, Mapping) else None
        if isinstance(items, list) and items:
            st.dataframe(pd.DataFrame(items), width="stretch", hide_index=True)
    with derecha:
        st.markdown("##### Conciliación operativa · no contable")
        st.caption(
            "Estos datos del programa sirven para contrastar el servicio; no "
            "reemplazan total, descuento, abonos ni saldo informados por Siigo."
        )
        st.write(f"**Origen:** {fila.get('origen_local') or 'Sin registro local'}")
        st.write(f"**Base registrada:** {fmt_cop(fila.get('valor_base_local'))}")
        st.write(f"**Standby:** {fmt_cop(fila.get('standby_local'))}")
        st.write(f"**Placas/equipos:** {fila.get('placas') or '—'}")
        st.write(f"**Manifiestos/órdenes:** {fila.get('manifiestos') or '—'}")
        st.write(f"**Conciliación:** {fila.get('resultado_conciliacion') or '—'}")


def tab_cartera_siigo(rol: str) -> None:
    """Consulta cartera directamente en Siigo y guarda solo su supervisión."""

    if rol not in {"Admin", "Finanzas"}:
        st.error("Esta vista está disponible únicamente para Admin y Finanzas.")
        return
    st.markdown("## Cartera Siigo")
    st.success(
        "SOLO CONSULTA · Esta pantalla puede leer facturas, saldos, clientes y recibos; "
        "no puede crear, editar, anular ni borrar documentos en Siigo."
    )
    st.info(
        "Los valores contables oficiales de esta vista provienen exclusivamente de "
        "Siigo. Los datos del programa se muestran aparte y solo se usan para conciliación."
    )
    configuracion, sin_configurar = configuracion_siigo_disponible()
    configuradas = [
        codigo for codigo in EMPRESAS_SIIGO
        if configuracion is not None and codigo not in sin_configurar
    ]
    estados = st.columns(3)
    for columna, codigo in zip(estados, EMPRESAS_SIIGO):
        columna.caption(
            f"{'🟢' if codigo in configuradas else '⚪'} {EMPRESAS_SIIGO[codigo]}"
        )

    if configuracion is None:
        st.warning("Aún no hay credenciales de Siigo configuradas en el servidor.")
        if sin_configurar.get("CONFIGURACION"):
            st.error(sin_configurar["CONFIGURACION"])
        with st.expander("Cómo activar la conexión"):
            st.code(
                "[siigo]\n"
                "partner_id = \"TU_PARTNER_ID\"\n\n"
                "[siigo.empresas.NOVASA]\n"
                "username = \"...\"\n"
                "access_key = \"...\"\n\n"
                "[siigo.empresas.LUAC]\n"
                "username = \"...\"\n"
                "access_key = \"...\"\n\n"
                "[siigo.empresas.MSU]\n"
                "username = \"...\"\n"
                "access_key = \"...\"",
                language="toml",
            )
            st.caption("Las claves se guardan en secretos del servidor; nunca en la base ni en el navegador.")
        return

    hoy = dt.date.today()
    inicio_mes = hoy.replace(day=1)
    inicio_anio = hoy.replace(month=1, day=1)
    with st.form("consulta_cartera_siigo"):
        a, b, c = st.columns([1.4, 1, 1])
        empresas = a.multiselect(
            "Empresas",
            configuradas,
            default=configuradas,
            format_func=lambda codigo: EMPRESAS_SIIGO[codigo],
        )
        desde = b.date_input("Periodo desde", value=inicio_mes, format="DD/MM/YYYY")
        hasta = c.date_input("Periodo hasta", value=hoy, format="DD/MM/YYYY")
        d, e = st.columns([1.4, 1])
        incluir_anteriores = d.checkbox(
            "Incluir facturas anteriores que todavía tengan saldo",
            value=True,
        )
        buscar_desde = e.date_input(
            "Buscar históricos desde",
            value=inicio_anio,
            format="DD/MM/YYYY",
            help="No limita el sistema a un año: puedes escoger cualquier fecha.",
        )
        consultar = st.form_submit_button("Consultar Siigo ahora", type="primary")

    if consultar:
        if not empresas:
            st.error("Selecciona al menos una empresa.")
        elif desde > hasta:
            st.error("La fecha inicial no puede ser posterior a la final.")
        elif incluir_anteriores and buscar_desde > desde:
            st.error("La búsqueda histórica debe comenzar antes del periodo visible.")
        else:
            inicio_consulta = buscar_desde if incluir_anteriores else desde
            with st.spinner("Leyendo Siigo y conciliando la operación…"):
                facturas, recibos, detalle, errores = _consultar_siigo(
                    configuracion, empresas, inicio_consulta, hasta
                )
                facturas_consultadas = _asegurar_campos_ui_siigo(facturas)
                facturas = facturas_consultadas.copy()
                empresas_consultadas = [
                    codigo for codigo in empresas if codigo not in errores
                ]
                if not facturas.empty:
                    facturas = _aplicar_periodo_visible(
                        facturas, desde, hasta, incluir_anteriores
                    )
                try:
                    rv, gruas, viajes = db.cargar_fuentes_facturacion_siigo()
                    operacion = _operacion_para_consulta(
                        rv, gruas, viajes, facturas, desde, hasta,
                        empresas_consultadas,
                    )
                except Exception as exc:
                    operacion = construir_operacion_local(None, None, None)
                    errores["OPERACION_LOCAL"] = (
                        f"No fue posible leer la operación local ({type(exc).__name__})."
                    )
                _guardar_snapshot(
                    facturas,
                    recibos,
                    operacion,
                    detalle,
                    errores,
                    {
                        "empresas": empresas,
                        "desde": desde,
                        "hasta": hasta,
                        "inicio_consulta": inicio_consulta,
                    },
                    facturas_consultadas=facturas_consultadas,
                )

    snapshot = st.session_state.get(_CLAVE_SNAPSHOT)
    if not snapshot:
        st.info("Selecciona el periodo y pulsa **Consultar Siigo ahora**.")
        return

    consultado_en = snapshot["consultado_en"]
    st.caption(f"Última lectura directa: {consultado_en:%d/%m/%Y %H:%M:%S %Z}")
    for empresa, error in snapshot["errores"].items():
        st.warning(f"{empresa}: {error}. Los demás resultados siguen disponibles.")

    empresas_snapshot = tuple(snapshot["parametros"].get("empresas") or ())
    revisiones_disponibles = True
    try:
        revisiones = db.cargar_revisiones_siigo(empresas_snapshot)
    except Exception as exc:
        revisiones = pd.DataFrame()
        revisiones_disponibles = False
        st.warning(
            "La cartera de Siigo sí se pudo leer, pero las notas internas no están "
            f"disponibles ({type(exc).__name__})."
        )
    facturas_snapshot = _asegurar_campos_ui_siigo(snapshot["facturas"])
    facturas_historicas = _asegurar_campos_ui_siigo(
        snapshot.get("facturas_consultadas", snapshot["facturas"])
    )
    cartera, faltantes = conciliar_cartera(
        facturas_snapshot,
        snapshot["operacion"],
        revisiones,
        snapshot["recibos"],
    )
    _metricas(cartera, faltantes)
    filtrada = _filtrar_vista(cartera)

    resumen, facturas_tab, diferencias, clientes = st.tabs(
        ["RESUMEN", "FACTURAS", "DIFERENCIAS", "CLIENTES"]
    )
    with resumen:
        vigentes = _cartera_vigente(cartera)
        if vigentes.empty:
            st.info("La consulta no devolvió facturas para esos filtros.")
        else:
            antiguedad = (
                vigentes.groupby(["moneda", "antiguedad"], dropna=False)["saldo_siigo"]
                .sum(min_count=1)
                .reset_index()
                .rename(columns={
                    "moneda": "MONEDA",
                    "antiguedad": "ANTIGÜEDAD",
                    "saldo_siigo": "SALDO",
                })
            )
            st.dataframe(
                antiguedad,
                width="stretch",
                hide_index=True,
                column_config={"SALDO": st.column_config.NumberColumn(format="$ %.0f")},
            )
            cuotas_indeterminadas = int(
                (
                    pd.to_numeric(vigentes.get("cuotas"), errors="coerce").gt(1)
                    & vigentes.get("estado_siigo").eq("DATO_INCOMPLETO")
                ).sum()
            )
            if cuotas_indeterminadas:
                st.info(
                    f"{cuotas_indeterminadas} factura(s) tienen cuotas con fechas "
                    "vencidas y futuras. Siigo entrega un saldo total, por eso no se "
                    "afirma mora hasta revisar la aplicación por cuota."
                )
    with facturas_tab:
        vista = _tabla_visible(filtrada)
        st.dataframe(vista, width="stretch", hide_index=True)
        st.download_button(
            "Descargar esta vista (CSV)",
            data=_csv_seguro(vista),
            file_name=f"cartera_siigo_{hoy.isoformat()}.csv",
            mime="text/csv",
        )
        _detalle_factura(filtrada, snapshot["detalle"])
        if rol in {"Admin", "Finanzas"} and revisiones_disponibles:
            _formulario_revision(
                filtrada,
                configuracion,
                snapshot["consultado_en"],
                snapshot["errores"],
            )
        elif rol in {"Admin", "Finanzas"}:
            st.caption(
                "La revisión interna está temporalmente deshabilitada; la consulta "
                "contable de Siigo permanece disponible en solo lectura."
            )
    with diferencias:
        novedades = cartera[
            ~cartera["resultado_conciliacion"].isin(["COINCIDE"])
            | cartera["estado_revision"].isin([
                "CON_DIFERENCIA", "EN_REVISION_CAMBIO_DATOS",
                "EN_REVISION_CAMBIO_SIIGO",
            ])
        ] if not cartera.empty else cartera
        st.markdown("##### Facturas con novedad")
        st.dataframe(_tabla_visible(novedades), width="stretch", hide_index=True)
        st.markdown("##### Registros operativos cuya factura no apareció en Siigo")
        st.dataframe(faltantes, width="stretch", hide_index=True)
        st.caption(
            "La diferencia compara el subtotal bruto de Siigo con la base "
            "operativa registrada; no usa la base neta ni el total con IVA. "
            "El standby queda visible por separado hasta que Finanzas confirme su regla."
        )
    with clientes:
        empresas_sin_recibos = {
            str(clave).split(" · ", 1)[0].strip().upper()
            for clave in snapshot["errores"]
            if str(clave).endswith(" · RECIBOS")
        }
        resumen_clientes = _resumen_historico_clientes(
            facturas_historicas,
            snapshot["recibos"],
            empresas_sin_recibos,
        )
        inicio_historico = snapshot["parametros"].get("inicio_consulta")
        fin_historico = snapshot["parametros"].get("hasta")
        st.markdown("##### Histórico por cliente según Siigo")
        st.caption(
            f"Facturas consultadas directamente en Siigo desde {inicio_historico} "
            f"hasta {fin_historico}, incluidas las ya pagadas. Las anuladas se "
            "excluyen y cada moneda se agrupa por separado."
        )
        if empresas_sin_recibos:
            st.warning(
                "ABONOS (RECIBOS CONSULTADOS) aparece como no disponible para: "
                + ", ".join(sorted(empresas_sin_recibos))
                + ". Los demás valores siguen siendo los oficiales de las facturas Siigo."
            )
        if resumen_clientes.empty:
            st.info("Sin facturas históricas de clientes para agrupar.")
        else:
            st.dataframe(
                resumen_clientes,
                width="stretch",
                hide_index=True,
                column_config={
                    columna: st.column_config.NumberColumn(format="%.2f")
                    for columna in (
                        "TOTAL FACTURADO", "DESCUENTOS SIIGO",
                        "ANTICIPOS SIIGO", "ABONOS (RECIBOS CONSULTADOS)",
                        "SALDO SIIGO", "VALOR CUBIERTO (TOTAL - SALDO)",
                    )
                },
            )
            st.caption(
                "VALOR CUBIERTO es una derivación auditable de TOTAL FACTURADO "
                "menos SALDO SIIGO. Puede incluir pagos, anticipos, retenciones, "
                "notas o compensaciones aplicadas en Siigo; no equivale por sí solo "
                "a dinero recibido en banco."
            )


__all__ = [
    "configuracion_siigo_disponible",
    "tab_cartera_siigo",
]
