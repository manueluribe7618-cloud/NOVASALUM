"""La pantalla de ingreso sobre la aplicación real.

Cubre lo que el dueño ve y lo que no debe ver: la tarjeta con sus campos y su
único botón, los avisos por campos vacíos, el mensaje genérico ante credenciales
incorrectas, el envío duplicado, el bloqueo por intentos y el cierre de sesión.
La autenticación y el bloqueo son los de ``src.autenticacion``; aquí se
comprueba que la pantalla los usa tal cual.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.proto.TextInput_pb2 import TextInput as TextInputProto
from streamlit.testing.v1 import AppTest

from src import autenticacion as auth
from src.ui import ingreso


RAIZ = Path(__file__).resolve().parent.parent
CLAVE = "MiClaveSegura123"


class PantallaDeIngresoTests(unittest.TestCase):
    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        # NOVASALUM_DB manda sobre la nube: la prueba nunca toca producción.
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(Path(temporal.name) / "cartera.db")})
        entorno.start()
        self.addCleanup(entorno.stop)
        auth.crear_usuario("martin", CLAVE, nombre="Martín")

    def _app(self) -> AppTest:
        prueba = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=90)
        prueba.secrets["acceso"] = {"usuario": "martin", "contrasena": CLAVE}
        prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)
        return prueba

    @staticmethod
    def _ingresar(prueba: AppTest, usuario: str, clave: str) -> AppTest:
        prueba.text_input(key="ingreso_usuario").set_value(usuario)
        prueba.text_input(key="ingreso_clave").set_value(clave)
        prueba.button[0].click().run()
        return prueba

    @staticmethod
    def _texto(prueba: AppTest) -> str:
        return " ".join(b.value for b in list(prueba.markdown) + list(prueba.caption))

    @staticmethod
    def _errores(prueba: AppTest) -> list[str]:
        return [b.value for b in prueba.error]

    @staticmethod
    def _fallos_registrados() -> int:
        return sum(1 for i in auth.intentos_recientes(horas=1) if not int(i["exitoso"]))

    def test_la_tarjeta_solo_tiene_lo_necesario_para_ingresar(self) -> None:
        prueba = self._app()
        texto = self._texto(prueba)
        for esperado in ("NOVASALUM", "Gestión de cartera empresarial", "Ingreso"):
            self.assertIn(esperado, texto)
        usuario = prueba.text_input(key="ingreso_usuario")
        clave = prueba.text_input(key="ingreso_clave")
        self.assertEqual((usuario.label, clave.label), ("Usuario", "Contraseña"))
        self.assertEqual(clave.proto.type, TextInputProto.PASSWORD)
        self.assertEqual([b.label for b in prueba.button], ["Ingresar"])
        self.assertFalse(prueba.button[0].disabled)
        # Ni selectores ni otras vías de acceso que no existen.
        self.assertEqual(len(prueba.selectbox) + len(prueba.radio) + len(prueba.checkbox), 0)
        for ajeno in ("Regístrate", "Google", "Olvidé", "Recuperar"):
            self.assertNotIn(ajeno, texto)
        # Nada de la cartera antes de ingresar.
        for prohibido in ("Total facturado", "Saldo pendiente", "Cartera manual"):
            self.assertNotIn(prohibido, texto)
        self.assertEqual(len(prueba.dataframe), 0)

    def test_los_campos_vacios_avisan_sin_registrar_intentos(self) -> None:
        prueba = self._app()
        casos = (
            ("", "", "Escribe tu usuario y tu contraseña."),
            ("martin", "", "Escribe tu contraseña."),
            ("   ", CLAVE, "Escribe tu usuario."),
        )
        for usuario, clave, aviso in casos:
            with self.subTest(usuario=usuario, clave=clave):
                self._ingresar(prueba, usuario, clave)
                self.assertFalse(prueba.exception, prueba.exception)
                self.assertEqual(self._errores(prueba), [aviso])
        self.assertEqual(self._fallos_registrados(), 0)
        self.assertNotIn("usuario_sesion", prueba.session_state)

    def test_usuario_inexistente_y_clave_incorrecta_dan_el_mismo_mensaje(self) -> None:
        con_usuario_falso = self._errores(self._ingresar(self._app(), "nadie", "ClaveCualquiera1"))
        con_clave_mala = self._errores(self._ingresar(self._app(), "martin", "ClaveEquivocada1"))
        self.assertEqual(con_usuario_falso, con_clave_mala)
        self.assertEqual(con_clave_mala, ["Usuario o contraseña incorrectos."])

    def test_un_envio_duplicado_cuenta_un_solo_intento(self) -> None:
        """Dos Enter seguidos con los mismos datos no gastan dos intentos."""

        prueba = self._ingresar(self._app(), "martin", "ClaveEquivocada1")
        self.assertEqual(self._errores(prueba), ["Usuario o contraseña incorrectos."])
        prueba.button[0].click().run()
        self.assertEqual(self._errores(prueba), ["Usuario o contraseña incorrectos."])
        self.assertEqual(self._fallos_registrados(), 1)
        # Otra contraseña sí es otro intento.
        self._ingresar(prueba, "martin", "ClaveEquivocada2")
        self.assertEqual(self._fallos_registrados(), 2)
        # Pasada la ventana, el mismo dato vuelve a verificarse.
        with patch.object(ingreso, "VENTANA_INTENTO_REPETIDO", 0.0):
            prueba.button[0].click().run()
        self.assertEqual(self._fallos_registrados(), 3)

    def test_tras_los_intentos_permitidos_la_cuenta_se_bloquea(self) -> None:
        prueba = self._app()
        for intento in range(1, auth.MAX_INTENTOS + 1):
            self._ingresar(prueba, "martin", f"ClaveEquivocada{intento}")
        self.assertIn("bloqueada", self._errores(prueba)[0])
        # Con la contraseña correcta tampoco entra mientras dure el bloqueo.
        self._ingresar(prueba, "martin", CLAVE)
        self.assertIn("bloqueada", self._errores(prueba)[0])
        self.assertNotIn("usuario_sesion", prueba.session_state)
        self.assertNotIn("Total facturado", self._texto(prueba))
        # Al desbloquear, el acceso vuelve. Son los mismos datos del intento
        # anterior: se deja pasar la ventana que frena los envíos duplicados.
        auth.desbloquear("martin")
        with patch.object(ingreso, "VENTANA_INTENTO_REPETIDO", 0.0):
            self._ingresar(prueba, "martin", CLAVE)
        self.assertFalse(prueba.exception, prueba.exception)
        self.assertEqual(prueba.session_state["usuario_sesion"].usuario, "martin")

    def test_el_ingreso_correcto_retira_la_tarjeta_y_muestra_la_cartera(self) -> None:
        prueba = self._ingresar(self._app(), "martin", CLAVE)
        self.assertFalse(prueba.exception, prueba.exception)
        self.assertEqual(self._errores(prueba), [])
        self.assertFalse([e for e in prueba.text_input if e.key == "ingreso_usuario"])
        self.assertIn("Cartera manual", self._texto(prueba))
        self.assertNotIn("ingreso_ultimo_intento", prueba.session_state)

    def test_cerrar_sesion_vuelve_a_la_pantalla_de_ingreso(self) -> None:
        prueba = self._ingresar(self._app(), "martin", CLAVE)
        prueba.sidebar.button(key="boton_salir").click().run()
        self.assertFalse(prueba.exception, prueba.exception)
        self.assertNotIn("usuario_sesion", prueba.session_state)
        self.assertTrue(prueba.text_input(key="ingreso_usuario"))
        self.assertEqual(prueba.text_input(key="ingreso_usuario").value, "")
        texto = self._texto(prueba)
        self.assertIn("Ingreso", texto)
        for prohibido in ("Total facturado", "Saldo pendiente", "Cartera manual"):
            self.assertNotIn(prohibido, texto)
        # Y se puede volver a entrar.
        self._ingresar(prueba, "martin", CLAVE)
        self.assertEqual(prueba.session_state["usuario_sesion"].usuario, "martin")


if __name__ == "__main__":
    unittest.main()
