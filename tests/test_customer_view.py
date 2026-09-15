"""Regresiones de la vista de cliente: búsqueda por razón social y desglose."""

from __future__ import annotations

import unittest

from src.views.manual import (
    ManualFilters,
    _customer_options,
    _filter_customers,
    _filter_rows,
    _statement_table,
)


def _factura(**cambios) -> dict:
    base = {
        "id": 1,
        "empresa_codigo": "NOVASA",
        "cliente_id": 1,
        "factura": "FEBA1079",
        "fecha": "2026-01-15",
        "cliente": "TMP Izajes y Transportes S.A.S",
        "descripcion": "Transporte de tubería",
        "placas": "SYS558",
        "subtotal_cop": 3_700_000,
        "iva_cop": 0,
        "retefuente_cop": 37_000,
        "ica_cop": 0,
        "abonos_cop": 1_420_000,
        "total_cop": 3_663_000,
        "saldo_cop": 2_243_000,
        "estado": "ABONADA",
    }
    base.update(cambios)
    return base


def _sin_filtros(clientes: tuple[str, ...] = ()) -> ManualFilters:
    return ManualFilters(
        term="",
        customers=clientes,
        states=(),
        year=None,
        month=None,
        balance="Todos",
    )


class OpcionesDeClienteTests(unittest.TestCase):
    def test_agrupa_por_razon_social_sin_duplicar_por_empresa(self) -> None:
        facturas = [
            _factura(id=1, empresa_codigo="NOVASA", cliente_id=1),
            _factura(id=2, empresa_codigo="LUAC", cliente_id=7),
            _factura(id=3, empresa_codigo="MSU", cliente_id=4),
            _factura(id=4, cliente="Otro Cliente SAS", cliente_id=9),
        ]
        opciones = _customer_options(facturas)
        self.assertEqual(len(opciones), 2)
        self.assertIn("TMP Izajes y Transportes S.A.S", opciones)

    def test_ignora_mayusculas_y_espacios_al_deduplicar(self) -> None:
        facturas = [
            _factura(id=1, cliente="ACME SAS"),
            _factura(id=2, cliente="  acme sas  ", empresa_codigo="LUAC"),
        ]
        opciones = _customer_options(facturas)
        self.assertEqual(list(opciones.values()), ["acme sas"])


class FiltroPorClienteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facturas = [
            _factura(id=1, empresa_codigo="NOVASA", cliente_id=1),
            _factura(id=2, empresa_codigo="LUAC", cliente_id=7),
            _factura(id=3, empresa_codigo="MSU", cliente_id=4),
            _factura(id=4, cliente="Otro Cliente SAS", cliente_id=9),
        ]

    def test_un_cliente_trae_sus_facturas_de_todas_las_empresas(self) -> None:
        filtros = _sin_filtros(("tmp izajes y transportes s.a.s",))
        filas = _filter_rows(self.facturas, filtros)
        self.assertEqual([fila["id"] for fila in filas], [1, 2, 3])
        self.assertEqual(
            {fila["empresa_codigo"] for fila in filas},
            {"NOVASA", "LUAC", "MSU"},
        )

    def test_sin_seleccion_no_filtra(self) -> None:
        self.assertEqual(len(_filter_rows(self.facturas, _sin_filtros())), 4)
        self.assertEqual(len(_filter_customers(self.facturas, ())), 4)

    def test_resumen_de_clientes_respeta_la_seleccion(self) -> None:
        filas = _filter_customers(self.facturas, ("otro cliente sas",))
        self.assertEqual([fila["id"] for fila in filas], [4])


class EstadoDeCuentaTests(unittest.TestCase):
    def test_columnas_y_blancos_como_en_el_excel(self) -> None:
        tabla = _statement_table([
            _factura(id=1, iva_cop=0, retefuente_cop=90_000, ica_cop=0,
                     abonos_cop=0, subtotal_cop=900_000, saldo_cop=810_000),
        ])
        self.assertEqual(
            list(tabla.columns),
            ["_factura_id", "Factura", "Fecha", "Detalle del servicio", "Placas",
             "Sub valor factura", "Impuestos", "Retención", "ICA", "Abono",
             "Descuento", "Saldo pendiente"],
        )
        fila = tabla.iloc[0]
        # Conceptos en cero quedan en blanco, como las celdas vacías del Excel.
        self.assertEqual(fila["Impuestos"], "")
        self.assertEqual(fila["ICA"], "")
        self.assertEqual(fila["Abono"], "")
        self.assertEqual(fila["Descuento"], "")
        self.assertEqual(fila["Sub valor factura"], "$ 900.000")
        self.assertEqual(fila["Retención"], "$ 90.000")
        self.assertEqual(fila["Saldo pendiente"], "$ 810.000")

    def test_el_descuento_se_muestra_cuando_existe(self) -> None:
        tabla = _statement_table([_factura(descuento_cop=1_400)])
        self.assertEqual(tabla.iloc[0]["Descuento"], "$ 1.400")

    def test_detalle_del_servicio_va_completo(self) -> None:
        detalle = "ALQUILER DE GRUA DE 70TON DE PLACA KPN553 " * 3
        tabla = _statement_table([_factura(descripcion=detalle)])
        self.assertEqual(tabla.iloc[0]["Detalle del servicio"], detalle.strip())


if __name__ == "__main__":
    unittest.main()
