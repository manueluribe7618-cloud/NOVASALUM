"""Lectura de la cartera Siigo, factura por factura.

El listado masivo de Siigo (``GET /v1/invoices``) sirve para descubrir qué
facturas existen en el período, pero no trae los ítems ni las retenciones: con
solo el listado, el subtotal, el IVA, la retefuente, el ICA y el detalle del
servicio quedan vacíos, y una factura vencida hace meses puede verse al día.
Por eso cada factura se consulta además de forma individual
(``GET /v1/invoices/{id}``), que es de donde sale la cartera de verdad.

Todo aquí es de solo lectura: el cliente de ``src.siigo`` únicamente permite
GET, salvo el POST de autenticación. Este módulo no importa Streamlit ni la
base de datos de la cartera manual.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import datetime as dt
import time
from typing import Any

import pandas as pd

from src.cartera_siigo import (
    enriquecer_facturas_clientes,
    facturas_a_dataframe,
)
from src.siigo import ClienteSiigo, ConfiguracionSiigo, ErrorSiigo


# Estados de lectura de cada fila. Son de supervisión, no contables.
LECTURA_DETALLE = "DETALLE"
LECTURA_SOLO_LISTADO = "SOLO_LISTADO"
LECTURA_FALLO = "FALLO"

COLUMNAS_SUPERVISION = ("estado_lectura", "lectura_completa", "leido_en")

# Consultas simultáneas por empresa. El cliente de Siigo es seguro para hilos
# (el token está protegido con un cerrojo y se pide una sola vez), y medido
# contra un transporte simulado, ocho hilos leen sesenta facturas casi siete
# veces más rápido que una por una. Se deja en seis para no provocar el límite
# de peticiones del proveedor.
TRABAJADORES_POR_EMPRESA = 6


@dataclass(frozen=True)
class ParametrosLectura:
    """Lo que se le pidió a Siigo, para poder mostrarlo junto al resultado."""

    empresas: tuple[str, ...]
    desde: dt.date
    hasta: dt.date


@dataclass
class ResumenEmpresa:
    """Qué pasó al leer una empresa. Es la materia prima de la supervisión."""

    empresa: str
    facturas_en_periodo: int = 0
    detalles_leidos: int = 0
    detalles_fallidos: int = 0
    segundos: float = 0.0
    llamadas: int = 0


@dataclass
class Reporte:
    """Resultado completo de una lectura, con su rastro de supervisión."""

    facturas: pd.DataFrame
    errores: dict[str, str] = field(default_factory=dict)
    resumenes: list[ResumenEmpresa] = field(default_factory=list)
    parametros: ParametrosLectura | None = None
    leido_en: dt.datetime | None = None
    origen: str = "Lectura directa"

    @property
    def total_facturas(self) -> int:
        return 0 if self.facturas is None else len(self.facturas)

    @property
    def sin_detalle(self) -> int:
        """Facturas publicadas cuyo detalle no se pudo leer."""

        if self.facturas is None or self.facturas.empty:
            return 0
        if "lectura_completa" not in self.facturas.columns:
            return 0
        return int((~self.facturas["lectura_completa"].fillna(False).astype(bool)).sum())

    @property
    def segundos(self) -> float:
        return sum(resumen.segundos for resumen in self.resumenes)

    @property
    def llamadas(self) -> int:
        return sum(resumen.llamadas for resumen in self.resumenes)


def _identificador(fila: Mapping[str, Any]) -> str:
    return str(fila.get("id") or "").strip()


def _nombre_visible(fila: Mapping[str, Any]) -> str:
    return str(fila.get("name") or fila.get("number") or _identificador(fila) or "?")


def _sin_nombre_de_cliente(factura: Mapping[str, Any]) -> bool:
    cliente = factura.get("customer")
    return not isinstance(cliente, Mapping) or not cliente.get("name")


def _completar_clientes(
    cliente_siigo: ClienteSiigo,
    facturas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Completa el nombre del cliente solo si el detalle no lo trajo.

    Se consulta uno por uno cuando son pocos; si son muchos o alguna factura no
    trae el identificador del tercero, sale más barato pedir el catálogo.
    """

    faltantes = [f for f in facturas if _sin_nombre_de_cliente(f)]
    if not faltantes:
        return facturas
    identificadores = {
        str(f.get("customer", {}).get("id") or "").strip()
        for f in faltantes
        if isinstance(f.get("customer"), Mapping)
    }
    identificadores.discard("")
    alguno_sin_id = any(
        not isinstance(f.get("customer"), Mapping)
        or not str(f["customer"].get("id") or "").strip()
        for f in faltantes
    )
    if identificadores and len(identificadores) <= 25 and not alguno_sin_id:
        catalogo = [
            cliente_siigo.consultar_cliente(identificador)
            for identificador in sorted(identificadores)
        ]
        return enriquecer_facturas_clientes(facturas, catalogo)

    catalogo = list(cliente_siigo.listar_clientes(activo=True))
    enriquecidas = enriquecer_facturas_clientes(facturas, catalogo)
    if any(_sin_nombre_de_cliente(f) for f in enriquecidas):
        # Las facturas históricas pueden apuntar a terceros ya inactivos, que
        # el catálogo por defecto no incluye.
        catalogo += list(cliente_siigo.listar_clientes(activo=False))
        enriquecidas = enriquecer_facturas_clientes(facturas, catalogo)
    return enriquecidas


def _leer_detalles(
    cliente_siigo: ClienteSiigo,
    indice: Sequence[Mapping[str, Any]],
    *,
    empresa: str,
    errores: dict[str, str],
    resumen: ResumenEmpresa,
    trabajadores: int,
    progreso: Callable[[str, int, int], None] | None,
) -> list[dict[str, Any]]:
    """Consulta el detalle de cada factura, sin que una mala tumbe el lote."""

    def consultar(fila: Mapping[str, Any]) -> tuple[dict[str, Any], str, str | None]:
        identificador = _identificador(fila)
        if not identificador:
            return dict(fila), LECTURA_SOLO_LISTADO, None
        try:
            detalle = cliente_siigo.consultar_factura(identificador)
        except ErrorSiigo as exc:
            return dict(fila), LECTURA_FALLO, str(exc)
        except Exception as exc:  # el lote continúa aunque una factura falle
            return dict(fila), LECTURA_FALLO, f"No se pudo leer ({type(exc).__name__})."
        return dict(detalle), LECTURA_DETALLE, None

    resultados: list[dict[str, Any]] = []
    total = len(indice)
    hilos = max(1, min(trabajadores, total)) if total else 1
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for posicion, (detalle, estado, error) in enumerate(
            pool.map(consultar, indice), start=1
        ):
            fila_original = indice[posicion - 1]
            detalle["_estado_lectura"] = estado
            resultados.append(detalle)
            if estado == LECTURA_DETALLE:
                resumen.detalles_leidos += 1
                resumen.llamadas += 1
            elif estado == LECTURA_FALLO:
                resumen.detalles_fallidos += 1
                resumen.llamadas += 1
                if error:
                    errores[f"{empresa} · FACTURA {_nombre_visible(fila_original)}"] = error
            if progreso is not None:
                progreso(empresa, posicion, total)
    return resultados


def _tabla_empresa(
    empresa: str,
    detalles: list[dict[str, Any]],
    *,
    hoy: dt.date | None,
    leido_en: dt.datetime,
) -> pd.DataFrame:
    """Arma la tabla de una empresa y le añade el rastro de cómo se leyó."""

    estados = [str(d.pop("_estado_lectura", LECTURA_DETALLE)) for d in detalles]
    tabla = facturas_a_dataframe(empresa, detalles, hoy=hoy)
    if tabla.empty:
        for columna in COLUMNAS_SUPERVISION:
            tabla[columna] = pd.Series(dtype="object")
        return tabla
    tabla["estado_lectura"] = estados
    tabla["lectura_completa"] = [estado == LECTURA_DETALLE for estado in estados]
    tabla["leido_en"] = leido_en.isoformat(timespec="seconds")
    return tabla


def leer_cartera(
    configuracion: ConfiguracionSiigo,
    parametros: ParametrosLectura,
    *,
    fabrica_cliente: Callable[..., ClienteSiigo] = ClienteSiigo,
    progreso: Callable[[str, int, int], None] | None = None,
    hoy: dt.date | None = None,
    trabajadores: int = TRABAJADORES_POR_EMPRESA,
    ahora: dt.datetime | None = None,
) -> Reporte:
    """Lee la cartera de las empresas indicadas, factura por factura.

    Por cada empresa: un solo cliente (el token se pide una vez), el listado
    del período para saber qué facturas existen, y el detalle individual de
    cada una. Si una empresa falla entera, las demás siguen; si falla una
    factura, se conserva lo que dio el listado y se marca como no leída.
    """

    leido_en = ahora or dt.datetime.now().astimezone()
    errores: dict[str, str] = {}
    resumenes: list[ResumenEmpresa] = []
    tablas: list[pd.DataFrame] = []

    for empresa in parametros.empresas:
        resumen = ResumenEmpresa(empresa=empresa)
        inicio = time.monotonic()
        try:
            cliente_siigo = fabrica_cliente(empresa, configuracion)
            indice = cliente_siigo.listar_facturas(parametros.desde, parametros.hasta)
            resumen.llamadas += 1
        except ErrorSiigo as exc:
            errores[empresa] = str(exc)
            resumen.segundos = time.monotonic() - inicio
            resumenes.append(resumen)
            continue
        except Exception as exc:
            errores[empresa] = f"No fue posible consultar esta empresa ({type(exc).__name__})."
            resumen.segundos = time.monotonic() - inicio
            resumenes.append(resumen)
            continue

        resumen.facturas_en_periodo = len(indice)
        if not indice:
            resumen.segundos = time.monotonic() - inicio
            resumenes.append(resumen)
            tablas.append(_tabla_empresa(empresa, [], hoy=hoy, leido_en=leido_en))
            continue

        detalles = _leer_detalles(
            cliente_siigo,
            indice,
            empresa=empresa,
            errores=errores,
            resumen=resumen,
            trabajadores=trabajadores,
            progreso=progreso,
        )
        try:
            detalles = _completar_clientes(cliente_siigo, detalles)
        except ErrorSiigo as exc:
            errores[f"{empresa} · CLIENTES"] = str(exc)
        except Exception as exc:
            errores[f"{empresa} · CLIENTES"] = (
                f"No se pudieron completar nombres de clientes ({type(exc).__name__})."
            )
        try:
            tablas.append(_tabla_empresa(empresa, detalles, hoy=hoy, leido_en=leido_en))
        except Exception as exc:
            errores[empresa] = f"Siigo entregó facturas no válidas ({type(exc).__name__})."
        resumen.segundos = time.monotonic() - inicio
        resumenes.append(resumen)

    facturas = (
        pd.concat(tablas, ignore_index=True)
        if tablas
        else _tabla_empresa("", [], hoy=hoy, leido_en=leido_en)
    )
    return Reporte(
        facturas=facturas,
        errores=errores,
        resumenes=resumenes,
        parametros=parametros,
        leido_en=leido_en,
        origen="Lectura directa",
    )


def reporte_desde_facturas(
    facturas_por_empresa: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    origen: str,
    hoy: dt.date | None = None,
    ahora: dt.datetime | None = None,
) -> Reporte:
    """Arma un reporte con facturas ya obtenidas, usando la misma tubería.

    Lo usa la muestra de demostración para producir exactamente las mismas
    columnas que una lectura real, sin tocar ninguna base de datos.
    """

    leido_en = ahora or dt.datetime.now().astimezone()
    tablas = []
    resumenes = []
    for empresa, facturas in facturas_por_empresa.items():
        detalles = [dict(factura) for factura in facturas]
        for detalle in detalles:
            detalle.setdefault("_estado_lectura", LECTURA_DETALLE)
        tablas.append(_tabla_empresa(empresa, detalles, hoy=hoy, leido_en=leido_en))
        resumenes.append(
            ResumenEmpresa(
                empresa=empresa,
                facturas_en_periodo=len(detalles),
                detalles_leidos=len(detalles),
            )
        )
    facturas_df = (
        pd.concat(tablas, ignore_index=True)
        if tablas
        else _tabla_empresa("", [], hoy=hoy, leido_en=leido_en)
    )
    return Reporte(
        facturas=facturas_df,
        resumenes=resumenes,
        leido_en=leido_en,
        origen=origen,
    )


__all__ = [
    "COLUMNAS_SUPERVISION",
    "LECTURA_DETALLE",
    "LECTURA_FALLO",
    "LECTURA_SOLO_LISTADO",
    "ParametrosLectura",
    "Reporte",
    "ResumenEmpresa",
    "leer_cartera",
    "reporte_desde_facturas",
]
