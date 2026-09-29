"""Conversión de importes digitados con puntos de miles."""

import datetime as dt
import unittest
from unittest import mock

from src import formato
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


class HoyColombiaTests(unittest.TestCase):
    def test_a_las_8_pm_de_colombia_sigue_siendo_hoy_aunque_en_utc_sea_manana(self) -> None:
        utc_1_am = dt.datetime(2026, 9, 30, 1, 0, tzinfo=dt.timezone.utc)

        class Reloj(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return utc_1_am.astimezone(tz)

        with mock.patch.object(formato.dt, "datetime", Reloj):
            self.assertEqual(formato.hoy_colombia(), dt.date(2026, 9, 29))
