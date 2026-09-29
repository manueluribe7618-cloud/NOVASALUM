"""La pantalla de conciliación, renderizada con la cartera manual en SQLite.

Aquí se prueba lo que ``_build_reconciliation`` no ve por sí sola: que la
pantalla compare solo lo que Siigo consultó, que una factura sin detalle no se
dé por faltante, que avise cuando el lado Siigo es la muestra de demostración
y que un dato ausente se vea con raya.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src import database as db
from src.formato import hoy_colombia


def _conciliar_lectura_de_novasa() -> None:
    """Una lectura real de solo NOVASA, del 1 del mes a hoy."""

    import streamlit as st

    from src.formato import hoy_colombia
    from src.siigo_lectura import ParametrosLectura, reporte_desde_facturas
    from src.views.conciliacion import render_reconciliation
    from src.views.siigo import _publicar

    if "siigo_reporte" not in st.session_state:
        hoy = hoy_colombia()
        factura = {
            "id": "x1", "name": "FEBA1001", "date": hoy.replace(day=1).isoformat(),
            "total": 1_000_000, "balance": 1_000_000,
            "customer": {"id": "c1", "identification": "900111222", "name": "Cliente Uno"},
            "currency": {"code": "COP"},
            "items": [{"description": "x", "price": 1_000_000, "quantity": 1, "taxes": []}],
            "retentions": [],
        }
        reporte = reporte_desde_facturas({"NOVASA": [factura]}, origen="Lectura directa")
        reporte.parametros = ParametrosLectura(("NOVASA",), hoy.replace(day=1), hoy)
        _publicar(reporte)
    render_reconciliation("TODAS")


def _conciliar_muestra() -> None:
    import streamlit as st

    from src.siigo_muestra import cargar_muestra
    from src.views.conciliacion import render_reconciliation
    from src.views.siigo import _publicar

    if "siigo_reporte" not in st.session_state:
        _publicar(cargar_muestra())
    render_reconciliation("TODAS")


def _kpis(app: AppTest) -> dict[str, str]:
    salida = {}
    for bloque in app.markdown:
        if "kpi-card" in bloque.value:
            etiqueta = re.search(r'kpi-label">([^<]*)', bloque.value).group(1)
            salida[etiqueta] = re.search(r'kpi-value">([^<]*)', bloque.value).group(1)
    return salida


class PantallaDeConciliacion(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(self.ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        self.hoy = hoy_colombia()

    def factura(self, empresa, prefijo, numero, dias_atras=0, *, fecha=None, **valores):
        datos = {
            "empresa_codigo": empresa, "prefijo": prefijo, "numero": numero,
            "fecha": fecha or self.hoy - dt.timedelta(days=dias_atras),
            "cliente": "Cliente Uno", "descripcion": "Servicio", "placas": "",
            "subtotal_cop": 1_000_000, "iva_cop": 0, "retefuente_cop": 0, "ica_cop": 0,
        }
        datos.update(valores)
        return db.crear_factura(datos)

    def test_solo_compara_lo_que_siigo_consulto(self) -> None:
        mes = self.hoy.replace(day=1)
        self.factura("NOVASA", "FEBA", "1001", fecha=mes)
        self.factura("NOVASA", "FEBA", "900", fecha=mes - dt.timedelta(days=5))
        self.factura("LUAC", "LUA", "50", fecha=mes)

        app = AppTest.from_function(_conciliar_lectura_de_novasa, default_timeout=60).run()
        self.assertFalse(app.exception, app.exception)

        tabla = app.dataframe[0].value
        self.assertEqual(list(tabla["Factura"]), ["FEBA1001"])
        self.assertEqual(list(tabla["Estado"]), ["Cuadrado"])
        self.assertEqual(_kpis(app)["Facturas faltantes"], "0")
        alcance = " ".join(bloque.value for bloque in app.caption)
        self.assertIn(f"emitidas del {mes:%d/%m/%Y}", alcance)
        self.assertIn("empresas NOVASA", alcance)
        self.assertIn("2 factura(s) manual(es) de otro período o empresa", alcance)
        # Con una lectura real la revisión sí se guarda.
        boton = next(b for b in app.button if b.label == "Marcar revisión")
        self.assertFalse(boton.disabled)
        boton.click().run()
        self.assertEqual([m.value for m in app.success], ["Revisión guardada en el historial interno."])

    def test_la_muestra_se_anuncia_y_no_deja_guardar_revisiones(self) -> None:
        self.factura("NOVASA", "FEBA", "2054", 3)
        self.factura("LUAC", "LUA", "1740", 25, subtotal_cop=2_400_000)
        self.factura("MSU", "MSU", "649", 12, subtotal_cop=1_500_000)
        self.factura("MSU", "MSU", "650", 5, subtotal_cop=2_000)
        anulada = self.factura("LUAC", "LUA", "1739", 30, subtotal_cop=1_800_000)
        db.anular_factura(anulada)

        app = AppTest.from_function(_conciliar_muestra, default_timeout=60).run()
        self.assertFalse(app.exception, app.exception)

        avisos = " ".join(bloque.value for bloque in app.warning)
        self.assertIn("muestra de demostración", avisos)
        boton = next(b for b in app.button if b.label == "Marcar revisión")
        self.assertTrue(boton.disabled)
        # Aunque el clic llegue (AppTest no respeta el deshabilitado), no se guarda.
        boton.click().run()
        self.assertFalse(app.success)
        with sqlite3.connect(self.ruta) as conexion:
            guardadas = conexion.execute("SELECT COUNT(*) FROM revisiones_conciliacion").fetchone()
        self.assertEqual(guardadas[0], 0)

        tabla = app.dataframe[0].value.set_index("Factura")
        # FEBA2054 existe en Siigo pero su detalle falló: no es «Solo manual».
        self.assertEqual(tabla.loc["FEBA2054", "Estado"], "Falta dato de Siigo")
        # LUA1740 llega de Siigo sin saldo: raya, no celda vacía.
        self.assertEqual(tabla.loc["LUA1740", "Saldo Siigo"], "—")
        self.assertEqual(tabla.loc["MSU649", "Estado"], "Anulada en una sola fuente")
        self.assertEqual(tabla.loc["LUA1739", "Estado"], "Anulada en una sola fuente")
        self.assertEqual(tabla.loc["MSU650", "Estado"], "Otra moneda")
        self.assertEqual(tabla.loc["MSU650", "Saldo Siigo"], "USD 2.000")
        self.assertEqual(tabla.loc["MSU650", "Dif. saldo"], "—")

    def test_la_ficha_de_siigo_muestra_raya_en_el_saldo_ausente(self) -> None:
        self.factura("LUAC", "LUA", "1740", 25, subtotal_cop=2_400_000)
        app = AppTest.from_function(_conciliar_muestra, default_timeout=60).run()
        selector = app.selectbox(key="conciliacion_factura")
        opcion = next(o for o in selector.options if "LUA1740" in o)
        selector.set_value(opcion).run()
        self.assertFalse(app.exception, app.exception)
        ficha = next(b.value for b in app.markdown if "split-card siigo" in b.value)
        self.assertIn("<span>Saldo</span><strong>—</strong>", ficha)


if __name__ == "__main__":
    unittest.main()
