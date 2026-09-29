"""Pruebas de la clasificación fiscal de la cartera Siigo.

``src/cartera_siigo.py`` no tenía archivo de prueba propio pese a contener
toda la aritmética fiscal de la segunda cartera. Se empieza por la pieza que
tenía un defecto real: repartir impuestos y retenciones según su nombre.
"""

from __future__ import annotations

import unittest

from src.cartera_siigo import _impuestos_factura, facturas_a_dataframe

# Un ítem sin impuestos: toda factura leída de Siigo trae al menos uno. Una
# lista de ítems vacía significa «no se leyó el detalle», no «sin impuestos».
ITEM_SIN_IMPUESTOS = {"description": "Servicio", "price": 1_000_000, "quantity": 1, "taxes": []}


def con_retencion(nombre: str, valor: float = 1_000.0, tipo: str = ""):
    return {
        "items": [ITEM_SIN_IMPUESTOS],
        "retentions": [{"type": tipo, "name": nombre, "value": valor}],
    }


def con_impuesto(nombre: str, valor: float = 1_000.0, tipo: str = ""):
    return {"items": [{"taxes": [{"type": tipo, "name": nombre, "value": valor}]}]}


class ClasificacionDeRetenciones(unittest.TestCase):
    def concepto(self, factura):
        """El único concepto que quedó con valor."""

        con_valor = [clave for clave, valor in _impuestos_factura(factura).items() if valor]
        self.assertEqual(len(con_valor), 1, f"se esperaba un solo concepto, hubo {con_valor}")
        return con_valor[0]

    def test_una_retefuente_con_ica_dentro_de_otra_palabra_no_es_ica(self):
        # El defecto original: 'LOGISTICA' contiene las letras I-C-A. En una
        # empresa de transporte de carga este nombre no es hipotético.
        for nombre in (
            "Retencion en la fuente servicios LOGISTICA",
            "Retefuente por servicios de MECANICA",
            "Retefuente servicios MEDICA",
        ):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.concepto(con_retencion(nombre)), "retefuente_siigo")

    def test_el_ica_verdadero_se_sigue_reconociendo(self):
        for nombre in (
            "ReteICA Bogota",
            "Retencion ICA",
            "RETEICA",
            "Impuesto de Industria y Comercio",
        ):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.concepto(con_retencion(nombre)), "reteica_siigo")

    def test_retefuente_y_reteiva_se_reconocen(self):
        self.assertEqual(self.concepto(con_retencion("Retefuente servicios")), "retefuente_siigo")
        self.assertEqual(self.concepto(con_retencion("ReteIVA")), "reteiva_siigo")

    def test_una_retencion_desconocida_no_se_reparte_a_la_fuerza(self):
        self.assertEqual(
            self.concepto(con_retencion("Retencion especial pactada")),
            "otras_retenciones_siigo",
        )

    def test_los_valores_se_acumulan_por_concepto(self):
        factura = {
            "items": [ITEM_SIN_IMPUESTOS],
            "retentions": [
                {"name": "Retefuente servicios", "value": 25_000},
                {"name": "Retencion en la fuente LOGISTICA", "value": 13_000},
                {"name": "ReteICA Bogota", "value": 4_140},
            ],
        }
        resultado = _impuestos_factura(factura)
        self.assertEqual(resultado["retefuente_siigo"], 38_000)
        self.assertEqual(resultado["reteica_siigo"], 4_140)


class ClasificacionDeImpuestos(unittest.TestCase):
    def test_el_iva_se_reconoce_por_su_nombre(self):
        for nombre in ("IVA", "IVA 19%", "VAT"):
            with self.subTest(nombre=nombre):
                self.assertEqual(_impuestos_factura(con_impuesto(nombre))["iva_siigo"], 1_000)

    def test_un_impuesto_que_solo_contiene_las_letras_iva_no_es_iva(self):
        resultado = _impuestos_factura(con_impuesto("Impuesto sobre consumo PRIVADO"))
        self.assertEqual(resultado["iva_siigo"], 0)
        self.assertEqual(resultado["otros_impuestos_siigo"], 1_000)

    def test_una_factura_sin_impuestos_deja_todo_en_cero(self):
        self.assertEqual(
            set(_impuestos_factura({"items": [ITEM_SIN_IMPUESTOS], "retentions": []}).values()),
            {0.0},
        )


class RetencionesDentroDeLosItems(unittest.TestCase):
    """Siigo Nube configura la retención por producto: llega en items[].taxes."""

    def test_la_retefuente_de_un_item_es_retefuente_y_no_otro_impuesto(self):
        factura = {"items": [{
            **ITEM_SIN_IMPUESTOS,
            "taxes": [
                {"type": "IVA", "name": "IVA 19%", "value": 190_000},
                {"type": "Retefuente", "name": "Retefuente 4% servicios", "value": 40_000},
            ],
        }]}
        resultado = _impuestos_factura(factura)
        self.assertEqual(resultado["iva_siigo"], 190_000)
        self.assertEqual(resultado["retefuente_siigo"], 40_000)
        self.assertEqual(resultado["otros_impuestos_siigo"], 0)

    def test_reteica_y_reteiva_de_un_item_tambien_se_reconocen(self):
        factura = {"items": [{
            **ITEM_SIN_IMPUESTOS,
            "taxes": [
                {"type": "ReteICA", "name": "ReteICA Bogota", "value": 4_140},
                {"type": "ReteIVA", "name": "ReteIVA 15%", "value": 28_500},
            ],
        }]}
        resultado = _impuestos_factura(factura)
        self.assertEqual(resultado["reteica_siigo"], 4_140)
        self.assertEqual(resultado["reteiva_siigo"], 28_500)
        self.assertEqual(resultado["iva_siigo"], 0)
        self.assertEqual(resultado["otros_impuestos_siigo"], 0)


class ValoresQueSiigoNoEntrego(unittest.TestCase):
    """Un impuesto sin «value» es «no se sabe», nunca $ 0."""

    def test_un_iva_sin_valor_deja_el_iva_desconocido(self):
        factura = {"items": [{
            **ITEM_SIN_IMPUESTOS,
            "taxes": [{"type": "IVA", "name": "IVA 19%", "percentage": 19}],
        }]}
        resultado = _impuestos_factura(factura)
        self.assertIsNone(resultado["iva_siigo"])
        # Lo que sí llegó completo conserva su cero contable.
        self.assertEqual(resultado["retefuente_siigo"], 0)

    def test_una_retencion_sin_valor_deja_su_concepto_desconocido(self):
        factura = {
            "items": [ITEM_SIN_IMPUESTOS],
            "retentions": [{"type": "Retefuente", "name": "Retefuente"}],
        }
        self.assertIsNone(_impuestos_factura(factura)["retefuente_siigo"])

    def test_sin_items_los_impuestos_de_los_items_no_se_saben(self):
        for items in (None, []):
            with self.subTest(items=items):
                resultado = _impuestos_factura({"items": items, "retentions": []})
                for concepto in ("iva_siigo", "retefuente_siigo", "reteica_siigo"):
                    self.assertIsNone(resultado[concepto], concepto)


class IdentificacionDelCliente(unittest.TestCase):
    """La cédula completa y sin DV es la que reconoce al cliente."""

    def identificacion(self, **cliente):
        factura = {"id": "1", "name": "FEBA1", "customer": {"name": "Cliente", **cliente}}
        return facturas_a_dataframe("NOVASA", [factura]).iloc[0]["identificacion"]

    def test_la_cedula_de_diez_digitos_no_se_recorta(self):
        self.assertEqual(self.identificacion(identification="1098765432"), "1098765432")

    def test_el_digito_de_verificacion_no_entra(self):
        self.assertEqual(self.identificacion(identification="79123456", check_digit="3"), "79123456")
        self.assertEqual(self.identificacion(identification="79123456-3"), "79123456")


if __name__ == "__main__":
    unittest.main()
