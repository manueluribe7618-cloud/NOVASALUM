"""Formato de dinero colombiano, tal como lo pidio el usuario.

Se copia aqui —son diez lineas— para no arrastrar el modulo de componentes del
proyecto anterior, que traia dependencias de toda la aplicacion de liquidacion.
"""
from __future__ import annotations

import datetime as dt
import re

# Colombia no tiene horario de verano; un desfase fijo evita depender de tzdata.
ZONA_COLOMBIA = dt.timezone(dt.timedelta(hours=-5), "COT")

# Tope de las columnas de dinero en Supabase (INTEGER de Postgres).
MAXIMO_COP = 2_147_483_647


def ahora_colombia() -> dt.datetime:
    return dt.datetime.now(ZONA_COLOMBIA)


def hoy_colombia() -> dt.date:
    """El día calendario en Colombia; el servidor de la nube corre en UTC."""

    return ahora_colombia().date()


def clave_nombre(nombre) -> str:
    """La misma razón social sin importar mayúsculas ni espacios repetidos."""

    return " ".join(str(nombre or "").split()).casefold()


def parse_cop(texto: str) -> int:
    """Lee pesos enteros, con puntos de miles opcionales y sin centavos."""

    valor = texto.strip()
    if valor.startswith("$"):
        valor = valor[1:].strip()
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)", valor):
        raise ValueError(
            "Escribe pesos sin centavos, por ejemplo 1.500.000 o 1500000."
        )
    return int(valor.replace(".", ""))


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
