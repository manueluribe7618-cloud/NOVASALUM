"""Orden, límites de antigüedad y alcance de las gráficas de cartera."""

from copy import deepcopy
from datetime import date, timedelta
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.ui.portfolio_analysis import (
    AGE_RANGES, NO_DATE, age_range, aging_summary, filter_age,
    portfolio_figures, sort_customer_table, sort_invoices,
)


TODAY = date(2026, 9, 29)


def invoice(id=1, days=0, balance=1000, **changes):
    row = dict(id=id, factura=f"FEBA{id}", fecha=(TODAY - timedelta(days=days)).isoformat(),
               cliente="Cliente SAS", empresa_codigo="NOVASA", saldo_cop=balance)
    row.update(changes)
    return row


class SortingTests(unittest.TestCase):
    def test_money_sort_uses_numeric_values_and_does_not_mutate(self):
        rows = [invoice(1, balance=900), invoice(2, balance=10000), invoice(3, balance=2000)]
        before = deepcopy(rows)
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Saldo: de menor a mayor")], [1, 3, 2])
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Saldo: de mayor a menor")], [2, 3, 1])
        self.assertEqual(rows, before)

    def test_alphabetic_order_handles_accents_case_and_enye(self):
        rows = [invoice(i, cliente=name) for i, name in enumerate(["Zulu", "Ñandú", "álamo", "nube", "Omega", " BETA "])]
        ascending = sort_invoices(rows, "Cliente: A a Z")
        self.assertEqual([r["id"] for r in ascending], [2, 5, 3, 1, 4, 0])
        self.assertEqual(sort_invoices(rows, "Cliente: Z a A"), list(reversed(ascending)))

    def test_invoice_numbers_use_natural_order(self):
        rows = [invoice(10), invoice(2), invoice(100)]
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Factura: de menor a mayor")], [2, 10, 100])

    def test_dates_and_days_order_across_months_and_years(self):
        rows = [invoice(1, days=370), invoice(2, days=1), invoice(3, days=50), invoice(4, fecha=None)]
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Fecha: más antiguas primero")], [1, 3, 2, 4])
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Fecha: más recientes primero")], [2, 3, 1, 4])
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Días en cartera: de mayor a menor", today=TODAY)], [1, 3, 2, 4])
        self.assertEqual([r["id"] for r in sort_invoices(rows, "Días en cartera: de menor a mayor", today=TODAY)], [2, 3, 1, 4])

    def test_siigo_unknown_balances_stay_last_both_directions(self):
        rows = [invoice(1, saldo_siigo=None), invoice(2, saldo_siigo=1000), invoice(3, saldo_siigo=2000)]
        for order, expected in [("Saldo: de menor a mayor", [2, 3, 1]), ("Saldo: de mayor a menor", [3, 2, 1])]:
            self.assertEqual([r["id"] for r in sort_invoices(rows, order, balance_field="saldo_siigo")], expected)

    def test_customer_summary_sorts_displayed_pesos_correctly(self):
        table = pd.DataFrame([{"Cliente": "Zulu", "Saldo pendiente": "$ 900"},
                              {"Cliente": "Álamo", "Saldo pendiente": "$ 10.000"}])
        self.assertEqual(sort_customer_table(table, "Saldo: de menor a mayor")["Cliente"].tolist(), ["Zulu", "Álamo"])
        self.assertEqual(sort_customer_table(table, "Cliente: A a Z")["Cliente"].tolist(), ["Álamo", "Zulu"])


class AgingTests(unittest.TestCase):
    def test_boundaries_do_not_omit_or_double_count_invoices(self):
        cases = {0: 0, 30: 0, 31: 1, 60: 1, 61: 2, 90: 2, 91: 3, 180: 3, 181: 4, 365: 4, 366: 5, 900: 5}
        rows = [invoice(i, days=days) for i, days in enumerate(cases)]
        for days, index in cases.items():
            self.assertEqual(age_range(TODAY - timedelta(days=days), today=TODAY), AGE_RANGES[index])
        result = aging_summary(rows, today=TODAY)
        self.assertEqual(result["Facturas"].sum(), len(rows))
        self.assertEqual(result["Saldo"].sum(), len(rows) * 1000)

    def test_uses_issue_date_not_due_date_and_keeps_unknown_dates_explicit(self):
        rows = [invoice(1, days=61, vencimiento=TODAY.isoformat()), invoice(2, fecha=None), invoice(3, days=-5)]
        result = aging_summary(rows, today=TODAY).set_index("Rango")
        self.assertEqual(result.loc[AGE_RANGES[2], "Saldo"], 1000)
        self.assertEqual(result.loc[NO_DATE, "Saldo"], 1000)
        self.assertEqual(result.loc[AGE_RANGES[0], "Saldo"], 1000)

    def test_zero_negative_annulled_and_unknown_balances_do_not_create_debt(self):
        rows = [invoice(1, balance=900), invoice(2, balance=0), invoice(3, balance=-3),
                invoice(4, balance=None), invoice(5, balance=2000, anulada=1)]
        result = aging_summary(rows, today=TODAY)
        self.assertEqual(result["Saldo"].sum(), 900)
        self.assertEqual(result["Facturas"].sum(), 1)
        self.assertTrue(aging_summary([]).empty)

    def test_filter_and_charts_keep_company_and_age_totals_equal(self):
        rows = [invoice(1, days=31, balance=1200), invoice(2, days=60, balance=300, empresa_codigo="LUAC"),
                invoice(3, days=61, balance=500, empresa_codigo="MSU")]
        selected = filter_age(rows, (AGE_RANGES[1],), today=TODAY)
        self.assertEqual([r["id"] for r in selected], [1, 2])
        summary = aging_summary(selected, today=TODAY)
        company, ages = portfolio_figures(summary)
        self.assertEqual(sum(company.data[0].values), 1500)
        self.assertEqual(sum(ages.data[0].y), 1500)
        self.assertEqual(set(company.data[0].labels), {"NOVASA", "LUAC"})
        self.assertEqual(list(ages.layout.xaxis.categoryarray), list(AGE_RANGES))
        self.assertIn("$ 1.200", [row[0] for row in company.data[0].customdata])
        company.to_json()
        ages.to_json()


def manual_app():
    import datetime as dt
    from unittest.mock import patch
    import streamlit as st
    from src.views import manual
    from tests.test_portfolio_analysis import invoice

    rows = [invoice(1, balance=10000, cliente="Zulu", fecha=(dt.date.today() - dt.timedelta(days=5)).isoformat()),
            invoice(2, balance=900, cliente="Álamo", empresa_codigo="LUAC", fecha=(dt.date.today() - dt.timedelta(days=45)).isoformat()),
            invoice(3, balance=2000, cliente="Beta", fecha=(dt.date.today() - dt.timedelta(days=65)).isoformat())]
    rows = st.session_state.get("test_rows", rows)
    for row in rows:
        row.update(cliente_id=row["id"], descripcion="Servicio", placas="ABC123", subtotal_cop=row["saldo_cop"],
                   iva_cop=0, retefuente_cop=0, ica_cop=0, descuento_cop=0, abonos_cop=0,
                   total_cop=row["saldo_cop"], estado="PENDIENTE")

    def capture(table, **kwargs):
        if kwargs["key"].startswith("tabla_cartera_general"):
            st.session_state["visible_ids"] = table["_factura_id"].tolist()
        elif kwargs["key"].startswith("tabla_clientes_manual"):
            st.session_state["customer_summary"] = table.to_dict("records")
        elif kwargs["key"].startswith("tabla_detalle_cliente"):
            st.session_state[kwargs["key"]] = table["_factura_id"].tolist()
        return None

    original_export = manual.render_excel_export

    def capture_export(rows, **kwargs):
        st.session_state["export_ids"] = [row["id"] for row in rows]
        original_export(rows, **kwargs)

    company = st.session_state.get("filtro_empresa_manual", "TODAS")
    with patch.object(manual.db, "listar_facturas", lambda code=None: [r for r in rows if code is None or r["empresa_codigo"] == code]), \
            patch.object(manual.db, "hay_datos", return_value=True), patch.object(manual, "_render_grid", capture), \
            patch.object(manual, "render_excel_export", capture_export):
        manual.render_manual_portfolio(company)


class PortfolioUiTests(unittest.TestCase):
    def test_customer_detail_matches_age_filter_summary_and_export(self):
        today = date.today()
        app = AppTest.from_function(manual_app, default_timeout=40)
        app.session_state["test_rows"] = [
            invoice(1, fecha=(today - timedelta(days=5)).isoformat(), balance=10000),
            invoice(2, fecha=(today - timedelta(days=45)).isoformat(), balance=2000),
            invoice(3, fecha=(today - timedelta(days=50)).isoformat(), balance=900),
        ]
        app.run()
        app.selectbox(key="detalle_cliente_manual").select("Cliente SAS").run()
        app.multiselect(key="filtro_dias_manual").set_value([AGE_RANGES[1]])
        app.selectbox(key="orden_facturas_manual").select("Saldo: de menor a mayor").run()
        app.radio(key="exportar_alcance_manual").set_value("Solo la vista filtrada").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["visible_ids"], [3, 2])
        self.assertEqual(app.session_state["export_ids"], [3, 2])
        self.assertEqual(app.session_state["customer_summary"][0]["Saldo pendiente"], "$ 2.900")
        self.assertEqual(app.session_state["tabla_detalle_cliente_NOVASA"], [3, 2])
        totals = " ".join(m.value for m in app.markdown if "statement-total-badge" in m.value)
        self.assertIn("$ 2.900", totals)
        next(button for button in app.button if button.label == "Limpiar filtros").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["tabla_detalle_cliente_NOVASA"], [3, 2, 1])

    def test_dropdown_sort_and_combined_filters_update_table_kpis_and_charts(self):
        app = AppTest.from_function(manual_app, default_timeout=40).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")), 2)
        app.selectbox(key="orden_facturas_manual").select("Saldo: de menor a mayor").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["visible_ids"], [2, 3, 1])
        app.selectbox(key="orden_facturas_manual").select("Cliente: Z a A").run()
        self.assertEqual(app.session_state["visible_ids"], [1, 3, 2])
        app.multiselect(key="filtro_dias_manual").set_value([AGE_RANGES[1]]).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["visible_ids"], [2])
        self.assertIn("$ 900", " ".join(block.value for block in app.markdown))
        self.assertEqual(len(app.get("plotly_chart")), 2)
        app.text_input(key="filtro_facturas_manual").set_value("sin coincidencia").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")), 0)
        self.assertIn("$ 0", " ".join(block.value for block in app.markdown))
        next(button for button in app.button if button.label == "Limpiar filtros").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.multiselect(key="filtro_dias_manual").value, [])
        self.assertEqual(len(app.get("plotly_chart")), 2)

    def test_full_export_ignores_view_filters_and_filtered_export_respects_them(self):
        app = AppTest.from_function(manual_app, default_timeout=40).run()
        app.selectbox(key="filtro_empresa_manual").select("LUAC").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["visible_ids"], [2])
        self.assertEqual(app.session_state["export_ids"], [1, 2, 3])
        app.radio(key="exportar_alcance_manual").set_value("Solo la vista filtrada").run()
        self.assertEqual(app.session_state["export_ids"], [2])
        app.button(key="actualizar_manual").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="filtro_empresa_manual").value, "LUAC")
        self.assertEqual(app.session_state["visible_ids"], [2])
        self.assertEqual(app.session_state["export_ids"], [2])


if __name__ == "__main__":
    unittest.main()
