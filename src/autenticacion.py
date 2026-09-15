"""Control de acceso de NOVASALUM: credenciales de Secrets e intentos.

El ingreso web lee usuario y contraseña exclusivamente de los Secrets de
Streamlit. La base conserva metadatos y vigilancia, sin copiar esa contraseña
ni su hash. Las funciones de cuentas locales se mantienen para compatibilidad
con herramientas anteriores y no habilitan el acceso a la interfaz.

Decisiones de seguridad que sostienen este módulo, por si algún día hay que
revisarlas:

- Para verificar las contraseñas se usa ``scrypt`` (en memoria para Secrets;
  persistido solo por las herramientas de cuentas heredadas): cada
  intento cuesta unos 30 ms y 16 MB. Probar millones de contraseñas deja de ser
  práctico, y ni siquiera quien tenga la base puede deshacer el resultado.
- Cada contraseña lleva su propia sal aleatoria, así dos personas con la misma
  contraseña producen resultados distintos y no se puede atacar a todas a la vez.
- La comparación se hace con ``hmac.compare_digest``, que tarda lo mismo
  acierte o falle. Una comparación normal revela la contraseña carácter por
  carácter según lo que se demore.
- Cuando el usuario no existe igual se calcula un hash de relleno, para que
  responder tarde lo mismo. Si no, el tiempo de respuesta delataría qué
  nombres de usuario son reales.
- Todo intento —bueno o malo— queda registrado, y la cuenta se bloquea sola
  tras varios fallos seguidos.

Este módulo no importa Streamlit: se prueba entero sin levantar la interfaz.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import hmac
from pathlib import Path
import re
import secrets
from typing import Any, Mapping

from src.database import ErrorCartera, _lectura, _transaccion, _insertar, inicializar


# Parámetros de scrypt. Medido en el equipo del proyecto: ~30 ms y 16 MB por
# intento. Quedan escritos dentro de cada hash, así que subirlos más adelante
# no invalida las contraseñas ya guardadas.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
LONGITUD_CLAVE = 32
LONGITUD_SAL = 16

# Política de intentos.
MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15
# Fallos en la última hora a partir de los cuales se considera que alguien está
# probando contraseñas por fuerza bruta y se avisa en el panel de seguridad.
UMBRAL_ALERTA = 10

MINIMO_CARACTERES = 8
ROLES = ("admin", "finanzas")


class ErrorAcceso(ErrorCartera):
    """El ingreso no se puede completar. El mensaje es apto para mostrar."""


@dataclass(frozen=True)
class Usuario:
    """Identidad de quien está usando la aplicación."""

    id: int
    usuario: str
    nombre: str
    rol: str

    @property
    def es_admin(self) -> bool:
        return self.rol == "admin"


@dataclass(frozen=True)
class CredencialConfigurada:
    """Verificador de la cuenta de Secrets; no conserva la contraseña en claro."""

    usuario: str
    clave_hash: str = field(repr=False)
    revision: str = field(repr=False)


_CLAVE_REVISION = secrets.token_bytes(32)

# La credencial vigente, memorizada por su revisión. ``usuario_actual`` se
# llama en CADA rerun de Streamlit y solo necesita el usuario y la revisión;
# sin esta memoria se pagaba un scrypt completo (~30 ms y 16 MB) en cada clic.
# La llave del diccionario es el HMAC de revisión, no la contraseña, y se
# calcula con una clave aleatoria de este proceso. Guarda una sola entrada:
# cambiar la contraseña en los Secrets deja fuera a la anterior.
_CREDENCIAL_VIGENTE: dict[str, "CredencialConfigurada"] = {}


def credencial_desde_secretos(secretos: Mapping[str, Any]) -> CredencialConfigurada:
    """La sección [acceso] es la única fuente de credenciales de la web."""

    seccion = secretos.get("acceso")
    if not isinstance(seccion, Mapping):
        raise ErrorAcceso("Configura el usuario y la contraseña en los Secrets de Streamlit.")
    usuario = seccion.get("usuario")
    clave = seccion.get("contrasena")
    if not isinstance(usuario, str) or not isinstance(clave, str) or not usuario.strip() or not clave:
        raise ErrorAcceso("Completa usuario y contrasena en la sección [acceso] de los Secrets de Streamlit.")
    if usuario.startswith("CAMBIA_") or clave.startswith("CAMBIA_"):
        raise ErrorAcceso("Reemplaza los valores de ejemplo del acceso en los Secrets de Streamlit.")
    normalizado = normalizar_usuario(usuario)
    revisar_fortaleza(clave)
    revision = hmac.new(
        _CLAVE_REVISION, (normalizado + "\0" + clave).encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    memorizada = _CREDENCIAL_VIGENTE.get(revision)
    if memorizada is not None:
        return memorizada
    credencial = CredencialConfigurada(normalizado, hash_clave(clave), revision)
    # Se reemplaza el diccionario entero: la revisión anterior deja de valer.
    _CREDENCIAL_VIGENTE.clear()
    _CREDENCIAL_VIGENTE[revision] = credencial
    return credencial


# --------------------------------------------------------------------------
# Contraseñas
# --------------------------------------------------------------------------

def _codificar(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def hash_clave(clave: str) -> str:
    """Convierte una contraseña en un texto que se puede guardar sin riesgo.

    El resultado incluye los parámetros usados, para poder endurecerlos después
    sin dejar inservibles las contraseñas existentes.
    """

    sal = secrets.token_bytes(LONGITUD_SAL)
    derivada = hashlib.scrypt(
        clave.encode("utf-8"), salt=sal,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=LONGITUD_CLAVE,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_codificar(sal)}${_codificar(derivada)}"


# Hash de relleno: se verifica contra él cuando el usuario no existe, para que
# la respuesta tarde lo mismo y no se pueda averiguar qué usuarios son reales.
_HASH_SEÑUELO = hash_clave(secrets.token_urlsafe(32))


def verificar_clave(clave: str, almacenado: str) -> bool:
    """Comprueba una contraseña contra lo guardado, en tiempo constante."""

    try:
        etiqueta, n, r, p, sal, esperado = str(almacenado).split("$")
        if etiqueta != "scrypt":
            return False
        derivada = hashlib.scrypt(
            clave.encode("utf-8"),
            salt=base64.b64decode(sal),
            n=int(n), r=int(r), p=int(p),
            dklen=len(base64.b64decode(esperado)),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(derivada, base64.b64decode(esperado))


def revisar_fortaleza(clave: str) -> None:
    """Rechaza contraseñas que no protegerían nada. Lanza ``ErrorAcceso``."""

    if len(clave) < MINIMO_CARACTERES:
        raise ErrorAcceso(
            f"La contraseña debe tener al menos {MINIMO_CARACTERES} caracteres."
        )
    if clave.isdigit():
        raise ErrorAcceso("La contraseña no puede ser solo números.")
    corrientes = {
        "12345678", "contrasena", "contraseña", "password", "novasalum",
        "qwertyui", "administrador", "11111111",
    }
    if clave.casefold() in corrientes:
        raise ErrorAcceso("Esa contraseña es demasiado común. Elige otra.")


def normalizar_usuario(valor: Any) -> str:
    """Los nombres de usuario no distinguen mayúsculas ni llevan espacios."""

    texto = str(valor or "").strip().casefold()
    if not texto:
        raise ErrorAcceso("El usuario es obligatorio.")
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", texto):
        raise ErrorAcceso(
            "El usuario debe tener entre 3 y 40 caracteres: letras, números, "
            "punto, guion o guion bajo."
        )
    return texto


def _ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Administración de usuarios
# --------------------------------------------------------------------------

def hay_usuarios(ruta: str | Path | None = None) -> bool:
    """Indica si ya existe al menos una cuenta creada."""

    inicializar(ruta)
    with _lectura(ruta) as conexion:
        fila = conexion.execute("SELECT COUNT(*) AS total FROM usuarios").fetchone()
    return int(dict(fila)["total"]) > 0


def crear_usuario(
    usuario: str,
    clave: str,
    *,
    nombre: str = "",
    rol: str = "admin",
    ruta: str | Path | None = None,
) -> int:
    """Crea una cuenta. Se guarda un hash de la contraseña, nunca el texto."""

    nombre_usuario = normalizar_usuario(usuario)
    revisar_fortaleza(clave)
    if rol not in ROLES:
        raise ErrorAcceso(f"El rol debe ser uno de: {', '.join(ROLES)}.")
    visible = str(nombre or "").strip() or nombre_usuario
    inicializar(ruta)
    with _transaccion(ruta) as conexion:
        existente = conexion.execute(
            "SELECT id FROM usuarios WHERE usuario = ?", (nombre_usuario,)
        ).fetchone()
        if existente:
            raise ErrorAcceso(f"El usuario {nombre_usuario} ya existe.")
        marca = _ahora()
        return _insertar(
            conexion,
            """
            INSERT INTO usuarios (
                usuario, nombre, clave_hash, rol, activo,
                intentos_fallidos, creado_en, actualizado_en
            ) VALUES (?, ?, ?, ?, 1, 0, ?, ?)
            """,
            (nombre_usuario, visible, hash_clave(clave), rol, marca, marca),
        )


def cambiar_clave(
    usuario: str,
    clave_actual: str,
    clave_nueva: str,
    ruta: str | Path | None = None,
) -> None:
    """Cambia la contraseña exigiendo la anterior."""

    nombre_usuario = normalizar_usuario(usuario)
    revisar_fortaleza(clave_nueva)
    inicializar(ruta)
    with _transaccion(ruta) as conexion:
        fila = conexion.execute(
            "SELECT clave_hash FROM usuarios WHERE usuario = ?", (nombre_usuario,)
        ).fetchone()
        if not fila or not verificar_clave(clave_actual, dict(fila)["clave_hash"]):
            raise ErrorAcceso("La contraseña actual no es correcta.")
        conexion.execute(
            """
            UPDATE usuarios
            SET clave_hash = ?, actualizado_en = ?, intentos_fallidos = 0,
                bloqueado_hasta = NULL
            WHERE usuario = ?
            """,
            (hash_clave(clave_nueva), _ahora(), nombre_usuario),
        )


def listar_usuarios(ruta: str | Path | None = None) -> list[dict[str, Any]]:
    """Cuentas existentes. Nunca devuelve el hash de la contraseña."""

    inicializar(ruta)
    with _lectura(ruta) as conexion:
        filas = conexion.execute(
            """
            SELECT id, usuario, nombre, rol, activo, intentos_fallidos,
                   bloqueado_hasta, ultimo_ingreso, creado_en
            FROM usuarios ORDER BY usuario
            """
        ).fetchall()
    return [dict(fila) for fila in filas]


def desbloquear(usuario: str, ruta: str | Path | None = None) -> None:
    """Levanta un bloqueo por intentos fallidos."""

    nombre_usuario = normalizar_usuario(usuario)
    inicializar(ruta)
    with _transaccion(ruta) as conexion:
        conexion.execute(
            """
            UPDATE usuarios
            SET intentos_fallidos = 0, bloqueado_hasta = NULL, actualizado_en = ?
            WHERE usuario = ?
            """,
            (_ahora(), nombre_usuario),
        )


# --------------------------------------------------------------------------
# Ingreso
# --------------------------------------------------------------------------

def _registrar_intento(
    conexion: Any, usuario: str, exitoso: bool, motivo: str
) -> None:
    conexion.execute(
        """
        INSERT INTO intentos_ingreso (usuario, exitoso, motivo, creado_en)
        VALUES (?, ?, ?, ?)
        """,
        (usuario, 1 if exitoso else 0, motivo, _ahora()),
    )


def _bloqueo_vigente(valor: Any) -> datetime | None:
    """Devuelve el fin del bloqueo si todavía no ha pasado."""

    if not valor:
        return None
    try:
        hasta = datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None
    ahora = datetime.now().astimezone()
    if hasta.tzinfo is None:
        hasta = hasta.replace(tzinfo=ahora.tzinfo)
    return hasta if hasta > ahora else None


def autenticar(
    usuario: str,
    clave: str,
    ruta: str | Path | None = None,
    *,
    credencial: CredencialConfigurada | None = None,
) -> Usuario:
    """Valida usuario y contraseña. Lanza ``ErrorAcceso`` si no procede.

    Cuenta los fallos seguidos y bloquea la cuenta al superar el límite. El
    mensaje de error nunca dice si el fallo fue por el usuario o por la
    contraseña: decirlo permitiría averiguar qué cuentas existen.
    """

    # IMPORTANTE: ningún ``raise`` puede ocurrir dentro de la transacción. Si
    # ocurriera, el ``rollback`` desharía el conteo de intentos fallidos y el
    # registro del intento, y el bloqueo jamás llegaría a activarse. Por eso el
    # resultado se decide dentro y el error se lanza después de confirmar.
    try:
        nombre_usuario = normalizar_usuario(usuario)
    except ErrorAcceso:
        # Se registra igual: los intentos con usuarios inventados son
        # justamente la señal de que alguien está probando a ciegas.
        inicializar(ruta)
        with _transaccion(ruta) as conexion:
            _registrar_intento(conexion, str(usuario or "")[:40], False, "USUARIO_INVALIDO")
        raise ErrorAcceso("Usuario o contraseña incorrectos.")

    fallo: str | None = None
    identidad: Usuario | None = None

    inicializar(ruta)
    with _transaccion(ruta) as conexion:
        if credencial is not None and nombre_usuario == credencial.usuario:
            # Solo metadatos de intentos y auditoría. La contraseña y su hash
            # configurado permanecen fuera de la base, administrados en Secrets.
            marca = _ahora()
            conexion.execute(
                """
                INSERT INTO usuarios (
                    usuario, nombre, clave_hash, rol, activo, intentos_fallidos,
                    creado_en, actualizado_en
                ) VALUES (?, ?, 'gestionado_en_streamlit', 'admin', 1, 0, ?, ?)
                ON CONFLICT (usuario) DO UPDATE SET
                    clave_hash = 'gestionado_en_streamlit', nombre = excluded.nombre,
                    rol = 'admin'
                """,
                (nombre_usuario, nombre_usuario, marca, marca),
            )
        fila = conexion.execute(
            """
            SELECT id, usuario, nombre, clave_hash, rol, activo, intentos_fallidos,
                   bloqueado_hasta
            FROM usuarios WHERE usuario = ?
            """,
            (nombre_usuario,),
        ).fetchone()
        datos = dict(fila) if fila else None
        if credencial is not None:
            if nombre_usuario != credencial.usuario:
                # Una cuenta antigua de la base no puede saltarse Secrets.
                datos = None
            elif datos is not None:
                datos["clave_hash"] = credencial.clave_hash

        if datos is None:
            # Se gasta el mismo tiempo que con un usuario real.
            verificar_clave(clave, _HASH_SEÑUELO)
            _registrar_intento(conexion, nombre_usuario, False, "NO_EXISTE")
            fallo = "Usuario o contraseña incorrectos."

        elif not int(datos["activo"]):
            _registrar_intento(conexion, nombre_usuario, False, "INACTIVO")
            fallo = "Esta cuenta está desactivada. Habla con el administrador."

        elif (bloqueo := _bloqueo_vigente(datos["bloqueado_hasta"])) is not None:
            _registrar_intento(conexion, nombre_usuario, False, "BLOQUEADO")
            minutos = max(
                1, int((bloqueo - datetime.now().astimezone()).total_seconds() // 60) + 1
            )
            fallo = (
                "Cuenta bloqueada por intentos fallidos. Vuelve a intentar en "
                f"{minutos} minuto(s)."
            )

        elif not verificar_clave(clave, datos["clave_hash"]):
            fallidos = int(datos["intentos_fallidos"]) + 1
            if fallidos >= MAX_INTENTOS:
                hasta = (
                    datetime.now().astimezone() + timedelta(minutes=MINUTOS_BLOQUEO)
                ).isoformat(timespec="seconds")
                conexion.execute(
                    """
                    UPDATE usuarios
                    SET intentos_fallidos = ?, bloqueado_hasta = ?, actualizado_en = ?
                    WHERE id = ?
                    """,
                    (fallidos, hasta, _ahora(), int(datos["id"])),
                )
                _registrar_intento(conexion, nombre_usuario, False, "CLAVE_INCORRECTA_BLOQUEA")
                fallo = (
                    f"Cuenta bloqueada tras {MAX_INTENTOS} intentos fallidos. "
                    f"Vuelve a intentar en {MINUTOS_BLOQUEO} minutos."
                )
            else:
                conexion.execute(
                    "UPDATE usuarios SET intentos_fallidos = ?, actualizado_en = ? WHERE id = ?",
                    (fallidos, _ahora(), int(datos["id"])),
                )
                _registrar_intento(conexion, nombre_usuario, False, "CLAVE_INCORRECTA")
                restantes = MAX_INTENTOS - fallidos
                fallo = (
                    f"Usuario o contraseña incorrectos. Te queda(n) {restantes} "
                    "intento(s) antes de que la cuenta se bloquee."
                )

        else:
            conexion.execute(
                """
                UPDATE usuarios
                SET intentos_fallidos = 0, bloqueado_hasta = NULL,
                    ultimo_ingreso = ?, actualizado_en = ?
                WHERE id = ?
                """,
                (_ahora(), _ahora(), int(datos["id"])),
            )
            _registrar_intento(conexion, nombre_usuario, True, "OK")
            identidad = Usuario(
                id=int(datos["id"]),
                usuario=str(datos["usuario"]),
                nombre=str(datos["nombre"]),
                rol=str(datos["rol"]),
            )

    # Fuera de la transacción: aquí el conteo y el registro ya quedaron firmes.
    if fallo is not None:
        raise ErrorAcceso(fallo)
    assert identidad is not None
    return identidad


# --------------------------------------------------------------------------
# Vigilancia
# --------------------------------------------------------------------------

def intentos_recientes(
    horas: int = 24,
    limite: int = 200,
    ruta: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Intentos de ingreso de las últimas horas, del más reciente al más viejo."""

    desde = (datetime.now().astimezone() - timedelta(hours=horas)).isoformat(timespec="seconds")
    inicializar(ruta)
    with _lectura(ruta) as conexion:
        filas = conexion.execute(
            """
            SELECT usuario, exitoso, motivo, creado_en
            FROM intentos_ingreso
            WHERE creado_en >= ?
            ORDER BY creado_en DESC
            LIMIT ?
            """,
            (desde, int(limite)),
        ).fetchall()
    return [dict(fila) for fila in filas]


def resumen_seguridad(ruta: str | Path | None = None) -> dict[str, Any]:
    """Panorama para el panel de seguridad, con la alerta ya evaluada.

    La alerta se enciende cuando hay muchos fallos en la última hora o cuando
    hay cuentas bloqueadas: las dos señales de que alguien está probando
    contraseñas.
    """

    ahora = datetime.now().astimezone()
    ultima_hora = (ahora - timedelta(hours=1)).isoformat(timespec="seconds")
    ultimo_dia = (ahora - timedelta(hours=24)).isoformat(timespec="seconds")
    inicializar(ruta)
    with _lectura(ruta) as conexion:
        fallos_hora = int(dict(conexion.execute(
            "SELECT COUNT(*) AS n FROM intentos_ingreso WHERE exitoso = 0 AND creado_en >= ?",
            (ultima_hora,),
        ).fetchone())["n"])
        fallos_dia = int(dict(conexion.execute(
            "SELECT COUNT(*) AS n FROM intentos_ingreso WHERE exitoso = 0 AND creado_en >= ?",
            (ultimo_dia,),
        ).fetchone())["n"])
        ingresos_dia = int(dict(conexion.execute(
            "SELECT COUNT(*) AS n FROM intentos_ingreso WHERE exitoso = 1 AND creado_en >= ?",
            (ultimo_dia,),
        ).fetchone())["n"])
        por_usuario = [dict(f) for f in conexion.execute(
            """
            SELECT usuario, COUNT(*) AS fallos
            FROM intentos_ingreso
            WHERE exitoso = 0 AND creado_en >= ?
            GROUP BY usuario
            ORDER BY fallos DESC
            """,
            (ultimo_dia,),
        ).fetchall()]
        bloqueadas = [
            dict(f) for f in conexion.execute(
                "SELECT usuario, bloqueado_hasta FROM usuarios WHERE bloqueado_hasta IS NOT NULL"
            ).fetchall()
        ]

    bloqueadas = [b for b in bloqueadas if _bloqueo_vigente(b["bloqueado_hasta"])]
    alerta = fallos_hora >= UMBRAL_ALERTA or bool(bloqueadas)
    if alerta and bloqueadas:
        motivo = (
            f"{len(bloqueadas)} cuenta(s) bloqueada(s) por intentos fallidos: "
            + ", ".join(b["usuario"] for b in bloqueadas)
        )
    elif alerta:
        motivo = (
            f"{fallos_hora} intentos fallidos en la última hora "
            f"(el umbral de aviso es {UMBRAL_ALERTA})"
        )
    else:
        motivo = ""
    return {
        "alerta": alerta,
        "motivo": motivo,
        "fallos_ultima_hora": fallos_hora,
        "fallos_ultimo_dia": fallos_dia,
        "ingresos_ultimo_dia": ingresos_dia,
        "fallos_por_usuario": por_usuario,
        "cuentas_bloqueadas": bloqueadas,
    }


__all__ = [
    "ErrorAcceso",
    "MAX_INTENTOS",
    "MINUTOS_BLOQUEO",
    "ROLES",
    "UMBRAL_ALERTA",
    "Usuario",
    "CredencialConfigurada",
    "autenticar",
    "cambiar_clave",
    "credencial_desde_secretos",
    "crear_usuario",
    "desbloquear",
    "hash_clave",
    "hay_usuarios",
    "intentos_recientes",
    "listar_usuarios",
    "normalizar_usuario",
    "resumen_seguridad",
    "revisar_fortaleza",
    "verificar_clave",
]
