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
from src.formato import hoy_colombia
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


class ElAbonoNuncaCambiaDeClienteEnSilencio(unittest.TestCase):
    """Mientras el diálogo está abierto, otra sesión puede mover los saldos.

    Antes la opción era «nombre · saldo»: si el saldo cambiaba, Streamlit
    volvía sin avisar a la primera opción, el mayor deudor, y el abono quedaba
    en otro cliente sin forma de reversarlo.
    """

    GUION = (
        "from src.views.manual import show_payment_dialog\n"
        "show_payment_dialog()\n"
    )

    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        ruta = Path(self.temporal.name) / "cartera.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        facturas = {}
        for numero, cliente, subtotal in (
            ("10", "Alfa Mayor SAS", 50_000_000),
            ("20", "Beta Pequena SAS", 5_000_000),
        ):
            facturas[cliente] = db.crear_factura(
                {
                    "empresa_codigo": "NOVASA", "prefijo": "FEBA", "numero": numero,
                    "fecha": hoy_colombia(), "cliente": cliente, "subtotal_cop": subtotal,
                }
            )
        self.alfa_factura = facturas["Alfa Mayor SAS"]
        self.beta_factura = facturas["Beta Pequena SAS"]
        self.beta = int(db.obtener_factura(self.beta_factura)["cliente_id"])

    def abrir(self, **sesion) -> AppTest:
        app = AppTest.from_string(self.GUION)
        app.session_state["empresa_activa"] = "NOVASA"
        for clave, valor in sesion.items():
            app.session_state[clave] = valor
        app.run()
        self.assertFalse(app.exception)
        return app

    def elegir_beta_y_escribir_pago(self, app: AppTest) -> None:
        app.selectbox(key="abono_cliente").set_value(self.beta).run()
        app.number_input(key="abono_monto").set_value(1_000_000)
        app.text_input(key="abono_referencia").input("TRANSF-BETA-1").run()
        self.assertFalse(app.exception)

    def abonar_a_beta_desde_otra_sesion(self, monto: int) -> None:
        db.registrar_abono(
            empresa_codigo="NOVASA", cliente_id=self.beta, fecha=hoy_colombia(),
            referencia="OTRA-SESION", monto_cop=monto,
            aplicaciones=[{"factura_id": self.beta_factura, "monto_cop": monto}],
        )

    def aplicar(self, app: AppTest) -> None:
        next(boton for boton in app.button if boton.label == "Aplicar abono").click().run()
        self.assertFalse(app.exception)

    def test_sin_preseleccion_no_queda_elegido_el_mayor_deudor(self) -> None:
        app = self.abrir()
        self.assertIsNone(app.selectbox(key="abono_cliente").value)
        self.assertFalse(any(boton.label == "Aplicar abono" for boton in app.button))

    def test_la_preseleccion_del_detalle_elige_a_ese_cliente(self) -> None:
        app = self.abrir(abono_preseleccion={"empresa": "NOVASA", "cliente_id": self.beta})
        self.assertEqual(app.selectbox(key="abono_cliente").value, self.beta)

    def test_si_el_saldo_cambia_el_abono_sigue_en_el_cliente_elegido(self) -> None:
        app = self.abrir()
        self.elegir_beta_y_escribir_pago(app)
        self.abonar_a_beta_desde_otra_sesion(500_000)
        self.aplicar(app)
        abono = next(a for a in db.listar_abonos() if a["referencia"] == "TRANSF-BETA-1")
        self.assertEqual(abono["cliente"], "Beta Pequena SAS")
        self.assertEqual(db.obtener_factura(self.alfa_factura)["abonos_cop"], 0)
        self.assertEqual(
            app.session_state["aviso_manual"], "Abono aplicado y registrado en auditoría."
        )

    def comprobar_que_un_cliente_saldado_no_recibe_el_abono(self, *, fifo: bool) -> None:
        app = self.abrir()
        self.elegir_beta_y_escribir_pago(app)
        if not fifo:
            app.toggle(key="abono_fifo").set_value(False).run()
        self.abonar_a_beta_desde_otra_sesion(5_000_000)
        self.aplicar(app)
        self.assertIn("ya no tiene saldo", " ".join(aviso.value for aviso in app.warning))
        self.assertFalse(any(boton.label == "Aplicar abono" for boton in app.button))
        self.assertEqual(
            [a["referencia"] for a in db.listar_abonos()], ["OTRA-SESION"]
        )

    def test_abono_general_a_un_cliente_que_quedo_sin_saldo_no_se_registra(self) -> None:
        self.comprobar_que_un_cliente_saldado_no_recibe_el_abono(fifo=True)

    def test_abono_especifico_a_un_cliente_que_quedo_sin_saldo_no_se_registra(self) -> None:
        self.comprobar_que_un_cliente_saldado_no_recibe_el_abono(fifo=False)


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
