"""Pruebas de los cálculos opcionales de impuestos de cartera manual."""

from __future__ import annotations

import unittest

from src.taxes import calculate_tax


class TaxCalculationTests(unittest.TestCase):
    def test_concepto_no_aplicado_es_cero(self) -> None:
        result = calculate_tax(1_000_000, "NO_APLICA")

        self.assertEqual(result.amount_cop, 0)

    def test_porcentaje_se_calcula_sobre_el_subtotal(self) -> None:
        result = calculate_tax(1_000_000, "PORCENTAJE", 19)

        self.assertEqual(result.amount_cop, 190_000)

    def test_valor_fijo_se_conserva_en_pesos(self) -> None:
        result = calculate_tax(1_000_000, "VALOR_FIJO", 45_500)

        self.assertEqual(result.amount_cop, 45_500)

    def test_porcentaje_se_redondea_a_peso_entero(self) -> None:
        result = calculate_tax(1_001, "PORCENTAJE", 2.5)

        self.assertEqual(result.amount_cop, 25)


if __name__ == "__main__":
    unittest.main()
