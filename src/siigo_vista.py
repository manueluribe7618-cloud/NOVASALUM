"""Presentación de la cartera Siigo, sin Streamlit y sin tocar la base manual.

Aquí viven las funciones puras que convierten la lectura del API en las mismas
columnas que muestra la cartera manual. Son puras a propósito: se prueban sin
red, sin credenciales y sin renderizar nada.

Regla que gobierna todo el módulo: **un dato que Siigo no entregó se muestra
como raya, nunca como cero**. Un cero es una afirmación contable; una raya dice
la verdad, que es «no lo sabemos todavía». Esa distinción es la supervisión que
pidió el dueño.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from src.formato import fmt_cop, hoy_colombia


# Estados contables que entrega ``src.cartera_siigo``, más el estado propio de
# esta vista para la factura cuyo detalle no se alcanzó a leer.
SIIGO_ESTADO_META: dict[str, str] = {
    "PAGADA": "Pagada",
    "PAGO_PARCIAL": "Pago parcial",
    "VENCIDA": "Vencida",
    "POR_VENCER": "Por vencer",
    "SIN_VENCIMIENTO": "Sin vencimiento",
    "DATO_INCOMPLETO": "Por revisar",
    "ANULADA": "Anulada",
    "SIN_DETALLE": "Sin leer",
}

# Columnas del cuadro general, en el mismo orden que la cartera manual. No
# lleva «Placas»: Siigo no guarda la placa en ningún campo propio, viene dentro
# del texto de la descripción, que es la columna «Detalle del servicio».
COLUMNAS_GENERAL = [
    "_factura_id",
    "Factura",
    "Fecha",
    "Cliente",
    "Detalle del servicio",
    "Subtotal",
    "IVA",
    "Retefuente",
    "ICA",
    "Abonos",
    "Descuento",
    "Saldo",
    "Días en cartera",
]

# Columnas del estado de cuenta por cliente, espejo del que ya se envía a los
# clientes desde la cartera manual.
COLUMNAS_ESTADO_CUENTA = [
    "_factura_id",
    "Factura",
    "Fecha",
    "Detalle del servicio",
    "Sub valor factura",
    "Impuestos",
    "Retención",
    "ICA",
    "Abono",
    "Descuento",
    "Saldo pendiente",
]

COLUMNAS_CLIENTES = ["Cliente", "Saldo pendiente", "Facturas con saldo", "Empresas"]

FILTROS_SALDO = ("Todos", "Con saldo pendiente", "Saldo en cero", "Saldo sin dato")

_CAMPOS_BUSQUEDA = ("factura", "cliente", "nit", "descripcion_siigo", "observaciones_siigo")


def es_ausente(valor: Any) -> bool:
    """Indica si un valor es «no lo sabemos», distinguiéndolo del cero."""

    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def money(valor: Any) -> str:
    """Dinero para celdas que siempre deben mostrar algo: ausente es raya."""

    if es_ausente(valor):
        return "—"
    return fmt_cop(valor, dash_zero=False)


def money_blanco(valor: Any) -> str:
    """Dinero para conceptos opcionales: el cero se deja en blanco.

    Replica la hoja de Finanzas, donde una celda sin IVA se ve vacía. El dato
    ausente sigue siendo raya, para no confundir «no aplica» con «no se leyó».
    """

    if es_ausente(valor):
        return "—"
    try:
        if float(valor) == 0:
            return ""
    except (TypeError, ValueError):
        return "—"
    return fmt_cop(valor, dash_zero=False)


def money_kpi(total: float, faltantes: int, filas: int) -> str:
    """Dinero para los totales: raya solo si ninguna de las filas trae el dato.

    Un cero que Siigo sí informó (o no tener facturas en pesos) es «$ 0»,
    igual que en la cartera manual; la raya queda para «no se sabe».
    """

    if filas and faltantes >= filas:
        return "—"
    return money(total)


def money_fila(fila: Mapping[str, Any], valor: Any, *, blanco: bool = False) -> str:
    """Importe de una factura; si no es en pesos, lleva el código de su moneda."""

    if es_cop(fila):
        return money_blanco(valor) if blanco else money(valor)
    if es_ausente(valor):
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    if blanco and numero == 0:
        return ""
    moneda = str(fila.get("moneda")).strip().upper()
    return f"{moneda} {numero:,.0f}".replace(",", ".")


def fecha_visible(valor: Any) -> str:
    """Fecha en día/mes/año, tolerante a la fecha ausente que Siigo permite."""

    if es_ausente(valor) or valor == "":
        return "—"
    if isinstance(valor, dt.date):
        return valor.strftime("%d/%m/%Y")
    try:
        return dt.date.fromisoformat(str(valor)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(valor)


def dias_en_cartera(valor: Any, *, hoy: dt.date | None = None) -> int | str:
    """Días desde la emisión; una fecha ausente permanece explícitamente vacía."""

    try:
        fecha = dt.date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return "—"
    return max(0, ((hoy or hoy_colombia()) - fecha).days)


def etiqueta_estado(fila: Mapping[str, Any]) -> str:
    """Traduce el estado contable de Siigo a la etiqueta visible de la tabla."""

    if not fila.get("lectura_completa", True):
        return SIIGO_ESTADO_META["SIN_DETALLE"]
    estado = str(fila.get("estado_siigo") or "").strip().upper()
    return SIIGO_ESTADO_META.get(estado, estado.replace("_", " ").capitalize() or "—")


def texto_corto(valor: Any, limite: int = 48) -> str:
    """Acorta el detalle para el cuadro general, igual que la cartera manual."""

    texto = "" if es_ausente(valor) else str(valor).strip()
    if not texto:
        return "—"
    return texto if len(texto) <= limite else f"{texto[:limite - 1].rstrip()}…"


def texto_completo(valor: Any) -> str:
    """Detalle sin recortar, para el estado de cuenta que se envía al cliente."""

    texto = "" if es_ausente(valor) else str(valor).strip()
    return texto or "—"


def _valor(fila: Mapping[str, Any], campo: str) -> Any:
    valor = fila.get(campo)
    return None if es_ausente(valor) else valor


def _sin_detalle(fila: Mapping[str, Any], campo: str) -> Any:
    """Devuelve el importe solo si la factura se leyó completa.

    Cuando falta el detalle, ``src.cartera_siigo`` puede entregar 0.0 (en el
    descuento, por ejemplo) porque no hay ítems que sumar. Ese cero no es un
    cero contable: es la ausencia del dato. Mostrarlo como «$ 0» sería afirmar
    algo que nadie leyó, y por eso aquí se convierte en raya.
    """

    if not fila.get("lectura_completa", True):
        return None
    return _valor(fila, campo)


def filas_de_dataframe(datos: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Convierte el DataFrame publicado en filas limpias, sin NaN sueltos."""

    if datos is None or datos.empty:
        return []
    filas: list[dict[str, Any]] = []
    for registro in datos.to_dict("records"):
        filas.append({
            clave: (None if es_ausente(valor) else valor)
            for clave, valor in registro.items()
        })
    return filas


def tabla_general(filas: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Cuadro general de la cartera Siigo, columna por columna como el manual.

    «Abonos» se deja vacía por decisión del dueño: Siigo no entrega el abono de
    cada factura y derivarlo de total − saldo sería inventar una cifra.
    """

    salida: list[dict[str, Any]] = []
    for fila in filas:
        salida.append({
            "_factura_id": str(fila.get("siigo_factura_id") or ""),
            "Factura": str(fila.get("factura") or "—"),
            "Fecha": fecha_visible(fila.get("fecha")),
            "Cliente": str(fila.get("cliente") or "—"),
            "Detalle del servicio": texto_corto(_sin_detalle(fila, "descripcion_siigo")),
            "Subtotal": money_fila(fila, _sin_detalle(fila, "subtotal_siigo")),
            "IVA": money_fila(fila, _sin_detalle(fila, "iva_siigo")),
            "Retefuente": money_fila(fila, _sin_detalle(fila, "retefuente_siigo")),
            "ICA": money_fila(fila, _sin_detalle(fila, "reteica_siigo")),
            "Abonos": "",
            "Descuento": money_fila(fila, _sin_detalle(fila, "descuento_siigo"), blanco=True),
            "Saldo": money_fila(fila, _valor(fila, "saldo_siigo")),
            "Días en cartera": dias_en_cartera(fila.get("fecha")),
        })
    return pd.DataFrame(salida, columns=COLUMNAS_GENERAL)


def tabla_estado_cuenta(filas: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Estado de cuenta de un cliente en una empresa, espejo del manual."""

    salida: list[dict[str, Any]] = []
    for fila in filas:
        salida.append({
            "_factura_id": str(fila.get("siigo_factura_id") or ""),
            "Factura": str(fila.get("factura") or "—"),
            "Fecha": fecha_visible(fila.get("fecha")),
            "Detalle del servicio": texto_completo(_sin_detalle(fila, "descripcion_siigo")),
            "Sub valor factura": money_fila(fila, _sin_detalle(fila, "subtotal_siigo")),
            "Impuestos": money_fila(fila, _sin_detalle(fila, "iva_siigo"), blanco=True),
            "Retención": money_fila(fila, _sin_detalle(fila, "retefuente_siigo"), blanco=True),
            "ICA": money_fila(fila, _sin_detalle(fila, "reteica_siigo"), blanco=True),
            "Abono": "",
            "Descuento": money_fila(fila, _sin_detalle(fila, "descuento_siigo"), blanco=True),
            "Saldo pendiente": money_fila(fila, _valor(fila, "saldo_siigo")),
        })
    return pd.DataFrame(salida, columns=COLUMNAS_ESTADO_CUENTA)


def clave_cliente(fila: Mapping[str, Any]) -> str:
    """Agrupa al mismo cliente aunque cada empresa escriba su nombre distinto.

    Se usa el documento sin dígito de verificación cuando existe, porque es el
    único identificador estable entre las tres empresas; si falta, el nombre.
    Va completo: recortarlo juntaba dos cédulas de 10 dígitos en un cliente.
    """

    documento = fila.get("identificacion") or str(fila.get("nit") or "").split("-")[0]
    documento = re.sub(r"\D", "", str(documento or ""))
    if documento:
        return f"nit:{documento}"
    return f"nombre:{str(fila.get('cliente') or '').strip().casefold()}"


def nombre_cliente(filas: Iterable[Mapping[str, Any]]) -> str:
    """Elige el nombre más repetido del cliente entre sus facturas."""

    conteo: dict[str, int] = {}
    for fila in filas:
        nombre = str(fila.get("cliente") or "").strip()
        if nombre:
            conteo[nombre] = conteo.get(nombre, 0) + 1
    if not conteo:
        return "—"
    return max(conteo.items(), key=lambda par: (par[1], par[0]))[0]


def etiqueta_cliente(filas: Iterable[Mapping[str, Any]]) -> str:
    """Nombre del cliente con su NIT, para que dos homónimos no se confundan."""

    filas = list(filas)
    nit = next((str(f["nit"]).strip() for f in filas if str(f.get("nit") or "").strip()), "")
    nombre = nombre_cliente(filas)
    return f"{nombre} · NIT {nit}" if nit else nombre


def es_vigente(fila: Mapping[str, Any]) -> bool:
    """Una factura anulada se ve en el detalle, pero no suma en los totales."""

    return str(fila.get("estado_siigo") or "").strip().upper() != "ANULADA"


def es_cop(fila: Mapping[str, Any]) -> bool:
    """Solo se suman pesos; otra moneda se muestra pero nunca se convierte."""

    return str(fila.get("moneda") or "COP").strip().upper() == "COP"


def filas_sumables(filas: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Filas que pueden entrar en un total: vigentes y en pesos."""

    return [dict(fila) for fila in filas if es_vigente(fila) and es_cop(fila)]


def suma_auditable(filas: Iterable[Mapping[str, Any]], campo: str) -> tuple[float, int]:
    """Suma un campo y cuenta aparte las filas sin dato.

    Devolver el faltante junto al total evita la mentira más cara de esta
    pantalla: tratar «no sé» como «cero» y mostrar un total que se ve completo
    estando por debajo del real. Un valor negativo tampoco es confiable (su
    estado es «Por revisar»): cuenta como faltante, igual que en la tabla de
    clientes y en las gráficas, para que todas muestren la misma cifra.
    """

    total = 0.0
    faltantes = 0
    for fila in filas:
        valor = _valor(fila, campo)
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            faltantes += 1
            continue
        if numero < 0:
            faltantes += 1
            continue
        total += numero
    return total, faltantes


def saldo_visible(filas: Iterable[Mapping[str, Any]]) -> str:
    """Saldo de unas facturas vigentes, sin mezclar monedas ni inventar ceros.

    Raya si ninguna trae saldo leído; si faltan algunas, se dice cuántas. Las
    de otra moneda van aparte con su código y nunca se suman a los pesos.
    """

    por_moneda: dict[str, list[Mapping[str, Any]]] = {}
    for fila in filas:
        if es_vigente(fila):
            moneda = "COP" if es_cop(fila) else str(fila.get("moneda")).strip().upper()
            por_moneda.setdefault(moneda, []).append(fila)
    partes = []
    for moneda, grupo in sorted(por_moneda.items(), key=lambda par: par[0] != "COP"):
        total, faltantes = suma_auditable(grupo, "saldo_siigo")
        if faltantes == len(grupo):
            partes.append("—" if moneda == "COP" else f"{moneda} —")
            continue
        texto = money_fila(grupo[0], total)
        if faltantes:
            texto += f" · {faltantes} sin saldo leído"
        partes.append(texto)
    return " · ".join(partes) or money(0)


def tabla_clientes(filas: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Saldo pendiente por cliente, sumando sus facturas de las tres empresas."""

    agrupado: dict[str, dict[str, Any]] = {}
    for fila in filas:
        if not es_vigente(fila) or not es_cop(fila):
            continue
        saldo = _valor(fila, "saldo_siigo")
        if saldo is None or float(saldo) <= 0:
            continue
        clave = clave_cliente(fila)
        grupo = agrupado.setdefault(clave, {"filas": [], "empresas": [], "saldo": 0.0})
        grupo["filas"].append(fila)
        empresa = str(fila.get("empresa_codigo") or "").strip().upper()
        if empresa and empresa not in grupo["empresas"]:
            grupo["empresas"].append(empresa)
        grupo["saldo"] += float(saldo)

    visibles = [
        {
            "Cliente": nombre_cliente(grupo["filas"]),
            "Saldo pendiente": money(grupo["saldo"]),
            "Facturas con saldo": len(grupo["filas"]),
            "Empresas": " · ".join(sorted(grupo["empresas"])),
            "_saldo": grupo["saldo"],
        }
        for grupo in agrupado.values()
    ]
    visibles.sort(key=lambda fila: (-fila["_saldo"], fila["Cliente"].casefold()))
    if not visibles:
        return pd.DataFrame(columns=COLUMNAS_CLIENTES)
    return pd.DataFrame(visibles)[COLUMNAS_CLIENTES]


def buscar_filas(
    filas: Iterable[Mapping[str, Any]],
    termino: str,
) -> list[dict[str, Any]]:
    """Busca en los campos que Siigo sí entrega, incluido el NIT."""

    consulta = str(termino or "").strip().casefold()
    filas = [dict(fila) for fila in filas]
    if not consulta:
        return filas
    encontradas = []
    for fila in filas:
        texto = " ".join(
            str(fila.get(campo) or "") for campo in _CAMPOS_BUSQUEDA
        ).casefold()
        if consulta in texto:
            encontradas.append(fila)
    return encontradas


def filtrar_saldo(
    filas: Iterable[Mapping[str, Any]],
    criterio: str,
) -> list[dict[str, Any]]:
    """Filtra por saldo sin romperse con las facturas cuyo saldo no se leyó."""

    filas = [dict(fila) for fila in filas]
    if criterio == "Con saldo pendiente":
        return [f for f in filas if (v := _valor(f, "saldo_siigo")) is not None and float(v) > 0]
    if criterio == "Saldo en cero":
        return [f for f in filas if (v := _valor(f, "saldo_siigo")) is not None and float(v) == 0]
    if criterio == "Saldo sin dato":
        return [f for f in filas if (v := _valor(f, "saldo_siigo")) is None or float(v) < 0]
    return filas


def ordenar_filas(filas: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ordena por fecha y factura, dejando al final las de fecha desconocida."""

    def clave(fila: Mapping[str, Any]) -> tuple[int, str, str]:
        fecha = fila.get("fecha")
        if es_ausente(fecha):
            return (1, "", str(fila.get("factura") or ""))
        return (0, str(fecha)[:10], str(fila.get("factura") or ""))

    return sorted((dict(fila) for fila in filas), key=clave)


__all__ = [
    "COLUMNAS_CLIENTES",
    "COLUMNAS_ESTADO_CUENTA",
    "COLUMNAS_GENERAL",
    "FILTROS_SALDO",
    "SIIGO_ESTADO_META",
    "buscar_filas",
    "clave_cliente",
    "es_ausente",
    "es_cop",
    "es_vigente",
    "etiqueta_cliente",
    "etiqueta_estado",
    "fecha_visible",
    "filas_de_dataframe",
    "filas_sumables",
    "filtrar_saldo",
    "money",
    "money_blanco",
    "money_fila",
    "money_kpi",
    "nombre_cliente",
    "ordenar_filas",
    "saldo_visible",
    "suma_auditable",
    "tabla_clientes",
    "tabla_estado_cuenta",
    "tabla_general",
    "texto_completo",
    "texto_corto",
]
