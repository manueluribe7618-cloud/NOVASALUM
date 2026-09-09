"""Persistencia de la cartera manual de NOVASALUM.

La aplicación puede funcionar desde el primer día sin depender de una conexión
externa: este módulo guarda exclusivamente la cartera operativa en SQLite. Las
lecturas de Siigo permanecen separadas y nunca pasan por estas tablas.

Todas las escrituras financieras se hacen dentro de una transacción. Los valores
monetarios se almacenan como pesos enteros para evitar diferencias de redondeo.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping, Sequence


EMPRESAS: dict[str, dict[str, str]] = {
    "NOVASA": {
        "nombre": "NOVASA Logistic SAS",
        "prefijo": "FEBA",
        "color": "#2563EB",
    },
    "LUAC": {
        "nombre": "LUAC Cargo SAS",
        "prefijo": "LUA",
        "color": "#059669",
    },
    "MSU": {
        "nombre": "MSU Máquinas y Servicios SAS",
        "prefijo": "MSU",
        "color": "#7C3AED",
    },
}


class ErrorCartera(ValueError):
    """Un dato impediría guardar una operación contable consistente."""


def _ruta_base(ruta: str | Path | None = None) -> Path:
    if ruta is not None:
        return Path(ruta).expanduser().resolve()
    configurada = os.getenv("NOVASALUM_DB", "").strip()
    if configurada:
        return Path(configurada).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "novasalum.db"


def _conexion(ruta: str | Path | None = None) -> sqlite3.Connection:
    destino = _ruta_base(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(str(destino), timeout=30, isolation_level=None)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 30000")
    conexion.execute("PRAGMA journal_mode = WAL")
    return conexion


@contextmanager
def _transaccion(ruta: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conexion = _conexion(ruta)
    try:
        conexion.execute("BEGIN IMMEDIATE")
        yield conexion
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


@contextmanager
def _lectura(ruta: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Entrega una conexión de solo lectura y siempre libera el archivo en Windows."""

    conexion = _conexion(ruta)
    try:
        yield conexion
    finally:
        conexion.close()


def inicializar(ruta: str | Path | None = None) -> None:
    """Crea el esquema y las tres empresas si todavía no existen."""

    with _transaccion(ruta) as conexion:
        conexion.executescript(
            """
            CREATE TABLE IF NOT EXISTS empresas (
                codigo TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                prefijo TEXT NOT NULL,
                color TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_codigo TEXT NOT NULL REFERENCES empresas(codigo),
                nombre TEXT NOT NULL,
                nit TEXT NOT NULL DEFAULT '',
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL,
                UNIQUE (empresa_codigo, nombre, nit)
            );

            CREATE TABLE IF NOT EXISTS facturas_manual (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_codigo TEXT NOT NULL REFERENCES empresas(codigo),
                cliente_id INTEGER NOT NULL REFERENCES clientes(id),
                prefijo TEXT NOT NULL,
                numero TEXT NOT NULL,
                fecha TEXT NOT NULL,
                vencimiento TEXT,
                descripcion TEXT NOT NULL DEFAULT '',
                placas TEXT NOT NULL DEFAULT '',
                subtotal_cop INTEGER NOT NULL DEFAULT 0 CHECK (subtotal_cop >= 0),
                iva_cop INTEGER NOT NULL DEFAULT 0 CHECK (iva_cop >= 0),
                retefuente_cop INTEGER NOT NULL DEFAULT 0 CHECK (retefuente_cop >= 0),
                ica_cop INTEGER NOT NULL DEFAULT 0 CHECK (ica_cop >= 0),
                anulada INTEGER NOT NULL DEFAULT 0 CHECK (anulada IN (0, 1)),
                creada_en TEXT NOT NULL,
                actualizada_en TEXT NOT NULL,
                UNIQUE (empresa_codigo, prefijo, numero)
            );

            CREATE TABLE IF NOT EXISTS abonos_manual (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_codigo TEXT NOT NULL REFERENCES empresas(codigo),
                cliente_id INTEGER NOT NULL REFERENCES clientes(id),
                fecha TEXT NOT NULL,
                referencia TEXT NOT NULL DEFAULT '',
                monto_cop INTEGER NOT NULL CHECK (monto_cop > 0),
                saldo_a_favor_cop INTEGER NOT NULL DEFAULT 0 CHECK (saldo_a_favor_cop >= 0),
                creado_en TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS aplicaciones_abono (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                abono_id INTEGER NOT NULL REFERENCES abonos_manual(id) ON DELETE CASCADE,
                factura_id INTEGER NOT NULL REFERENCES facturas_manual(id),
                monto_cop INTEGER NOT NULL CHECK (monto_cop > 0),
                creado_en TEXT NOT NULL,
                UNIQUE (abono_id, factura_id)
            );

            CREATE TABLE IF NOT EXISTS revisiones_conciliacion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_codigo TEXT NOT NULL REFERENCES empresas(codigo),
                factura_clave TEXT NOT NULL,
                estado TEXT NOT NULL,
                observacion TEXT NOT NULL DEFAULT '',
                manual_json TEXT NOT NULL,
                siigo_json TEXT NOT NULL,
                revisado_en TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entidad TEXT NOT NULL,
                entidad_id TEXT NOT NULL,
                accion TEXT NOT NULL,
                detalle TEXT NOT NULL,
                creado_en TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_facturas_empresa_fecha
                ON facturas_manual(empresa_codigo, fecha);
            CREATE INDEX IF NOT EXISTS idx_facturas_cliente
                ON facturas_manual(cliente_id);
            CREATE INDEX IF NOT EXISTS idx_abonos_cliente
                ON abonos_manual(cliente_id, fecha);
            CREATE INDEX IF NOT EXISTS idx_aplicaciones_factura
                ON aplicaciones_abono(factura_id);
            """
        )
        for codigo, datos in EMPRESAS.items():
            conexion.execute(
                """
                INSERT OR IGNORE INTO empresas (codigo, nombre, prefijo, color)
                VALUES (?, ?, ?, ?)
                """,
                (codigo, datos["nombre"], datos["prefijo"], datos["color"]),
            )


def _ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _texto(valor: Any, campo: str, *, obligatorio: bool = False) -> str:
    texto = str(valor or "").strip()
    if obligatorio and not texto:
        raise ErrorCartera(f"{campo} es obligatorio.")
    return texto


def _empresa(valor: Any) -> str:
    codigo = _texto(valor, "Empresa", obligatorio=True).upper()
    if codigo not in EMPRESAS:
        raise ErrorCartera("La empresa seleccionada no existe.")
    return codigo


def _pesos(valor: Any, campo: str, *, permite_cero: bool = True) -> int:
    if isinstance(valor, bool):
        raise ErrorCartera(f"{campo} debe ser un valor numérico.")
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ErrorCartera(f"{campo} debe ser un valor numérico.") from exc
    if numero != numero or numero in (float("inf"), float("-inf")):
        raise ErrorCartera(f"{campo} no tiene un valor válido.")
    redondeado = int(round(numero))
    if redondeado < 0 or (not permite_cero and redondeado == 0):
        operador = "mayor que cero" if not permite_cero else "igual o mayor que cero"
        raise ErrorCartera(f"{campo} debe ser {operador}.")
    return redondeado


def _fecha(valor: Any, campo: str, *, obligatoria: bool = True) -> str | None:
    if valor is None or valor == "":
        if obligatoria:
            raise ErrorCartera(f"{campo} es obligatoria.")
        return None
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        return valor.isoformat()
    try:
        return date.fromisoformat(str(valor)[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise ErrorCartera(f"{campo} debe tener formato de fecha válido.") from exc


def _total_factura(fila: Mapping[str, Any]) -> int:
    return (
        int(fila["subtotal_cop"])
        + int(fila["iva_cop"])
        - int(fila["retefuente_cop"])
        - int(fila["ica_cop"])
    )


def _registrar(
    conexion: sqlite3.Connection,
    entidad: str,
    entidad_id: str | int,
    accion: str,
    detalle: Mapping[str, Any],
) -> None:
    conexion.execute(
        """
        INSERT INTO auditoria (entidad, entidad_id, accion, detalle, creado_en)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            entidad,
            str(entidad_id),
            accion,
            json.dumps(dict(detalle), ensure_ascii=False, default=str, sort_keys=True),
            _ahora(),
        ),
    )


def _cliente_id(
    conexion: sqlite3.Connection,
    empresa_codigo: str,
    nombre: Any,
) -> int:
    nombre_limpio = _texto(nombre, "Cliente", obligatorio=True)
    encontrado = conexion.execute(
        """
        SELECT id FROM clientes
        WHERE empresa_codigo = ? AND nombre = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (empresa_codigo, nombre_limpio),
    ).fetchone()
    if encontrado:
        return int(encontrado["id"])

    marca = _ahora()
    cursor = conexion.execute(
        """
        INSERT INTO clientes (empresa_codigo, nombre, nit, creado_en, actualizado_en)
        VALUES (?, ?, ?, ?, ?)
        """,
        (empresa_codigo, nombre_limpio, "", marca, marca),
    )
    return int(cursor.lastrowid)


def crear_factura(datos: Mapping[str, Any], ruta: str | Path | None = None) -> int:
    """Registra una factura manual y devuelve su identificador."""

    inicializar(ruta)
    empresa = _empresa(datos.get("empresa_codigo"))
    prefijo = _texto(datos.get("prefijo"), "Prefijo", obligatorio=True).upper()
    numero = _texto(datos.get("numero"), "Número de factura", obligatorio=True).upper()
    fecha = _fecha(datos.get("fecha"), "Fecha de emisión")
    vencimiento = _fecha(datos.get("vencimiento"), "Fecha de vencimiento", obligatoria=False)
    if vencimiento and vencimiento < fecha:
        raise ErrorCartera("El vencimiento no puede ser anterior a la fecha de emisión.")
    valores = {
        "subtotal_cop": _pesos(datos.get("subtotal_cop", 0), "Subtotal"),
        "iva_cop": _pesos(datos.get("iva_cop", 0), "IVA"),
        "retefuente_cop": _pesos(datos.get("retefuente_cop", 0), "Retefuente"),
        "ica_cop": _pesos(datos.get("ica_cop", 0), "ICA"),
    }
    if _total_factura(valores) <= 0:
        raise ErrorCartera("El total de la factura debe ser mayor que cero.")

    with _transaccion(ruta) as conexion:
        cliente_id = _cliente_id(conexion, empresa, datos.get("cliente"))
        try:
            cursor = conexion.execute(
                """
                INSERT INTO facturas_manual (
                    empresa_codigo, cliente_id, prefijo, numero, fecha, vencimiento,
                    descripcion, placas, subtotal_cop, iva_cop, retefuente_cop, ica_cop,
                    creada_en, actualizada_en
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    empresa,
                    cliente_id,
                    prefijo,
                    numero,
                    fecha,
                    vencimiento,
                    _texto(datos.get("descripcion"), "Detalle del servicio"),
                    _texto(datos.get("placas"), "Placas"),
                    valores["subtotal_cop"],
                    valores["iva_cop"],
                    valores["retefuente_cop"],
                    valores["ica_cop"],
                    _ahora(),
                    _ahora(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ErrorCartera(
                f"La factura {prefijo}{numero} ya existe para {empresa}."
            ) from exc
        factura_id = int(cursor.lastrowid)
        _registrar(
            conexion,
            "factura_manual",
            factura_id,
            "CREADA",
            {"empresa": empresa, "factura": f"{prefijo}{numero}", **valores},
        )
        return factura_id


def _factura_para_editar(
    conexion: sqlite3.Connection,
    factura_id: int,
) -> sqlite3.Row:
    fila = conexion.execute(
        """
        SELECT f.*, COALESCE(SUM(a.monto_cop), 0) AS abonos_cop
        FROM facturas_manual f
        LEFT JOIN aplicaciones_abono a ON a.factura_id = f.id
        WHERE f.id = ?
        GROUP BY f.id
        """,
        (factura_id,),
    ).fetchone()
    if fila is None:
        raise ErrorCartera("La factura que intentas editar no existe.")
    if int(fila["anulada"]):
        raise ErrorCartera("No se puede editar una factura anulada.")
    return fila


def actualizar_campos_factura(
    factura_id: int,
    datos: Mapping[str, Any],
    ruta: str | Path | None = None,
) -> None:
    """Actualiza los campos operativos editables sin alterar los abonos aplicados."""

    inicializar(ruta)
    with _transaccion(ruta) as conexion:
        anterior = _factura_para_editar(conexion, int(factura_id))
        valores = {
            "subtotal_cop": _pesos(datos.get("subtotal_cop"), "Subtotal"),
            "iva_cop": _pesos(datos.get("iva_cop"), "IVA"),
            "retefuente_cop": _pesos(datos.get("retefuente_cop"), "Retefuente"),
            "ica_cop": _pesos(datos.get("ica_cop"), "ICA"),
        }
        total = _total_factura(valores)
        if total <= 0:
            raise ErrorCartera("El total de la factura debe ser mayor que cero.")
        if total < int(anterior["abonos_cop"]):
            raise ErrorCartera(
                "El total nuevo no puede ser menor que los abonos ya aplicados."
            )
        conexion.execute(
            """
            UPDATE facturas_manual
            SET descripcion = ?, placas = ?, subtotal_cop = ?, iva_cop = ?,
                retefuente_cop = ?, ica_cop = ?, actualizada_en = ?
            WHERE id = ?
            """,
            (
                _texto(datos.get("descripcion"), "Detalle del servicio"),
                _texto(datos.get("placas"), "Placas"),
                valores["subtotal_cop"],
                valores["iva_cop"],
                valores["retefuente_cop"],
                valores["ica_cop"],
                _ahora(),
                int(factura_id),
            ),
        )
        _registrar(
            conexion,
            "factura_manual",
            factura_id,
            "ACTUALIZADA",
            {"antes": dict(anterior), "despues": dict(datos), "total_cop": total},
        )


def anular_factura(
    factura_id: int,
    ruta: str | Path | None = None,
) -> None:
    """Anula una factura sin borrar su rastro. No permite anular facturas abonadas."""

    inicializar(ruta)
    with _transaccion(ruta) as conexion:
        factura = _factura_para_editar(conexion, int(factura_id))
        if int(factura["abonos_cop"]) > 0:
            raise ErrorCartera(
                "No se puede anular una factura con abonos; primero revisa el pago."
            )
        conexion.execute(
            "UPDATE facturas_manual SET anulada = 1, actualizada_en = ? WHERE id = ?",
            (_ahora(), int(factura_id)),
        )
        _registrar(
            conexion,
            "factura_manual",
            factura_id,
            "ANULADA",
            {"factura": f"{factura['prefijo']}{factura['numero']}"},
        )


def _filas_facturas(
    conexion: sqlite3.Connection,
    empresa_codigo: str | None = None,
    *,
    incluir_anuladas: bool = False,
) -> list[dict[str, Any]]:
    parametros: list[Any] = []
    filtros: list[str] = []
    if empresa_codigo:
        filtros.append("f.empresa_codigo = ?")
        parametros.append(_empresa(empresa_codigo))
    if not incluir_anuladas:
        filtros.append("f.anulada = 0")
    clausula = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    consulta = f"""
        SELECT
            f.id, f.empresa_codigo, f.prefijo, f.numero, f.fecha, f.vencimiento,
            f.descripcion, f.placas, f.subtotal_cop, f.iva_cop, f.retefuente_cop,
            f.ica_cop, f.anulada, f.creada_en, f.actualizada_en,
            c.id AS cliente_id, c.nombre AS cliente, c.nit AS nit,
            COALESCE(SUM(a.monto_cop), 0) AS abonos_cop
        FROM facturas_manual f
        INNER JOIN clientes c ON c.id = f.cliente_id
        LEFT JOIN aplicaciones_abono a ON a.factura_id = f.id
        {clausula}
        GROUP BY f.id
        ORDER BY f.fecha ASC, f.id ASC
    """
    hoy = date.today()
    filas: list[dict[str, Any]] = []
    for fila_cruda in conexion.execute(consulta, parametros).fetchall():
        fila = dict(fila_cruda)
        total = _total_factura(fila)
        saldo = total - int(fila["abonos_cop"])
        vencimiento = fila["vencimiento"]
        vencida = bool(vencimiento and date.fromisoformat(vencimiento) < hoy and saldo > 0)
        if int(fila["anulada"]):
            estado = "ANULADA"
        elif saldo <= 0:
            estado = "PAGADA"
        elif vencida:
            estado = "VENCIDA"
        elif int(fila["abonos_cop"]) > 0:
            estado = "ABONADA"
        else:
            estado = "PENDIENTE"
        fila.update(
            {
                "factura": f"{fila['prefijo']}{fila['numero']}",
                "total_cop": total,
                "saldo_cop": saldo,
                "estado": estado,
                "dias_mora": (
                    max(0, (hoy - date.fromisoformat(vencimiento)).days)
                    if vencida and vencimiento
                    else 0
                ),
            }
        )
        filas.append(fila)
    return filas


def listar_facturas(
    empresa_codigo: str | None = None,
    *,
    incluir_anuladas: bool = False,
    ruta: str | Path | None = None,
) -> list[dict[str, Any]]:
    inicializar(ruta)
    with _lectura(ruta) as conexion:
        return _filas_facturas(
            conexion,
            empresa_codigo,
            incluir_anuladas=incluir_anuladas,
        )


def obtener_factura(
    factura_id: int,
    ruta: str | Path | None = None,
) -> dict[str, Any] | None:
    for factura in listar_facturas(incluir_anuladas=True, ruta=ruta):
        if int(factura["id"]) == int(factura_id):
            return factura
    return None


def resumen_cartera(
    empresa_codigo: str | None = None,
    ruta: str | Path | None = None,
) -> dict[str, int]:
    facturas = listar_facturas(empresa_codigo, ruta=ruta)
    return {
        "total_facturado_cop": sum(int(f["total_cop"]) for f in facturas),
        "total_abonos_cop": sum(int(f["abonos_cop"]) for f in facturas),
        "saldo_cartera_cop": sum(int(f["saldo_cop"]) for f in facturas),
        "facturas_pendientes": sum(1 for f in facturas if int(f["saldo_cop"]) > 0),
        "facturas_vencidas": sum(1 for f in facturas if f["estado"] == "VENCIDA"),
    }


def clientes_con_saldo(
    empresa_codigo: str | None = None,
    ruta: str | Path | None = None,
) -> list[dict[str, Any]]:
    agrupados: dict[tuple[str, int], dict[str, Any]] = {}
    for factura in listar_facturas(empresa_codigo, ruta=ruta):
        if int(factura["saldo_cop"]) <= 0:
            continue
        clave = (str(factura["empresa_codigo"]), int(factura["cliente_id"]))
        cliente = agrupados.setdefault(
            clave,
            {
                "empresa_codigo": factura["empresa_codigo"],
                "cliente_id": int(factura["cliente_id"]),
                "cliente": factura["cliente"],
                "nit": factura["nit"],
                "saldo_cop": 0,
                "facturas_pendientes": 0,
            },
        )
        cliente["saldo_cop"] += int(factura["saldo_cop"])
        cliente["facturas_pendientes"] += 1
    return sorted(
        agrupados.values(),
        key=lambda fila: (-int(fila["saldo_cop"]), str(fila["cliente"]).casefold()),
    )


def facturas_pendientes_cliente(
    empresa_codigo: str,
    cliente_id: int,
    ruta: str | Path | None = None,
) -> list[dict[str, Any]]:
    return [
        factura
        for factura in listar_facturas(empresa_codigo, ruta=ruta)
        if int(factura["cliente_id"]) == int(cliente_id)
        and int(factura["saldo_cop"]) > 0
        and factura["estado"] != "ANULADA"
    ]


def previsualizar_fifo(
    facturas: Sequence[Mapping[str, Any]],
    monto_cop: Any,
) -> tuple[list[dict[str, int]], int]:
    """Calcula cómo se repartiría un abono sin escribir nada."""

    restante = _pesos(monto_cop, "Monto del abono", permite_cero=False)
    aplicaciones: list[dict[str, int]] = []
    for factura in sorted(facturas, key=lambda fila: (str(fila["fecha"]), int(fila["id"]))):
        saldo = int(factura["saldo_cop"])
        if saldo <= 0 or restante <= 0:
            continue
        aplicado = min(saldo, restante)
        aplicaciones.append({"factura_id": int(factura["id"]), "monto_cop": aplicado})
        restante -= aplicado
    return aplicaciones, restante


def registrar_abono(
    *,
    empresa_codigo: str,
    cliente_id: int,
    fecha: Any,
    referencia: Any,
    monto_cop: Any,
    aplicaciones: Sequence[Mapping[str, Any]],
    ruta: str | Path | None = None,
) -> int:
    """Guarda un abono y sus aplicaciones en una única transacción."""

    inicializar(ruta)
    empresa = _empresa(empresa_codigo)
    monto = _pesos(monto_cop, "Monto del abono", permite_cero=False)
    fecha_pago = _fecha(fecha, "Fecha de pago")
    aplicaciones_limpias: dict[int, int] = {}
    for aplicacion in aplicaciones:
        try:
            factura_id = int(aplicacion["factura_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ErrorCartera("Una aplicación de abono no tiene factura válida.") from exc
        valor = _pesos(aplicacion.get("monto_cop"), "Valor aplicado")
        if valor:
            aplicaciones_limpias[factura_id] = aplicaciones_limpias.get(factura_id, 0) + valor
    total_aplicado = sum(aplicaciones_limpias.values())
    if total_aplicado > monto:
        raise ErrorCartera("Las aplicaciones superan el monto recibido.")

    with _transaccion(ruta) as conexion:
        cliente = conexion.execute(
            """
            SELECT id FROM clientes WHERE id = ? AND empresa_codigo = ?
            """,
            (int(cliente_id), empresa),
        ).fetchone()
        if cliente is None:
            raise ErrorCartera("El cliente no pertenece a la empresa seleccionada.")

        for factura_id, valor in aplicaciones_limpias.items():
            factura = _factura_para_editar(conexion, factura_id)
            if factura["empresa_codigo"] != empresa or int(factura["cliente_id"]) != int(cliente_id):
                raise ErrorCartera("No puedes aplicar este abono a una factura de otro cliente.")
            saldo_disponible = _total_factura(factura) - int(factura["abonos_cop"])
            if valor > saldo_disponible:
                raise ErrorCartera(
                    f"La aplicación supera el saldo de {factura['prefijo']}{factura['numero']}."
                )

        cursor = conexion.execute(
            """
            INSERT INTO abonos_manual (
                empresa_codigo, cliente_id, fecha, referencia, monto_cop,
                saldo_a_favor_cop, creado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa,
                int(cliente_id),
                fecha_pago,
                _texto(referencia, "Referencia bancaria"),
                monto,
                monto - total_aplicado,
                _ahora(),
            ),
        )
        abono_id = int(cursor.lastrowid)
        for factura_id, valor in aplicaciones_limpias.items():
            conexion.execute(
                """
                INSERT INTO aplicaciones_abono (abono_id, factura_id, monto_cop, creado_en)
                VALUES (?, ?, ?, ?)
                """,
                (abono_id, factura_id, valor, _ahora()),
            )
        _registrar(
            conexion,
            "abono_manual",
            abono_id,
            "REGISTRADO",
            {
                "empresa": empresa,
                "cliente_id": int(cliente_id),
                "monto_cop": monto,
                "aplicado_cop": total_aplicado,
                "saldo_a_favor_cop": monto - total_aplicado,
                "referencia": _texto(referencia, "Referencia bancaria"),
            },
        )
        return abono_id


def listar_abonos(
    empresa_codigo: str | None = None,
    ruta: str | Path | None = None,
) -> list[dict[str, Any]]:
    inicializar(ruta)
    filtros = ""
    parametros: list[Any] = []
    if empresa_codigo:
        filtros = "WHERE a.empresa_codigo = ?"
        parametros.append(_empresa(empresa_codigo))
    with _lectura(ruta) as conexion:
        filas = conexion.execute(
            f"""
            SELECT
                a.id, a.empresa_codigo, a.fecha, a.referencia, a.monto_cop,
                a.saldo_a_favor_cop, a.creado_en, c.nombre AS cliente, c.nit,
                COALESCE(SUM(ap.monto_cop), 0) AS aplicado_cop
            FROM abonos_manual a
            INNER JOIN clientes c ON c.id = a.cliente_id
            LEFT JOIN aplicaciones_abono ap ON ap.abono_id = a.id
            {filtros}
            GROUP BY a.id
            ORDER BY a.fecha DESC, a.id DESC
            """,
            parametros,
        ).fetchall()
    return [dict(fila) for fila in filas]


def guardar_revision_conciliacion(
    *,
    empresa_codigo: str,
    factura_clave: str,
    estado: str,
    observacion: str,
    manual: Mapping[str, Any] | None,
    siigo: Mapping[str, Any] | None,
    ruta: str | Path | None = None,
) -> int:
    """Registra la revisión; jamás escribe en Siigo."""

    inicializar(ruta)
    empresa = _empresa(empresa_codigo)
    clave = _texto(factura_clave, "Factura", obligatorio=True)
    estado_limpio = _texto(estado, "Estado", obligatorio=True).upper()
    with _transaccion(ruta) as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO revisiones_conciliacion (
                empresa_codigo, factura_clave, estado, observacion, manual_json,
                siigo_json, revisado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empresa,
                clave,
                estado_limpio,
                _texto(observacion, "Observación"),
                json.dumps(manual or {}, ensure_ascii=False, default=str, sort_keys=True),
                json.dumps(siigo or {}, ensure_ascii=False, default=str, sort_keys=True),
                _ahora(),
            ),
        )
        revision_id = int(cursor.lastrowid)
        _registrar(
            conexion,
            "conciliacion",
            revision_id,
            "REVISADA",
            {"empresa": empresa, "factura": clave, "estado": estado_limpio},
        )
        return revision_id


def resumen_actividad(
    limite: int = 6,
    ruta: str | Path | None = None,
) -> list[dict[str, Any]]:
    inicializar(ruta)
    with _lectura(ruta) as conexion:
        filas = conexion.execute(
            """
            SELECT entidad, entidad_id, accion, detalle, creado_en
            FROM auditoria
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limite)),),
        ).fetchall()
    return [dict(fila) for fila in filas]


def hay_datos(ruta: str | Path | None = None) -> bool:
    inicializar(ruta)
    with _lectura(ruta) as conexion:
        return bool(
            conexion.execute("SELECT 1 FROM facturas_manual LIMIT 1").fetchone()
        )


def cargar_datos_demostracion(ruta: str | Path | None = None) -> None:
    """Carga una muestra explícita para conocer la interfaz sin datos reales."""

    if hay_datos(ruta):
        raise ErrorCartera(
            "La demostración solo se puede cargar en una cartera manual vacía."
        )
    hoy = date.today()
    muestras = [
        {
            "empresa_codigo": "NOVASA",
            "prefijo": "FEBA",
            "numero": "1079",
            "fecha": hoy - timedelta(days=55),
            "vencimiento": hoy - timedelta(days=25),
            "cliente": "Transportes Andinos SAS",
            "nit": "901.222.333-4",
            "descripcion": "Servicio Bogotá → Medellín · Manifiesto 47821",
            "placas": "SOQ766, TAW897",
            "subtotal_cop": 12_247_644,
            "iva_cop": 0,
            "retefuente_cop": 306_191,
            "ica_cop": 49_000,
        },
        {
            "empresa_codigo": "NOVASA",
            "prefijo": "FEBA",
            "numero": "1082",
            "fecha": hoy - timedelta(days=20),
            "vencimiento": hoy + timedelta(days=10),
            "cliente": "Transportes Andinos SAS",
            "nit": "901.222.333-4",
            "descripcion": "Servicio Medellín → Cartagena · Manifiesto 48102",
            "placas": "SOQ766",
            "subtotal_cop": 8_760_000,
            "iva_cop": 0,
            "retefuente_cop": 219_000,
            "ica_cop": 35_040,
        },
        {
            "empresa_codigo": "NOVASA",
            "prefijo": "FEBA",
            "numero": "1084",
            "fecha": hoy - timedelta(days=8),
            "vencimiento": hoy + timedelta(days=22),
            "cliente": "Alimentos del Norte SAS",
            "nit": "800.456.789-1",
            "descripcion": "Servicio Bogotá → Barranquilla · Manifiesto 48271",
            "placas": "URO212",
            "subtotal_cop": 5_490_000,
            "iva_cop": 0,
            "retefuente_cop": 137_250,
            "ica_cop": 21_960,
        },
        {
            "empresa_codigo": "LUAC",
            "prefijo": "LUA",
            "numero": "208",
            "fecha": hoy - timedelta(days=34),
            "vencimiento": hoy - timedelta(days=4),
            "cliente": "Comercializadora Central Ltda",
            "nit": "900.786.123-9",
            "descripcion": "Servicio Cali → Bogotá · Manifiesto 32018",
            "placas": "JTL485",
            "subtotal_cop": 7_850_000,
            "iva_cop": 0,
            "retefuente_cop": 196_250,
            "ica_cop": 31_400,
        },
        {
            "empresa_codigo": "MSU",
            "prefijo": "MSU",
            "numero": "679",
            "fecha": hoy - timedelta(days=12),
            "vencimiento": hoy + timedelta(days=18),
            "cliente": "Obras y Maquinaria SAS",
            "nit": "901.871.020-3",
            "descripcion": "Transporte especializado de maquinaria",
            "placas": "TIS003",
            "subtotal_cop": 15_000_000,
            "iva_cop": 2_850_000,
            "retefuente_cop": 375_000,
            "ica_cop": 60_000,
        },
    ]
    ids = [crear_factura(fila, ruta) for fila in muestras]
    factura = obtener_factura(ids[0], ruta)
    if factura is not None:
        registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=int(factura["cliente_id"]),
            fecha=hoy - timedelta(days=4),
            referencia="RC-DEM-001",
            monto_cop=4_500_000,
            aplicaciones=[{"factura_id": ids[0], "monto_cop": 4_500_000}],
            ruta=ruta,
        )


__all__ = [
    "EMPRESAS",
    "ErrorCartera",
    "actualizar_campos_factura",
    "anular_factura",
    "cargar_datos_demostracion",
    "clientes_con_saldo",
    "crear_factura",
    "facturas_pendientes_cliente",
    "guardar_revision_conciliacion",
    "hay_datos",
    "inicializar",
    "listar_abonos",
    "listar_facturas",
    "obtener_factura",
    "previsualizar_fifo",
    "registrar_abono",
    "resumen_actividad",
    "resumen_cartera",
]
