"""Conversión de importes digitados con puntos de miles."""

import unittest

from src.formato import parse_cop


class ParseCopTests(unittest.TestCase):
    def test_acepta_pesos_con_y_sin_separadores(self) -> None:
        for text, expected in (
            ("1500000", 1_500_000),
            ("1.500.000", 1_500_000),
            ("$ 1.500.000", 1_500_000),
            (" 12.247.644 ", 12_247_644),
            ("0", 0),
            ("999", 999),
            ("1.000", 1_000),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_cop(text), expected)

    def test_rechaza_formatos_ambiguos_sin_cambiar_su_magnitud(self) -> None:
        for text in ("", "1.5", "1..000", "1.000.00", "1,000", "1.000,50", "-1000", "1e6", "abc"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_cop(text)


if __name__ == "__main__":
    unittest.main()
