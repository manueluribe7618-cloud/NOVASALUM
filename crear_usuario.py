"""Crea una cuenta de NOVASALUM desde la terminal.

Herramienta heredada de cuentas en base de datos. El ingreso web utiliza
exclusivamente la sección [acceso] de los Secrets de Streamlit; crear una
cuenta aquí no habilita el acceso web.

Uso:
    python crear_usuario.py

La contraseña no se ve mientras se escribe y nunca queda guardada en el
historial de la terminal.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _cargar_secretos() -> None:
    """Lee .streamlit/secrets.toml para saber a qué base conectarse."""

    archivo = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not archivo.exists():
        return
    try:
        import tomllib

        datos = tomllib.loads(archivo.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"No se pudo leer {archivo.name}: {exc}")
        return
    url = str(datos.get("SUPABASE_DB_URL", "")).strip()
    if url and not url.startswith("PEGA_"):
        os.environ["SUPABASE_DB_URL"] = url


def main() -> int:
    _cargar_secretos()
    from src import autenticacion as auth
    from src import database as db

    print("=" * 58)
    print("  NOVASALUM · crear una cuenta de acceso")
    print("=" * 58)
    print(f"  Base de datos: {db.descripcion_almacen()}")
    print()

    try:
        primera = not auth.hay_usuarios()
    except Exception as exc:
        print(f"  No fue posible conectar con la base de datos: {exc}")
        return 1

    if primera:
        print("  No hay ninguna cuenta todavía: esta será la primera,")
        print("  y quedará como administradora.")
    else:
        existentes = [u["usuario"] for u in auth.listar_usuarios()]
        print(f"  Cuentas existentes: {', '.join(existentes)}")
    print()

    try:
        usuario = input("  Usuario (por ejemplo: martin): ").strip()
        nombre = input("  Nombre visible (por ejemplo: Martín Guerrero): ").strip()
        if primera:
            rol = "admin"
            print("  Rol: admin")
        else:
            rol = input(f"  Rol {auth.ROLES} [admin]: ").strip() or "admin"
        print()
        print(f"  La contraseña debe tener al menos {auth.MINIMO_CARACTERES} caracteres.")
        print("  No se verá mientras la escribes.")
        clave = getpass.getpass("  Contraseña: ")
        repetida = getpass.getpass("  Repite la contraseña: ")
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelado.")
        return 1

    if clave != repetida:
        print("\n  Las contraseñas no coinciden. No se creó nada.")
        return 1

    try:
        auth.crear_usuario(usuario, clave, nombre=nombre, rol=rol)
    except auth.ErrorAcceso as exc:
        print(f"\n  No se pudo crear: {exc}")
        return 1
    except Exception as exc:
        print(f"\n  Error inesperado ({type(exc).__name__}): {exc}")
        return 1

    print()
    print("  " + "-" * 54)
    print(f"  Cuenta creada: {auth.normalizar_usuario(usuario)}  ·  rol {rol}")
    print("  El ingreso web se configura en [acceso] de los Secrets de Streamlit.")
    print("  " + "-" * 54)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
