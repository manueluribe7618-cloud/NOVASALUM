"""La conexión con Supabase: la contraseña nunca se asoma y la URL no se rompe.

La pantalla de error de la conexión sale antes del ingreso, así que la ve
cualquiera que abra la aplicación. Ninguna prueba abre una conexión de red:
libpq se ejercita solo en su lectura de la URL.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from streamlit.testing.v1 import AppTest

from src import database as db


RAIZ = Path(__file__).resolve().parent.parent
CLAVES_RARAS = ("Secre@ta2026", "Se?cre/ta2026", "Mi clave#2026", "Cla%zz@ve2026")


def _url(clave: str, sufijo: str = "") -> str:
    return f"postgresql://postgres.abc:{clave}@pooler.supabase.com:6543/postgres{sufijo}"


class ContrasenaConCaracteresEspeciales(unittest.TestCase):
    def test_una_contrasena_sin_codificar_igual_conecta(self) -> None:
        for clave in CLAVES_RARAS:
            with self.subTest(clave=clave):
                url, separada = db._separar_clave(_url(clave))
                self.assertEqual(separada, clave)
                # Lo que psycopg le entrega a libpq al conectar.
                datos = conninfo_to_dict(make_conninfo(db._url_con_tls(url), password=separada))
                self.assertEqual(datos["password"], clave)
                self.assertEqual(datos["host"], "pooler.supabase.com")
                self.assertEqual(datos["port"], "6543")
                self.assertEqual(datos["user"], "postgres.abc")
                self.assertEqual(datos["dbname"], "postgres")

    def test_una_contrasena_ya_codificada_se_decodifica(self) -> None:
        _, separada = db._separar_clave(_url("Secre%40ta%3F2026"))
        self.assertEqual(separada, "Secre@ta?2026")

    def test_la_url_que_lee_libpq_no_lleva_ni_un_pedazo_de_la_contrasena(self) -> None:
        for clave in CLAVES_RARAS:
            url, _ = db._separar_clave(_url(clave))
            for inicio in range(len(clave) - 3):
                self.assertNotIn(clave[inicio:inicio + 4], url, clave)

    def test_una_url_sin_contrasena_queda_igual(self) -> None:
        for url in ("postgresql://postgres.abc@host:6543/postgres", "host=x dbname=y"):
            self.assertEqual(db._separar_clave(url), (url, None))

    def test_la_contrasena_viaja_aparte_al_conectar(self) -> None:
        conectar = MagicMock()
        with patch.dict("os.environ", {"SUPABASE_DB_URL": _url("Se?cre/ta@2026")}), \
             patch.object(db, "_CONEXION_PG", None), \
             patch.object(psycopg, "connect", conectar):
            db._conexion_pg()
        url = conectar.call_args.args[0]
        self.assertNotIn("ta@2026", url)
        self.assertEqual(conectar.call_args.kwargs["password"], "Se?cre/ta@2026")


class ErroresSinContrasena(unittest.TestCase):
    CLAVE = "Cla?ve/Oculta77"

    def _falla_al_conectar(self, error: Exception) -> str:
        with patch.dict("os.environ", {"SUPABASE_DB_URL": _url(self.CLAVE)}), \
             patch.object(db, "_CONEXION_PG", None), \
             patch.object(psycopg, "connect", side_effect=error):
            with self.assertRaises(db.ErrorCartera) as capturado:
                db._conexion_pg()
        self.assertTrue(capturado.exception.__suppress_context__)
        return str(capturado.exception)

    def test_un_error_de_formato_no_repite_la_url(self) -> None:
        mensaje = self._falla_al_conectar(psycopg.ProgrammingError(f'URI "{self.CLAVE}@host"'))
        self.assertNotIn("Oculta77", mensaje)
        self.assertIn("SUPABASE_DB_URL", mensaje)

    def test_un_error_de_conexion_oculta_la_contrasena(self) -> None:
        mensaje = self._falla_al_conectar(
            psycopg.OperationalError(f"failed for password '{self.CLAVE}': timeout expired")
        )
        self.assertNotIn("Oculta77", mensaje)
        self.assertIn("timeout expired", mensaje)


class PantallaAntesDelIngreso(unittest.TestCase):
    """Lo que ve un visitante sin cuenta cuando la base no responde."""

    def _app(self, url: str) -> AppTest:
        # patch.dict deshace también lo que app_shell copia de Secrets al entorno.
        with patch.dict("os.environ", {
            "SUPABASE_DB_URL": "", "NOVASALUM_DB": "", "NOVASALUM_EXIGE_NUBE": "",
        }), patch.object(db, "_CONEXION_PG", None):
            prueba = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=90)
            prueba.secrets["SUPABASE_DB_URL"] = url
            prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)
        return prueba

    @staticmethod
    def _texto(prueba: AppTest) -> str:
        return " ".join(b.value for b in list(prueba.error) + list(prueba.info) + list(prueba.markdown))

    def test_una_url_mal_escrita_no_muestra_la_contrasena(self) -> None:
        # El parámetro raro hace fallar la lectura de la URL sin abrir ningún socket.
        prueba = self._app(_url("Cla?ve/Oculta77", "?parametro_raro"))
        texto = self._texto(prueba)
        self.assertIn("No fue posible conectar", texto)
        self.assertNotIn("Oculta77", texto)

    def test_un_error_ajeno_solo_muestra_su_tipo(self) -> None:
        error = RuntimeError("failed to resolve host 'Oculta77@pooler.supabase.com'")
        with patch.object(db, "inicializar", side_effect=error):
            prueba = self._app(_url("Clave@Oculta77"))
        texto = self._texto(prueba)
        self.assertNotIn("Oculta77", texto)
        self.assertIn("RuntimeError", texto)


class CertificadoEnCarpetaConEspacios(unittest.TestCase):
    def test_la_ruta_del_certificado_se_codifica_en_la_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporal:
            certificado = Path(temporal) / "Mi Cartera #1 & 50%" / "certs" / "raíz ca.pem"
            certificado.parent.mkdir(parents=True)
            certificado.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
            with patch.object(db, "_CERTIFICADO_SUPABASE", certificado):
                datos = conninfo_to_dict(db._url_con_tls(_url("clave")))
        self.assertEqual(datos["sslrootcert"], str(certificado))
        self.assertEqual(datos["sslmode"], "verify-full")
        self.assertEqual(datos["host"], "pooler.supabase.com")


if __name__ == "__main__":
    unittest.main()
