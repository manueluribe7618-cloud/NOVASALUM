"""Pruebas de las reglas que no pueden fallar en la cartera manual."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from src import database as db


class CarteraManualTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "cartera.db"
        self.hoy = date(2026, 9, 9)
        db.inicializar(self.ruta)

    def tearDown(self) -> None:
        self.temporal.cleanup()

    def crear_factura(self, numero: str, fecha: date, subtotal: int = 100_000) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": numero,
                "fecha": fecha,
                "vencimiento": fecha + timedelta(days=30),
                "cliente": "Cliente de prueba SAS",
                "descripcion": "Servicio de prueba",
                "placas": "ABC123",
                "subtotal_cop": subtotal,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

    def test_fifo_aplica_primero_la_factura_mas_antigua(self) -> None:
        primera = self.crear_factura("100", self.hoy - timedelta(days=12), 100_000)
        segunda = self.crear_factura("101", self.hoy - timedelta(days=3), 100_000)
        pendientes = db.facturas_pendientes_cliente("NOVASA", 1, self.ruta)

        aplicaciones, sobrante = db.previsualizar_fifo(pendientes, 150_000)

        self.assertEqual(sobrante, 0)
        self.assertEqual(
            aplicaciones,
            [
                {"factura_id": primera, "monto_cop": 100_000},
                {"factura_id": segunda, "monto_cop": 50_000},
            ],
        )
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="TRX-1",
            monto_cop=150_000,
            aplicaciones=aplicaciones,
            ruta=self.ruta,
        )
        facturas = db.listar_facturas("NOVASA", ruta=self.ruta)
        self.assertEqual([fila["saldo_cop"] for fila in facturas], [0, 50_000])
        self.assertEqual([fila["estado"] for fila in facturas], ["PAGADA", "ABONADA"])

    def test_no_permite_aplicar_mas_del_saldo_real(self) -> None:
        factura = self.crear_factura("200", self.hoy, 90_000)
        with self.assertRaises(db.ErrorCartera):
            db.registrar_abono(
                empresa_codigo="NOVASA",
                cliente_id=1,
                fecha=self.hoy,
                referencia="TRX-2",
                monto_cop=100_000,
                aplicaciones=[{"factura_id": factura, "monto_cop": 100_000}],
                ruta=self.ruta,
            )
        self.assertEqual(db.listar_abonos("NOVASA", self.ruta), [])
        self.assertEqual(db.obtener_factura(factura, self.ruta)["saldo_cop"], 90_000)

    def test_no_permite_reducir_factura_por_debajo_de_abonos(self) -> None:
        factura = self.crear_factura("300", self.hoy, 100_000)
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="TRX-3",
            monto_cop=70_000,
            aplicaciones=[{"factura_id": factura, "monto_cop": 70_000}],
            ruta=self.ruta,
        )
        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura,
                {
                    "descripcion": "Editada",
                    "placas": "ABC123",
                    "subtotal_cop": 60_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                },
                self.ruta,
            )
        self.assertEqual(db.obtener_factura(factura, self.ruta)["saldo_cop"], 30_000)

    def test_editar_corrige_numero_y_fechas(self) -> None:
        factura = self.crear_factura("700", self.hoy)
        nueva_fecha = self.hoy - timedelta(days=5)
        nuevo_vencimiento = self.hoy + timedelta(days=45)

        db.actualizar_campos_factura(
            factura,
            {
                "numero": "701",
                "fecha": nueva_fecha,
                "vencimiento": nuevo_vencimiento,
                "descripcion": "Servicio de prueba",
                "placas": "ABC123",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

        editada = db.obtener_factura(factura, self.ruta)
        self.assertEqual(editada["factura"], "FEBA701")
        self.assertEqual(editada["fecha"], nueva_fecha.isoformat())
        self.assertEqual(editada["vencimiento"], nuevo_vencimiento.isoformat())

    def test_editar_sin_numero_ni_fechas_conserva_los_guardados(self) -> None:
        factura = self.crear_factura("710", self.hoy)

        db.actualizar_campos_factura(
            factura,
            {
                "descripcion": "Solo cambia el detalle",
                "placas": "ABC123",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

        editada = db.obtener_factura(factura, self.ruta)
        self.assertEqual(editada["factura"], "FEBA710")
        self.assertEqual(editada["fecha"], self.hoy.isoformat())
        self.assertEqual(
            editada["vencimiento"], (self.hoy + timedelta(days=30)).isoformat()
        )

    def test_editar_rechaza_numero_repetido_en_la_misma_empresa(self) -> None:
        self.crear_factura("720", self.hoy)
        factura = self.crear_factura("721", self.hoy)

        with self.assertRaises(db.ErrorCartera) as contexto:
            db.actualizar_campos_factura(
                factura,
                {
                    "numero": "720",
                    "descripcion": "Duplicada",
                    "placas": "ABC123",
                    "subtotal_cop": 100_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                },
                self.ruta,
            )
        self.assertIn("ya existe", str(contexto.exception))
        self.assertEqual(db.obtener_factura(factura, self.ruta)["factura"], "FEBA721")

    def test_editar_rechaza_vencimiento_anterior_a_la_emision(self) -> None:
        factura = self.crear_factura("730", self.hoy)

        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura,
                {
                    "fecha": self.hoy,
                    "vencimiento": self.hoy - timedelta(days=1),
                    "descripcion": "Fechas invertidas",
                    "placas": "ABC123",
                    "subtotal_cop": 100_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                },
                self.ruta,
            )

    def test_factura_manual_no_registra_nit(self) -> None:
        factura = self.crear_factura("400", self.hoy)

        self.assertEqual(db.obtener_factura(factura, self.ruta)["nit"], "")

    def test_sugerencias_incluyen_clientes_pagados_y_no_repiten_razones_sociales(self) -> None:
        factura = self.crear_factura("500", self.hoy)
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="PAGO-TOTAL",
            monto_cop=100_000,
            aplicaciones=[{"factura_id": factura, "monto_cop": 100_000}],
            ruta=self.ruta,
        )
        self.assertEqual(db.clientes_con_saldo("NOVASA", self.ruta), [])
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Cliente de prueba SAS"])
        datos = dict(db.obtener_factura(factura, self.ruta))
        datos.update(empresa_codigo="LUAC", prefijo="LUA", numero="500")
        db.crear_factura(datos, self.ruta)
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Cliente de prueba SAS"])
        datos.update(numero="501", cliente="Alimentos de prueba SAS")
        db.crear_factura(datos, self.ruta)
        self.assertEqual(
            db.listar_nombres_clientes(self.ruta),
            ["Alimentos de prueba SAS", "Cliente de prueba SAS"],
        )


if __name__ == "__main__":
    unittest.main()
