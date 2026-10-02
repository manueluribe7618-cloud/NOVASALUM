"""Comprueba el archivo que Excel abrirá, incluidas fórmulas y valores iniciales."""

from datetime import date
from io import BytesIO
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from streamlit.testing.v1 import AppTest

from src.exportacion import crear_excel
from src.siigo_muestra import cargar_muestra
from src.siigo_vista import es_vigente, etiqueta_estado, filas_de_dataframe


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CORTE = date(2026, 9, 29)


def serial(fecha):
    return str((fecha - date(1899, 12, 30)).days)


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

    def columna(self, indice, letra):
        """Valores de una columna en las filas de facturas (hasta la primera fila vacía)."""
        valores, n = [], 8
        while self.celda(indice, f"A{n}")[1] is not None:
            valores.append(self.celda(indice, f"{letra}{n}")[1])
            n += 1
        return valores

    def detalle(self, indice):
        """Filas de facturas de una hoja de cliente, con su valor inicial por cabecera."""
        cabecera = {}
        for celda in self.hoja(indice).findall(".//m:row[@r='7']/m:c", NS):
            cabecera[self.celda(indice, celda.get("r"))[1]] = celda.get("r")[:-1]
        filas = []
        for n in range(8, 8 + len(self.columna(indice, "A"))):
            filas.append({nombre: self.celda(indice, f"{letra}{n}")[1] for nombre, letra in cabecera.items()})
        return filas

    def reglas(self, indice):
        return {f.text for f in self.hoja(indice).findall("m:conditionalFormatting/m:cfRule/m:formula", NS)}


class ExportacionTests(unittest.TestCase):
    def exportar(self, filas, origen="manual", **opciones):
        return Libro(crear_excel(filas, origen=origen, fecha_corte=CORTE, **opciones))

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

    def test_apostrophe_at_position_31_and_odd_names_give_valid_unique_linked_sheets(self):
        nombres = ["GRUAS Y MONTAJES DEL LLANITO D'ORO S.A.S", "GRUAS Y MONTAJES DEL LLANITO D'ORO LTDA",
                   "Distribuidora Nacional de Cafe's Premium SAS", "A" * 26 + "'BBBB1", "A" * 26 + "'BBBB2",
                   "'''", "[]:*?/\\", "History", " 'Resumen' ", "Tab\tcon\x01control"]
        libro = self.exportar([factura(cliente=n) for n in nombres])
        hojas = libro.nombres[1:]
        self.assertEqual(len(hojas), len(nombres))
        self.assertEqual(len({h.casefold() for h in libro.nombres}), len(libro.nombres))
        for hoja in hojas:
            self.assertTrue(0 < len(hoja) <= 31, hoja)
            self.assertFalse(hoja.startswith("'") or hoja.endswith("'"), hoja)
            self.assertFalse(any(c in "[]:*?/\\" or ord(c) < 32 for c in hoja), hoja)
        self.assertIn("GRUAS Y MONTAJES DEL LLANITO D", hojas)
        self.assertIn("GRUAS Y MONTAJES DEL LLANIT (2)", hojas)
        self.assertIn("Distribuidora Nacional de Cafe", hojas)
        destinos = [e.get("location") for e in libro.hoja(0).findall("m:hyperlinks/m:hyperlink", NS)]
        self.assertEqual(sorted(d[1:-4].replace("''", "'") for d in destinos), sorted(hojas))

    def test_manual_status_says_what_the_app_says_including_overdue(self):
        filas = [factura(factura="FEBA1", vencimiento="2026-09-01", abonos_cop=0, saldo_cop=1138940, estado="VENCIDA"),
                 factura(factura="FEBA2", vencimiento="2026-09-10", estado="VENCIDA"),
                 factura(factura="FEBA3", vencimiento="2026-10-30", estado="ABONADA"),
                 factura(factura="FEBA4", abonos_cop=0, saldo_cop=1138940, estado="PENDIENTE"),
                 factura(factura="FEBA5", vencimiento="2026-09-01", abonos_cop=1138940, saldo_cop=0, estado="PAGADA"),
                 factura(factura="FEBA6", vencimiento="2026-09-28")]
        libro = self.exportar(filas)
        self.assertEqual(libro.celda(1, "R7")[1], "Vencimiento")
        self.assertEqual(libro.columna(1, "Q"), ["Vencida", "Vencida", "Abonada", "Pendiente", "Pagada", "Vencida"])
        self.assertEqual(libro.columna(1, "R"), [serial(date(2026, 9, 1)), serial(date(2026, 9, 10)),
                                                 serial(date(2026, 10, 30)), None, serial(date(2026, 9, 1)),
                                                 serial(date(2026, 9, 28))])
        self.assertEqual(libro.celda(1, "Q8")[0], 'IF(M8<=0,"Pagada",IF(AND(R8<>"",R8<\'Resumen\'!$B$3),"Vencida",'
                                                  'IF(L8>0,"Abonada","Pendiente")))')
        self.assertLessEqual({f'"{e}"' for e in ("Vencida", "Abonada", "Pendiente", "Pagada")}, libro.reglas(1))
        self.assertEqual(libro.celda(1, "S7")[1], None)

    def test_siigo_status_is_the_screen_label_and_never_pending_without_balance(self):
        filas = filas_de_dataframe(cargar_muestra(CORTE).facturas)
        libro = self.exportar(filas, "siigo")
        por_factura = {f["factura"]: f for f in filas}
        vistos = {}
        for indice in range(1, len(libro.nombres)):
            for fila in libro.detalle(indice):
                vistos[fila["Factura"]] = fila
                original = por_factura[fila["Factura"]]
                esperado = etiqueta_estado(original) if es_vigente(original) else "Anulada"
                self.assertEqual(fila["Estado"], esperado, fila["Factura"])
                self.assertFalse(fila["Saldo pendiente"] is None and fila["Estado"] == "Pendiente")
                self.assertIn(f'"{fila["Estado"]}"', libro.reglas(indice))
                vence = original.get("vencimiento")
                self.assertEqual(fila["Vencimiento"], serial(vence) if vence else None)
        self.assertEqual(set(vistos), set(por_factura))
        self.assertEqual(vistos["FEBA2054"]["Estado"], "Sin leer")
        self.assertEqual(vistos["FEBA2050"]["Estado"], "Vencida")
        self.assertLessEqual({"Vencida", "Por vencer", "Sin vencimiento", "Por revisar", "Sin leer", "Anulada"},
                             {f["Estado"] for f in vistos.values()})

    def test_siigo_exports_nit_and_extra_concepts_that_reconcile_with_the_total(self):
        base = dict(cliente="Cliente", nit="900123456-7", empresa_codigo="NOVASA", fecha="2026-09-01",
                    vencimiento="2026-10-01", moneda="USD", tasa_cambio=3900.5, subtotal_siigo=1000,
                    descuento_siigo=100, iva_siigo=171, otros_impuestos_siigo=80, retefuente_siigo=25,
                    reteica_siigo=10, reteiva_siigo=26, otras_retenciones_siigo=5, anticipo_aplicado=200,
                    total_siigo=1085, saldo_siigo=885, estado_siigo="POR_VENCER")
        libro = self.exportar([{**base, "factura": "FV1"}, {**base, "factura": "FV2", "lectura_completa": False}], "siigo")
        completa, incompleta = libro.detalle(1)
        self.assertEqual([libro.celda(1, f"{c}7")[1] for c in "RSTUVWX"],
                         ["Vencimiento", "NIT", "Otros impuestos", "ReteIVA", "Otras retenciones",
                          "Anticipo aplicado", "Tasa de cambio"])
        self.assertEqual([completa[k] for k in ("NIT", "Otros impuestos", "ReteIVA", "Otras retenciones",
                                                "Anticipo aplicado", "Tasa de cambio")],
                         ["900123456-7", "80", "26", "5", "200", "3900.5"])
        n = {k: float(completa[k]) for k in ("Subtotal", "IVA", "Otros impuestos", "Retefuente", "ICA", "ReteIVA",
                                            "Otras retenciones", "Descuento", "Total factura")}
        self.assertEqual(n["Subtotal"] + n["IVA"] + n["Otros impuestos"] - n["Retefuente"] - n["ICA"] - n["ReteIVA"]
                         - n["Otras retenciones"] - n["Descuento"], n["Total factura"])
        self.assertEqual(completa["Estado"], "Por vencer")
        self.assertEqual(incompleta["NIT"], "900123456-7")
        for campo in ("Subtotal", "IVA", "Otros impuestos", "ReteIVA", "Otras retenciones", "Anticipo aplicado"):
            self.assertIsNone(incompleta[campo], campo)
        self.assertEqual(incompleta["Estado"], "Sin leer")

    def test_rows_keep_incoming_order_grouped_by_company_and_customers_sort_like_the_app(self):
        filas = [factura(factura="MSU647", empresa_codigo="MSU"), factura(factura="FEBA10"),
                 factura(factura="LUA1728", empresa_codigo="LUAC"), factura(factura="FEBA9")]
        libro = self.exportar(filas)
        self.assertEqual(libro.columna(1, "B"), ["FEBA10", "FEBA9", "LUA1728", "MSU647"])
        self.assertEqual([libro.celda(1, f"A{n}")[1] for n in (14, 15, 16)], ["NOVASA", "LUAC", "MSU"])
        nombres = ["Zapata Transportes SAS", "Álvarez y Cía SAS", "Ñandú Logística SAS", "Éxito Carga SAS",
                   "Beta SAS", "Obras SAS", "nube SAS"]
        libro = self.exportar([factura(cliente=n) for n in nombres])
        esperado = ["Álvarez y Cía SAS", "Beta SAS", "Éxito Carga SAS", "nube SAS", "Ñandú Logística SAS",
                    "Obras SAS", "Zapata Transportes SAS"]
        self.assertEqual(libro.nombres[1:], esperado)
        self.assertEqual([libro.celda(0, f"A{n}")[1] for n in range(14, 21)], esperado)

    def test_siigo_company_not_read_is_marked_and_never_zero(self):
        fila = dict(cliente="Cliente", factura="FV1", empresa_codigo="NOVASA", fecha="2026-09-01", moneda="COP",
                    total_siigo=5000, saldo_siigo=5000, estado_siigo="POR_VENCER")
        libro = self.exportar([fila], "siigo", empresas_consultadas={"NOVASA"})
        self.assertEqual(libro.celda(0, "C7")[1], "5000")
        self.assertEqual(libro.celda(0, "C8"), (None, "Sin lectura"))
        self.assertEqual(libro.celda(0, "C9"), (None, "Sin lectura"))
        self.assertEqual(libro.celda(0, "G15"), (None, "Sin lectura"))
        self.assertEqual(libro.celda(0, "H15"), (None, "Sin lectura"))
        self.assertEqual(libro.celda(0, "C10")[1], "5000")
        manual = self.exportar([factura()])
        self.assertEqual(manual.celda(0, "G15"), ("0", "0"))
        self.assertEqual(manual.celda(0, "C8")[1], "0")


def vista_manual():
    from types import SimpleNamespace
    from unittest.mock import patch
    import streamlit as st
    from src.formato import hoy_colombia
    from src.ui import exports
    from src.views import manual
    from tests.test_exportacion import factura

    hoy = hoy_colombia()
    filas = [factura(id=i, cliente=c, empresa_codigo=e, factura=f, saldo_cop=s, estado="PENDIENTE",
                     fecha=hoy.replace(day=1).isoformat())
             for i, (c, e, f, s) in enumerate([("Zulu", "NOVASA", "FEBA1", 900), ("Álamo", "LUAC", "LUA2", 5000),
                                               ("Beta", "MSU", "MSU3", 2000)], 1)]

    def capturar(*args, data, **kwargs):
        st.session_state["excel_ids"] = [fila["id"] for fila in data.args[0]]
        st.session_state["excel_opciones"] = data.keywords

    with patch.object(manual.db, "listar_facturas", lambda code=None: [f for f in filas if code in (None, f["empresa_codigo"])]), \
            patch.object(manual.db, "hay_datos", return_value=True), patch.object(manual, "_render_grid", lambda *a, **k: None), \
            patch.object(exports, "st", SimpleNamespace(download_button=capturar)):
        manual.render_manual_portfolio(st.session_state.get("filtro_empresa_manual", "TODAS"))


def vista_siigo():
    import datetime as dt
    from types import SimpleNamespace
    from unittest.mock import patch
    import streamlit as st
    from src.siigo_lectura import ParametrosLectura
    from src.siigo_muestra import cargar_muestra
    from src.ui import exports
    from src.views.siigo import _publicar, render_siigo_portfolio

    reporte = cargar_muestra()
    if st.session_state.get("lectura_real"):
        reporte.facturas = reporte.facturas[reporte.facturas["empresa_codigo"] == "NOVASA"]
        reporte.parametros = ParametrosLectura(("NOVASA", "LUAC"), dt.date(2026, 9, 1), dt.date(2026, 9, 29))
        reporte.errores["LUAC"] = "No fue posible consultar esta empresa (Timeout)."

    def capturar(*args, data, **kwargs):
        st.session_state["excel_facturas"] = [fila["factura"] for fila in data.args[0]]
        st.session_state["excel_opciones"] = data.keywords
        st.session_state["excel"] = data()

    with patch.object(exports, "st", SimpleNamespace(download_button=capturar)):
        _publicar(reporte)
        render_siigo_portfolio("TODAS")


class ExportacionDesdeLasVistasTests(unittest.TestCase):
    def test_manual_full_export_follows_the_screen_order(self):
        app = AppTest.from_function(vista_manual, default_timeout=40).run()
        app.selectbox(key="orden_facturas_manual").select("Saldo: de mayor a menor").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["excel_ids"], [2, 3, 1])
        app.selectbox(key="orden_facturas_manual").select("Cliente: Z a A").run()
        self.assertEqual(app.session_state["excel_ids"], [1, 3, 2])
        app.selectbox(key="orden_facturas_manual").select("Factura: de mayor a menor").run()
        self.assertEqual(app.session_state["excel_ids"], [3, 2, 1])
        self.assertIsNone(app.session_state["excel_opciones"]["empresas_consultadas"])

    def test_siigo_export_names_period_companies_and_marks_failed_company(self):
        app = AppTest.from_function(vista_siigo, default_timeout=60)
        app.session_state["lectura_real"] = True
        app.run()
        self.assertFalse(app.exception)
        opciones = app.session_state["excel_opciones"]
        self.assertEqual(set(opciones["empresas_consultadas"]), {"NOVASA"})
        self.assertIn("Período: 01/09/2026 a 29/09/2026.", opciones["fuente"])
        self.assertIn("Empresas consultadas: NOVASA, LUAC.", opciones["fuente"])
        libro = Libro(app.session_state["excel"])
        self.assertEqual(libro.celda(0, "C8"), (None, "Sin lectura"))
        self.assertEqual(libro.celda(0, "C9"), (None, "Sin lectura"))
        self.assertIn("Período: 01/09/2026", libro.celda(0, "A2")[1])

    def test_siigo_sample_export_says_it_is_demo_data_and_follows_the_screen_order(self):
        app = AppTest.from_function(vista_siigo, default_timeout=60).run()
        app.selectbox(key="orden_facturas_siigo").select("Saldo: de mayor a menor").run()
        self.assertFalse(app.exception)
        opciones = app.session_state["excel_opciones"]
        self.assertIsNone(opciones["empresas_consultadas"])
        self.assertIn("demostración", opciones["fuente"])
        facturas = app.session_state["excel_facturas"]
        self.assertEqual(facturas[:3], ["LUA1739", "MSU649", "MSU647"])
        self.assertEqual(facturas[-2:], ["FEBA2054", "LUA1740"])


if __name__ == "__main__":
    unittest.main()
