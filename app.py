"""Punto de entrada de Streamlit para NOVASALUM.

La composición de la aplicación vive en ``src.app_shell``. Mantener este
archivo mínimo permite escalar las vistas, los componentes y la lógica de
negocio sin convertir el punto de entrada en un módulo monolítico.
"""

from src.app_shell import run_application


if __name__ == "__main__":
    run_application()
