"""Los diálogos de la cartera manual deben sobrevivir a los reruns.

Streamlit vuelve a ejecutar la página con cada tecla. Un diálogo cuya apertura
dependa de un gesto momentáneo se cierra en cuanto se toca el primer campo, y
no hay forma de completar una factura o un abono de varios datos.

Estas pruebas fijan las dos reglas: se abre y se queda abierto mientras el
usuario trabaja, y se cierra por CUALQUIER vía de salida, no solo al guardar.
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


class BanderasDeDialogo(unittest.TestCase):
    """Las tres funciones de cierre, sin levantar la interfaz completa."""

    def setUp(self) -> None:
        self.sesion = {}
        self.parche = patch.object(manual.st, "session_state", self.sesion)
        self.parche.start()
        self.addCleanup(self.parche.stop)

    def test_cerrar_la_edicion_olvida_la_factura_seleccionada(self) -> None:
        self.sesion[manual.CLAVE_FACTURA_EN_EDICION] = 7
        manual._cerrar_dialogo_edicion()
        self.assertNotIn(manual.CLAVE_FACTURA_EN_EDICION, self.sesion)

    def test_cerrar_la_edicion_dos_veces_no_falla(self) -> None:
        manual._cerrar_dialogo_edicion()
        manual._cerrar_dialogo_edicion()
        self.assertNotIn(manual.CLAVE_FACTURA_EN_EDICION, self.sesion)

    def test_cerrar_el_abono_apaga_su_bandera(self) -> None:
        self.sesion["dialogo_abono_abierto"] = True
        manual._cerrar_dialogo_abono()
        self.assertFalse(self.sesion["dialogo_abono_abierto"])

    def test_cerrar_la_factura_apaga_su_bandera_y_limpia_el_borrador(self) -> None:
        self.sesion["dialogo_factura_abierto"] = True
        self.sesion["factura_subtotal"] = "1.500.000"
        self.sesion["factura_cliente"] = "ACME SAS"
        manual._cerrar_dialogo_factura()
        self.assertFalse(self.sesion["dialogo_factura_abierto"])
        self.assertNotIn("factura_subtotal", self.sesion)
        self.assertNotIn("factura_cliente", self.sesion)


class LosDialogosDeclaranComoSeCierran(unittest.TestCase):
    """Salir con la X o con Esc tiene que apagar la bandera correspondiente.

    Sin ``on_dismiss`` la bandera quedaba encendida y el diálogo se reabría
    solo en el siguiente rerun, dejándolo pegado en pantalla.
    """

    def test_los_tres_dialogos_tienen_cierre_declarado(self) -> None:
        for nombre in ("show_invoice_dialog", "show_edit_invoice_dialog", "show_payment_dialog"):
            with self.subTest(dialogo=nombre):
                self.assertTrue(
                    hasattr(manual, nombre),
                    f"{nombre} debe existir en la vista manual",
                )
        fuente = Path("src/views/manual.py").read_text(encoding="utf-8")
        self.assertIn('@st.dialog("Registrar nueva factura"', fuente)
        for decorador in (
            'on_dismiss=_cerrar_dialogo_factura',
            'on_dismiss=_cerrar_dialogo_edicion',
            'on_dismiss=_cerrar_dialogo_abono',
        ):
            with self.subTest(decorador=decorador):
                self.assertIn(decorador, fuente)


class LaEdicionSobreviveAlRerun(unittest.TestCase):
    """La factura en edición vive en la sesión, no en el gesto de la grilla."""

    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        ruta = Path(self.temporal.name) / "cartera.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        self.factura_id = db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": "5001",
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

    def app_con_edicion_abierta(self) -> AppTest:
        """Levanta la vista con una factura ya marcada para editar."""

        app = AppTest.from_string(
            "import streamlit as st\n"
            "from src.views.manual import CLAVE_FACTURA_EN_EDICION\n"
            "st.write(st.session_state.get(CLAVE_FACTURA_EN_EDICION))\n"
        )
        app.session_state[manual.CLAVE_FACTURA_EN_EDICION] = self.factura_id
        return app.run()

    def test_la_factura_en_edicion_se_conserva_entre_ejecuciones(self) -> None:
        app = self.app_con_edicion_abierta()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state[manual.CLAVE_FACTURA_EN_EDICION], self.factura_id
        )
        # Un segundo rerun, como el que provoca escribir en cualquier campo.
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state[manual.CLAVE_FACTURA_EN_EDICION], self.factura_id
        )

    def test_el_formulario_de_edicion_abre_con_los_valores_guardados(self) -> None:
        app = AppTest.from_string(
            "from src.views.manual import _render_quick_edit\n"
            "from src import database as db\n"
            "filas = db.listar_facturas(None)\n"
            f"_render_quick_edit(filas, use_expander=False, invoice_id={self.factura_id})\n"
        ).run()
        self.assertFalse(app.exception)
        # El formulario arranca con lo guardado, no en blanco. El detalle y las
        # placas se editan en una cuadrícula, así que aquí se comprueban los
        # campos de texto y la ficha de la factura seleccionada.
        valores = [entrada.value for entrada in app.text_input]
        self.assertIn("5001", valores, "el número de la factura debe venir cargado")
        self.assertIn("1.000.000", valores, "el subtotal guardado debe venir cargado")
        ficha = " ".join(bloque.value for bloque in app.markdown)
        self.assertIn("FEBA5001", ficha)
        self.assertIn("Detalle original", ficha)
        self.assertIn("ABC123", ficha)


class LaSesionQuedaLimpiaAlSalir(unittest.TestCase):
    def test_cerrar_sesion_apaga_las_banderas_de_dialogo(self) -> None:
        from src.ui import ingreso

        sesion = {
            "dialogo_factura_abierto": True,
            "dialogo_abono_abierto": True,
            manual.CLAVE_FACTURA_EN_EDICION: 12,
            "vista": "Cartera manual",
        }
        with patch.object(ingreso.st, "session_state", sesion):
            ingreso.cerrar_sesion()
        self.assertEqual(sesion, {})


if __name__ == "__main__":
    unittest.main()
