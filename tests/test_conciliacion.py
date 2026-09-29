"""Pruebas del cruce entre la cartera manual y la lectura de Siigo.

La vista tenía 292 líneas sin una sola prueba, y es la que decide si una
factura está cuadrada o descuadrada. Aquí se fija el comportamiento de
``_build_reconciliation``, que es aritmética pura y no necesita Streamlit.

La prueba central es la del dato ausente: antes, una factura sin dato en
Siigo se comparaba contra un cero y podía salir CUADRADA sin que nadie
hubiera verificado nada.
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.views.conciliacion import _build_reconciliation, _entero_o_desconocido


def factura_manual(**cambios):
    """Una fila de la cartera manual, con los campos que usa la conciliación."""

    fila = {
        "empresa_codigo": "NOVASA",
        "factura": "FEBA2050",
        "cliente": "TMP IZAJES Y TRANSPORTES S.A.S",
        "subtotal_cop": 1_000_000,
        "iva_cop": 190_000,
        "retefuente_cop": 25_000,
        "ica_cop": 4_140,
        "descuento_cop": 0,
        "saldo_cop": 1_160_860,
        "fecha": "2026-09-01",
        "descripcion": "Servicio de transporte",
    }
    fila.update(cambios)
    return fila


def facturas_siigo(*filas):
    """Construye el DataFrame que entrega la lectura de Siigo."""

    base = {
        "empresa_codigo": "NOVASA",
        "factura": "FEBA2050",
        "cliente": "TMP IZAJES Y TRANSPORTES S.A.S",
        "subtotal_siigo": 1_000_000,
        "iva_siigo": 190_000,
        "retefuente_siigo": 25_000,
        "reteica_siigo": 4_140,
        "descuento_siigo": 0,
        "saldo_siigo": 1_160_860,
        "fecha": "2026-09-01",
        "descripcion_siigo": "Servicio de transporte",
    }
    return pd.DataFrame([{**base, **fila} for fila in filas])


class ConversionDeValores(unittest.TestCase):
    """Un dato ausente vale «no se sabe», nunca cero."""

    def test_los_valores_ausentes_no_se_convierten_en_cero(self):
        for ausente in (None, "", float("nan"), pd.NA, "no es un número"):
            with self.subTest(ausente=repr(ausente)):
                self.assertIsNone(_entero_o_desconocido(ausente))

    def test_los_valores_presentes_se_leen_como_pesos_enteros(self):
        self.assertEqual(_entero_o_desconocido(0), 0)
        self.assertEqual(_entero_o_desconocido("1234"), 1234)
        self.assertEqual(_entero_o_desconocido(1234.6), 1235)
        self.assertEqual(_entero_o_desconocido(-500), -500)


class CruceDeCarteras(unittest.TestCase):
    def estado(self, manual, siigo):
        filas = _build_reconciliation(manual, siigo)
        self.assertEqual(len(filas), 1, "se esperaba una sola factura cruzada")
        return filas[0]

    def test_valores_identicos_cuadran(self):
        fila = self.estado([factura_manual()], facturas_siigo({}))
        self.assertEqual(fila["estado"], "CUADRADO")
        self.assertEqual(fila["dif_saldo"], 0)
        self.assertEqual(fila["dif_descuento"], 0)

    def test_un_peso_de_diferencia_se_tolera(self):
        fila = self.estado(
            [factura_manual(saldo_cop=1_160_861)], facturas_siigo({})
        )
        self.assertEqual(fila["estado"], "CUADRADO")

    def test_dos_pesos_de_diferencia_en_el_saldo_son_descuadre(self):
        fila = self.estado(
            [factura_manual(saldo_cop=1_160_862)], facturas_siigo({})
        )
        self.assertEqual(fila["estado"], "DESCUADRE")
        self.assertEqual(fila["dif_saldo"], 2)

    def test_saldo_igual_pero_impuesto_distinto_es_diferencia_de_impuestos(self):
        fila = self.estado(
            [factura_manual(iva_cop=180_000)], facturas_siigo({})
        )
        self.assertEqual(fila["estado"], "DIFERENCIA_IMPUESTOS")
        self.assertEqual(fila["dif_iva"], -10_000)

    def test_el_descuento_distinto_se_detecta_y_se_reporta(self):
        # Antes el descuento no se comparaba: esta factura salía CUADRADA.
        fila = self.estado(
            [factura_manual(descuento_cop=1_400)], facturas_siigo({})
        )
        self.assertEqual(fila["estado"], "DIFERENCIA_IMPUESTOS")
        self.assertEqual(fila["dif_descuento"], 1_400)


class DatosQueSiigoNoEntrego(unittest.TestCase):
    """El caso que producía cuadres inventados."""

    def test_un_saldo_ausente_no_se_declara_cuadrado(self):
        # Manual en cero contra Siigo sin dato: la resta daba 0 y la factura
        # aparecía CUADRADA sin que nadie hubiera comparado nada.
        filas = _build_reconciliation(
            [factura_manual(saldo_cop=0)],
            facturas_siigo({"saldo_siigo": None}),
        )
        self.assertEqual(filas[0]["estado"], "DATO_INCOMPLETO")
        self.assertIsNone(filas[0]["dif_saldo"])

    def test_un_impuesto_ausente_no_se_declara_cuadrado(self):
        filas = _build_reconciliation(
            [factura_manual(ica_cop=0)],
            facturas_siigo({"reteica_siigo": float("nan")}),
        )
        self.assertEqual(filas[0]["estado"], "DATO_INCOMPLETO")
        self.assertIsNone(filas[0]["dif_ica"])

    def test_los_conceptos_si_entregados_conservan_su_diferencia(self):
        filas = _build_reconciliation(
            [factura_manual(iva_cop=200_000)],
            facturas_siigo({"descuento_siigo": None}),
        )
        fila = filas[0]
        self.assertEqual(fila["estado"], "DATO_INCOMPLETO")
        self.assertEqual(fila["dif_iva"], 10_000)
        self.assertIsNone(fila["dif_descuento"])

    def test_un_saldo_ausente_tampoco_se_declara_descuadre(self):
        filas = _build_reconciliation(
            [factura_manual(saldo_cop=1_160_860)],
            facturas_siigo({"saldo_siigo": None}),
        )
        self.assertEqual(filas[0]["estado"], "DATO_INCOMPLETO")


class FacturasEnUnaSolaFuente(unittest.TestCase):
    def test_solo_en_la_cartera_manual(self):
        filas = _build_reconciliation([factura_manual()], pd.DataFrame())
        self.assertEqual(filas[0]["estado"], "SOLO_MANUAL")
        self.assertIsNone(filas[0]["dif_saldo"])
        self.assertIsNone(filas[0]["dif_descuento"])

    def test_solo_en_la_lectura_de_siigo(self):
        filas = _build_reconciliation([], facturas_siigo({}))
        self.assertEqual(filas[0]["estado"], "SOLO_SIIGO")
        self.assertIsNone(filas[0]["dif_saldo"])

    def test_el_mismo_numero_en_dos_empresas_no_se_confunde(self):
        # FEBA2050 de NOVASA y LUA2050 de LUAC son facturas distintas.
        filas = _build_reconciliation(
            [factura_manual(), factura_manual(empresa_codigo="LUAC", factura="LUA2050")],
            facturas_siigo({}),
        )
        estados = {
            (fila["empresa_codigo"], fila["estado"]) for fila in filas
        }
        self.assertIn(("NOVASA", "CUADRADO"), estados)
        self.assertIn(("LUAC", "SOLO_MANUAL"), estados)


class FacturasAnuladas(unittest.TestCase):
    def test_anulada_en_siigo_y_viva_en_la_manual_no_cuadra(self):
        # MSU649: Siigo la anuló con su saldo original; antes salía CUADRADA.
        filas = _build_reconciliation(
            [factura_manual()], facturas_siigo({"estado_siigo": "ANULADA"})
        )
        self.assertEqual(filas[0]["estado"], "ANULADA_EN_UNA_FUENTE")
        self.assertIsNone(filas[0]["dif_saldo"])

    def test_anulada_en_la_manual_y_viva_en_siigo_no_es_solo_siigo(self):
        # LUA1739: antes la manual anulada ni se leía y salía «Solo Siigo».
        filas = _build_reconciliation(
            [factura_manual(estado="ANULADA", anulada=1)], facturas_siigo({"estado_siigo": "VENCIDA"})
        )
        self.assertEqual(filas[0]["estado"], "ANULADA_EN_UNA_FUENTE")

    def test_anulada_en_las_dos_fuentes_no_se_lista(self):
        filas = _build_reconciliation(
            [factura_manual(estado="ANULADA", anulada=1)],
            facturas_siigo({"estado_siigo": "ANULADA"}),
        )
        self.assertEqual(filas, [])

    def test_el_estado_nuevo_tiene_etiqueta(self):
        from src.ui.components import ESTADO_META

        for estado in ("ANULADA_EN_UNA_FUENTE", "OTRA_MONEDA"):
            self.assertIn(estado, ESTADO_META)


class FacturasEnOtraMoneda(unittest.TestCase):
    def test_dolares_no_se_comparan_contra_pesos(self):
        # MSU650: US$ 2.000 en Siigo contra $ 2.000 en la manual salía CUADRADA.
        filas = _build_reconciliation(
            [factura_manual(saldo_cop=2_000)],
            facturas_siigo({"moneda": "USD", "saldo_siigo": 2_000}),
        )
        self.assertEqual(filas[0]["estado"], "OTRA_MONEDA")
        for clave in ("dif_saldo", "dif_iva", "dif_retefuente", "dif_ica", "dif_descuento"):
            self.assertIsNone(filas[0][clave], clave)


class AlcanceDeLaLectura(unittest.TestCase):
    """Solo se compara lo que Siigo alcanzó a consultar."""

    def setUp(self):
        import datetime as dt

        from src.siigo_lectura import ParametrosLectura

        self.parametros = ParametrosLectura(
            ("NOVASA",), dt.date(2026, 9, 1), dt.date(2026, 9, 29)
        )

    def consultadas(self, manual, siigo=None, errores=None, parametros="por_defecto"):
        from src.views.conciliacion import _manual_consultado

        parametros = self.parametros if parametros == "por_defecto" else parametros
        filas, _ = _manual_consultado(
            manual, siigo if siigo is not None else pd.DataFrame(), parametros, errores or {}
        )
        return [fila["factura"] for fila in filas]

    def test_otro_periodo_u_otra_empresa_no_se_comparan(self):
        manual = [
            factura_manual(factura="FEBA1001", fecha="2026-09-01"),
            factura_manual(factura="FEBA900", fecha="2026-08-27"),
            factura_manual(empresa_codigo="LUAC", factura="LUA50", fecha="2026-09-01"),
        ]
        self.assertEqual(self.consultadas(manual), ["FEBA1001"])

    def test_una_empresa_que_fallo_entera_no_se_compara(self):
        manual = [factura_manual(factura="FEBA1001", fecha="2026-09-01")]
        self.assertEqual(self.consultadas(manual, errores={"NOVASA": "HTTP 500"}), [])
        # Una falla de una sola factura no excluye a la empresa.
        self.assertEqual(
            self.consultadas(manual, errores={"NOVASA · FACTURA FEBA7": "HTTP 500"}),
            ["FEBA1001"],
        )

    def test_si_siigo_la_devolvio_se_compara_aunque_la_fecha_difiera(self):
        manual = [factura_manual(factura="FEBA2050", fecha="2026-08-15")]
        self.assertEqual(self.consultadas(manual, siigo=facturas_siigo({})), ["FEBA2050"])

    def test_sin_parametros_la_muestra_no_filtra(self):
        manual = [factura_manual(empresa_codigo="LUAC", factura="LUA50", fecha="2020-01-01")]
        self.assertEqual(self.consultadas(manual, parametros=None), ["LUA50"])


if __name__ == "__main__":
    unittest.main()
