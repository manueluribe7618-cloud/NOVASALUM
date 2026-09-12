"""La cartera Siigo es independiente de la cartera manual.

No basta con revisar los imports: estas pruebas comprueban el comportamiento.
Si mañana alguien lee la base manual desde la vista Siigo, o reutiliza una
clave de sesión del manual, estas pruebas lo dicen.
"""

from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


CLAVES_DEL_MANUAL = (
    "filtro_facturas_manual",
    "filtro_empresa_manual",
    "filtro_clientes_manual",
    "filtro_estados_manual",
    "filtro_anio_manual",
    "filtro_mes_manual",
    "filtro_saldo_manual",
    "detalle_cliente_manual",
    "ultima_edicion_grilla",
    "empresa_activa",
)


def _vista_siigo_con_base_rota() -> None:
    """Renderiza la cartera Siigo con toda lectura de la base manual rota."""

    import sys

    sys.path.insert(0, r"D:\NOVASALUM")
    from unittest.mock import patch

    from src import database as db
    from src.siigo_muestra import cargar_muestra
    from src.views.siigo import _publicar, render_siigo_portfolio

    def prohibido(*args, **kwargs):
        raise AssertionError("la cartera Siigo no debe leer la cartera manual")

    with patch.object(db, "listar_facturas", prohibido), \
            patch.object(db, "hay_datos", prohibido), \
            patch.object(db, "resumen_actividad", prohibido), \
            patch.object(db, "clientes_con_saldo", prohibido), \
            patch.object(db, "obtener_factura", prohibido), \
            patch.object(db, "listar_nombres_clientes", prohibido):
        _publicar(cargar_muestra())
        render_siigo_portfolio("TODAS")


def _vista_siigo_sin_lectura() -> None:
    """Primera apertura: nunca se ha consultado Siigo y no hay credenciales."""

    import sys

    sys.path.insert(0, r"D:\NOVASALUM")
    from src.views.siigo import render_siigo_portfolio

    render_siigo_portfolio("TODAS")


class IndependenciaTests(unittest.TestCase):
    def test_se_pinta_aunque_la_base_manual_este_rota(self) -> None:
        prueba = AppTest.from_function(_vista_siigo_con_base_rota, default_timeout=90)
        prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)

    def test_no_deja_ninguna_clave_de_la_cartera_manual(self) -> None:
        prueba = AppTest.from_function(_vista_siigo_con_base_rota, default_timeout=90)
        prueba.run()
        presentes = [
            clave for clave in CLAVES_DEL_MANUAL
            if clave in prueba.session_state.filtered_state
        ]
        self.assertEqual(presentes, [])

    def test_sin_credenciales_avisa_en_vez_de_caerse(self) -> None:
        prueba = AppTest.from_function(_vista_siigo_sin_lectura, default_timeout=90)
        prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)
        textos = " ".join(bloque.value for bloque in prueba.info)
        self.assertIn("credenciales", textos.casefold())

    def test_la_cabecera_no_ofrece_escritura_fuera_de_la_cartera_manual(self) -> None:
        def cabecera_siigo() -> None:
            import sys

            sys.path.insert(0, r"D:\NOVASALUM")
            from src.ui.layout import render_page_header

            render_page_header(view="Espejo Siigo")

        prueba = AppTest.from_function(cabecera_siigo, default_timeout=60)
        prueba.run()
        self.assertFalse(prueba.exception, prueba.exception)
        etiquetas = [boton.label for boton in prueba.button]
        self.assertEqual(etiquetas, [])

    def test_cada_cartera_elige_su_propia_empresa(self) -> None:
        def empresas_separadas() -> None:
            import sys

            sys.path.insert(0, r"D:\NOVASALUM")
            import streamlit as st

            from src.ui.layout import active_company

            st.session_state["filtro_empresa_manual"] = "NOVASA"
            st.session_state["filtro_empresa_siigo"] = "LUAC"
            st.write(f"manual={active_company('manual')}")
            st.write(f"siigo={active_company('siigo')}")

        prueba = AppTest.from_function(empresas_separadas, default_timeout=60)
        prueba.run()
        textos = [bloque.value for bloque in prueba.markdown]
        self.assertIn("manual=NOVASA", textos)
        self.assertIn("siigo=LUAC", textos)


if __name__ == "__main__":
    unittest.main()
