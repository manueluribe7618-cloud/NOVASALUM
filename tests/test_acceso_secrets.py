"""Secrets es la autoridad del ingreso; la base solo registra la vigilancia."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import autenticacion as auth
from src import database as db


CLAVE = "UnaClavePrivada2026"


class AccesoSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = Path(temporal.name) / "acceso.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(self.ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        self.credencial = auth.credencial_desde_secretos({
            "acceso": {"usuario": "finanzas", "contrasena": CLAVE},
        })

    def test_rechaza_configuracion_incompleta_sin_clave_predeterminada(self) -> None:
        for secretos in ({}, {"acceso": {}}, {"acceso": "incorrecto"},
                         {"acceso": {"usuario": "finanzas", "contrasena": ""}},
                         {"acceso": {"usuario": "CAMBIA_USUARIO", "contrasena": "CAMBIA_CLAVE"}}):
            with self.assertRaises(auth.ErrorAcceso):
                auth.credencial_desde_secretos(secretos)

    def test_ingresa_sin_registro_previo_y_no_copia_la_clave_a_la_base(self) -> None:
        self.assertFalse(auth.hay_usuarios())
        identidad = auth.autenticar("FINANZAS", CLAVE, credencial=self.credencial)
        self.assertTrue(identidad.es_admin)
        with db._lectura(self.ruta) as conexion:
            datos = dict(conexion.execute("SELECT * FROM usuarios").fetchone())
        self.assertEqual(datos["clave_hash"], "gestionado_en_streamlit")
        self.assertNotIn(CLAVE, str(datos))
        self.assertNotIn(CLAVE, repr(self.credencial))
        self.assertEqual(auth.intentos_recientes()[0]["motivo"], "OK")

    def test_cuentas_antiguas_no_pueden_saltarse_la_configuracion(self) -> None:
        auth.crear_usuario("cuenta_anterior", CLAVE)
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("cuenta_anterior", CLAVE, credencial=self.credencial)

    def test_una_clave_antigua_del_mismo_usuario_no_se_acepta(self) -> None:
        auth.crear_usuario("finanzas", "ClaveAnterior2025")
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("finanzas", "ClaveAnterior2025", credencial=self.credencial)
        self.assertEqual(auth.autenticar("finanzas", CLAVE, credencial=self.credencial).usuario, "finanzas")

    def test_cambio_de_secrets_revoca_el_ingreso_con_la_clave_anterior(self) -> None:
        nueva = auth.credencial_desde_secretos({
            "acceso": {"usuario": "finanzas", "contrasena": "ClaveReemplazada2027"},
        })
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("finanzas", CLAVE, credencial=nueva)
        self.assertTrue(auth.autenticar("finanzas", "ClaveReemplazada2027", credencial=nueva).es_admin)
        self.assertNotEqual(nueva.revision, self.credencial.revision)

    def test_bloqueo_y_reporte_se_conservan_con_secrets(self) -> None:
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("finanzas", "Incorrecta", credencial=self.credencial)
        with self.assertRaisesRegex(auth.ErrorAcceso, "bloqueada"):
            auth.autenticar("finanzas", CLAVE, credencial=self.credencial)
        self.assertTrue(auth.resumen_seguridad()["alerta"])
        auth.desbloquear("finanzas")
        self.assertTrue(auth.autenticar("finanzas", CLAVE, credencial=self.credencial).es_admin)


if __name__ == "__main__":
    unittest.main()
