"""Regresiones de captura reactiva: porcentajes, clientes y edición."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src import database as db
from src.views.manual import _consume_invoice_edit_event


class InvoiceFormTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "cartera.db"
        self.environment = patch.dict("os.environ", {"NOVASALUM_DB": str(self.path)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.invoice_id = db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": "PRUEBA-1",
                "fecha": date.today(),
                "cliente": "Transportes de Prueba SAS",
                "descripcion": "Detalle original",
                "placas": "ABC123",
                "subtotal_cop": 1_000_000,
                "iva_cop": 190_000,
                "retefuente_cop": 25_000,
                "ica_cop": 4_140,
            }
        )

    def new_form(self) -> AppTest:
        app = AppTest.from_string(
            "from src.views.manual import _render_invoice_form\n"
            "_render_invoice_form('TODAS', use_expander=False)\n"
        ).run()
        self.assertFalse(app.exception)
        return app

    def test_porcentajes_recalculan_antes_de_guardar_y_persisten(self) -> None:
        app = self.new_form()
        app.selectbox(key="factura_cliente").select("Transportes de Prueba SAS")
        app.text_input(key="factura_numero").input("PRUEBA-2")
        app.text_input(key="factura_subtotal").input("1.000.000")
        app.number_input(key="factura_iva_porcentaje").set_value(19.0)
        app.number_input(key="factura_retefuente_porcentaje").set_value(2.5)
        app.number_input(key="factura_ica_porcentaje").set_value(0.414)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "$ 1.160.900")
        self.assertEqual(app.number_input(key="factura_ica_porcentaje").value, 0.41)
        self.assertEqual(len(db.listar_facturas()), 1)

        app.text_input(key="factura_subtotal").input("2000000").run()
        self.assertEqual(app.text_input(key="factura_subtotal").value, "2.000.000")
        self.assertEqual(app.metric[0].value, "$ 2.321.800")
        self.assertEqual(app.selectbox(key="factura_cliente").value, "Transportes de Prueba SAS")
        app.button(key="factura_guardar").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        saved = next(row for row in db.listar_facturas() if row["numero"] == "PRUEBA-2")
        self.assertEqual(saved["iva_cop"], 380_000)
        self.assertEqual(saved["retefuente_cop"], 50_000)
        self.assertEqual(saved["ica_cop"], 8_200)
        self.assertEqual(saved["saldo_cop"], 2_321_800)
        self.assertEqual(saved["cliente_id"], db.obtener_factura(self.invoice_id)["cliente_id"])

    def test_puede_cambiar_de_porcentaje_a_valor_fijo_y_no_aplica(self) -> None:
        app = self.new_form()
        app.text_input(key="factura_subtotal").input("1.000.000")
        app.radio(key="factura_iva_modo").set_value("VALOR_FIJO").run()
        app.number_input(key="factura_iva_valor").set_value(12_345).run()
        self.assertEqual(app.metric[0].value, "$ 1.012.345")
        app.radio(key="factura_iva_modo").set_value("NO_APLICA").run()
        self.assertEqual(app.metric[0].value, "$ 1.000.000")
        self.assertFalse(app.exception)

    def test_cliente_es_obligatorio_y_error_conserva_la_captura(self) -> None:
        app = self.new_form()
        app.text_input(key="factura_numero").input("NUEVO")
        app.text_input(key="factura_subtotal").input("500000")
        app.button(key="factura_guardar").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(len(db.listar_facturas()), 1)
        self.assertEqual(app.text_input(key="factura_subtotal").value, "500.000")

    def test_subtotal_invalido_impide_guardar_y_permite_corregir(self) -> None:
        app = self.new_form()
        app.text_input(key="factura_subtotal").input("1.5").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertTrue(app.button(key="factura_guardar").disabled)
        self.assertEqual(app.metric[0].value, "—")
        app.text_input(key="factura_subtotal").input("$ 1.500.000").run()
        self.assertFalse(app.error)
        self.assertFalse(app.button(key="factura_guardar").disabled)
        self.assertEqual(app.text_input(key="factura_subtotal").value, "1.500.000")
        self.assertEqual(app.metric[0].value, "$ 1.500.000")

    def test_edicion_conserva_importes_y_permite_porcentajes(self) -> None:
        app = AppTest.from_string(
            "from src import database as db\n"
            "from src.views.manual import _render_quick_edit\n"
            "_render_quick_edit(db.listar_facturas(), use_expander=False)\n"
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "$ 1.160.860")
        prefix = f"editar_factura_{self.invoice_id}"
        app.radio(key=f"{prefix}_iva_modo").set_value("PORCENTAJE").run()
        app.number_input(key=f"{prefix}_iva_porcentaje").set_value(10.0).run()
        self.assertEqual(app.metric[0].value, "$ 1.070.860")
        next(button for button in app.button if button.label == "Guardar cambios").click().run()
        self.assertFalse(app.exception)
        saved = db.obtener_factura(self.invoice_id)
        self.assertEqual(saved["iva_cop"], 100_000)
        self.assertEqual(saved["retefuente_cop"], 25_000)
        self.assertEqual(saved["ica_cop"], 4_140)

        app.text_input(key=f"{prefix}_subtotal").input("2.000.000").run()
        self.assertEqual(app.metric[0].value, "$ 2.170.860")
        next(button for button in app.button if button.label == "Guardar cambios").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(db.obtener_factura(self.invoice_id)["subtotal_cop"], 2_000_000)

    def test_prefijo_sigue_la_empresa_y_respeta_un_prefijo_personalizado(self) -> None:
        app = self.new_form()
        app.selectbox(key="factura_empresa").select("LUAC").run()
        self.assertEqual(app.text_input(key="factura_prefijo").value, "LUA")
        app.text_input(key="factura_prefijo").input("ESPECIAL").run()
        app.selectbox(key="factura_empresa").select("MSU").run()
        self.assertEqual(app.text_input(key="factura_prefijo").value, "ESPECIAL")
        self.assertFalse(app.exception)

    def test_edicion_directa_abre_y_guarda_solo_la_factura_indicada(self) -> None:
        second_id = db.crear_factura(
            {
                "empresa_codigo": "MSU",
                "prefijo": "FEBA",
                "numero": "PRUEBA-1",
                "fecha": date.today(),
                "cliente": "Transportes de Prueba SAS",
                "subtotal_cop": 700_000,
            }
        )
        app = AppTest.from_string(
            "from src import database as db\n"
            "from src.views.manual import _render_quick_edit\n"
            f"_render_quick_edit(db.listar_facturas(), use_expander=False, invoice_id={second_id})\n"
        ).run()
        self.assertFalse(app.exception)
        self.assertFalse(any(widget.label == "Factura a editar" for widget in app.selectbox))
        self.assertEqual(app.metric[0].value, "$ 700.000")
        app.text_input(key=f"editar_factura_{second_id}_subtotal").input("800.000").run()
        next(button for button in app.button if button.label == "Guardar cambios").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(db.obtener_factura(second_id)["subtotal_cop"], 800_000)
        self.assertEqual(db.obtener_factura(self.invoice_id)["subtotal_cop"], 1_000_000)

    def test_doble_clic_usa_id_y_no_se_repite_al_recalcular_o_cerrar(self) -> None:
        event = {
            "type": "invoiceEditRequested",
            "data": {"invoice_id": self.invoice_id, "request_id": "primer-gesto"},
        }
        state = {
            f"editar_factura_{self.invoice_id}_subtotal": "123",
            f"editor_factura_{self.invoice_id}": {"edited_rows": {}},
            "factura_subtotal": "456",
        }
        with patch("src.views.manual.st.session_state", state):
            # El ID real puede estar en cualquier posición tras ordenar o filtrar.
            invoices = [{"id": 9000}, {"id": self.invoice_id}]
            self.assertEqual(_consume_invoice_edit_event(event, invoices), self.invoice_id)
            self.assertNotIn(f"editar_factura_{self.invoice_id}_subtotal", state)
            self.assertEqual(state["factura_subtotal"], "456")
            self.assertIsNone(_consume_invoice_edit_event(event, invoices))
            event["data"]["request_id"] = "segundo-gesto"
            self.assertEqual(_consume_invoice_edit_event(event, invoices), self.invoice_id)
            event["data"]["request_id"] = "factura-fuera-del-filtro"
            self.assertIsNone(_consume_invoice_edit_event(event, [{"id": 9000}]))
            self.assertIsNone(_consume_invoice_edit_event(None, invoices))


if __name__ == "__main__":
    unittest.main()
