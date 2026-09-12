"""La puerta de acceso de la aplicación, probada sobre la app real.

No basta con que exista la pantalla de ingreso: hay que comprobar que sin
ingresar no se alcanza a ver ni un peso de la cartera.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src import autenticacion as auth


RAIZ = str(Path(__file__).resolve().parent.parent)
CLAVE = "MiClaveSegura123"


def _preparar_base() -> tuple[tempfile.TemporaryDirectory, Path]:
    temporal = tempfile.TemporaryDirectory()
    ruta = Path(temporal.name) / "cartera.db"
    return temporal, ruta


class PuertaDeAccesoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal, self.ruta = _preparar_base()
        self.addCleanup(self.temporal.cleanup)
        # NOVASALUM_DB manda sobre la nube: la prueba nunca toca producción.
        self.entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(self.ruta)})
        self.entorno.start()
        self.addCleanup(self.entorno.stop)
        auth.crear_usuario("martin", CLAVE, nombre="Martín")

    def _app(self, *, configurar: bool = True) -> AppTest:
        prueba = AppTest.from_file(str(Path(RAIZ) / "app.py"), default_timeout=90)
        prueba.secrets["acceso"] = {"usuario": "martin", "contrasena": CLAVE} if configurar else {}
        prueba.run()
        return prueba

    def test_sin_ingresar_no_se_ve_nada_de_la_cartera(self) -> None:
        prueba = self._app()
        self.assertFalse(prueba.exception, prueba.exception)
        texto = " ".join(
            bloque.value for bloque in list(prueba.markdown) + list(prueba.caption)
        )
        self.assertIn("Ingreso", texto)
        # Ni los títulos ni las cifras de la cartera aparecen.
        for prohibido in ("Total facturado", "Saldo pendiente", "Cartera manual"):
            self.assertNotIn(prohibido, texto, prohibido)
        # Y no hay tablas de datos renderizadas.
        self.assertEqual(len(prueba.dataframe), 0)

    def test_la_pantalla_de_ingreso_pide_usuario_y_contrasena(self) -> None:
        prueba = self._app()
        claves = {entrada.key for entrada in prueba.text_input}
        self.assertIn("ingreso_usuario", claves)
        self.assertIn("ingreso_clave", claves)

    def test_con_credenciales_correctas_entra_a_la_cartera(self) -> None:
        prueba = self._app()
        prueba.text_input(key="ingreso_usuario").set_value("martin")
        prueba.text_input(key="ingreso_clave").set_value(CLAVE)
        prueba.button[0].click()
        prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)
        texto = " ".join(
            bloque.value for bloque in list(prueba.markdown) + list(prueba.caption)
        )
        self.assertIn("Cartera", texto)

    def test_con_credenciales_incorrectas_no_entra_y_avisa(self) -> None:
        prueba = self._app()
        prueba.text_input(key="ingreso_usuario").set_value("martin")
        prueba.text_input(key="ingreso_clave").set_value("claveEquivocada")
        prueba.button[0].click()
        prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)
        errores = " ".join(bloque.value for bloque in prueba.error)
        self.assertIn("incorrect", errores.casefold())
        texto = " ".join(bloque.value for bloque in prueba.markdown)
        self.assertNotIn("Total facturado", texto)

    def test_la_contrasena_no_queda_guardada_en_la_sesion(self) -> None:
        prueba = self._app()
        prueba.text_input(key="ingreso_usuario").set_value("martin")
        prueba.text_input(key="ingreso_clave").set_value(CLAVE)
        prueba.button[0].click()
        prueba.run()
        valores = [str(v) for v in prueba.session_state.filtered_state.values()]
        self.assertFalse(
            any(CLAVE in valor for valor in valores),
            "la contraseña quedó en el estado de sesión",
        )

    def test_sin_secretos_muestra_ingreso_pendiente_sin_registro_publico(self) -> None:
        otro, ruta = _preparar_base()
        self.addCleanup(otro.cleanup)
        with patch.dict("os.environ", {"NOVASALUM_DB": str(ruta)}):
            prueba = self._app(configurar=False)
            self.assertFalse(prueba.exception, prueba.exception)
            self.assertIn("Secrets", " ".join(bloque.value for bloque in prueba.info))
            self.assertTrue(prueba.text_input(key="ingreso_usuario").disabled)
            self.assertTrue(prueba.text_input(key="ingreso_clave").disabled)
            self.assertTrue(prueba.button[0].disabled)
            self.assertFalse(prueba.code)

    def test_secretos_permiten_ingresar_sin_crear_una_cuenta_previamente(self) -> None:
        otro, ruta = _preparar_base()
        self.addCleanup(otro.cleanup)
        with patch.dict("os.environ", {"NOVASALUM_DB": str(ruta)}):
            prueba = self._app()
            self.assertFalse(prueba.text_input(key="ingreso_usuario").disabled)
            self.assertEqual([b.label for b in prueba.button], ["Entrar"])
            prueba.text_input(key="ingreso_usuario").set_value("martin")
            prueba.text_input(key="ingreso_clave").set_value(CLAVE)
            prueba.button[0].click().run()
            self.assertFalse(prueba.exception)
            self.assertEqual(prueba.session_state["usuario_sesion"].usuario, "martin")

    def test_cambiar_secrets_cierra_sesion_y_rechaza_la_clave_anterior(self) -> None:
        prueba = self._app()
        prueba.text_input(key="ingreso_usuario").set_value("martin")
        prueba.text_input(key="ingreso_clave").set_value(CLAVE)
        prueba.button[0].click().run()
        prueba.secrets["acceso"]["contrasena"] = "UnaClaveNueva2026"
        prueba.run()
        self.assertFalse(prueba.exception)
        self.assertTrue(prueba.text_input(key="ingreso_usuario"))
        prueba.text_input(key="ingreso_usuario").set_value("martin")
        prueba.text_input(key="ingreso_clave").set_value(CLAVE)
        prueba.button[0].click().run()
        self.assertTrue(prueba.error)
        prueba.text_input(key="ingreso_clave").set_value("UnaClaveNueva2026")
        prueba.button[0].click().run()
        self.assertFalse(prueba.exception)
        self.assertEqual(prueba.session_state["usuario_sesion"].usuario, "martin")


if __name__ == "__main__":
    unittest.main()
