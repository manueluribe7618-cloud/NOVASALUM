"""Reglas configurables de impuestos para facturas manuales.

Las tasas predeterminadas se definen aquí, separadas de la interfaz y de la
persistencia. Una factura puede omitir cualquier concepto, calcularlo como
porcentaje del subtotal o usar un valor fijo en pesos.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


TAX_MODES = ("NO_APLICA", "PORCENTAJE", "VALOR_FIJO")
TAX_MODE_LABELS = {
    "NO_APLICA": "No aplica",
    "PORCENTAJE": "Porcentaje sobre subtotal",
    "VALOR_FIJO": "Valor fijo (COP)",
}
TAX_COMPONENTS = {
    "iva": "IVA",
    "retefuente": "Retefuente",
    "ica": "ICA",
}
# Punto único para futuras tasas predeterminadas por empresa o concepto.
TAX_DEFAULTS = {
    component: {"mode": "NO_APLICA", "value": 0.0}
    for component in TAX_COMPONENTS
}


@dataclass(frozen=True)
class TaxCalculation:
    """Resultado entero en COP y trazabilidad de la regla aplicada."""

    mode: str
    configured_value: Decimal
    amount_cop: int


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as exc:  # La vista traduce la validación a un mensaje claro.
        raise ValueError(f"{field} debe ser numérico.") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} debe ser un número válido mayor o igual a cero.")
    return number


def calculate_tax(subtotal_cop: Any, mode: str, value: Any = 0) -> TaxCalculation:
    """Calcula un impuesto individual sin alterar el subtotal de la factura."""

    subtotal = _decimal(subtotal_cop, "Subtotal")
    if mode not in TAX_MODES:
        raise ValueError("El modo de impuesto no es válido.")
    if mode == "NO_APLICA":
        return TaxCalculation(mode=mode, configured_value=Decimal("0"), amount_cop=0)

    configured_value = _decimal(value, "El valor de impuesto")
    if mode == "PORCENTAJE":
        if configured_value > 100:
            raise ValueError("El porcentaje no puede superar 100 %.")
        amount = subtotal * configured_value / Decimal("100")
    else:
        amount = configured_value
    return TaxCalculation(
        mode=mode,
        configured_value=configured_value,
        amount_cop=int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
    )


__all__ = [
    "TAX_COMPONENTS",
    "TAX_DEFAULTS",
    "TAX_MODE_LABELS",
    "TAX_MODES",
    "TaxCalculation",
    "calculate_tax",
]
