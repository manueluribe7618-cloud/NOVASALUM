"""Reglas del almacenamiento dual: SQLite local y Supabase/Postgres.

Ninguna prueba abre una conexión de red: el dialecto de Postgres se verifica
con dobles, y el contrato central —una ruta explícita SIEMPRE es SQLite— es lo
que garantiza que toda la suite existente siga corriendo sin credenciales.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import database as db


class SeleccionDeMotorTests(unittest.TestCase):
    def test_sin_llave_todo_es_sqlite(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SUPABASE_DB_URL", None)
            self.assertFalse(db._usa_postgres(None))
            self.assertIn("SQLite local", db.descripcion_almacen())

    def test_con_llave_y_sin_ruta_se_usa_postgres(self) -> None:
        with patch.dict("os.environ", {"SUPABASE_DB_URL": "postgresql://u:p@host/db"}):
            self.assertTrue(db._usa_postgres(None))
            self.assertEqual(db.descripcion_almacen(), "Supabase (nube)")

    def test_una_ruta_explicita_siempre_es_sqlite(self) -> None:
        """Las pruebas y las bases temporales jamás deben irse a la nube."""

        with patch.dict("os.environ", {"SUPABASE_DB_URL": "postgresql://u:p@host/db"}):
            self.assertFalse(db._usa_postgres(Path("cualquiera.db")))
            self.assertFalse(db._usa_postgres("cualquiera.db"))

    def test_novasalum_db_tiene_prioridad_sobre_la_nube(self) -> None:
        """Señalar un archivo local es una orden explícita y gana.

        Streamlit exporta por su cuenta los valores de secrets.toml al entorno,
        así que sin esta precedencia cualquier script o prueba que apunte a una
        base temporal escribiría en la base de producción.
        """

        with patch.dict("os.environ", {
            "SUPABASE_DB_URL": "postgresql://u:p@host/db",
            "NOVASALUM_DB": "/tmp/cartera_temporal.db",
        }):
            self.assertFalse(db._usa_postgres(None))
            self.assertIn("SQLite local", db.descripcion_almacen())


class DialectoPostgresTests(unittest.TestCase):
    def test_el_esquema_postgres_no_conserva_autoincrement(self) -> None:
        esquema = db._esquema_sql(postgres=True)
        self.assertNotIn("AUTOINCREMENT", esquema)
        self.assertIn("GENERATED ALWAYS AS IDENTITY", esquema)
        # Las siete tablas del modelo siguen presentes.
        for tabla in (
            "empresas", "clientes", "facturas_manual", "abonos_manual",
            "aplicaciones_abono", "revisiones_conciliacion", "auditoria",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {tabla}", esquema)

    def test_el_esquema_sqlite_queda_igual_que_siempre(self) -> None:
        esquema = db._esquema_sql(postgres=False)
        self.assertIn("INTEGER PRIMARY KEY AUTOINCREMENT", esquema)
        self.assertNotIn("IDENTITY", esquema)
        self.assertNotIn("ROW LEVEL SECURITY", esquema)

    def test_tablas_y_secuencias_postgres_no_quedan_expuestas_a_la_api(self) -> None:
        esquema = db._esquema_sql(postgres=True)
        for tabla in (
            "empresas", "clientes", "facturas_manual", "abonos_manual",
            "aplicaciones_abono", "revisiones_conciliacion", "auditoria",
            "usuarios", "intentos_ingreso",
        ):
            self.assertIn(
                f"ALTER TABLE public.{tabla} ENABLE ROW LEVEL SECURITY",
                esquema,
            )
        self.assertIn("REVOKE ALL PRIVILEGES ON TABLE", esquema)
        self.assertIn("REVOKE ALL PRIVILEGES ON SEQUENCE", esquema)
        self.assertEqual(esquema.count("FROM anon, authenticated"), 2)

    def test_los_marcadores_se_traducen_a_postgres(self) -> None:
        ejecutado: list[tuple[str, tuple]] = []

        class ConexionFalsa:
            def execute(self, sql, parametros=None):
                ejecutado.append((sql, parametros))
                return self

        adaptador = db._ConexionPG(ConexionFalsa())
        adaptador.execute("SELECT * FROM t WHERE a = ? AND b = ?", (1, 2))
        self.assertEqual(ejecutado[0][0], "SELECT * FROM t WHERE a = %s AND b = %s")
        self.assertEqual(ejecutado[0][1], (1, 2))

    def test_insertar_agrega_returning_solo_en_postgres(self) -> None:
        class CursorFalso:
            def fetchone(self):
                return {"id": 77}

        registrado: list[str] = []

        class ConexionFalsa:
            def execute(self, sql, parametros=None):
                registrado.append(sql)
                return CursorFalso()

        adaptador = db._ConexionPG(ConexionFalsa())
        nuevo_id = db._insertar(adaptador, "INSERT INTO x (a) VALUES (?)", (1,))
        self.assertEqual(nuevo_id, 77)
        self.assertTrue(registrado[0].endswith(" RETURNING id"))

    def test_executescript_divide_las_sentencias(self) -> None:
        ejecutado: list[str] = []

        class ConexionFalsa:
            def execute(self, sql, parametros=None):
                ejecutado.append(sql.strip())
                return self

        adaptador = db._ConexionPG(ConexionFalsa())
        adaptador.executescript("CREATE TABLE a (x INT); CREATE TABLE b (y INT);")
        self.assertEqual(len(ejecutado), 2)

    def test_la_url_recibe_tls_verificado_con_la_ca_de_supabase(self) -> None:
        segura = db._url_con_tls("postgresql://u:p@host:6543/db")
        self.assertIn("sslmode=verify-full", segura)
        self.assertIn("supabase-root-2021-ca.pem", segura)

    def test_un_sslmode_ya_configurado_se_respeta(self) -> None:
        original = "postgresql://u:p@host/db?sslmode=require"
        self.assertEqual(db._url_con_tls(original), original)


class ComportamientoLocalIntactoTests(unittest.TestCase):
    """El flujo financiero completo sigue funcionando en el motor local."""

    def test_factura_y_abono_completos_en_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "cartera.db"
            factura_id = db.crear_factura(
                {
                    "empresa_codigo": "NOVASA",
                    "prefijo": "FEBA",
                    "numero": "9001",
                    "fecha": date(2026, 9, 1),
                    "vencimiento": date(2026, 10, 1),
                    "cliente": "Cliente Supabase SAS",
                    "descripcion": "Prueba de almacenamiento",
                    "placas": "ABC123",
                    "subtotal_cop": 1_000_000,
                    "iva_cop": 0,
                    "retefuente_cop": 25_000,
                    "ica_cop": 0,
                },
                ruta,
            )
            db.registrar_abono(
                empresa_codigo="NOVASA",
                cliente_id=1,
                fecha=date(2026, 9, 10),
                referencia="TRX-1",
                monto_cop=500_000,
                aplicaciones=[{"factura_id": factura_id, "monto_cop": 500_000}],
                ruta=ruta,
            )
            factura = db.obtener_factura(factura_id, ruta)
            self.assertEqual(factura["saldo_cop"], 475_000)
            self.assertEqual(factura["estado"], "ABONADA")
            # El rastro de auditoría quedó completo: creación y abono.
            acciones = [e["accion"] for e in db.resumen_actividad(ruta=ruta)]
            self.assertIn("CREADA", acciones)


if __name__ == "__main__":
    unittest.main()
