"""El estado y la mora de una factura, que ninguna prueba producía.

El estado no se guarda: se deriva en cada lectura comparando el vencimiento
con el día de hoy y el saldo con los abonos. Nadie lo estaba comprobando, así
que un cambio en esa cadena de condiciones podía pasar inadvertido.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from src import database as db


class EstadoDerivadoDeCadaFactura(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        db.inicializar(self.ruta)
        self.hoy = date.today()

    def crear(self, numero: str, *, vence_en_dias: int, subtotal: int = 1_000_000) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": numero,
                # La emisión va siempre 30 días antes del vencimiento: es el
                # plazo que usa la casa y evita construir fechas imposibles.
                "fecha": self.hoy + timedelta(days=vence_en_dias - 30),
                "vencimiento": self.hoy + timedelta(days=vence_en_dias),
                "cliente": "Transportes Andinos SAS",
                "descripcion": "Servicio de transporte",
                "placas": "ABC123",
                "subtotal_cop": subtotal,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

    def leer(self, factura_id: int) -> dict:
        return db.obtener_factura(factura_id, self.ruta)

    def abonar(self, factura_id: int, monto: int) -> None:
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="TRX",
            monto_cop=monto,
            aplicaciones=[{"factura_id": factura_id, "monto_cop": monto}],
            ruta=self.ruta,
        )

    def test_sin_abonos_y_sin_vencer_es_pendiente(self) -> None:
        factura = self.leer(self.crear("1", vence_en_dias=30))
        self.assertEqual(factura["estado"], "PENDIENTE")
        self.assertEqual(factura["dias_mora"], 0)

    def test_con_abono_parcial_y_sin_vencer_es_abonada(self) -> None:
        factura_id = self.crear("2", vence_en_dias=30)
        self.abonar(factura_id, 400_000)
        factura = self.leer(factura_id)
        self.assertEqual(factura["estado"], "ABONADA")
        self.assertEqual(factura["saldo_cop"], 600_000)

    def test_pasado_el_vencimiento_con_saldo_es_vencida_y_cuenta_la_mora(self) -> None:
        factura = self.leer(self.crear("3", vence_en_dias=-45))
        self.assertEqual(factura["estado"], "VENCIDA")
        self.assertEqual(factura["dias_mora"], 45)

    def test_la_mora_se_cuenta_desde_el_vencimiento_no_desde_la_emision(self) -> None:
        # El dueño cobra por antigüedad de la mora, no por el plazo formal.
        factura = self.leer(self.crear("4", vence_en_dias=-1))
        self.assertEqual(factura["dias_mora"], 1)

    def test_una_factura_vencida_pero_abonada_sigue_vencida(self) -> None:
        factura_id = self.crear("5", vence_en_dias=-10)
        self.abonar(factura_id, 400_000)
        self.assertEqual(self.leer(factura_id)["estado"], "VENCIDA")

    def test_pagada_gana_sobre_vencida_y_apaga_la_mora(self) -> None:
        factura_id = self.crear("6", vence_en_dias=-90)
        self.abonar(factura_id, 1_000_000)
        factura = self.leer(factura_id)
        self.assertEqual(factura["estado"], "PAGADA")
        self.assertEqual(factura["saldo_cop"], 0)
        self.assertEqual(factura["dias_mora"], 0)

    def test_anulada_gana_sobre_cualquier_otro_estado(self) -> None:
        factura_id = self.crear("7", vence_en_dias=-90)
        db.anular_factura(factura_id, ruta=self.ruta)
        self.assertEqual(self.leer(factura_id)["estado"], "ANULADA")

    def test_no_se_puede_anular_una_factura_con_abonos(self) -> None:
        factura_id = self.crear("8", vence_en_dias=30)
        self.abonar(factura_id, 100_000)
        with self.assertRaises(db.ErrorCartera):
            db.anular_factura(factura_id, ruta=self.ruta)
        self.assertEqual(self.leer(factura_id)["estado"], "ABONADA")

    def test_no_se_puede_editar_una_factura_anulada(self) -> None:
        factura_id = self.crear("9", vence_en_dias=30)
        db.anular_factura(factura_id, ruta=self.ruta)
        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura_id, {"descripcion": "otro detalle"}, ruta=self.ruta
            )


class GuardasQueImpidenCruzarDinero(unittest.TestCase):
    """Un abono no puede saltar de cliente ni de empresa."""

    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        db.inicializar(self.ruta)
        self.hoy = date.today()
        self.factura_a = self._crear("NOVASA", "FEBA", "100", "Cliente A SAS")
        self.factura_b = self._crear("LUAC", "LUA", "200", "Cliente B SAS")

    def _crear(self, empresa: str, prefijo: str, numero: str, cliente: str) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": empresa,
                "prefijo": prefijo,
                "numero": numero,
                "fecha": self.hoy,
                "vencimiento": self.hoy + timedelta(days=30),
                "cliente": cliente,
                "descripcion": "Servicio",
                "placas": "",
                "subtotal_cop": 500_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

    def _cliente_id(self, factura_id: int) -> int:
        return int(db.obtener_factura(factura_id, self.ruta)["cliente_id"])

    def test_un_abono_no_se_aplica_a_la_factura_de_otro_cliente(self) -> None:
        with self.assertRaises(db.ErrorCartera):
            db.registrar_abono(
                empresa_codigo="NOVASA",
                cliente_id=self._cliente_id(self.factura_a),
                fecha=self.hoy,
                referencia="TRX",
                monto_cop=100_000,
                aplicaciones=[{"factura_id": self.factura_b, "monto_cop": 100_000}],
                ruta=self.ruta,
            )

    def test_el_cliente_debe_pertenecer_a_la_empresa_del_abono(self) -> None:
        with self.assertRaises(db.ErrorCartera):
            db.registrar_abono(
                empresa_codigo="MSU",
                cliente_id=self._cliente_id(self.factura_a),
                fecha=self.hoy,
                referencia="TRX",
                monto_cop=100_000,
                aplicaciones=[],
                ruta=self.ruta,
            )

    def test_no_se_puede_aplicar_mas_de_lo_recibido(self) -> None:
        with self.assertRaises(db.ErrorCartera):
            db.registrar_abono(
                empresa_codigo="NOVASA",
                cliente_id=self._cliente_id(self.factura_a),
                fecha=self.hoy,
                referencia="TRX",
                monto_cop=50_000,
                aplicaciones=[{"factura_id": self.factura_a, "monto_cop": 80_000}],
                ruta=self.ruta,
            )
        self.assertEqual(db.obtener_factura(self.factura_a, self.ruta)["saldo_cop"], 500_000)

    def test_el_excedente_queda_como_saldo_a_favor(self) -> None:
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=self._cliente_id(self.factura_a),
            fecha=self.hoy,
            referencia="TRX",
            monto_cop=700_000,
            aplicaciones=[{"factura_id": self.factura_a, "monto_cop": 500_000}],
            ruta=self.ruta,
        )
        abono = db.listar_abonos("NOVASA", ruta=self.ruta)[0]
        self.assertEqual(abono["saldo_a_favor_cop"], 200_000)
        self.assertEqual(db.obtener_factura(self.factura_a, self.ruta)["estado"], "PAGADA")


if __name__ == "__main__":
    unittest.main()
