"""Las dos guardas que protegen los datos en el despliegue.

Ninguna toca la cartera: comprueban que la aplicación se niegue a trabajar en
condiciones donde perdería facturas o las transportaría sin verificar quién
está al otro lado.
"""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from src import app_shell
from src import database as db


class DetectarDiscoEfimero(unittest.TestCase):
    """Streamlit Cloud borra los archivos del contenedor en cada reinicio."""

    def test_en_un_equipo_normal_el_disco_no_es_efimero(self) -> None:
        with patch.dict("os.environ", {}, clear=False), \
             patch.object(Path, "is_dir", return_value=False):
            self.assertFalse(app_shell.disco_efimero())

    def test_el_montaje_de_streamlit_cloud_se_reconoce(self) -> None:
        with patch.object(Path, "is_dir", return_value=True):
            self.assertTrue(app_shell.disco_efimero())

    def test_cualquier_hospedaje_puede_declararlo_por_variable(self) -> None:
        for valor in ("1", "si", "sí", "true", "TRUE"):
            with self.subTest(valor=valor):
                with patch.dict("os.environ", {"NOVASALUM_EXIGE_NUBE": valor}), \
                     patch.object(Path, "is_dir", return_value=False):
                    self.assertTrue(app_shell.disco_efimero())

    def test_una_variable_vacia_o_apagada_no_lo_activa(self) -> None:
        for valor in ("", "0", "no", "false"):
            with self.subTest(valor=valor):
                with patch.dict("os.environ", {"NOVASALUM_EXIGE_NUBE": valor}), \
                     patch.object(Path, "is_dir", return_value=False):
                    self.assertFalse(app_shell.disco_efimero())


class TlsSinDegradacionSilenciosa(unittest.TestCase):
    """Sin el certificado raíz no se conecta: no se conecta a medias."""

    URL = "postgresql://usuario:clave@pooler.supabase.com:6543/postgres"

    def test_con_el_certificado_presente_se_verifica_el_servidor(self) -> None:
        resultado = db._url_con_tls(self.URL)
        self.assertIn("sslmode=verify-full", resultado)
        self.assertIn("sslrootcert=", resultado)

    def test_sin_el_certificado_se_levanta_un_error_en_vez_de_degradar(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            with self.assertRaises(db.ErrorCartera) as capturado:
                db._url_con_tls(self.URL)
        mensaje = str(capturado.exception)
        self.assertIn("certificado", mensaje.lower())
        # La regresión concreta: antes devolvía una URL con sslmode=require,
        # que cifra pero no comprueba la identidad del servidor.
        self.assertNotIn("sslmode=require", mensaje)

    def test_un_sslmode_elegido_a_proposito_se_respeta(self) -> None:
        elegida = f"{self.URL}?sslmode=verify-ca"
        self.assertEqual(db._url_con_tls(elegida), elegida)

    def test_el_certificado_esta_en_el_repositorio(self) -> None:
        certificado = Path("certs/supabase-root-2021-ca.pem")
        self.assertTrue(certificado.is_file(), "el certificado raíz debe viajar con el código")
        self.assertIn("BEGIN CERTIFICATE", certificado.read_text(encoding="utf-8"))


class PrecedenciaDelAlmacen(unittest.TestCase):
    """Señalar un archivo local siempre gana sobre la nube."""

    NUBE = "postgresql://usuario:clave@pooler.supabase.com:6543/postgres"

    def test_una_ruta_explicita_nunca_se_va_a_la_nube(self) -> None:
        with patch.dict("os.environ", {"SUPABASE_DB_URL": self.NUBE}):
            self.assertFalse(db._usa_postgres("/tmp/cualquier.db"))

    def test_la_variable_de_base_local_tambien_gana(self) -> None:
        with patch.dict(
            "os.environ",
            {"SUPABASE_DB_URL": self.NUBE, "NOVASALUM_DB": "/tmp/cualquier.db"},
        ):
            self.assertFalse(db._usa_postgres(None))

    def test_sin_senal_local_y_con_url_se_usa_la_nube(self) -> None:
        with patch.dict("os.environ", {"SUPABASE_DB_URL": self.NUBE}, clear=False):
            with patch.dict("os.environ", {"NOVASALUM_DB": ""}):
                self.assertTrue(db._usa_postgres(None))


if __name__ == "__main__":
    unittest.main()
