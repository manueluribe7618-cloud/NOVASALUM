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
                "nit": "900000001-1",
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

    def test_editar_puede_actualizar_cliente_y_empresa_sin_abonos(self) -> None:
        factura = self.crear_factura("400", self.hoy, 100_000)

        db.actualizar_campos_factura(
            factura,
            {
                "empresa_codigo": "LUAC",
                "prefijo": "LUA",
                "numero": "400",
                "cliente": "Cliente actualizado SAS",
                "fecha": self.hoy,
                "vencimiento": self.hoy + timedelta(days=30),
                "descripcion": "Servicio actualizado",
                "placas": "XYZ789",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

        editada = db.obtener_factura(factura, self.ruta)
        self.assertEqual(editada["empresa_codigo"], "LUAC")
        self.assertEqual(editada["prefijo"], "LUA")
        self.assertEqual(editada["cliente"], "Cliente actualizado SAS")


if __name__ == "__main__":
    unittest.main()
