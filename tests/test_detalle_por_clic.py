"""Abrir el detalle de un cliente con un clic sobre la tabla.

Petición del dueño (2026-09-16): al investigar un cliente, poder dar clic
sobre su fila en «Clientes y saldo pendiente» y ver sus facturas, sin retirar
el buscador — los dos caminos llevan al mismo detalle. La tabla, además, queda
con anchos fijos para que siempre se lea bien.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src import database as db
from src.views import manual


def evento(cliente: str, request_id: str = "req-1") -> dict:
    return {
        "type": "customerDetailRequested",
        "data": {"cliente": cliente, "request_id": request_id},
    }


class ConsumoDelClic(unittest.TestCase):
    """El clic se consume una sola vez, igual que el doble clic de edición."""

    def setUp(self) -> None:
        self.sesion = {}
        parche = patch.object(manual.st, "session_state", self.sesion)
        parche.start()
        self.addCleanup(parche.stop)

    def test_el_primer_clic_devuelve_la_razon_social(self) -> None:
        self.assertEqual(
            manual._consume_customer_click_event(evento("ACME SAS")), "ACME SAS"
        )

    def test_el_mismo_clic_no_se_consume_dos_veces(self) -> None:
        # El evento de la grilla sobrevive a los reruns: sin esta regla, el
        # clic viejo pisaría al buscador en cada reejecución de la página.
        manual._consume_customer_click_event(evento("ACME SAS"))
        self.assertIsNone(manual._consume_customer_click_event(evento("ACME SAS")))

    def test_un_clic_nuevo_si_se_consume(self) -> None:
        manual._consume_customer_click_event(evento("ACME SAS", "req-1"))
        self.assertEqual(
            manual._consume_customer_click_event(evento("OTRA SAS", "req-2")),
            "OTRA SAS",
        )

    def test_otros_eventos_y_datos_vacios_se_ignoran(self) -> None:
        self.assertIsNone(manual._consume_customer_click_event(None))
        self.assertIsNone(
            manual._consume_customer_click_event({"type": "invoiceEditRequested"})
        )
        self.assertIsNone(manual._consume_customer_click_event(evento("   ")))


class AnchosFijosDeLaTablaDeClientes(unittest.TestCase):
    """Pedido textual: ancho fijo para siempre visualizar eso bien."""

    def test_ninguna_columna_se_puede_arrastrar(self) -> None:
        for nombre, config in manual.COLUMNAS_CLIENTES.items():
            with self.subTest(columna=nombre):
                self.assertIs(config.get("resizable"), False)

    def test_los_datos_tienen_ancho_cerrado_y_el_cliente_flexible(self) -> None:
        for nombre in ("Saldo pendiente", "Facturas con saldo", "Empresas"):
            config = manual.COLUMNAS_CLIENTES[nombre]
            with self.subTest(columna=nombre):
                self.assertEqual(config["width"], config["minWidth"])
                self.assertEqual(config["width"], config["maxWidth"])
        # La razón social absorbe el espacio restante para leerse completa.
        self.assertEqual(manual.COLUMNAS_CLIENTES["Cliente"].get("flex"), 1)
        self.assertNotIn("maxWidth", manual.COLUMNAS_CLIENTES["Cliente"])


class ElClicAbreElDetalle(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        ruta = Path(self.temporal.name) / "cartera.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        for numero, cliente in (("1", "Transportes Andinos SAS"), ("2", "ACME SAS")):
            db.crear_factura(
                {
                    "empresa_codigo": "NOVASA",
                    "prefijo": "FEBA",
                    "numero": numero,
                    "fecha": date.today(),
                    "cliente": cliente,
                    "descripcion": "Servicio",
                    "placas": "ABC123",
                    "subtotal_cop": 1_000_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                }
            )

    GUION = (
        "import streamlit as st\n"
        "from src import database as db\n"
        "from src.views.manual import ManualFilters, _render_customer_detail\n"
        "filas = db.listar_facturas(None)\n"
        "filtros = ManualFilters('', (), (), None, None, 'Todas')\n"
        "_render_customer_detail(filas, filtros)\n"
    )

    def test_la_solicitud_por_clic_selecciona_al_cliente_en_el_buscador(self) -> None:
        app = AppTest.from_string(self.GUION)
        # El clic llega con otra capitalización: se resuelve sin distinguirla.
        app.session_state[manual.CLAVE_DETALLE_SOLICITADO] = "acme sas"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["detalle_cliente_manual"], "ACME SAS")
        # La solicitud se consumió: no queda pegada en la sesión.
        self.assertNotIn(manual.CLAVE_DETALLE_SOLICITADO, app.session_state)

    def test_un_cliente_desconocido_no_rompe_ni_selecciona_nada(self) -> None:
        app = AppTest.from_string(self.GUION)
        app.session_state[manual.CLAVE_DETALLE_SOLICITADO] = "NO EXISTE SAS"
        app.run()
        self.assertFalse(app.exception)
        # El buscador queda sin selección (la clave del widget existe vacía).
        self.assertIsNone(app.session_state["detalle_cliente_manual"])

    def test_el_buscador_sigue_funcionando_sin_ningun_clic(self) -> None:
        app = AppTest.from_string(self.GUION).run()
        self.assertFalse(app.exception)
        seleccion = app.selectbox[0].set_value("Transportes Andinos SAS")
        seleccion.run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state["detalle_cliente_manual"], "Transportes Andinos SAS"
        )


if __name__ == "__main__":
    unittest.main()
