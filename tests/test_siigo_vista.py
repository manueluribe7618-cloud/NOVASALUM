"""Reglas de presentación de la cartera Siigo.

La prueba más importante de este archivo es la que compara las columnas contra
las de la cartera manual: es lo que impide que las dos vistas se separen sin
que nadie se dé cuenta.
"""

from __future__ import annotations

import datetime as dt
import unittest

import pandas as pd

from src.siigo_vista import (
    COLUMNAS_ESTADO_CUENTA,
    COLUMNAS_GENERAL,
    buscar_filas,
    etiqueta_estado,
    fecha_visible,
    filas_de_dataframe,
    filtrar_saldo,
    money,
    money_blanco,
    money_kpi,
    ordenar_filas,
    suma_auditable,
    tabla_clientes,
    tabla_estado_cuenta,
    tabla_general,
)
from src.views.manual import _invoices_table, _statement_table


def _fila(**cambios) -> dict:
    base = {
        "empresa_codigo": "NOVASA",
        "siigo_factura_id": "nov-1",
        "factura": "FEBA2050",
        "fecha": "2026-03-12",
        "cliente": "TMP Izajes y Transportes S.A.S",
        "nit": "900123456-7",
        "moneda": "COP",
        "descripcion_siigo": "Transporte de tractocamión",
        "subtotal_siigo": 900_000.0,
        "iva_siigo": 0.0,
        "retefuente_siigo": 90_000.0,
        "reteica_siigo": 0.0,
        "total_siigo": 810_000.0,
        "saldo_siigo": 810_000.0,
        "estado_siigo": "VENCIDA",
        "lectura_completa": True,
        "estado_lectura": "DETALLE",
    }
    base.update(cambios)
    return base


class FormatoDeDineroTests(unittest.TestCase):
    def test_distingue_el_cero_del_dato_ausente(self) -> None:
        self.assertEqual(money(1_500_000), "$ 1.500.000")
        self.assertEqual(money(0), "$ 0")
        self.assertEqual(money(None), "—")
        self.assertEqual(money(float("nan")), "—")

    def test_money_blanco_deja_el_cero_vacio_como_en_el_excel(self) -> None:
        self.assertEqual(money_blanco(0), "")
        self.assertEqual(money_blanco(None), "—")
        self.assertEqual(money_blanco(190_000), "$ 190.000")

    def test_money_kpi_no_deja_la_tarjeta_en_blanco(self) -> None:
        self.assertEqual(money_kpi(float("nan")), "—")
        self.assertEqual(money_kpi(0), "—")

    def test_sin_centavos(self) -> None:
        self.assertEqual(money(1_500_000.49), "$ 1.500.000")


class EstadoYFechaTests(unittest.TestCase):
    def test_traduce_los_siete_estados_de_siigo(self) -> None:
        esperado = {
            "PAGADA": "Pagada",
            "PAGO_PARCIAL": "Pago parcial",
            "VENCIDA": "Vencida",
            "POR_VENCER": "Por vencer",
            "SIN_VENCIMIENTO": "Sin vencimiento",
            "DATO_INCOMPLETO": "Por revisar",
            "ANULADA": "Anulada",
        }
        for estado, etiqueta in esperado.items():
            self.assertEqual(etiqueta_estado(_fila(estado_siigo=estado)), etiqueta)

    def test_una_factura_sin_detalle_se_marca_sin_leer(self) -> None:
        fila = _fila(lectura_completa=False, estado_siigo="DATO_INCOMPLETO")
        self.assertEqual(etiqueta_estado(fila), "Sin leer")

    def test_estado_desconocido_no_revienta(self) -> None:
        self.assertEqual(etiqueta_estado(_fila(estado_siigo="ALGO_NUEVO")), "Algo nuevo")

    def test_fecha_ausente_no_lanza(self) -> None:
        self.assertEqual(fecha_visible(None), "—")
        self.assertEqual(fecha_visible("2026-03-12"), "12/03/2026")
        self.assertEqual(fecha_visible(dt.date(2026, 3, 12)), "12/03/2026")


class EspejoDeLaCarteraManualTests(unittest.TestCase):
    """Las dos carteras se envían como imagen: deben verse igual."""

    def _fila_manual(self) -> dict:
        return {
            "id": 1, "factura": "FEBA2050", "fecha": "2026-03-12",
            "cliente": "TMP Izajes", "descripcion": "Transporte", "placas": "TBZ935",
            "subtotal_cop": 900_000, "iva_cop": 0, "retefuente_cop": 90_000,
            "ica_cop": 0, "abonos_cop": 0, "saldo_cop": 810_000, "estado": "VENCIDA",
        }

    def test_cuadro_general_tiene_las_columnas_del_manual(self) -> None:
        del_manual = list(_invoices_table([self._fila_manual()]).columns)
        de_siigo = list(tabla_general([_fila()]).columns)
        # Siigo no guarda la placa en un campo propio: viene dentro del texto
        # de la descripción, que es la columna «Detalle del servicio».
        self.assertEqual(de_siigo, [c for c in del_manual if c != "Placas"])
        self.assertEqual(de_siigo, COLUMNAS_GENERAL)

    def test_estado_de_cuenta_tiene_las_columnas_del_manual(self) -> None:
        del_manual = list(_statement_table([self._fila_manual()]).columns)
        de_siigo = list(tabla_estado_cuenta([_fila()]).columns)
        self.assertEqual(de_siigo, [c for c in del_manual if c != "Placas"])
        self.assertEqual(de_siigo, COLUMNAS_ESTADO_CUENTA)


class TablasTests(unittest.TestCase):
    def test_una_factura_sin_detalle_muestra_rayas_y_nunca_ceros(self) -> None:
        fila = _fila(
            lectura_completa=False,
            descripcion_siigo="",
            subtotal_siigo=None,
            iva_siigo=0.0,
            retefuente_siigo=0.0,
            reteica_siigo=0.0,
        )
        visible = tabla_general([fila]).iloc[0]
        for columna in ("Detalle del servicio", "Subtotal", "IVA", "Retefuente", "ICA"):
            self.assertEqual(visible[columna], "—", columna)
        self.assertEqual(visible["Estado"], "Sin leer")

    def test_la_columna_abonos_queda_vacia(self) -> None:
        self.assertEqual(tabla_general([_fila()]).iloc[0]["Abonos"], "")
        self.assertEqual(tabla_estado_cuenta([_fila()]).iloc[0]["Abono"], "")

    def test_el_estado_de_cuenta_no_recorta_el_detalle(self) -> None:
        detalle = "TRANSPORTE DE TRACTOCAMION DE PLACA TBZ935 EN POZO NUTRIA " * 2
        visible = tabla_estado_cuenta([_fila(descripcion_siigo=detalle)]).iloc[0]
        self.assertEqual(visible["Detalle del servicio"], detalle.strip())

    def test_saldo_desconocido_se_ve_como_raya(self) -> None:
        self.assertEqual(tabla_general([_fila(saldo_siigo=None)]).iloc[0]["Saldo"], "—")


class TotalesTests(unittest.TestCase):
    def test_no_convierte_lo_ausente_en_cero(self) -> None:
        filas = [_fila(total_siigo=100.0), _fila(total_siigo=None)]
        total, faltantes = suma_auditable(filas, "total_siigo")
        self.assertEqual(total, 100.0)
        self.assertEqual(faltantes, 1)

    def test_clientes_agrupa_las_tres_empresas_del_mismo_nit(self) -> None:
        filas = [
            _fila(empresa_codigo="NOVASA", saldo_siigo=810_000.0),
            _fila(empresa_codigo="LUAC", saldo_siigo=972_000.0),
            _fila(empresa_codigo="MSU", saldo_siigo=2_050_000.0),
        ]
        tabla = tabla_clientes(filas)
        self.assertEqual(len(tabla), 1)
        self.assertEqual(tabla.iloc[0]["Facturas con saldo"], 3)
        self.assertEqual(tabla.iloc[0]["Empresas"], "LUAC · MSU · NOVASA")
        self.assertEqual(tabla.iloc[0]["Saldo pendiente"], "$ 3.832.000")

    def test_anuladas_y_otras_monedas_no_entran_en_clientes(self) -> None:
        filas = [
            _fila(estado_siigo="ANULADA", saldo_siigo=999.0),
            _fila(moneda="USD", saldo_siigo=999.0),
        ]
        self.assertTrue(tabla_clientes(filas).empty)


class FiltrosTests(unittest.TestCase):
    def test_busca_por_nit_y_por_detalle(self) -> None:
        filas = [_fila()]
        self.assertEqual(len(buscar_filas(filas, "900123456")), 1)
        self.assertEqual(len(buscar_filas(filas, "tractocamión")), 1)
        self.assertEqual(len(buscar_filas(filas, "no existe")), 0)

    def test_filtro_de_saldo_tolera_el_saldo_desconocido(self) -> None:
        filas = [
            _fila(saldo_siigo=810_000.0),
            _fila(saldo_siigo=0.0),
            _fila(saldo_siigo=None),
        ]
        self.assertEqual(len(filtrar_saldo(filas, "Con saldo pendiente")), 1)
        self.assertEqual(len(filtrar_saldo(filas, "Saldo en cero")), 1)
        self.assertEqual(len(filtrar_saldo(filas, "Saldo sin dato")), 1)
        self.assertEqual(len(filtrar_saldo(filas, "Todos")), 3)

    def test_ordena_dejando_al_final_las_fechas_desconocidas(self) -> None:
        filas = [
            _fila(factura="B", fecha=None),
            _fila(factura="A", fecha="2026-01-05"),
        ]
        self.assertEqual([f["factura"] for f in ordenar_filas(filas)], ["A", "B"])

    def test_filas_de_dataframe_limpia_los_nan(self) -> None:
        datos = pd.DataFrame([{"saldo_siigo": float("nan"), "factura": "A"}])
        self.assertIsNone(filas_de_dataframe(datos)[0]["saldo_siigo"])


if __name__ == "__main__":
    unittest.main()
