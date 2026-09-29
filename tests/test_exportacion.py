"""Comprueba el archivo que Excel abrirá, incluidas fórmulas y valores iniciales."""

from datetime import date
from io import BytesIO
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from src.exportacion import crear_excel


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def factura(**cambios):
    fila = dict(cliente="Cliente SAS", empresa_codigo="NOVASA", factura="FEBA1", fecha="2026-08-29",
                descripcion="Detalle completo", placas="ABC123", subtotal_cop=1000000, iva_cop=190000,
                retefuente_cop=40000, ica_cop=9660, descuento_cop=1400, total_cop=1138940,
                abonos_cop=138940, saldo_cop=1000000)
    fila.update(cambios)
    return fila


class Libro:
    def __init__(self, datos):
        self.zip = ZipFile(BytesIO(datos))
        self.textos = ["".join(n.itertext()) for n in ET.fromstring(self.zip.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        self.nombres = [n.attrib["name"] for n in ET.fromstring(self.zip.read("xl/workbook.xml")).findall("m:sheets/m:sheet", NS)]

    def hoja(self, indice):
        return ET.fromstring(self.zip.read(f"xl/worksheets/sheet{indice + 1}.xml"))

    def celda(self, indice, referencia):
        celda = self.hoja(indice).find(f".//m:c[@r='{referencia}']", NS)
        if celda is None:
            return None, None
        formula = celda.find("m:f", NS)
        valor = celda.find("m:v", NS)
        texto = valor.text if valor is not None else None
        if texto is not None and celda.get("t") == "s":
            texto = self.textos[int(texto)]
        return formula.text if formula is not None else None, texto


class ExportacionTests(unittest.TestCase):
    def exportar(self, filas, origen="manual"):
        return Libro(crear_excel(filas, origen=origen, fecha_corte=date(2026, 9, 29)))

    def test_manual_formulas_keep_taxes_discount_payments_and_exact_totals(self):
        libro = self.exportar([factura(), factura(factura="LUA2", empresa_codigo="LUAC")])
        self.assertEqual(libro.nombres, ["Resumen", "Cliente SAS"])
        self.assertEqual(libro.celda(1, "K8"), ("F8+G8-H8-I8-J8", "1138940"))
        self.assertEqual(libro.celda(1, "M8"), ("K8-L8", "1000000"))
        self.assertEqual(libro.celda(1, "I8")[1], "9660")
        self.assertEqual(libro.celda(1, "J8")[1], "1400")
        self.assertEqual(libro.celda(1, "N8")[1], "31")
        self.assertEqual(libro.celda(1, "O8")[1], "31 a 60 días")
        self.assertEqual(libro.celda(0, "C10")[1], "2000000")
        self.assertEqual(libro.celda(0, "F14")[1], "1000000")
        self.assertEqual(libro.celda(0, "G14")[1], "1000000")
        self.assertEqual(libro.celda(0, "D14")[1], "277880")

    def test_customer_names_collisions_and_literal_formula_text_are_safe(self):
        nombres = ["Resumen", "A/B", "A:B", "x" * 40 + "1", "x" * 40 + "2", "O'BRIEN"]
        libro = self.exportar([factura(cliente=n, descripcion='=HYPERLINK("https://example.test","texto")') for n in nombres])
        self.assertEqual(len(libro.nombres), 7)
        self.assertEqual(len(set(n.casefold() for n in libro.nombres)), 7)
        self.assertTrue(all(len(n) <= 31 for n in libro.nombres))
        self.assertFalse(any(any(c in n for c in "[]:*?/\\") for n in libro.nombres))
        for i in range(1, 7):
            self.assertIsNone(libro.celda(i, "D8")[0])
            self.assertTrue(libro.celda(i, "D8")[1].startswith("=HYPERLINK"))

    def test_siigo_unknown_is_blank_and_no_payment_is_inferred(self):
        fila = dict(cliente="Cliente", factura="FV1", empresa_codigo="NOVASA", fecha=None, moneda="COP",
                    saldo_siigo=None, total_siigo=5000, lectura_completa=False, iva_siigo=0)
        libro = self.exportar([fila], "siigo")
        self.assertIsNone(libro.celda(1, "G8")[1])
        self.assertIsNone(libro.celda(1, "L8")[1])
        self.assertIsNone(libro.celda(1, "M8")[1])
        self.assertEqual(libro.celda(1, "K8"), (None, "5000"))
        self.assertIsNone(libro.celda(1, "N8")[1])
        self.assertEqual(libro.celda(0, "I14")[1], "1")
        self.assertIsNone(libro.celda(0, "C10")[1])
        self.assertIsNone(libro.celda(0, "C7")[1])

    def test_siigo_different_currencies_and_annulled_do_not_inflate_cop(self):
        base = dict(cliente="Cliente", empresa_codigo="NOVASA", fecha="2026-09-01", total_siigo=10000, saldo_siigo=10000)
        filas = [{**base, "factura": "FV1", "moneda": "COP"}, {**base, "factura": "FV2", "moneda": "USD"},
                 {**base, "factura": "FV3", "moneda": "COP", "estado_siigo": "ANULADA"}]
        libro = self.exportar(filas, "siigo")
        self.assertEqual(libro.celda(0, "C10")[1], "10000")
        self.assertEqual(libro.celda(0, "B14")[1], "1")
        self.assertEqual(libro.celda(1, "P9")[1], "USD")
        self.assertEqual(libro.celda(1, "Q10")[1], "Anulada")

    def test_detail_is_complete_and_print_filters_panes_are_present(self):
        detalle = "TRANSPORTE ABC123 MANIFIESTO 123 " * 50
        libro = self.exportar([factura(descripcion=detalle)])
        self.assertEqual(libro.celda(1, "D8")[1], detalle)
        self.assertIsNotNone(libro.hoja(1).find("m:autoFilter", NS))
        pane = libro.hoja(1).find("m:sheetViews/m:sheetView/m:pane", NS)
        self.assertEqual(pane.get("topLeftCell"), "D8")
        self.assertEqual(libro.hoja(1).find("m:pageSetup", NS).get("orientation"), "landscape")
        self.assertIsNotNone(libro.hoja(1).find("m:conditionalFormatting", NS))

    def test_empty_export_is_a_valid_zero_summary_without_reverse_ranges(self):
        libro = self.exportar([])
        self.assertEqual(libro.nombres, ["Resumen"])
        self.assertEqual(libro.celda(0, "C10")[1], "0")
        formulas = " ".join(f.text for f in libro.hoja(0).findall(".//m:f", NS))
        self.assertNotIn("14:", formulas)


if __name__ == "__main__":
    unittest.main()
