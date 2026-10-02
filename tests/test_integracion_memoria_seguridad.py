"""Contrato conjunto de cartera manual, memoria de lecturas y conexión segura.

Las operaciones financieras usan únicamente SQLite temporal. Las conexiones
Postgres son dobles: ninguna prueba abre la base de Supabase ni la red.
"""

from __future__ import annotations

from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from psycopg.conninfo import conninfo_to_dict

from src import database as db
from src.formato import hoy_colombia


class OperacionesConMemoriaTests(unittest.TestCase):
    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = Path(temporal.name) / "cartera.db"
        self.hoy = hoy_colombia()
        db.invalidar_lecturas()
        self.addCleanup(db.invalidar_lecturas)

    def datos(self, numero: str, cliente: str = "Cliente original SAS") -> dict:
        return {
            "empresa_codigo": "NOVASA",
            "prefijo": "FEBA",
            "numero": numero,
            "fecha": self.hoy,
            "vencimiento": self.hoy + timedelta(days=30),
            "cliente": cliente,
            "subtotal_cop": 100_000,
            "iva_cop": 0,
            "retefuente_cop": 0,
            "ica_cop": 0,
        }

    def llenar_memoria(self) -> None:
        db.listar_facturas(ruta=self.ruta)
        db.listar_facturas("NOVASA", ruta=self.ruta)
        db.listar_facturas(incluir_anuladas=True, ruta=self.ruta)
        db.listar_nombres_clientes(ruta=self.ruta)
        db.resumen_actividad(ruta=self.ruta)

    def test_factura_con_abono_inicial_actualiza_cartera_clientes_y_actividad(self) -> None:
        self.llenar_memoria()

        factura_id = db.crear_factura_con_abono(
            self.datos("101"),
            {"monto_cop": 40_000, "fecha": self.hoy, "referencia": "RC-INICIAL"},
            self.ruta,
        )

        factura = db.obtener_factura(factura_id, self.ruta)
        self.assertEqual(factura["abonos_cop"], 40_000)
        self.assertEqual(factura["saldo_cop"], 60_000)
        self.assertEqual(factura["estado"], "ABONADA")
        self.assertEqual(db.listar_facturas("NOVASA", ruta=self.ruta), [factura])
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Cliente original SAS"])
        cliente = db.clientes_con_saldo("NOVASA", self.ruta)[0]
        self.assertEqual(cliente["saldo_cop"], 60_000)
        self.assertEqual(db.resumen_actividad(ruta=self.ruta)[0]["accion"], "REGISTRADO")

    def test_cambiar_cliente_se_ve_en_todos_los_listados_memorizados(self) -> None:
        factura_id = db.crear_factura(self.datos("102"), self.ruta)
        self.llenar_memoria()
        lista_anterior = db.listar_facturas(ruta=self.ruta)
        cliente_anterior = lista_anterior[0]["cliente_id"]

        db.actualizar_campos_factura(
            factura_id, self.datos("102", "Cliente corregido SAS"), self.ruta
        )

        for argumentos in ({}, {"empresa_codigo": "NOVASA"}, {"incluir_anuladas": True}):
            factura = db.listar_facturas(ruta=self.ruta, **argumentos)[0]
            self.assertEqual(factura["cliente"], "Cliente corregido SAS")
            self.assertNotEqual(factura["cliente_id"], cliente_anterior)
        self.assertIn("Cliente corregido SAS", db.listar_nombres_clientes(self.ruta))
        pendientes = db.clientes_con_saldo("NOVASA", self.ruta)
        self.assertEqual([cliente["cliente"] for cliente in pendientes], ["Cliente corregido SAS"])
        self.assertEqual(db.resumen_actividad(ruta=self.ruta)[0]["accion"], "ACTUALIZADA")
        self.assertEqual(lista_anterior[0]["cliente"], "Cliente original SAS")

    def test_una_previsualizacion_vieja_no_permite_abonar_mas_del_saldo_real(self) -> None:
        factura_id = db.crear_factura(self.datos("103"), self.ruta)
        pendientes = db.facturas_pendientes_cliente("NOVASA", 1, self.ruta)
        cliente_id = pendientes[0]["cliente_id"]
        # Representa un pago escrito por otro proceso, que no comparte memoria.
        with closing(sqlite3.connect(self.ruta)) as conexion:
            abono_id = conexion.execute(
                """
                INSERT INTO abonos_manual (
                    empresa_codigo, cliente_id, fecha, referencia, monto_cop,
                    saldo_a_favor_cop, creado_en
                ) VALUES ('NOVASA', ?, ?, 'OTRO-PROCESO', 40000, 0, ?)
                """,
                (cliente_id, self.hoy.isoformat(), self.hoy.isoformat()),
            ).lastrowid
            conexion.execute(
                """
                INSERT INTO aplicaciones_abono (abono_id, factura_id, monto_cop, creado_en)
                VALUES (?, ?, 40000, ?)
                """,
                (abono_id, factura_id, self.hoy.isoformat()),
            )
            conexion.commit()

        aplicaciones, _ = db.previsualizar_fifo(pendientes, 100_000)
        with self.assertRaisesRegex(db.ErrorCartera, "supera el saldo"):
            db.registrar_abono(
                empresa_codigo="NOVASA",
                cliente_id=cliente_id,
                fecha=self.hoy,
                referencia="PREVISUALIZACION-VIEJA",
                monto_cop=100_000,
                aplicaciones=aplicaciones,
                ruta=self.ruta,
            )

        self.assertEqual(len(db.listar_abonos("NOVASA", self.ruta)), 1)
        db.invalidar_lecturas()
        self.assertEqual(db.obtener_factura(factura_id, self.ruta)["saldo_cop"], 60_000)


class ReconectarSinExponerCredencialesTests(unittest.TestCase):
    CLAVE = "Sintetica@50%final"
    URL = "postgresql://postgres.prueba:Sintetica%4050%25final@pooler.example:6543/postgres"

    def setUp(self) -> None:
        for parche in (
            patch.dict("os.environ", {"SUPABASE_DB_URL": self.URL, "NOVASALUM_DB": ""}),
            patch.object(db, "_CONEXION_PG", None),
            patch.object(db, "_PG_RESPONDIO_EN", 99.0),
            patch.object(db.time, "monotonic", return_value=100.0),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    def test_una_conexion_reciente_se_reutiliza_sin_reconectar(self) -> None:
        vigente = MagicMock(closed=False)
        with patch.object(db, "_CONEXION_PG", vigente), patch.object(psycopg, "connect") as conectar:
            adaptador = db._conexion_pg()

        self.assertIs(adaptador._conexion, vigente)
        vigente.execute.assert_not_called()
        conectar.assert_not_called()

    def test_reconexion_tras_inactividad_separa_clave_y_conserva_tls(self) -> None:
        anterior = MagicMock(closed=False)
        anterior.execute.side_effect = psycopg.OperationalError("conexión cerrada")
        nueva = MagicMock(closed=False)
        with patch.object(db, "_CONEXION_PG", anterior), \
             patch.object(db, "_PG_RESPONDIO_EN", 0.0), \
             patch.object(psycopg, "connect", return_value=nueva) as conectar:
            adaptador = db._conexion_pg()

        anterior.execute.assert_called_once_with("SELECT 1")
        anterior.close.assert_called_once()
        self.assertIs(adaptador._conexion, nueva)
        url = conectar.call_args.args[0]
        self.assertNotIn("Sintetica", url)
        self.assertEqual(conectar.call_args.kwargs["password"], self.CLAVE)
        self.assertIsNone(conectar.call_args.kwargs["prepare_threshold"])
        opciones = conninfo_to_dict(url)
        self.assertEqual(opciones["sslmode"], "verify-full")
        self.assertIn("supabase-root-2021-ca.pem", opciones["sslrootcert"])

    def test_una_reconexion_fallida_no_repite_la_clave_en_el_error(self) -> None:
        anterior = MagicMock(closed=False)
        anterior.execute.side_effect = psycopg.OperationalError("conexión cerrada")
        for error in (
            psycopg.OperationalError(f"timeout con contraseña '{self.CLAVE}'"),
            psycopg.ProgrammingError(f"URI inválida: {self.URL}"),
        ):
            with self.subTest(tipo=type(error).__name__), \
                 patch.object(db, "_CONEXION_PG", anterior), \
                 patch.object(db, "_PG_RESPONDIO_EN", 0.0), \
                 patch.object(psycopg, "connect", side_effect=error):
                with self.assertRaises(db.ErrorCartera) as contexto:
                    db._conexion_pg()
            mensaje = str(contexto.exception)
            self.assertNotIn(self.CLAVE, mensaje)
            self.assertNotIn("Sintetica", mensaje)
            self.assertTrue(contexto.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
