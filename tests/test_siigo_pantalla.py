"""La pantalla Espejo Siigo, renderizada con la muestra y con casos de borde.

La grilla se sustituye por una función que guarda cada tabla en la sesión, así
se puede leer lo que la pantalla le entrega al cliente sin el componente AgGrid.
"""

from __future__ import annotations

import re
import unittest

from streamlit.testing.v1 import AppTest


def _vista_siigo() -> None:
    import datetime as dt
    from unittest.mock import patch

    import streamlit as st

    import src.views.siigo as vista
    from src.formato import hoy_colombia
    from src.siigo_lectura import reporte_desde_facturas
    from src.siigo_muestra import cargar_muestra

    def factura(identificador, nombre, cliente, nit, saldo, dv=None):
        tercero = {"id": f"c{nit}", "identification": nit, "name": cliente, "branch_office": 0}
        if dv:
            tercero["check_digit"] = dv
        return {
            "id": identificador, "name": nombre,
            "date": (hoy_colombia() - dt.timedelta(days=10)).isoformat(),
            "total": max(saldo, 500_000), "balance": saldo, "customer": tercero,
            "currency": {"code": "COP"},
            "items": [{"description": "srv", "price": 500_000, "quantity": 1, "taxes": []}],
            "retentions": [],
        }

    if "siigo_reporte" not in st.session_state:
        if st.session_state.get("_escenario") == "bordes":
            vista._publicar(reporte_desde_facturas({
                "NOVASA": [
                    factura("n1", "FEBA1", "Juan Perez", "1098765432", 1_000_000),
                    factura("n3", "FEBA3", "Transportes XYZ SAS", "900111222", 300_000),
                    factura("n4", "FEBA4", "Cliente Negativo", "700700700", 1_000_000),
                    factura("n5", "FEBA5", "Cliente Negativo", "700700700", -200_000),
                    factura("n6", "FEBA6", "Persona CC", "79123456", 400_000),
                ],
                "LUAC": [
                    factura("l1", "LUA1", "Pedro Gomez", "1098765439", 2_000_000),
                    factura("l2", "LUA2", "Persona CC", "79123456", 500_000, dv="3"),
                ],
                "MSU": [factura("m1", "MSU1", "Transportes XYZ SAS", "800333444", 900_000)],
            }, origen="Prueba"))
        else:
            vista._publicar(cargar_muestra())

    tablas = {}

    def capturar(tabla, *, key, **_):
        tablas[key] = tabla

    with patch.object(vista, "render_grid", capturar):
        vista.render_siigo_portfolio("TODAS")
    st.session_state["_tablas"] = tablas


def _texto(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ")).strip()


class EspejoSiigo(unittest.TestCase):
    def abrir(self, escenario: str = "muestra", **estado) -> AppTest:
        app = AppTest.from_function(_vista_siigo, default_timeout=90)
        app.session_state["_escenario"] = escenario
        app.run()
        for clave, valor in estado.items():
            app.session_state[clave] = valor
        if estado:
            app.run()
        self.assertFalse(app.exception, app.exception)
        return app

    def tablas(self, app: AppTest) -> dict:
        return app.session_state["_tablas"]

    def kpis(self, app: AppTest) -> dict[str, str]:
        salida = {}
        for bloque in app.markdown:
            if "kpi-card" in bloque.value:
                etiqueta = re.search(r'kpi-label">([^<]*)', bloque.value).group(1)
                salida[etiqueta] = re.search(r'kpi-value">([^<]*)', bloque.value).group(1)
        return salida

    def totales_por_empresa(self, app: AppTest) -> list[str]:
        return [
            _texto(b.value) for b in app.markdown if "statement-company-total" in b.value
        ]

    def test_homonimos_y_cedulas_largas_se_pueden_abrir_por_separado(self) -> None:
        app = self.abrir("bordes")
        selector = app.selectbox(key="detalle_cliente_siigo")
        self.assertEqual(selector.options, [
            "Cliente Negativo · NIT 700700700",
            "Juan Perez · NIT 1098765432",
            "Pedro Gomez · NIT 1098765439",
            # La misma cédula con DV en LUAC y sin DV en NOVASA es un cliente.
            "Persona CC · NIT 79123456",
            "Transportes XYZ SAS · NIT 800333444",
            "Transportes XYZ SAS · NIT 900111222",
        ])
        filtro = app.multiselect(key="filtro_clientes_siigo")
        self.assertEqual(filtro.options, selector.options)

        selector.set_value("nit:800333444").run()
        tablas = self.tablas(app)
        self.assertEqual(list(tablas["tabla_detalle_cliente_siigo_MSU"]["Factura"]), ["MSU1"])
        self.assertNotIn("tabla_detalle_cliente_siigo_NOVASA", tablas)

    def test_la_tarjeta_de_saldo_coincide_con_la_tabla_de_clientes(self) -> None:
        app = self.abrir("bordes")
        clientes = next(t for k, t in self.tablas(app).items() if k.startswith("tabla_clientes_siigo"))
        suma = sum(int(v.replace("$ ", "").replace(".", "")) for v in clientes["Saldo pendiente"])
        self.assertEqual(self.kpis(app)["Saldo pendiente"], f"$ {suma:,}".replace(",", "."))

    def test_el_saldo_de_empresa_sin_dato_es_raya_y_la_anulada_va_aparte(self) -> None:
        app = self.abrir(detalle_cliente_siigo="nit:901555222")  # YEGO
        totales = self.totales_por_empresa(app)
        self.assertIn("Saldo pendiente LUAC Cargo SAS: —", totales)
        self.assertFalse(any(t.endswith("$ 0") for t in totales), totales)
        tablas = self.tablas(app)
        # MSU649 está anulada: no aparece como deuda en el estado de cuenta.
        self.assertNotIn("tabla_detalle_cliente_siigo_MSU", tablas)
        self.assertEqual(list(tablas["tabla_detalle_anuladas_siigo"]["Factura"]), ["MSU649"])

    def test_los_dolares_se_marcan_en_el_estado_de_cuenta(self) -> None:
        app = self.abrir(detalle_cliente_siigo="nit:800999888")  # ANCA
        msu = self.tablas(app)["tabla_detalle_cliente_siigo_MSU"].set_index("Factura")
        self.assertEqual(msu.loc["MSU650", "Saldo pendiente"], "USD 2.000")
        self.assertIn(
            "Saldo pendiente MSU Máquinas y Servicios SAS: $ 610.000 · USD 2.000",
            self.totales_por_empresa(app),
        )

    def test_un_saldo_cero_conocido_es_cero_y_no_raya(self) -> None:
        app = self.abrir(filtro_saldo_siigo="Saldo en cero")
        self.assertEqual(self.kpis(app)["Saldo pendiente"], "$ 0")

    def test_sin_saldo_leido_no_sugiere_que_todo_este_pagado(self) -> None:
        app = self.abrir(filtro_saldo_siigo="Saldo sin dato")
        vacios = " ".join(_texto(b.value) for b in app.markdown if "empty-state" in b.value)
        self.assertIn("sin saldo leído en Siigo", vacios)
        self.assertNotIn("estén pagadas", vacios)
        self.assertEqual(self.kpis(app)["Saldo pendiente"], "—")


if __name__ == "__main__":
    unittest.main()
