"""Los clientes repetidos se distinguen sin cambiar el registro existente."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src import database as db
from src.formato import hoy_colombia
from src.views import manual


class ClientesLegacyEnLaInterfaz(unittest.TestCase):
    PAYMENT_APP = "from src.views.manual import show_payment_dialog\nshow_payment_dialog()\n"
    DETAIL_APP = (
        "from unittest.mock import patch\n"
        "from src import database as db\n"
        "from src.views import manual\n"
        "filas = db.listar_facturas()\n"
        "filtros = manual.ManualFilters('', (), (), None, None, 'Todos')\n"
        "with patch.object(manual, '_render_grid', lambda *args, **kwargs: None):\n"
        "    manual._render_customer_detail(filas, filtros)\n"
    )

    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = Path(temporal.name) / "cartera.db"
        entorno = patch.dict(
            "os.environ", {"NOVASALUM_DB": str(self.ruta), "SUPABASE_DB_URL": ""}
        )
        entorno.start()
        self.addCleanup(entorno.stop)
        nube = patch.object(db, "_conexion_pg", side_effect=AssertionError("Sin Supabase"))
        nube.start()
        self.addCleanup(nube.stop)
        db.invalidar_lecturas()
        self.addCleanup(db.invalidar_lecturas)
        self.hoy = hoy_colombia()
        self.primera = self.crear("NOVASA", "1", "Transportes Ávila SAS", 300_000)
        self.segunda = self.crear("NOVASA", "2", "Temporal SAS", 200_000)
        self.luac = self.crear("LUAC", "3", "Transportes Ávila SAS", 100_000)
        self.crear("NOVASA", "4", "Otro Cliente SAS", 50_000)
        self.primer_cliente = int(db.obtener_factura(self.primera)["cliente_id"])
        self.segundo_cliente = int(db.obtener_factura(self.segunda)["cliente_id"])
        self.cliente_luac = int(db.obtener_factura(self.luac)["cliente_id"])
        # Reproduce dos registros anteriores al reconocimiento por razón social.
        with closing(sqlite3.connect(self.ruta)) as conexion:
            conexion.execute(
                "UPDATE clientes SET nombre = ? WHERE id = ?",
                ("TRANSPORTES  ÁVILA SAS", self.segundo_cliente),
            )
            conexion.commit()
        db.invalidar_lecturas()

    def crear(self, empresa: str, numero: str, cliente: str, subtotal: int) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": empresa,
                "prefijo": db.EMPRESAS[empresa]["prefijo"],
                "numero": numero,
                "fecha": self.hoy,
                "cliente": cliente,
                "subtotal_cop": subtotal,
            }
        )

    def abrir_abono(self, empresa: str = "NOVASA") -> AppTest:
        app = AppTest.from_string(self.PAYMENT_APP)
        app.session_state["empresa_activa"] = empresa
        app.run()
        self.assertFalse(app.exception)
        return app

    def abrir_detalle(self) -> AppTest:
        app = AppTest.from_string(self.DETAIL_APP)
        app.session_state[manual.CLAVE_DETALLE_SOLICITADO] = "Transportes Ávila SAS"
        app.run()
        self.assertFalse(app.exception)
        return app

    def abonar(self, factura: int, cliente: int, monto: int) -> None:
        db.registrar_abono(
            empresa_codigo="NOVASA", cliente_id=cliente, fecha=self.hoy,
            referencia="OTRA-SESION", monto_cop=monto,
            aplicaciones=[{"factura_id": factura, "monto_cop": monto}],
        )

    def test_los_nombres_equivalentes_identifican_su_registro_en_el_abono(self) -> None:
        app = self.abrir_abono()
        opciones = app.selectbox(key="abono_cliente").options
        self.assertIn(f"Transportes Ávila SAS · Registro {self.primer_cliente}", opciones)
        self.assertIn(f"TRANSPORTES ÁVILA SAS · Registro {self.segundo_cliente}", opciones)
        self.assertIn("Otro Cliente SAS", opciones)
        self.assertIsNone(app.selectbox(key="abono_cliente").value)
        # Mostrar las opciones no unifica, limpia ni reasigna los datos históricos.
        with closing(sqlite3.connect(self.ruta)) as conexion:
            nombre = conexion.execute(
                "SELECT nombre FROM clientes WHERE id = ?", (self.segundo_cliente,)
            ).fetchone()[0]
        self.assertEqual(nombre, "TRANSPORTES  ÁVILA SAS")

    def test_el_pago_solo_afecta_al_registro_elegido(self) -> None:
        app = self.abrir_abono()
        app.selectbox(key="abono_cliente").set_value(self.segundo_cliente).run()
        avisos = " ".join(caption.value for caption in app.caption)
        self.assertIn(f"solo a las facturas del registro {self.segundo_cliente}", avisos)
        app.number_input(key="abono_monto").set_value(50_000)
        app.text_input(key="abono_referencia").input("LEGACY-2").run()
        next(button for button in app.button if button.label == "Aplicar abono").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(db.obtener_factura(self.primera)["abonos_cop"], 0)
        self.assertEqual(db.obtener_factura(self.segunda)["abonos_cop"], 50_000)
        self.assertEqual(db.obtener_factura(self.luac)["abonos_cop"], 0)
        self.assertEqual(db.obtener_factura(self.segunda)["cliente_id"], self.segundo_cliente)

    def test_el_detalle_explica_la_agrupacion_y_abona_al_registro_indicado(self) -> None:
        app = self.abrir_detalle()
        avisos = " ".join(caption.value for caption in app.caption)
        self.assertIn("2 registros en NOVASA Logistic SAS", avisos)
        self.assertIn("cada abono se aplica solo", avisos)
        self.assertIn("$ 600.000", " ".join(block.value for block in app.markdown))
        self.assertFalse(any(button.key == "abono_detalle_NOVASA" for button in app.button))
        app.button(key=f"abono_detalle_NOVASA_{self.segundo_cliente}").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state["abono_preseleccion"],
            {"empresa": "NOVASA", "cliente_id": self.segundo_cliente},
        )
        pendientes = db.facturas_pendientes_cliente("NOVASA", self.segundo_cliente)
        self.assertEqual([factura["id"] for factura in pendientes], [self.segunda])

    def test_otra_empresa_con_un_solo_registro_conserva_su_accion(self) -> None:
        app = self.abrir_detalle()
        app.button(key="abono_detalle_LUAC").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state["abono_preseleccion"],
            {"empresa": "LUAC", "cliente_id": self.cliente_luac},
        )
        abono = self.abrir_abono("LUAC")
        self.assertEqual(abono.selectbox(key="abono_cliente").options, ["Transportes Ávila SAS"])

    def test_saldar_otro_registro_no_cambia_el_cliente_elegido(self) -> None:
        app = self.abrir_abono()
        app.selectbox(key="abono_cliente").set_value(self.segundo_cliente).run()
        self.abonar(self.primera, self.primer_cliente, 300_000)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="abono_cliente").value, self.segundo_cliente)

    def test_el_detalle_no_ofrece_abonar_a_un_registro_saldado(self) -> None:
        self.abonar(self.primera, self.primer_cliente, 300_000)
        app = self.abrir_detalle()
        self.assertIn("2 registros", " ".join(caption.value for caption in app.caption))
        claves = {button.key for button in app.button}
        self.assertNotIn(f"abono_detalle_NOVASA_{self.primer_cliente}", claves)
        self.assertIn(f"abono_detalle_NOVASA_{self.segundo_cliente}", claves)


if __name__ == "__main__":
    unittest.main()
