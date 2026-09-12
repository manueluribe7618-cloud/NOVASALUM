"""Muestra de demostración de la cartera Siigo, sin tocar ninguna base.

Los datos tienen la forma exacta de una respuesta del API de Siigo y pasan por
la misma tubería que una lectura real, así que la pantalla se ve igual que en
producción. Antes esta muestra se fabricaba copiando facturas y clientes
REALES de la cartera manual y rotulándolos como lectura de Siigo: además de
mezclar las dos carteras, hacía que la conciliación saliera siempre cuadrada,
porque ambos lados salían de la misma fuente.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from src.siigo_lectura import (
    LECTURA_FALLO,
    Reporte,
    reporte_desde_facturas,
)


def _factura(
    identificador: str,
    nombre: str,
    cliente: str,
    nit: str,
    fecha: dt.date,
    *,
    vencimiento: dt.date | None = None,
    subtotal: int = 0,
    iva: int = 0,
    retefuente: int = 0,
    ica: int = 0,
    saldo: int | None = None,
    descripcion: str = "",
    anulada: bool = False,
    moneda: str = "COP",
) -> dict[str, Any]:
    """Construye una factura con la forma que entrega el detalle de Siigo."""

    total = subtotal + iva - retefuente - ica
    impuestos = [{"type": "IVA", "name": "IVA 19%", "value": iva}] if iva else []
    retenciones = []
    if retefuente:
        retenciones.append({"type": "Retefuente", "name": "Retefuente", "value": retefuente})
    if ica:
        retenciones.append({"type": "ReteICA", "name": "ReteICA", "value": ica})
    factura: dict[str, Any] = {
        "id": identificador,
        "name": nombre,
        "date": fecha.isoformat(),
        "total": total,
        "customer": {
            "id": f"cli-{nit}",
            "identification": nit,
            "name": cliente,
            "branch_office": 0,
        },
        "currency": {"code": moneda},
        "items": [
            {
                "description": descripcion,
                "price": subtotal,
                "quantity": 1,
                "taxes": impuestos,
            }
        ],
        "retentions": retenciones,
        "metadata": {"last_updated": fecha.isoformat()},
    }
    if saldo is not None:
        factura["balance"] = saldo
    if vencimiento is not None:
        factura["due_date"] = vencimiento.isoformat()
        factura["payments"] = [{"due_date": vencimiento.isoformat(), "value": 0}]
    if anulada:
        factura["annulled"] = True
    return factura


def cargar_muestra(hoy: dt.date | None = None) -> Reporte:
    """Devuelve una lectura de demostración con todos los casos de supervisión.

    Incluye a propósito las situaciones que la pantalla debe saber mostrar sin
    mentir: una factura pagada, una con pago parcial, una vencida, una anulada,
    una sin vencimiento, una que Siigo entrega sin saldo, una en otra moneda y
    una cuyo detalle no se pudo leer.
    """

    hoy = hoy or dt.date.today()
    cliente_a = ("TMP Izajes y Transportes S.A.S", "900123456")
    cliente_b = ("Suministros y Transportes ANCA S.A.S", "800999888")
    cliente_c = ("YEGO ECO-T S.A.S PLEXA", "901555222")

    novasa = [
        _factura(
            "nov-1", "FEBA2050", *cliente_a, hoy - dt.timedelta(days=150),
            vencimiento=hoy - dt.timedelta(days=120), subtotal=900_000,
            retefuente=90_000, saldo=810_000,
            descripcion="TRANSPORTE DE TRACTOCAMION DE PLACA TBZ935 EN POZO NUTRIA CON ORDEN DE SERVICIO Nº MQ-070",
        ),
        _factura(
            "nov-2", "FEBA2051", *cliente_c, hoy - dt.timedelta(days=40),
            vencimiento=hoy - dt.timedelta(days=10), subtotal=3_800_000,
            retefuente=38_000, saldo=1_102_000,
            descripcion="MOVILIZACION DE TUBERIA DESDE CARTAGENA HASTA BARRANCABERMEJA PLACA TAV906",
        ),
        _factura(
            "nov-3", "FEBA2052", *cliente_b, hoy - dt.timedelta(days=20),
            vencimiento=hoy + dt.timedelta(days=10), subtotal=1_000_000,
            iva=190_000, retefuente=25_000, ica=4_000, saldo=0,
            descripcion="ALQUILER DE GRUA DE 70 TON PLACA KPN553 EN PLATO MAGDALENA",
        ),
        _factura(
            "nov-4", "FEBA2053", *cliente_a, hoy - dt.timedelta(days=8),
            subtotal=500_000, saldo=500_000,
            descripcion="MOVILIZACION INTERNA MANIFIESTO 91 REMESA 98 PLACA TBZ935",
        ),
    ]
    luac = [
        _factura(
            "lua-1", "LUA1728", *cliente_a, hoy - dt.timedelta(days=95),
            vencimiento=hoy - dt.timedelta(days=65), subtotal=1_080_000,
            retefuente=108_000, saldo=972_000,
            descripcion="TBZ935 9 VIAJES CON MANIFIESTO 45 EN PLATO MAGDALENA",
        ),
        _factura(
            "lua-2", "LUA1739", *cliente_b, hoy - dt.timedelta(days=30),
            vencimiento=hoy + dt.timedelta(days=15), subtotal=1_800_000,
            retefuente=18_000, saldo=1_782_000,
            descripcion="TRANSPORTE EN TRACTOCAMION DE PLACA TBZ935 MOVILIZACION INTERNA",
        ),
        _factura(
            "lua-3", "LUA1740", *cliente_c, hoy - dt.timedelta(days=25),
            vencimiento=hoy + dt.timedelta(days=5), subtotal=2_400_000,
            saldo=None,
            descripcion="ALQUILER DE GRUA DE 40 TON PLACA FST026 EN AGUAS BLANCAS",
        ),
    ]
    msu = [
        _factura(
            "msu-1", "MSU647", *cliente_a, hoy - dt.timedelta(days=60),
            vencimiento=hoy - dt.timedelta(days=30), subtotal=6_000_000,
            retefuente=60_000, saldo=1_440_000,
            descripcion="PLACA SSA-079 CON MANIFIESTO 00044 CON MOVILIZACION EN SIMACOTA",
        ),
        _factura(
            "msu-2", "MSU648", *cliente_b, hoy - dt.timedelta(days=55),
            vencimiento=hoy - dt.timedelta(days=25), subtotal=320_000,
            iva=418_000, retefuente=128_000, saldo=610_000,
            descripcion="ALQUILER DE GRUA DE 40 T PLACA FST-026 CON ORDEN DE COMPRA Nº36",
        ),
        _factura(
            "msu-3", "MSU649", *cliente_c, hoy - dt.timedelta(days=12),
            vencimiento=hoy + dt.timedelta(days=18), subtotal=1_500_000,
            saldo=1_500_000, anulada=True,
            descripcion="SERVICIO ANULADO POR SOLICITUD DEL CLIENTE",
        ),
        _factura(
            "msu-4", "MSU650", *cliente_b, hoy - dt.timedelta(days=5),
            vencimiento=hoy + dt.timedelta(days=25), subtotal=2_000,
            saldo=2_000, moneda="USD",
            descripcion="SERVICIO FACTURADO EN DOLARES",
        ),
    ]

    # Una factura cuyo detalle no se pudo leer: solo se conoce lo que dio el
    # listado, y la pantalla debe mostrarla como «Sin leer», nunca con ceros.
    sin_detalle = {
        "id": "nov-5",
        "name": "FEBA2054",
        "date": (hoy - dt.timedelta(days=3)).isoformat(),
        "total": 1_190_000,
        "customer": {"id": "cli-900123456", "identification": "900123456",
                     "name": cliente_a[0], "branch_office": 0},
        "_estado_lectura": LECTURA_FALLO,
    }
    novasa.append(sin_detalle)

    reporte = reporte_desde_facturas(
        {"NOVASA": novasa, "LUAC": luac, "MSU": msu},
        origen="Muestra de demostración",
        hoy=hoy,
    )
    reporte.errores["NOVASA · FACTURA FEBA2054"] = (
        "Siigo respondió HTTP 500 al consultar el detalle de esta factura."
    )
    return reporte


__all__ = ["cargar_muestra"]
