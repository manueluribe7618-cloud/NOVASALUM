"""Reglas de supervisión para la cartera consultada en Siigo.

Este módulo no escribe documentos contables ni conserva copias de sus valores.
Convierte las respuestas de Siigo en una vista comparable con los registros
operativos del sistema y calcula estados de lectura para la interfaz.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


API_VERSION = "2026.08.21.1"

EMPRESAS_SIIGO = {
    "NOVASA": "NOVASA Logistic SAS",
    "LUAC": "LUAC Cargo SAS",
    "MSU": "MSU Maquinas y Serv",
}

ESTADOS_REVISION = ("EN_REVISION", "APROBADA", "CON_DIFERENCIA")
ESTADOS_CONTABLES = (
    "ANULADA",
    "PAGADA",
    "PAGO_PARCIAL",
    "VENCIDA",
    "POR_VENCER",
    "SIN_VENCIMIENTO",
    "DATO_INCOMPLETO",
)

COLUMNAS_CARTERA_SIIGO = [
    "empresa_codigo",
    "empresa",
    "siigo_factura_id",
    "factura",
    "fecha",
    "cliente",
    "nit",
    "sucursal",
    "moneda",
    "tasa_cambio",
    "descripcion_siigo",
    "subtotal_siigo",
    "descuento_siigo",
    "base_siigo",
    "iva_siigo",
    "otros_impuestos_siigo",
    "retefuente_siigo",
    "reteica_siigo",
    "reteiva_siigo",
    "otras_retenciones_siigo",
    "total_siigo",
    "saldo_siigo",
    "anticipo_aplicado",
    "vencimiento_inicial",
    "vencimiento",
    "cuotas",
    "dias_mora",
    "antiguedad",
    "estado_siigo",
    "pago_parcial",
    "actualizado_siigo",
    "observaciones_siigo",
    "fuente_hash",
]

COLUMNAS_OPERACION = [
    "empresa_codigo",
    "factura_clave",
    "factura_local",
    "valor_base_local",
    "standby_local",
    "origen_local",
    "registros_locales",
    "placas",
    "manifiestos",
    "clientes_locales",
]

COLUMNAS_RECIBOS = [
    "empresa_codigo",
    "factura_clave",
    "abonos_recibos",
    "recibos_caja",
    "cuotas_abonadas",
    "ultimo_abono",
]


def _texto_dato(valor: Any) -> str:
    if valor is None:
        return ""
    try:
        if bool(pd.isna(valor)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def normalizar_factura(valor: Any) -> str:
    """Normaliza una referencia para comparar, sin cambiar el texto visible."""

    texto = unicodedata.normalize("NFKD", _texto_dato(valor).upper())
    return "".join(caracter for caracter in texto if caracter.isalnum())


def codigo_empresa(valor: Any) -> str:
    """Traduce las variantes operativas a la cuenta Siigo correspondiente."""

    texto = unicodedata.normalize("NFKD", str(valor or "").strip().upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    compacto = re.sub(r"[^A-Z0-9]+", " ", texto).strip()
    if "NOVASA" in compacto:
        return "NOVASA"
    if "LUAC" in compacto:
        return "LUAC"
    if compacto == "MSU" or compacto.startswith("MSU "):
        return "MSU"
    return ""


def _numero(valor: Any) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def _fecha(valor: Any) -> dt.date | None:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    try:
        return dt.date.fromisoformat(str(valor or "")[:10])
    except (TypeError, ValueError):
        return None


def _texto_cliente(cliente: Any) -> tuple[str, str]:
    if not isinstance(cliente, Mapping):
        return "", ""
    nombres = cliente.get("name")
    if isinstance(nombres, (list, tuple)):
        nombre = " ".join(str(parte).strip() for parte in nombres if str(parte).strip())
    else:
        nombre = str(nombres or cliente.get("commercial_name") or "").strip()
    nit = str(cliente.get("identification") or "").strip()
    digito = _texto_dato(cliente.get("check_digit"))
    if nit and digito:
        nit = f"{nit}-{digito}"
    return nombre, nit


def _vencimientos_factura(factura: Mapping[str, Any]) -> list[dt.date]:
    """Fechas pactadas, ordenadas y sin confundirlas con pagos recibidos."""

    fechas: list[dt.date] = []
    pagos = factura.get("payments")
    if isinstance(pagos, Iterable) and not isinstance(pagos, (str, bytes, Mapping)):
        for pago in pagos:
            if isinstance(pago, Mapping):
                fecha = _fecha(pago.get("due_date"))
                if fecha:
                    fechas.append(fecha)
    directa = _fecha(factura.get("due_date"))
    if directa:
        fechas.append(directa)
    return sorted(set(fechas))


def _vencimiento_factura(factura: Mapping[str, Any]) -> dt.date | None:
    """Obtiene el último vencimiento pactado; no lo trata como un abono."""

    fechas = _vencimientos_factura(factura)
    return max(fechas) if fechas else None


def _factura_anulada(factura: Mapping[str, Any]) -> bool:
    for clave in ("annulled", "cancelled", "canceled", "voided"):
        if factura.get(clave) is True:
            return True
    estados = [factura.get("status"), factura.get("state")]
    sello = factura.get("stamp")
    if isinstance(sello, Mapping):
        estados.append(sello.get("status"))
    anulados = {"annulled", "anulada", "anulado", "cancelled", "canceled", "voided"}
    return any(str(estado or "").strip().casefold() in anulados for estado in estados)


def _suma_valores_explicitos(elementos: Any) -> float | None:
    """Suma ``value`` de una colección Siigo sin calcular porcentajes ausentes."""

    if elementos is None:
        return 0.0
    if not isinstance(elementos, Iterable) or isinstance(
        elementos, (str, bytes, Mapping)
    ):
        return None
    total = 0.0
    for elemento in elementos:
        if not isinstance(elemento, Mapping):
            return None
        valor = _numero(elemento.get("value"))
        if valor is None:
            return None
        total += valor
    return total


def _resumen_valores_factura(factura: Mapping[str, Any]) -> dict[str, float | None]:
    """Separa subtotal bruto, descuento documental y base neta de Siigo.

    ``subtotal_siigo`` es exclusivamente la suma ``quantity * price`` de los
    ítems, antes de descuentos, impuestos y cargos. ``descuento_siigo`` suma una
    sola vez los ``value`` explícitos de cada ``item.discount`` y de
    ``global_discounts``. Nunca deriva un valor desde ``percentage``: si Siigo
    anuncia un descuento pero omite su valor, tanto descuento como base quedan
    incompletos. ``base_siigo`` es la base neta: subtotal menos descuentos más
    cargos globales explícitos; ``item.total`` no se usa porque incluye impuestos.
    """

    items = factura.get("items")
    descuentos_items = 0.0
    descuentos_completos = True
    subtotal = 0.0
    subtotal_completo = isinstance(items, list) and bool(items)

    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                subtotal_completo = False
                descuentos_completos = False
                continue
            precio = _numero(item.get("price"))
            cantidad = _numero(item.get("quantity"))
            if precio is None or cantidad is None:
                subtotal_completo = False
            else:
                subtotal += precio * cantidad

            descuento = item.get("discount")
            if descuento is None:
                continue
            if not isinstance(descuento, Mapping):
                descuentos_completos = False
                continue
            valor_descuento = _numero(descuento.get("value"))
            if valor_descuento is None:
                descuentos_completos = False
            else:
                descuentos_items += valor_descuento

    descuentos_globales = _suma_valores_explicitos(factura.get("global_discounts"))
    cargos_globales = _suma_valores_explicitos(factura.get("global_charges"))
    if descuentos_globales is None:
        descuentos_completos = False

    descuento_total = (
        descuentos_items + descuentos_globales
        if descuentos_completos and descuentos_globales is not None
        else None
    )
    subtotal_resultado = subtotal if subtotal_completo else None
    base = (
        subtotal_resultado - descuento_total + cargos_globales
        if subtotal_resultado is not None
        and descuento_total is not None
        and cargos_globales is not None
        else None
    )

    if base is None and not items:
        # Compatibilidad con respuestas antiguas que ya entregaban una base, pero
        # sin llamarla subtotal bruto ni volver a restarle descuentos.
        for clave in ("subtotal", "sub_total", "gross_value"):
            valor = _numero(factura.get(clave))
            if valor is not None:
                base = valor
                break

    return {
        "subtotal_siigo": subtotal_resultado,
        "descuento_siigo": descuento_total,
        "base_siigo": base,
    }


def _base_factura(factura: Mapping[str, Any]) -> float | None:
    return _resumen_valores_factura(factura)["base_siigo"]


def _descripcion_factura(factura: Mapping[str, Any]) -> str:
    """Une las descripciones documentales de los ítems, sin fuentes alternativas."""

    items = factura.get("items")
    if not isinstance(items, list):
        return ""
    descripciones: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        descripcion = _texto_dato(item.get("description"))
        if descripcion and descripcion not in descripciones:
            descripciones.append(descripcion)
    return " | ".join(descripciones)


def _clave_fiscal(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "").upper())
    return re.sub(
        r"[^A-Z0-9]+",
        "",
        "".join(c for c in texto if not unicodedata.combining(c)),
    )


def _impuestos_factura(factura: Mapping[str, Any]) -> dict[str, float]:
    """Resume impuestos informativos sin inferir valores ausentes en Siigo."""

    salida = {
        "iva_siigo": 0.0,
        "otros_impuestos_siigo": 0.0,
        "retefuente_siigo": 0.0,
        "reteica_siigo": 0.0,
        "reteiva_siigo": 0.0,
        "otras_retenciones_siigo": 0.0,
    }
    for item in factura.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        for impuesto in item.get("taxes") or []:
            if not isinstance(impuesto, Mapping):
                continue
            valor = _numero(impuesto.get("value")) or 0.0
            clave = _clave_fiscal(
                f"{impuesto.get('type', '')} {impuesto.get('name', '')}"
            )
            if "IVA" in clave or "VAT" in clave:
                salida["iva_siigo"] += valor
            else:
                salida["otros_impuestos_siigo"] += valor
    for retencion in factura.get("retentions") or []:
        if not isinstance(retencion, Mapping):
            continue
        valor = _numero(retencion.get("value")) or 0.0
        clave = _clave_fiscal(
            f"{retencion.get('type', '')} {retencion.get('name', '')}"
        )
        if "RETEIVA" in clave:
            salida["reteiva_siigo"] += valor
        elif "RETEICA" in clave or ("RETE" in clave and "ICA" in clave):
            salida["reteica_siigo"] += valor
        elif "RETEFUENTE" in clave or "FUENTE" in clave:
            salida["retefuente_siigo"] += valor
        else:
            salida["otras_retenciones_siigo"] += valor
    return salida


def enriquecer_facturas_clientes(
    facturas: Iterable[Mapping[str, Any]],
    clientes: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Añade el nombre del catálogo de clientes sin alterar el JSON original."""

    por_id: dict[str, Mapping[str, Any]] = {}
    por_documento: dict[tuple[str, str], Mapping[str, Any]] = {}
    for cliente in clientes or []:
        if not isinstance(cliente, Mapping):
            continue
        cliente_id = _texto_dato(cliente.get("id"))
        if cliente_id:
            por_id[cliente_id] = cliente
        identificacion = _texto_dato(cliente.get("identification"))
        sucursal = _texto_dato(cliente.get("branch_office") or 0)
        if identificacion:
            por_documento[(identificacion, sucursal)] = cliente

    salida: list[dict[str, Any]] = []
    for factura in facturas or []:
        if not isinstance(factura, Mapping):
            continue
        copia = dict(factura)
        cliente_factura = factura.get("customer")
        cliente_factura = dict(cliente_factura) if isinstance(cliente_factura, Mapping) else {}
        if not cliente_factura.get("name"):
            cliente = por_id.get(_texto_dato(cliente_factura.get("id")))
            if cliente is None:
                clave = (
                    _texto_dato(cliente_factura.get("identification")),
                    _texto_dato(cliente_factura.get("branch_office") or 0),
                )
                cliente = por_documento.get(clave)
            if cliente is not None:
                nombre = cliente.get("name") or cliente.get("commercial_name")
                if nombre:
                    cliente_factura["name"] = nombre
                if not cliente_factura.get("identification"):
                    cliente_factura["identification"] = cliente.get("identification")
                if not cliente_factura.get("check_digit"):
                    cliente_factura["check_digit"] = cliente.get("check_digit")
        copia["customer"] = cliente_factura
        salida.append(copia)
    return salida


def estado_contable(factura: Mapping[str, Any], hoy: dt.date | None = None) -> str:
    """Clasifica usando exclusivamente el saldo explícito entregado por Siigo."""

    hoy = hoy or dt.date.today()
    if _factura_anulada(factura):
        return "ANULADA"
    saldo = _numero(factura.get("balance"))
    if saldo is None or saldo < -0.5:
        return "DATO_INCOMPLETO"
    if abs(saldo) <= 0.5:
        return "PAGADA"
    vencimientos = _vencimientos_factura(factura)
    if vencimientos and vencimientos[-1] < hoy:
        return "VENCIDA"
    # Con varias cuotas, un saldo global no permite afirmar si corresponde a la
    # cuota vencida o a una futura. El rango mixto queda para revisión humana.
    if vencimientos and vencimientos[0] < hoy <= vencimientos[-1]:
        return "DATO_INCOMPLETO"
    total = _numero(factura.get("total"))
    if total is not None and saldo < total - 0.5:
        return "PAGO_PARCIAL"
    return "POR_VENCER" if vencimientos else "SIN_VENCIMIENTO"


def _antiguedad(dias_mora: int) -> str:
    if dias_mora <= 0:
        return "AL_DIA"
    if dias_mora <= 30:
        return "1_30_DIAS"
    if dias_mora <= 60:
        return "31_60_DIAS"
    if dias_mora <= 90:
        return "61_90_DIAS"
    return "MAS_DE_90_DIAS"


def hash_fuente_siigo(factura: Mapping[str, Any]) -> str:
    """Huella sin secretos para detectar cambios posteriores a una aprobación."""

    metadatos = factura.get("metadata") if isinstance(factura.get("metadata"), Mapping) else {}
    cliente = factura.get("customer") if isinstance(factura.get("customer"), Mapping) else {}
    contenido = {
        "id": factura.get("id"),
        "name": factura.get("name"),
        "date": factura.get("date"),
        "total": factura.get("total"),
        "balance": factura.get("balance"),
        "status": factura.get("status"),
        "annulled": factura.get("annulled"),
        "customer": {
            "id": cliente.get("id"),
            "identification": cliente.get("identification"),
            "branch_office": cliente.get("branch_office"),
        },
        "currency": factura.get("currency"),
        "items": factura.get("items"),
        "retentions": factura.get("retentions"),
        "advance_payment": factura.get("advance_payment"),
        "payments": factura.get("payments"),
        "global_charges": factura.get("global_charges"),
        "global_discounts": factura.get("global_discounts"),
        "observations": factura.get("observations"),
        "updated": metadatos.get("last_updated") or metadatos.get("updated"),
    }
    canonico = json.dumps(contenido, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def facturas_a_dataframe(
    empresa_codigo: str,
    facturas: Iterable[Mapping[str, Any]],
    *,
    hoy: dt.date | None = None,
) -> pd.DataFrame:
    """Convierte el JSON paginado de Siigo a una tabla estable para supervisión."""

    hoy = hoy or dt.date.today()
    codigo = str(empresa_codigo or "").strip().upper()
    empresa = EMPRESAS_SIIGO.get(codigo, codigo)
    filas: list[dict[str, Any]] = []
    for factura in facturas or []:
        if not isinstance(factura, Mapping):
            continue
        cliente_crudo = factura.get("customer")
        cliente, nit = _texto_cliente(cliente_crudo)
        sucursal = (
            _texto_dato(cliente_crudo.get("branch_office"))
            if isinstance(cliente_crudo, Mapping) else ""
        )
        fecha = _fecha(factura.get("date"))
        vencimientos = _vencimientos_factura(factura)
        vencimiento = max(vencimientos) if vencimientos else None
        saldo = _numero(factura.get("balance"))
        total = _numero(factura.get("total"))
        estado = estado_contable(factura, hoy)
        dias_mora = (
            max(0, (hoy - vencimiento).days)
            if estado == "VENCIDA" and vencimiento else 0
        )
        metadatos = factura.get("metadata") if isinstance(factura.get("metadata"), Mapping) else {}
        moneda = factura.get("currency")
        tasa_cambio = None
        if isinstance(moneda, Mapping):
            tasa_cambio = _numero(moneda.get("exchange_rate"))
            moneda = moneda.get("code") or moneda.get("name")
        impuestos = _impuestos_factura(factura)
        valores = _resumen_valores_factura(factura)
        filas.append({
            "empresa_codigo": codigo,
            "empresa": empresa,
            "siigo_factura_id": str(factura.get("id") or "").strip(),
            "factura": str(factura.get("name") or factura.get("number") or "").strip(),
            "fecha": fecha,
            "cliente": cliente,
            "nit": nit,
            "sucursal": sucursal,
            "moneda": str(moneda or "COP").strip(),
            "tasa_cambio": tasa_cambio,
            "descripcion_siigo": _descripcion_factura(factura),
            **valores,
            **impuestos,
            "total_siigo": total,
            "saldo_siigo": saldo,
            "anticipo_aplicado": _numero(factura.get("advance_payment")) or 0.0,
            "vencimiento_inicial": min(vencimientos) if vencimientos else None,
            "vencimiento": vencimiento,
            "cuotas": len(vencimientos),
            "dias_mora": dias_mora,
            "antiguedad": _antiguedad(dias_mora),
            "estado_siigo": estado,
            "pago_parcial": bool(
                saldo is not None and total is not None and 0.5 < saldo < total - 0.5
            ),
            "actualizado_siigo": metadatos.get("last_updated") or metadatos.get("updated") or "",
            "observaciones_siigo": _texto_dato(factura.get("observations")),
            "fuente_hash": hash_fuente_siigo(factura),
        })
    return pd.DataFrame(filas, columns=COLUMNAS_CARTERA_SIIGO)


def _texto_unico(valores: Iterable[Any]) -> str:
    unicos: list[str] = []
    for valor in valores:
        texto = _texto_dato(valor)
        if texto and texto not in unicos:
            unicos.append(texto)
    return ", ".join(unicos)


def _filas_operativas(
    datos: pd.DataFrame | None,
    *,
    origen: str,
    columna_fecha: str,
    columna_valor: str,
    columna_standby: str | None = None,
) -> list[dict[str, Any]]:
    if datos is None or datos.empty or "factura" not in datos.columns:
        return []
    filas: list[dict[str, Any]] = []
    for _, fila in datos.iterrows():
        factura = _texto_dato(fila.get("factura"))
        clave = normalizar_factura(factura)
        if not clave:
            continue
        empresa = codigo_empresa(fila.get("empresa_factura"))
        filas.append({
            "empresa_codigo": empresa,
            "factura_clave": clave,
            "factura_local": factura,
            "valor_base_local": _numero(fila.get(columna_valor)) or 0.0,
            "standby_local": _numero(fila.get(columna_standby)) or 0.0 if columna_standby else 0.0,
            "origen_local": origen,
            "placas": _texto_dato(fila.get("placa")) or _texto_dato(fila.get("equipo")),
            "manifiestos": _texto_dato(fila.get("manifiesto")) or _texto_dato(fila.get("reporte_orden")),
            "clientes_locales": _texto_dato(fila.get("cliente")) or _texto_dato(fila.get("empresa")),
            "fecha_local": _texto_dato(fila.get(columna_fecha)),
        })
    return filas


def construir_operacion_local(
    reportes_vehiculos: pd.DataFrame | None,
    cobros_gruas: pd.DataFrame | None,
    viajes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Agrupa facturación operativa evitando sumar dos veces viajes sincronizados."""

    vehiculos = _filas_operativas(
        reportes_vehiculos,
        origen="VEHICULO",
        columna_fecha="fecha",
        columna_valor="flete",
        columna_standby="standby",
    )
    gruas = _filas_operativas(
        cobros_gruas,
        origen="GRUA",
        columna_fecha="fecha_inicio",
        columna_valor="valor",
    )
    claves_vehiculos = {(fila["empresa_codigo"], fila["factura_clave"]) for fila in vehiculos}
    viajes_preparados = []
    if viajes is not None and not viajes.empty:
        copia = viajes.rename(columns={"numero_factura": "factura", "valor_flete": "flete"}).copy()
        if "empresa_factura" not in copia.columns and "empresa" in copia.columns:
            copia["empresa_factura"] = copia["empresa"]
        viajes_preparados = _filas_operativas(
            copia,
            origen="VIAJE_RESPALDO",
            columna_fecha="fecha",
            columna_valor="flete",
        )
        viajes_preparados = [
            fila for fila in viajes_preparados
            if (fila["empresa_codigo"], fila["factura_clave"]) not in claves_vehiculos
        ]

    filas = vehiculos + gruas + viajes_preparados
    if not filas:
        return pd.DataFrame(columns=COLUMNAS_OPERACION)
    base = pd.DataFrame(filas)
    salida: list[dict[str, Any]] = []
    for (empresa, clave), grupo in base.groupby(["empresa_codigo", "factura_clave"], dropna=False):
        salida.append({
            "empresa_codigo": empresa,
            "factura_clave": clave,
            "factura_local": _texto_unico(grupo["factura_local"]),
            "valor_base_local": float(pd.to_numeric(grupo["valor_base_local"], errors="coerce").fillna(0).sum()),
            "standby_local": float(pd.to_numeric(grupo["standby_local"], errors="coerce").fillna(0).sum()),
            "origen_local": _texto_unico(grupo["origen_local"]),
            "registros_locales": int(len(grupo)),
            "placas": _texto_unico(grupo["placas"]),
            "manifiestos": _texto_unico(grupo["manifiestos"]),
            "clientes_locales": _texto_unico(grupo["clientes_locales"]),
        })
    return pd.DataFrame(salida, columns=COLUMNAS_OPERACION)


def recibos_a_dataframe(
    empresa_codigo: str,
    recibos: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Agrupa valores realmente aplicados por recibos de caja a cada factura."""

    codigo = str(empresa_codigo or "").strip().upper()
    filas: list[dict[str, Any]] = []
    for recibo in recibos or []:
        if not isinstance(recibo, Mapping):
            continue
        nombre_recibo = str(recibo.get("name") or recibo.get("number") or "").strip()
        fecha_recibo = _fecha(recibo.get("date"))
        items = recibo.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            vencimiento = item.get("due")
            if not isinstance(vencimiento, Mapping):
                continue
            prefijo = str(vencimiento.get("prefix") or "").strip()
            consecutivo = str(
                vencimiento.get("consecutive") or vencimiento.get("number") or ""
            ).strip()
            clave = normalizar_factura(f"{prefijo}{consecutivo}")
            valor = _numero(item.get("value"))
            if not clave or valor is None:
                continue
            filas.append({
                "empresa_codigo": codigo,
                "factura_clave": clave,
                "abonos_recibos": valor,
                "recibos_caja": nombre_recibo,
                "cuotas_abonadas": _texto_dato(vencimiento.get("quote")),
                "ultimo_abono": fecha_recibo,
            })
    if not filas:
        return pd.DataFrame(columns=COLUMNAS_RECIBOS)
    base = pd.DataFrame(filas)
    salida: list[dict[str, Any]] = []
    for (empresa, clave), grupo in base.groupby(["empresa_codigo", "factura_clave"]):
        fechas = [fecha for fecha in grupo["ultimo_abono"] if isinstance(fecha, dt.date)]
        salida.append({
            "empresa_codigo": empresa,
            "factura_clave": clave,
            "abonos_recibos": float(
                pd.to_numeric(grupo["abonos_recibos"], errors="coerce").fillna(0).sum()
            ),
            "recibos_caja": _texto_unico(grupo["recibos_caja"]),
            "cuotas_abonadas": _texto_unico(grupo["cuotas_abonadas"]),
            "ultimo_abono": max(fechas) if fechas else None,
        })
    return pd.DataFrame(salida, columns=COLUMNAS_RECIBOS)


def hash_revision_fila(fila: Mapping[str, Any]) -> str:
    """Huella de todo lo supervisado: Siigo, cruce local y abonos visibles."""

    campos_numericos = {
        "subtotal_siigo", "descuento_siigo", "base_siigo",
        "valor_base_local", "standby_local", "registros_locales",
        "diferencia_base", "abonos_recibos", "otros_ajustes",
        "anticipo_aplicado",
    }
    campos = (
        "fuente_hash", "descripcion_siigo", "subtotal_siigo",
        "descuento_siigo", "base_siigo", "resultado_conciliacion", "valor_base_local",
        "standby_local", "origen_local", "registros_locales", "placas",
        "manifiestos", "clientes_locales", "diferencia_base",
        "abonos_recibos", "recibos_caja", "cuotas_abonadas",
        "ultimo_abono", "otros_ajustes", "anticipo_aplicado",
    )
    contenido: dict[str, Any] = {}
    for campo in campos:
        valor = fila.get(campo)
        if campo in campos_numericos:
            numero = _numero(valor)
            contenido[campo] = round(numero, 6) if numero is not None else None
        else:
            contenido[campo] = _texto_dato(valor)
    canonico = json.dumps(contenido, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def conciliar_cartera(
    facturas: pd.DataFrame,
    operacion: pd.DataFrame | None = None,
    revisiones: pd.DataFrame | None = None,
    recibos: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cruza Siigo, operación y revisión; retorna cartera y registros sin Siigo."""

    cartera = facturas.copy()
    if cartera.empty:
        cartera = pd.DataFrame(columns=COLUMNAS_CARTERA_SIIGO)
    cartera["factura_clave"] = cartera.get("factura", pd.Series(dtype="object")).apply(normalizar_factura)

    operacion = operacion.copy() if operacion is not None else pd.DataFrame(columns=COLUMNAS_OPERACION)
    for columna in COLUMNAS_OPERACION:
        if columna not in operacion.columns:
            operacion[columna] = pd.Series(dtype="object")
    if not operacion.empty:
        cartera = cartera.merge(
            operacion,
            on=["empresa_codigo", "factura_clave"],
            how="left",
        )
    else:
        for columna in COLUMNAS_OPERACION[2:]:
            cartera[columna] = None

    cartera["resultado_conciliacion"] = "SIN_REGISTRO_LOCAL"
    encontrada = cartera["origen_local"].fillna("").astype(str).ne("")
    moneda_cop = cartera.get("moneda", pd.Series("COP", index=cartera.index)) \
        .fillna("COP").astype(str).str.upper().eq("COP")
    # El registro operativo guarda el flete bruto. Se compara contra el subtotal
    # bruto de los ítems Siigo para que un descuento documental no produzca una
    # falsa diferencia. ``base_siigo`` permanece neta para lectura tributaria. El
    # fallback conserva compatibilidad con tablas antiguas sin ``subtotal_siigo``.
    subtotal_siigo = pd.to_numeric(
        cartera.get("subtotal_siigo", pd.Series(index=cartera.index, dtype="float64")),
        errors="coerce",
    )
    base_siigo = pd.to_numeric(cartera["base_siigo"], errors="coerce")
    valor_comparable_siigo = subtotal_siigo.where(subtotal_siigo.notna(), base_siigo)
    comparable = (
        encontrada
        & moneda_cop
        & valor_comparable_siigo.notna()
    )
    diferencia = (
        valor_comparable_siigo
        - pd.to_numeric(cartera["valor_base_local"], errors="coerce")
    )
    cartera["diferencia_base"] = diferencia.where(comparable)
    cartera.loc[encontrada & ~comparable, "resultado_conciliacion"] = "SIN_BASE_COMPARABLE"
    cartera.loc[
        encontrada & ~moneda_cop,
        "resultado_conciliacion",
    ] = "SIN_BASE_COMPARABLE_MONEDA"
    cartera.loc[comparable & diferencia.abs().le(1), "resultado_conciliacion"] = "COINCIDE"
    cartera.loc[comparable & diferencia.abs().gt(1), "resultado_conciliacion"] = "VALOR_DIFERENTE"
    cartera.loc[
        encontrada & cartera["estado_siigo"].eq("ANULADA"),
        "resultado_conciliacion",
    ] = "ANULADA_CON_OPERACION"

    recibos = recibos.copy() if recibos is not None else pd.DataFrame(columns=COLUMNAS_RECIBOS)
    if not recibos.empty:
        cartera = cartera.merge(
            recibos,
            on=["empresa_codigo", "factura_clave"],
            how="left",
        )
    for columna in ("abonos_recibos", "recibos_caja", "cuotas_abonadas", "ultimo_abono"):
        if columna not in cartera.columns:
            cartera[columna] = None
    cartera["abonos_recibos"] = pd.to_numeric(
        cartera["abonos_recibos"], errors="coerce"
    ).fillna(0.0)
    total = pd.to_numeric(cartera["total_siigo"], errors="coerce")
    saldo = pd.to_numeric(cartera["saldo_siigo"], errors="coerce")
    anticipo = pd.to_numeric(cartera.get("anticipo_aplicado"), errors="coerce").fillna(0.0)
    cartera["otros_ajustes"] = (
        total - saldo - cartera["abonos_recibos"] - anticipo
    ).where(
        total.notna() & saldo.notna()
    )
    cartera["huella_revision"] = cartera.apply(hash_revision_fila, axis=1)

    revisiones = revisiones.copy() if revisiones is not None else pd.DataFrame()
    columnas_revision = [
        "empresa_codigo", "siigo_factura_id", "estado", "observacion",
        "fuente_hash_revision", "actualizado_por", "actualizado_en", "version",
    ]
    if not revisiones.empty:
        if "fuente_hash" in revisiones.columns and "fuente_hash_revision" not in revisiones.columns:
            revisiones = revisiones.rename(columns={"fuente_hash": "fuente_hash_revision"})
        disponibles = [c for c in columnas_revision if c in revisiones.columns]
        cartera = cartera.merge(
            revisiones[disponibles],
            on=["empresa_codigo", "siigo_factura_id"],
            how="left",
        )
    for columna in columnas_revision[2:]:
        if columna not in cartera.columns:
            cartera[columna] = None
    cartera["estado_revision"] = cartera["estado"].fillna("EN_REVISION")
    cambio = (
        cartera["estado_revision"].eq("APROBADA")
        & cartera["fuente_hash_revision"].fillna("").ne(
            cartera["huella_revision"].fillna("")
        )
    )
    cartera.loc[cambio, "estado_revision"] = "EN_REVISION_CAMBIO_DATOS"

    if operacion.empty:
        faltantes = operacion.copy()
    else:
        claves_siigo = set(zip(cartera["empresa_codigo"], cartera["factura_clave"]))
        faltantes = operacion[
            ~operacion.apply(
                lambda fila: (fila["empresa_codigo"], fila["factura_clave"]) in claves_siigo,
                axis=1,
            )
        ].copy()
        faltantes["resultado_conciliacion"] = "NO_EXISTE_EN_SIIGO"
    return cartera, faltantes.reset_index(drop=True)


__all__ = [
    "COLUMNAS_CARTERA_SIIGO",
    "COLUMNAS_OPERACION",
    "COLUMNAS_RECIBOS",
    "EMPRESAS_SIIGO",
    "ESTADOS_CONTABLES",
    "ESTADOS_REVISION",
    "codigo_empresa",
    "conciliar_cartera",
    "construir_operacion_local",
    "estado_contable",
    "enriquecer_facturas_clientes",
    "facturas_a_dataframe",
    "hash_fuente_siigo",
    "hash_revision_fila",
    "normalizar_factura",
    "recibos_a_dataframe",
]
