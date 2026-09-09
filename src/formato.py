"""Formato de dinero colombiano, tal como lo pidio el usuario.

Se copia aqui —son diez lineas— para no arrastrar el modulo de componentes del
proyecto anterior, que traia dependencias de toda la aplicacion de liquidacion.
"""
from __future__ import annotations


def fmt_cop(valor, dash_zero=True):
    """Pesos con punto de miles y SIN centavos: '$ 1.500.000'.

    Un cero se muestra como raya para que las tablas no se llenen de ceros.
    """
    try:
        num = float(valor)
    except (TypeError, ValueError):
        return "—" if dash_zero else ""
    if num != num or num in (float("inf"), float("-inf")):   # NaN / infinito
        return "—" if dash_zero else ""
    if dash_zero and num == 0:
        return "—"
    return f"$ {num:,.0f}".replace(",", ".")
