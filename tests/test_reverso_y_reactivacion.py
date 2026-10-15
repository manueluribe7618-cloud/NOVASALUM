"""Reversar un abono y reactivar una factura anulada.

Pedido del dueño (2026-10-15): un abono mal registrado era permanente y una
factura anulada por error no volvía. Las dos acciones piden motivo y
confirmación, devuelven los saldos y quedan en la auditoría.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src import database as db


def factura(numero: str, fecha: date, subtotal: int = 100_000, ruta=None) -> int:
    return db.crear_factura(
        {
            "empresa_codigo": "NOVASA",
            "prefijo": "FEBA",
            "numero": numero,
            "fecha": fecha,
            "vencimiento": fecha + timedelta(days=30),
            "cliente": "Cliente de prueba SAS",
            "descripcion": "Servicio de prueba",
            "placas": "ABC123",
            "subtotal_cop": subtotal,
            "iva_cop": 0,
            "retefuente_cop": 0,
            "ica_cop": 0,
        },
        ruta,
    )


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(self.ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        db.inicializar()
        self.hoy = date.today()

    def abonar(self, monto: int, aplicaciones, referencia: str = "TRX-1", ruta=None) -> int:
        return db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia=referencia,
            monto_cop=monto,
            aplicaciones=aplicaciones,
            ruta=ruta,
        )

    def auditoria(self, accion: str) -> list[dict]:
        return [
            json.loads(evento["detalle"])
            for evento in db.resumen_actividad(50)
            if evento["accion"] == accion
        ]


class ReversarAbono(Base):
    def test_reversar_devuelve_el_saldo_a_todas_las_facturas_del_fifo(self) -> None:
        primera = factura("100", self.hoy - timedelta(days=12))
        segunda = factura("101", self.hoy - timedelta(days=3))
        aplicaciones, _ = db.previsualizar_fifo(
            db.facturas_pendientes_cliente("NOVASA", 1), 150_000
        )
        abono = self.abonar(150_000, aplicaciones)

        db.reversar_abono(abono, "Consignación de otro cliente")

        facturas = db.listar_facturas("NOVASA")
        self.assertEqual([fila["saldo_cop"] for fila in facturas], [100_000, 100_000])
        self.assertEqual([fila["estado"] for fila in facturas], ["PENDIENTE", "PENDIENTE"])
        [registro] = db.listar_abonos("NOVASA")
        self.assertEqual(registro["aplicado_cop"], 0)
        self.assertEqual(registro["monto_cop"], 150_000)
        self.assertTrue(registro["reversado_en"])
        self.assertEqual(registro["motivo_reverso"], "Consignación de otro cliente")
        [detalle] = self.auditoria("REVERSADO")
        self.assertEqual(
            detalle["aplicaciones"],
            [
                {"factura_id": primera, "monto_cop": 100_000},
                {"factura_id": segunda, "monto_cop": 50_000},
            ],
        )
        self.assertEqual(detalle["motivo"], "Consignación de otro cliente")

    def test_reversar_un_abono_especifico_deja_los_demas_intactos(self) -> None:
        primera = factura("100", self.hoy - timedelta(days=12))
        segunda = factura("101", self.hoy - timedelta(days=3))
        especifico = self.abonar(100_000, [{"factura_id": segunda, "monto_cop": 100_000}], "ESP")
        self.abonar(40_000, [{"factura_id": primera, "monto_cop": 40_000}], "GEN")

        db.reversar_abono(especifico, "Era de otra factura")

        saldos = {fila["id"]: fila["saldo_cop"] for fila in db.listar_facturas("NOVASA")}
        self.assertEqual(saldos, {primera: 60_000, segunda: 100_000})
        vigentes = [a["referencia"] for a in db.listar_abonos("NOVASA") if not a["reversado_en"]]
        self.assertEqual(vigentes, ["GEN"])
        # El saldo liberado vuelve a aceptar abonos.
        self.abonar(100_000, [{"factura_id": segunda, "monto_cop": 100_000}], "NUEVO")
        self.assertEqual(db.obtener_factura(segunda)["estado"], "PAGADA")

    def test_un_abono_con_saldo_a_favor_se_reversa_completo(self) -> None:
        pendiente = factura("100", self.hoy)
        abono = self.abonar(130_000, [{"factura_id": pendiente, "monto_cop": 100_000}])

        db.reversar_abono(abono, "Pago duplicado")

        [registro] = db.listar_abonos("NOVASA")
        self.assertEqual(registro["saldo_a_favor_cop"], 30_000)
        self.assertEqual(self.auditoria("REVERSADO")[0]["saldo_a_favor_cop"], 30_000)
        self.assertEqual(db.obtener_factura(pendiente)["saldo_cop"], 100_000)

    def test_no_se_reversa_dos_veces_ni_sin_motivo_ni_uno_inexistente(self) -> None:
        pendiente = factura("100", self.hoy)
        abono = self.abonar(100_000, [{"factura_id": pendiente, "monto_cop": 100_000}])

        with self.assertRaisesRegex(db.ErrorCartera, "motivo"):
            db.reversar_abono(abono, "   ")
        self.assertEqual(db.obtener_factura(pendiente)["estado"], "PAGADA")
        db.reversar_abono(abono, "Error de digitación")
        with self.assertRaisesRegex(db.ErrorCartera, "ya fue reversado"):
            db.reversar_abono(abono, "Otra vez")
        with self.assertRaisesRegex(db.ErrorCartera, "no existe"):
            db.reversar_abono(abono + 99, "Nada")
        self.assertEqual(len(self.auditoria("REVERSADO")), 1)

    def test_tras_reversar_la_factura_se_puede_anular(self) -> None:
        pendiente = factura("100", self.hoy)
        abono = self.abonar(100_000, [{"factura_id": pendiente, "monto_cop": 100_000}])
        with self.assertRaises(db.ErrorCartera):
            db.anular_factura(pendiente)

        db.reversar_abono(abono, "Se cobró a otro cliente")
        db.anular_factura(pendiente)

        self.assertEqual(db.listar_facturas("NOVASA"), [])

    def test_una_base_anterior_se_migra_sola(self) -> None:
        vieja = Path(self.temporal.name) / "vieja.db"
        db.inicializar(vieja)
        conexion = sqlite3.connect(vieja)
        try:
            conexion.execute("ALTER TABLE abonos_manual DROP COLUMN reversado_en")
            conexion.execute("ALTER TABLE abonos_manual DROP COLUMN motivo_reverso")
            conexion.commit()
        finally:
            conexion.close()
        pendiente = factura("900", self.hoy, ruta=vieja)
        abono = self.abonar(100_000, [{"factura_id": pendiente, "monto_cop": 100_000}], ruta=vieja)

        db.reversar_abono(abono, "Base anterior", ruta=vieja)

        [registro] = db.listar_abonos("NOVASA", ruta=vieja)
        self.assertEqual(registro["motivo_reverso"], "Base anterior")
        self.assertEqual(db.obtener_factura(pendiente, vieja)["saldo_cop"], 100_000)


class ReactivarFactura(Base):
    def test_reactivar_devuelve_la_factura_con_su_numero_y_estado(self) -> None:
        pendiente = factura("100", self.hoy)
        db.anular_factura(pendiente)
        self.assertEqual(db.listar_facturas("NOVASA"), [])

        db.reactivar_factura(pendiente, "Se anuló por error")

        [fila] = db.listar_facturas("NOVASA")
        self.assertEqual((fila["id"], fila["factura"], fila["estado"]), (pendiente, "FEBA100", "PENDIENTE"))
        [detalle] = self.auditoria("REACTIVADA")
        self.assertEqual(detalle, {"factura": "FEBA100", "motivo": "Se anuló por error"})
        # Vuelve a recibir abonos como cualquier otra.
        self.abonar(100_000, [{"factura_id": pendiente, "monto_cop": 100_000}])
        self.assertEqual(db.obtener_factura(pendiente)["estado"], "PAGADA")

    def test_no_reactiva_una_viva_ni_sin_motivo_ni_una_inexistente(self) -> None:
        pendiente = factura("100", self.hoy)
        with self.assertRaisesRegex(db.ErrorCartera, "no está anulada"):
            db.reactivar_factura(pendiente, "Motivo")
        db.anular_factura(pendiente)
        with self.assertRaisesRegex(db.ErrorCartera, "motivo"):
            db.reactivar_factura(pendiente, "")
        self.assertEqual(db.listar_facturas("NOVASA"), [])
        with self.assertRaisesRegex(db.ErrorCartera, "no existe"):
            db.reactivar_factura(pendiente + 99, "Motivo")
        self.assertEqual(self.auditoria("REACTIVADA"), [])

    def test_una_vencida_reactivada_vuelve_como_vencida(self) -> None:
        vencida = factura("100", self.hoy - timedelta(days=60))
        db.anular_factura(vencida)
        db.reactivar_factura(vencida, "Error")
        self.assertEqual(db.obtener_factura(vencida)["estado"], "VENCIDA")


GUION_ABONOS = (
    "from src.views.manual import _render_customer_payments\n"
    "_render_customer_payments('NOVASA', [1])\n"
)
GUION_ANULADAS = (
    "from src.views.manual import _render_annulled_invoices\n"
    "_render_annulled_invoices('{empresa}')\n"
)
GUION_DIALOGO = (
    "import streamlit as st\n"
    "from src.views.manual import _render_customer_payments, _request_payment_for\n"
    "st.session_state.setdefault('abono_empresa', 'NOVASA')\n"
    "st.session_state.setdefault('abono_cliente', 1)\n"
    "_render_customer_payments('NOVASA', [1])\n"
    "if st.button('pedir'):\n"
    "    _request_payment_for('LUAC', 3)\n"
)


class PantallaDeReverso(Base):
    def test_el_boton_se_enciende_solo_con_abono_motivo_y_confirmacion(self) -> None:
        pendiente = factura("100", self.hoy)
        self.abonar(100_000, [{"factura_id": pendiente, "monto_cop": 100_000}], "TRX-9")
        app = AppTest.from_string(GUION_ABONOS).run()
        self.assertFalse(app.exception)
        self.assertTrue(next(b for b in app.button if b.label == "Reversar abono").disabled)

        app.selectbox(key="reverso_abono_NOVASA_1").select_index(0)
        app.text_input(key="reverso_motivo_NOVASA_1").input("Se registró al cliente equivocado")
        app.checkbox(key="reverso_confirmar_NOVASA_1").check().run()
        boton = next(b for b in app.button if b.label == "Reversar abono")
        self.assertFalse(boton.disabled)
        boton.click().run()
        self.assertFalse(app.exception)
        # AppTest conserva los campos del clic; la pantalla se carga de nuevo
        # para ver lo mismo que el usuario tras el st.rerun().
        app = AppTest.from_string(GUION_ABONOS).run()

        self.assertFalse(app.exception)
        self.assertEqual(db.obtener_factura(pendiente)["saldo_cop"], 100_000)
        self.assertEqual(
            db.listar_abonos("NOVASA")[0]["motivo_reverso"], "Se registró al cliente equivocado"
        )
        # Ya reversado: la tabla lo marca y no queda nada más que reversar.
        self.assertIn("Reversado el", app.dataframe[0].value["Estado"].iloc[0])
        self.assertEqual([b for b in app.button if b.label == "Reversar abono"], [])

    def test_tras_reversar_el_formulario_queda_limpio_para_el_siguiente(self) -> None:
        primera = factura("100", self.hoy - timedelta(days=5))
        segunda = factura("101", self.hoy)
        self.abonar(100_000, [{"factura_id": primera, "monto_cop": 100_000}], "A")
        self.abonar(100_000, [{"factura_id": segunda, "monto_cop": 100_000}], "B")
        app = AppTest.from_string(GUION_ABONOS).run()
        app.selectbox(key="reverso_abono_NOVASA_1").select_index(0)
        app.text_input(key="reverso_motivo_NOVASA_1").input("Error")
        app.checkbox(key="reverso_confirmar_NOVASA_1").check().run()
        next(b for b in app.button if b.label == "Reversar abono").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len([a for a in db.listar_abonos("NOVASA") if a["reversado_en"]]), 1)
        # Queda un abono vigente, así que el formulario se dibuja de nuevo, en blanco.
        self.assertIsNone(app.session_state["reverso_abono_NOVASA_1"])
        self.assertEqual(app.session_state["reverso_motivo_NOVASA_1"], "")
        self.assertIs(app.session_state["reverso_confirmar_NOVASA_1"], False)

    def test_un_abono_reversado_no_muestra_saldo_a_favor(self) -> None:
        pendiente = factura("100", self.hoy)
        abono = self.abonar(130_000, [{"factura_id": pendiente, "monto_cop": 100_000}])
        app = AppTest.from_string(GUION_ABONOS).run()
        self.assertEqual(app.dataframe[0].value["Saldo a favor"].iloc[0], "$ 30.000")
        db.reversar_abono(abono, "Pago duplicado")
        app = AppTest.from_string(GUION_ABONOS).run()
        self.assertEqual(app.dataframe[0].value["Saldo a favor"].iloc[0], "")

    def test_listar_los_abonos_no_borra_la_seleccion_del_dialogo_de_abono(self) -> None:
        """El bloque que limpia el diálogo vive en _request_payment_for, no aquí."""

        pendiente = factura("100", self.hoy)
        self.abonar(50_000, [{"factura_id": pendiente, "monto_cop": 50_000}])
        app = AppTest.from_string(GUION_DIALOGO).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["abono_empresa"], "NOVASA")
        self.assertEqual(app.session_state["abono_cliente"], 1)
        next(b for b in app.button if b.label == "pedir").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["abono_preseleccion"], {"empresa": "LUAC", "cliente_id": 3})
        self.assertNotIn("abono_empresa", app.session_state)
        self.assertNotIn("abono_cliente", app.session_state)

    def test_sin_abonos_no_dibuja_nada(self) -> None:
        factura("100", self.hoy)
        app = AppTest.from_string(GUION_ABONOS).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 0)


class PantallaDeReactivacion(Base):
    def test_reactivar_desde_la_lista_de_anuladas(self) -> None:
        pendiente = factura("100", self.hoy)
        db.anular_factura(pendiente)
        app = AppTest.from_string(GUION_ANULADAS.format(empresa="NOVASA")).run()
        self.assertFalse(app.exception)
        self.assertTrue(next(b for b in app.button if b.label == "Reactivar factura").disabled)

        app.selectbox(key="reactivar_factura").select_index(0)
        app.text_input(key="reactivar_motivo").input("Se anuló por error")
        app.checkbox(key="reactivar_confirmar").check().run()
        next(b for b in app.button if b.label == "Reactivar factura").click().run()
        self.assertFalse(app.exception)
        app = AppTest.from_string(GUION_ANULADAS.format(empresa="NOVASA")).run()

        self.assertFalse(app.exception)
        self.assertEqual(db.obtener_factura(pendiente)["estado"], "PENDIENTE")
        self.assertEqual(len(app.expander), 0)
        for key in ("reactivar_factura", "reactivar_motivo", "reactivar_confirmar"):
            self.assertNotIn(key, app.session_state)

    def test_dos_anuladas_iguales_en_todas_las_empresas_se_distinguen(self) -> None:
        primera = factura("100", self.hoy)
        segunda = db.crear_factura({**{
            "empresa_codigo": "LUAC", "prefijo": "LUA", "numero": "100", "fecha": self.hoy,
            "vencimiento": self.hoy + timedelta(days=30), "cliente": "Cliente de prueba SAS",
            "descripcion": "x", "placas": "", "subtotal_cop": 100_000, "iva_cop": 0,
            "retefuente_cop": 0, "ica_cop": 0,
        }})
        db.anular_factura(primera)
        db.anular_factura(segunda)
        app = AppTest.from_string(GUION_ANULADAS.format(empresa="TODAS")).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.selectbox(key="reactivar_factura").options), 2)

    def test_solo_lista_las_anuladas_de_la_empresa_de_la_vista(self) -> None:
        db.anular_factura(factura("100", self.hoy))
        app = AppTest.from_string(GUION_ANULADAS.format(empresa="LUAC")).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 0)
