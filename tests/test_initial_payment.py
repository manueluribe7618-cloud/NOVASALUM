"""Factura y abono inicial: ambos se guardan o ninguno se guarda."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database as db


class FacturaConAbonoInicialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "cartera.db"
        # Relativa al día real: un vencimiento a 30 días desde una fecha fija
        # se vuelve VENCIDA al pasar el calendario y tumba la prueba sola.
        self.emision = date.today()
        db.inicializar(self.ruta)

    def tearDown(self) -> None:
        self.temporal.cleanup()

    def datos_factura(self, numero: str = "100") -> dict:
        return {
            "empresa_codigo": "NOVASA",
            "prefijo": "FEBA",
            "numero": numero,
            "fecha": self.emision,
            "vencimiento": self.emision + timedelta(days=30),
            "cliente": "Cliente para digitación SAS",
            "descripcion": "Servicio registrado de forma manual",
            "placas": "ABC123",
            "subtotal_cop": 100_000,
            "iva_cop": 0,
            "retefuente_cop": 0,
            "ica_cop": 0,
        }

    def datos_abono(self, monto: int = 40_000) -> dict:
        return {
            "fecha": self.emision + timedelta(days=2),
            "referencia": "TRX-ABONO-INICIAL",
            "monto_cop": monto,
        }

    def conteos(self) -> tuple[int, int, int, int, int]:
        with sqlite3.connect(self.ruta) as conexion:
            return tuple(
                conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
                for tabla in (
                    "clientes",
                    "facturas_manual",
                    "abonos_manual",
                    "aplicaciones_abono",
                    "auditoria",
                )
            )

    def test_crear_factura_con_abono_parcial_actualiza_ambos_cuadros(self) -> None:
        factura_id = db.crear_factura_con_abono(
            self.datos_factura(), self.datos_abono(), self.ruta
        )

        factura = db.obtener_factura(factura_id, self.ruta)
        self.assertEqual(factura["total_cop"], 100_000)
        self.assertEqual(factura["abonos_cop"], 40_000)
        self.assertEqual(factura["saldo_cop"], 60_000)
        self.assertEqual(factura["estado"], "ABONADA")
        self.assertEqual(len(db.listar_facturas("NOVASA", ruta=self.ruta)), 1)
        self.assertEqual(db.clientes_con_saldo("NOVASA", self.ruta)[0]["saldo_cop"], 60_000)

        abonos = db.listar_abonos("NOVASA", self.ruta)
        self.assertEqual(len(abonos), 1)
        self.assertEqual(abonos[0]["monto_cop"], 40_000)
        self.assertEqual(abonos[0]["aplicado_cop"], 40_000)
        self.assertEqual(abonos[0]["saldo_a_favor_cop"], 0)
        self.assertEqual(abonos[0]["cliente"], "Cliente para digitación SAS")
        self.assertEqual(self.conteos(), (1, 1, 1, 1, 2))

        with sqlite3.connect(self.ruta) as conexion:
            aplicado = conexion.execute(
                "SELECT factura_id, monto_cop FROM aplicaciones_abono"
            ).fetchone()
            self.assertEqual(aplicado, (factura_id, 40_000))
            auditoria = conexion.execute(
                "SELECT entidad, accion FROM auditoria ORDER BY id"
            ).fetchall()
            self.assertEqual(
                auditoria,
                [("factura_manual", "CREADA"), ("abono_manual", "REGISTRADO")],
            )

    def test_abono_inicial_por_total_deja_factura_pagada(self) -> None:
        factura_id = db.crear_factura_con_abono(
            self.datos_factura("101"), self.datos_abono(100_000), self.ruta
        )
        factura = db.obtener_factura(factura_id, self.ruta)
        self.assertEqual(factura["saldo_cop"], 0)
        self.assertEqual(factura["estado"], "PAGADA")
        self.assertEqual(db.clientes_con_saldo("NOVASA", self.ruta), [])

    def test_abono_mayor_al_total_no_deja_factura_ni_cliente(self) -> None:
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura_con_abono(
                self.datos_factura("102"), self.datos_abono(100_001), self.ruta
            )
        self.assertEqual(self.conteos(), (0, 0, 0, 0, 0))

    def test_abono_inicial_en_cero_no_guarda_nada(self) -> None:
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura_con_abono(
                self.datos_factura("102A"), self.datos_abono(0), self.ruta
            )
        self.assertEqual(self.conteos(), (0, 0, 0, 0, 0))

    def test_limite_del_abono_es_total_con_descuento_no_subtotal(self) -> None:
        datos = self.datos_factura("102B")
        datos["descuento_cop"] = 20_000
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura_con_abono(datos, self.datos_abono(90_000), self.ruta)
        self.assertEqual(self.conteos(), (0, 0, 0, 0, 0))

        factura_id = db.crear_factura_con_abono(
            datos, self.datos_abono(80_000), self.ruta
        )
        self.assertEqual(db.obtener_factura(factura_id, self.ruta)["total_cop"], 80_000)
        self.assertEqual(db.obtener_factura(factura_id, self.ruta)["saldo_cop"], 0)

    def test_fecha_de_abono_invalida_no_guarda_nada(self) -> None:
        abono = self.datos_abono()
        abono["fecha"] = "fecha-no-valida"
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura_con_abono(self.datos_factura("103"), abono, self.ruta)
        self.assertEqual(self.conteos(), (0, 0, 0, 0, 0))

    def test_anticipo_anterior_a_emision_sin_referencia_se_acepta(self) -> None:
        abono = self.datos_abono()
        abono["fecha"] = self.emision - timedelta(days=1)
        abono["referencia"] = "  "
        factura_id = db.crear_factura_con_abono(
            self.datos_factura("104"), abono, self.ruta
        )
        self.assertEqual(db.obtener_factura(factura_id, self.ruta)["saldo_cop"], 60_000)
        self.assertEqual(db.listar_abonos("NOVASA", self.ruta)[0]["referencia"], "")

    def test_factura_duplicada_no_registra_abono_ni_cliente_nuevo(self) -> None:
        db.crear_factura(self.datos_factura("105"), self.ruta)
        anterior = self.conteos()
        datos = self.datos_factura("105")
        datos["cliente"] = "Otro cliente que no debe crearse SAS"

        with self.assertRaises(db.ErrorCartera):
            db.crear_factura_con_abono(datos, self.datos_abono(), self.ruta)

        self.assertEqual(self.conteos(), anterior)
        self.assertEqual(
            db.listar_nombres_clientes(self.ruta), ["Cliente para digitación SAS"]
        )
        self.assertEqual(db.listar_abonos("NOVASA", self.ruta), [])
        self.assertEqual(db.listar_facturas("NOVASA", ruta=self.ruta)[0]["saldo_cop"], 100_000)

    def test_fallo_despues_de_insertar_abono_revierte_toda_la_operacion(self) -> None:
        registrar_original = db._registrar

        def fallar_tras_auditar_abono(conexion, entidad, entidad_id, accion, detalle):
            registrar_original(conexion, entidad, entidad_id, accion, detalle)
            if entidad == "abono_manual":
                raise RuntimeError("Fallo simulado antes del commit")

        with patch.object(db, "_registrar", side_effect=fallar_tras_auditar_abono):
            with self.assertRaises(RuntimeError):
                db.crear_factura_con_abono(
                    self.datos_factura("105B"), self.datos_abono(), self.ruta
                )

        self.assertEqual(self.conteos(), (0, 0, 0, 0, 0))

    def test_flujo_original_de_factura_y_abono_sigue_disponible(self) -> None:
        factura_id = db.crear_factura(self.datos_factura("106"), self.ruta)
        factura = db.obtener_factura(factura_id, self.ruta)
        self.assertEqual(factura["saldo_cop"], 100_000)
        self.assertEqual(db.listar_abonos("NOVASA", self.ruta), [])
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=factura["cliente_id"],
            fecha=self.emision + timedelta(days=3),
            referencia="TRX-POSTERIOR",
            monto_cop=25_000,
            aplicaciones=[{"factura_id": factura_id, "monto_cop": 25_000}],
            ruta=self.ruta,
        )
        self.assertEqual(db.obtener_factura(factura_id, self.ruta)["saldo_cop"], 75_000)


if __name__ == "__main__":
    unittest.main()
