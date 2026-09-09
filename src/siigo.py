"""Cliente de consulta para la API de Siigo.

El modulo es deliberadamente de solo lectura: la unica solicitud ``POST`` que
acepta es ``/auth`` para obtener el token. Las facturas, recibos de caja y
clientes se consultan exclusivamente con ``GET``.

Las credenciales nunca se escriben en este archivo. Se pueden entregar mediante
``ConfiguracionSiigo`` o cargar por empresa desde variables de entorno, por
ejemplo::

    SIIGO_PARTNER_ID=NovaLogistics
    SIIGO_NOVASA_USERNAME=usuario@empresa.com
    SIIGO_NOVASA_ACCESS_KEY=...

    configuracion = ConfiguracionSiigo.desde_entorno({"NOVASA": "NOVASA"})
    cliente = ClienteSiigo("NOVASA", configuracion)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime
import json as json_lib
import os
import re
import socket
import threading
import time
from typing import Any, Protocol
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


URL_BASE_SIIGO = "https://api.siigo.com"
# Contrato de recarga de la aplicación. La versión de las rutas públicas de
# Siigo se conserva aparte para no confundir ambos conceptos.
API_VERSION = "2026.08.21.1"
VERSION_API_SIIGO = "v1"
ESTADOS_REINTENTABLES = frozenset({408, 429, 500, 502, 503, 504})


# ``importlib.reload`` reutiliza el diccionario del módulo. Mantener la misma
# jerarquía de errores hace que sesiones y pruebas que ya capturaban estas clases
# sigan funcionando después de la autocuración de Streamlit.
if "ErrorSiigo" not in globals():
    class ErrorSiigo(RuntimeError):
        """Error base del conector de Siigo."""


    class ErrorConfiguracionSiigo(ErrorSiigo):
        """La configuracion o las credenciales estan incompletas."""


    class ErrorSoloLecturaSiigo(ErrorSiigo):
        """Se intento ejecutar una operacion que podria modificar Siigo."""


    class ErrorTransporteSiigo(ErrorSiigo):
        """No fue posible comunicarse con Siigo."""


    class ErrorAPISiigo(ErrorSiigo):
        """Siigo respondio con un error HTTP o con una respuesta invalida."""

        def __init__(self, mensaje: str, *, estado: int | None = None, detalle: Any = None):
            super().__init__(mensaje)
            self.estado = estado
            self.detalle = detalle


    class ErrorAutenticacionSiigo(ErrorAPISiigo):
        """Siigo rechazo las credenciales o no entrego un token valido."""


    class ErrorLimiteSiigo(ErrorAPISiigo):
        """Se agoto el limite de solicitudes o el limite seguro de paginacion."""


def _texto_no_vacio(valor: Any, nombre: str) -> str:
    texto = str(valor or "").strip()
    if not texto:
        raise ErrorConfiguracionSiigo(f"Falta el valor obligatorio de {nombre}.")
    return texto


def _clave_empresa(nombre: str) -> str:
    return " ".join(_texto_no_vacio(nombre, "empresa").casefold().split())


def _sufijo_entorno(nombre: str) -> str:
    normalizado = unicodedata.normalize("NFKD", nombre)
    sin_tildes = "".join(c for c in normalizado if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "_", sin_tildes.upper()).strip("_")


@dataclass(frozen=True)
class CredencialesSiigo:
    """Credenciales API de una sola empresa en Siigo."""

    usuario: str
    access_key: str = field(repr=False)
    partner_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "usuario", _texto_no_vacio(self.usuario, "usuario"))
        object.__setattr__(self, "access_key", _texto_no_vacio(self.access_key, "access_key"))
        partner_id = _texto_no_vacio(self.partner_id, "partner_id")
        if not re.fullmatch(r"[A-Za-z0-9]{3,100}", partner_id):
            raise ErrorConfiguracionSiigo(
                "Partner-Id debe tener entre 3 y 100 caracteres alfanuméricos, "
                "sin espacios ni caracteres especiales."
            )
        object.__setattr__(self, "partner_id", partner_id)


@dataclass(frozen=True)
class ConfiguracionSiigo:
    """Configuracion del cliente y credenciales separadas por empresa."""

    empresas: Mapping[str, CredencialesSiigo]
    url_base: str = URL_BASE_SIIGO
    timeout_s: float = 15.0
    reintentos: int = 2
    retroceso_s: float = 0.5
    espera_maxima_s: float = 30.0
    tamano_pagina: int = 100
    max_paginas: int = 500
    _empresas_normalizadas: Mapping[str, CredencialesSiigo] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.empresas, Mapping) or not self.empresas:
            raise ErrorConfiguracionSiigo("Debe configurar al menos una empresa para Siigo.")

        normalizadas: dict[str, CredencialesSiigo] = {}
        for nombre, credenciales in self.empresas.items():
            clave = _clave_empresa(nombre)
            if clave in normalizadas:
                raise ErrorConfiguracionSiigo(f"La empresa {nombre!r} esta configurada dos veces.")
            # ``importlib.reload`` conserva instancias creadas por la pantalla con
            # la clase anterior. Se reconstruyen por atributos para que una recarga
            # de Streamlit no invalide credenciales correctas por identidad de clase.
            try:
                normalizadas[clave] = CredencialesSiigo(
                    usuario=getattr(credenciales, "usuario"),
                    access_key=getattr(credenciales, "access_key"),
                    partner_id=getattr(credenciales, "partner_id"),
                )
            except (AttributeError, ErrorConfiguracionSiigo) as exc:
                raise ErrorConfiguracionSiigo(
                    f"Las credenciales de {nombre!r} deben ser un objeto CredencialesSiigo."
                ) from exc

        partner_ids = {cred.partner_id.casefold() for cred in normalizadas.values()}
        if len(partner_ids) > 1:
            raise ErrorConfiguracionSiigo(
                "Todas las empresas deben usar el mismo Partner-Id registrado en Siigo."
            )

        url_base = _texto_no_vacio(self.url_base, "url_base").rstrip("/")
        partes = urlsplit(url_base)
        if (
            partes.scheme != "https"
            or partes.hostname != "api.siigo.com"
            or partes.username is not None
            or partes.password is not None
            or partes.query
            or partes.fragment
            or partes.path not in ("", "/")
        ):
            raise ErrorConfiguracionSiigo(
                "La URL base debe ser exactamente el servicio HTTPS oficial de Siigo."
            )
        if self.timeout_s <= 0:
            raise ErrorConfiguracionSiigo("timeout_s debe ser mayor que cero.")
        if self.reintentos < 0:
            raise ErrorConfiguracionSiigo("reintentos no puede ser negativo.")
        if self.retroceso_s < 0 or self.espera_maxima_s < 0:
            raise ErrorConfiguracionSiigo("Los tiempos de retroceso no pueden ser negativos.")
        if not 1 <= self.tamano_pagina <= 100:
            raise ErrorConfiguracionSiigo("tamano_pagina debe estar entre 1 y 100.")
        if self.max_paginas <= 0:
            raise ErrorConfiguracionSiigo("max_paginas debe ser mayor que cero.")

        object.__setattr__(self, "url_base", url_base)
        object.__setattr__(self, "_empresas_normalizadas", normalizadas)

    def credenciales_para(self, empresa: str) -> CredencialesSiigo:
        """Retorna las credenciales de ``empresa`` sin mezclar sus tokens."""

        clave = _clave_empresa(empresa)
        try:
            return self._empresas_normalizadas[clave]
        except KeyError as exc:
            raise ErrorConfiguracionSiigo(
                f"No hay credenciales de Siigo configuradas para la empresa {empresa!r}."
            ) from exc

    @classmethod
    def desde_entorno(
        cls,
        empresas: Mapping[str, str] | Iterable[str],
        *,
        entorno: Mapping[str, str] | None = None,
        prefijo: str = "SIIGO",
        **opciones: Any,
    ) -> "ConfiguracionSiigo":
        """Carga credenciales por empresa desde variables de entorno.

        ``empresas`` puede ser un mapeo ``nombre -> sufijo`` para controlar los
        nombres de las variables, o una lista; en este ultimo caso se genera un
        sufijo seguro a partir del nombre de cada empresa.
        """

        valores = os.environ if entorno is None else entorno
        prefijo = _sufijo_entorno(_texto_no_vacio(prefijo, "prefijo"))
        if isinstance(empresas, Mapping):
            pares = list(empresas.items())
        else:
            pares = [(nombre, _sufijo_entorno(nombre)) for nombre in empresas]
        if not pares:
            raise ErrorConfiguracionSiigo("Debe indicar al menos una empresa.")

        partner_global = str(valores.get(f"{prefijo}_PARTNER_ID", "")).strip()
        credenciales: dict[str, CredencialesSiigo] = {}
        faltantes: list[str] = []
        for empresa, sufijo_crudo in pares:
            sufijo = _sufijo_entorno(_texto_no_vacio(sufijo_crudo, "sufijo de empresa"))
            base = f"{prefijo}_{sufijo}"
            usuario = str(valores.get(f"{base}_USERNAME", "")).strip()
            access_key = str(valores.get(f"{base}_ACCESS_KEY", "")).strip()
            partner_id = str(valores.get(f"{base}_PARTNER_ID", partner_global)).strip()
            if not usuario:
                faltantes.append(f"{base}_USERNAME")
            if not access_key:
                faltantes.append(f"{base}_ACCESS_KEY")
            if not partner_id:
                faltantes.append(f"{base}_PARTNER_ID o {prefijo}_PARTNER_ID")
            if usuario and access_key and partner_id:
                credenciales[str(empresa)] = CredencialesSiigo(
                    usuario=usuario,
                    access_key=access_key,
                    partner_id=partner_id,
                )

        if faltantes:
            raise ErrorConfiguracionSiigo(
                "Faltan variables de entorno de Siigo: " + ", ".join(faltantes) + "."
            )
        return cls(empresas=credenciales, **opciones)

    @classmethod
    def desde_mapeo_secretos(
        cls,
        secretos: Mapping[str, Any],
        empresas: Mapping[str, str] | Iterable[str],
        *,
        seccion: str = "siigo",
        **opciones: Any,
    ) -> "ConfiguracionSiigo":
        """Carga credenciales desde ``st.secrets`` u otro mapeo equivalente.

        La estructura recomendada en ``secrets.toml`` es::

            [siigo]
            partner_id = "NovaLogistics"

            [siigo.empresas.NOVASA]
            username = "usuario@empresa.com"
            access_key = "..."

        ``empresas`` relaciona el nombre visible con la clave dentro de la
        seccion ``empresas``. Tambien acepta el formato aplanado de variables
        ``SIIGO_*`` para facilitar pruebas y migraciones.
        """

        if not isinstance(secretos, Mapping):
            raise ErrorConfiguracionSiigo("Los secretos de Siigo deben ser un mapeo.")
        if isinstance(empresas, Mapping):
            pares = list(empresas.items())
        else:
            pares = [(nombre, _sufijo_entorno(nombre)) for nombre in empresas]
        if not pares:
            raise ErrorConfiguracionSiigo("Debe indicar al menos una empresa.")

        # ``st.secrets`` tambien puede contener las variables aplanadas que se
        # usan en produccion fuera de Streamlit.
        if any(str(clave).upper().startswith("SIIGO_") for clave in secretos):
            return cls.desde_entorno(
                dict(pares),
                entorno=secretos,  # type: ignore[arg-type]
                **opciones,
            )

        raiz: Any = secretos.get(seccion, secretos)
        if not isinstance(raiz, Mapping):
            raise ErrorConfiguracionSiigo(
                f"La seccion {seccion!r} de secretos de Siigo debe ser un mapeo."
            )
        empresas_secretas = raiz.get("empresas")
        if not isinstance(empresas_secretas, Mapping):
            raise ErrorConfiguracionSiigo(
                f"Falta el mapeo {seccion}.empresas en los secretos de Siigo."
            )

        partner_global = str(raiz.get("partner_id") or raiz.get("Partner-Id") or "").strip()
        credenciales: dict[str, CredencialesSiigo] = {}
        faltantes: list[str] = []
        for empresa, clave_cruda in pares:
            clave = _texto_no_vacio(clave_cruda, "clave de empresa")
            datos = empresas_secretas.get(clave)
            if datos is None:
                # Hace tolerante el uso de nombres en mayusculas/minusculas en TOML.
                datos = next(
                    (
                        valor
                        for nombre, valor in empresas_secretas.items()
                        if str(nombre).casefold() == clave.casefold()
                    ),
                    None,
                )
            ruta = f"{seccion}.empresas.{clave}"
            if not isinstance(datos, Mapping):
                faltantes.append(ruta)
                continue
            usuario = str(datos.get("username") or datos.get("usuario") or "").strip()
            access_key = str(datos.get("access_key") or "").strip()
            partner_id = str(datos.get("partner_id") or partner_global).strip()
            if not usuario:
                faltantes.append(f"{ruta}.username")
            if not access_key:
                faltantes.append(f"{ruta}.access_key")
            if not partner_id:
                faltantes.append(f"{ruta}.partner_id o {seccion}.partner_id")
            if usuario and access_key and partner_id:
                credenciales[str(empresa)] = CredencialesSiigo(
                    usuario=usuario,
                    access_key=access_key,
                    partner_id=partner_id,
                )

        if faltantes:
            raise ErrorConfiguracionSiigo(
                "Faltan secretos de Siigo: " + ", ".join(faltantes) + "."
            )
        return cls(empresas=credenciales, **opciones)


@dataclass(frozen=True)
class RespuestaHTTP:
    """Respuesta neutral usada por el transporte inyectable."""

    estado: int
    datos: Any
    encabezados: Mapping[str, str] = field(default_factory=dict)


class TransporteSiigo(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None,
        timeout: float,
    ) -> RespuestaHTTP:
        """Ejecuta una solicitud HTTP y retorna una ``RespuestaHTTP``."""


def _decodificar_respuesta(contenido: bytes, content_type: str = "") -> Any:
    if not contenido:
        return None
    charset = "utf-8"
    coincidencia = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    if coincidencia:
        charset = coincidencia.group(1).strip('"\'')
    texto = contenido.decode(charset, errors="replace")
    try:
        return json_lib.loads(texto)
    except json_lib.JSONDecodeError:
        return texto


class _RedireccionesBloqueadas(HTTPRedirectHandler):
    """Evita reenviar Authorization/Partner-Id a un destino indicado por 30x."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TransporteUrllib:
    """Transporte predeterminado, implementado solo con la libreria estandar."""

    def __init__(self) -> None:
        self._abridor = build_opener(_RedireccionesBloqueadas())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None,
        timeout: float,
    ) -> RespuestaHTTP:
        contenido = None if json is None else json_lib.dumps(json).encode("utf-8")
        solicitud = Request(url, data=contenido, headers=dict(headers), method=method)
        try:
            with self._abridor.open(solicitud, timeout=timeout) as respuesta:
                cuerpo = respuesta.read()
                encabezados = dict(respuesta.headers.items())
                return RespuestaHTTP(
                    estado=respuesta.status,
                    datos=_decodificar_respuesta(cuerpo, respuesta.headers.get("Content-Type", "")),
                    encabezados=encabezados,
                )
        except HTTPError as exc:
            cuerpo = exc.read()
            encabezados = dict(exc.headers.items()) if exc.headers else {}
            return RespuestaHTTP(
                estado=exc.code,
                datos=_decodificar_respuesta(cuerpo, encabezados.get("Content-Type", "")),
                encabezados=encabezados,
            )
        except (URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise ErrorTransporteSiigo("No fue posible comunicarse con Siigo.") from exc


def _adaptar_respuesta(respuesta: Any) -> RespuestaHTTP:
    if isinstance(respuesta, RespuestaHTTP):
        return respuesta
    estado = getattr(
        respuesta,
        "status_code",
        getattr(respuesta, "status", getattr(respuesta, "estado", None)),
    )
    if estado is None:
        raise ErrorTransporteSiigo("El transporte devolvio una respuesta sin estado HTTP.")
    datos = getattr(respuesta, "datos", None)
    if datos is None and callable(getattr(respuesta, "json", None)):
        try:
            datos = respuesta.json()
        except (TypeError, ValueError):
            datos = getattr(respuesta, "text", None)
    encabezados = getattr(respuesta, "headers", getattr(respuesta, "encabezados", {})) or {}
    return RespuestaHTTP(int(estado), datos, dict(encabezados))


def _normalizar_fecha(valor: str | date | datetime, nombre: str) -> tuple[str, date]:
    if isinstance(valor, datetime):
        return valor.isoformat(), valor.date()
    if isinstance(valor, date):
        return valor.isoformat(), valor
    texto = str(valor or "").strip()
    try:
        comparacion = date.fromisoformat(texto[:10])
        if len(texto) > 10:
            datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{nombre} debe tener formato YYYY-MM-DD o ser una fecha ISO 8601 valida."
        ) from exc
    return texto, comparacion


def _rango_fechas(
    date_start: str | date | datetime, date_end: str | date | datetime
) -> tuple[str, str]:
    inicio, inicio_comparable = _normalizar_fecha(date_start, "date_start")
    fin, fin_comparable = _normalizar_fecha(date_end, "date_end")
    if inicio_comparable > fin_comparable:
        raise ValueError("date_start no puede ser posterior a date_end.")
    return inicio, fin


class ClienteSiigo:
    """Cliente por empresa para consultar datos contables sin modificarlos."""

    def __init__(
        self,
        empresa: str,
        configuracion: ConfiguracionSiigo,
        *,
        transporte: TransporteSiigo | None = None,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if not all(
            hasattr(configuracion, atributo)
            for atributo in ("credenciales_para", "url_base", "timeout_s", "reintentos")
        ):
            raise ErrorConfiguracionSiigo("configuracion debe ser un objeto ConfiguracionSiigo.")
        self.empresa = _texto_no_vacio(empresa, "empresa")
        self.configuracion = configuracion
        self.credenciales = configuracion.credenciales_para(empresa)
        self._transporte = transporte or TransporteUrllib()
        self._dormir = dormir
        self._reloj = reloj
        self._token: str | None = None
        self._tipo_token = "Bearer"
        self._token_expira_en = 0.0
        self._cerrojo_token = threading.RLock()

    @classmethod
    def desde_entorno(
        cls,
        empresa: str,
        empresas: Mapping[str, str] | Iterable[str],
        *,
        entorno: Mapping[str, str] | None = None,
        transporte: TransporteSiigo | None = None,
        **opciones_configuracion: Any,
    ) -> "ClienteSiigo":
        configuracion = ConfiguracionSiigo.desde_entorno(
            empresas, entorno=entorno, **opciones_configuracion
        )
        return cls(empresa, configuracion, transporte=transporte)

    @staticmethod
    def _validar_metodo(method: str, ruta: str) -> str:
        metodo = str(method or "").upper()
        ruta_normalizada = urlsplit(ruta).path.rstrip("/") or "/"
        if metodo == "GET" or (metodo == "POST" and ruta_normalizada == "/auth"):
            return metodo
        raise ErrorSoloLecturaSiigo(
            "El conector es de solo lectura: solo permite GET; POST se reserva para /auth."
        )

    def _autenticar(self, *, forzar: bool = False) -> None:
        with self._cerrojo_token:
            if not forzar and self._token and self._reloj() < self._token_expira_en:
                return
            respuesta = self._solicitar_json(
                "POST",
                "/auth",
                cuerpo={
                    "username": self.credenciales.usuario,
                    "access_key": self.credenciales.access_key,
                },
                autenticado=False,
            )
            if not isinstance(respuesta, Mapping) or not respuesta.get("access_token"):
                raise ErrorAutenticacionSiigo(
                    "Siigo no entrego un token de acceso valido.", detalle=respuesta
                )
            self._token = str(respuesta["access_token"])
            self._tipo_token = str(respuesta.get("token_type") or "Bearer")
            try:
                duracion = max(1.0, float(respuesta.get("expires_in", 86400)))
            except (TypeError, ValueError):
                duracion = 86400.0
            margen = min(60.0, duracion * 0.1)
            self._token_expira_en = self._reloj() + max(1.0, duracion - margen)

    def _encabezados(self, *, autenticado: bool, con_cuerpo: bool) -> dict[str, str]:
        encabezados = {
            "Accept": "application/json",
            "Partner-Id": self.credenciales.partner_id,
        }
        if con_cuerpo:
            encabezados["Content-Type"] = "application/json"
        if autenticado:
            self._autenticar()
            encabezados["Authorization"] = f"{self._tipo_token} {self._token}"
        return encabezados

    def _espera_reintento(self, intento: int, encabezados: Mapping[str, str]) -> float:
        retry_after = next(
            (valor for clave, valor in encabezados.items() if clave.lower() == "retry-after"),
            None,
        )
        espera: float | None = None
        if retry_after is not None:
            try:
                espera = max(0.0, float(retry_after))
            except (TypeError, ValueError):
                try:
                    fecha = parsedate_to_datetime(str(retry_after))
                    espera = max(0.0, fecha.timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    espera = None
        if espera is None:
            espera = self.configuracion.retroceso_s * (2**intento)
        return min(espera, self.configuracion.espera_maxima_s)

    def _solicitar_json(
        self,
        method: str,
        ruta: str,
        *,
        parametros: Mapping[str, Any] | None = None,
        cuerpo: Mapping[str, Any] | None = None,
        autenticado: bool = True,
    ) -> Any:
        metodo = self._validar_metodo(method, ruta)
        if cuerpo is not None and metodo != "POST":
            raise ErrorSoloLecturaSiigo("Las consultas GET no pueden enviar un cuerpo modificable.")

        parametros_limpios = {
            clave: valor for clave, valor in (parametros or {}).items() if valor is not None
        }
        url = f"{self.configuracion.url_base}/{ruta.lstrip('/')}"
        if parametros_limpios:
            url = f"{url}?{urlencode(parametros_limpios, doseq=True)}"
        encabezados = self._encabezados(autenticado=autenticado, con_cuerpo=cuerpo is not None)
        reintento = 0
        token_renovado = False

        while True:
            try:
                respuesta_cruda = self._transporte.request(
                    metodo,
                    url,
                    headers=encabezados,
                    json=cuerpo,
                    timeout=self.configuracion.timeout_s,
                )
                respuesta = _adaptar_respuesta(respuesta_cruda)
            except (ErrorTransporteSiigo, TimeoutError, OSError) as exc:
                if reintento >= self.configuracion.reintentos:
                    if isinstance(exc, ErrorTransporteSiigo):
                        raise
                    raise ErrorTransporteSiigo(
                        "No fue posible comunicarse con Siigo dentro del tiempo esperado."
                    ) from exc
                self._dormir(self._espera_reintento(reintento, {}))
                reintento += 1
                continue

            if respuesta.estado == 401 and autenticado and not token_renovado:
                self._token = None
                self._token_expira_en = 0.0
                self._autenticar(forzar=True)
                encabezados["Authorization"] = f"{self._tipo_token} {self._token}"
                token_renovado = True
                continue

            if respuesta.estado in ESTADOS_REINTENTABLES and reintento < self.configuracion.reintentos:
                self._dormir(self._espera_reintento(reintento, respuesta.encabezados))
                reintento += 1
                continue

            if 200 <= respuesta.estado < 300:
                return {} if respuesta.datos is None else respuesta.datos
            self._lanzar_error_api(respuesta)

    @staticmethod
    def _mensaje_error(datos: Any) -> str:
        if isinstance(datos, Mapping):
            for clave in ("message", "error", "detail", "title"):
                valor = datos.get(clave)
                if isinstance(valor, str) and valor.strip():
                    return valor.strip()
            errores = datos.get("errors")
            if isinstance(errores, list) and errores:
                primero = errores[0]
                if isinstance(primero, Mapping):
                    return str(primero.get("message") or primero.get("detail") or primero)
                return str(primero)
        if isinstance(datos, str) and datos.strip():
            return datos.strip()[:300]
        return "Siigo no informo el detalle del error."

    def _lanzar_error_api(self, respuesta: RespuestaHTTP) -> None:
        detalle = self._mensaje_error(respuesta.datos)
        mensaje = f"Siigo respondio HTTP {respuesta.estado}: {detalle}"
        if respuesta.estado in {401, 403}:
            raise ErrorAutenticacionSiigo(mensaje, estado=respuesta.estado, detalle=respuesta.datos)
        if respuesta.estado == 429:
            raise ErrorLimiteSiigo(mensaje, estado=respuesta.estado, detalle=respuesta.datos)
        raise ErrorAPISiigo(mensaje, estado=respuesta.estado, detalle=respuesta.datos)

    @staticmethod
    def _validar_paginacion(
        tamano_pagina: int, limite: int | None, max_paginas: int
    ) -> tuple[int, int | None, int]:
        if not 1 <= tamano_pagina <= 100:
            raise ValueError("tamano_pagina debe estar entre 1 y 100.")
        if limite is not None and limite <= 0:
            raise ValueError("limite debe ser mayor que cero.")
        if max_paginas <= 0:
            raise ValueError("max_paginas debe ser mayor que cero.")
        return tamano_pagina, limite, max_paginas

    def _listar_paginas(
        self,
        ruta: str,
        parametros: Mapping[str, Any],
        *,
        tamano_pagina: int | None = None,
        limite: int | None = None,
        max_paginas: int | None = None,
    ) -> list[dict[str, Any]]:
        tamano = tamano_pagina or self.configuracion.tamano_pagina
        paginas_maximas = max_paginas or self.configuracion.max_paginas
        tamano, limite, paginas_maximas = self._validar_paginacion(
            tamano, limite, paginas_maximas
        )
        resultados: list[dict[str, Any]] = []

        for pagina in range(1, paginas_maximas + 1):
            tamano_solicitado = min(tamano, limite - len(resultados)) if limite else tamano
            consulta = dict(parametros)
            consulta.update({"page": pagina, "page_size": tamano_solicitado})
            respuesta = self._solicitar_json("GET", ruta, parametros=consulta)
            if not isinstance(respuesta, Mapping) or not isinstance(respuesta.get("results"), list):
                raise ErrorAPISiigo(
                    f"Siigo devolvio una paginacion invalida para {ruta}.", detalle=respuesta
                )
            pagina_resultados = respuesta["results"]
            if any(not isinstance(fila, Mapping) for fila in pagina_resultados):
                raise ErrorAPISiigo(
                    f"Siigo devolvio resultados invalidos para {ruta}.", detalle=respuesta
                )
            resultados.extend(dict(fila) for fila in pagina_resultados)
            if limite is not None and len(resultados) >= limite:
                return resultados[:limite]
            if not pagina_resultados:
                return resultados

            paginacion = respuesta.get("pagination")
            total: int | None = None
            if isinstance(paginacion, Mapping):
                try:
                    total = int(paginacion.get("total_results"))
                except (TypeError, ValueError):
                    total = None
            if total is not None and len(resultados) >= total:
                return resultados
            if total is None and len(pagina_resultados) < tamano_solicitado:
                return resultados

        raise ErrorLimiteSiigo(
            f"La consulta alcanzo el limite seguro de {paginas_maximas} paginas; "
            "reduzca el rango de fechas para no entregar datos incompletos."
        )

    def listar_facturas(
        self,
        date_start: str | date | datetime,
        date_end: str | date | datetime,
        *,
        cliente_identificacion: str | None = None,
        sucursal_cliente: int | None = None,
        nombre: str | None = None,
        documento_id: int | None = None,
        tamano_pagina: int | None = None,
        limite: int | None = None,
        max_paginas: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lista todas las facturas elaboradas dentro del rango indicado."""

        inicio, fin = _rango_fechas(date_start, date_end)
        return self._listar_paginas(
            f"/{VERSION_API_SIIGO}/invoices",
            {
                "date_start": inicio,
                "date_end": fin,
                "customer_identification": cliente_identificacion,
                "customer_branch_office": sucursal_cliente,
                "name": nombre,
                "document_id": documento_id,
            },
            tamano_pagina=tamano_pagina,
            limite=limite,
            max_paginas=max_paginas,
        )

    def consultar_factura(self, factura_id: str) -> dict[str, Any]:
        """Consulta el detalle y saldo de una factura por su id."""

        respuesta = self._solicitar_json(
            "GET",
            f"/{VERSION_API_SIIGO}/invoices/{quote(_texto_no_vacio(factura_id, 'factura_id'), safe='')}",
        )
        if not isinstance(respuesta, Mapping):
            raise ErrorAPISiigo("Siigo devolvio una factura invalida.", detalle=respuesta)
        return dict(respuesta)

    def listar_recibos_caja(
        self,
        date_start: str | date | datetime,
        date_end: str | date | datetime,
        *,
        nombre: str | None = None,
        tamano_pagina: int | None = None,
        limite: int | None = None,
        max_paginas: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lista los recibos de caja dentro del rango indicado."""

        inicio, fin = _rango_fechas(date_start, date_end)
        return self._listar_paginas(
            f"/{VERSION_API_SIIGO}/vouchers",
            {"date_start": inicio, "date_end": fin, "name": nombre},
            tamano_pagina=tamano_pagina,
            limite=limite,
            max_paginas=max_paginas,
        )

    def consultar_recibo_caja(self, recibo_id: str) -> dict[str, Any]:
        respuesta = self._solicitar_json(
            "GET",
            f"/{VERSION_API_SIIGO}/vouchers/{quote(_texto_no_vacio(recibo_id, 'recibo_id'), safe='')}",
        )
        if not isinstance(respuesta, Mapping):
            raise ErrorAPISiigo("Siigo devolvio un recibo de caja invalido.", detalle=respuesta)
        return dict(respuesta)

    def listar_clientes(
        self,
        *,
        identificacion: str | None = None,
        sucursal: int | None = None,
        activo: bool | None = True,
        tipo: str | None = None,
        tamano_pagina: int | None = None,
        limite: int | None = None,
        max_paginas: int | None = None,
    ) -> list[dict[str, Any]]:
        """Consulta clientes/terceros para enriquecer la vista de cartera."""

        activo_api = None if activo is None else str(activo).lower()
        return self._listar_paginas(
            f"/{VERSION_API_SIIGO}/customers",
            {
                "identification": identificacion,
                "branch_office": sucursal,
                "active": activo_api,
                "type": tipo,
            },
            tamano_pagina=tamano_pagina,
            limite=limite,
            max_paginas=max_paginas,
        )

    def consultar_cliente(self, cliente_id: str) -> dict[str, Any]:
        respuesta = self._solicitar_json(
            "GET",
            f"/{VERSION_API_SIIGO}/customers/{quote(_texto_no_vacio(cliente_id, 'cliente_id'), safe='')}",
        )
        if not isinstance(respuesta, Mapping):
            raise ErrorAPISiigo("Siigo devolvio un cliente invalido.", detalle=respuesta)
        return dict(respuesta)

    # Alias en ingles para integraciones que sigan los nombres oficiales de la API.
    list_invoices = listar_facturas
    get_invoice = consultar_factura
    list_vouchers = listar_recibos_caja
    get_voucher = consultar_recibo_caja
    list_customers = listar_clientes
    get_customer = consultar_cliente


# Alias cortos y previsibles para codigo nuevo en ingles.
SiigoCredentials = CredencialesSiigo
SiigoConfig = ConfiguracionSiigo
SiigoClient = ClienteSiigo
SiigoError = ErrorSiigo
SiigoReadOnlyError = ErrorSoloLecturaSiigo


__all__ = [
    "API_VERSION",
    "VERSION_API_SIIGO",
    "ClienteSiigo",
    "ConfiguracionSiigo",
    "CredencialesSiigo",
    "ErrorAPISiigo",
    "ErrorAutenticacionSiigo",
    "ErrorConfiguracionSiigo",
    "ErrorLimiteSiigo",
    "ErrorSiigo",
    "ErrorSoloLecturaSiigo",
    "ErrorTransporteSiigo",
    "RespuestaHTTP",
    "SiigoClient",
    "SiigoConfig",
    "SiigoCredentials",
    "SiigoError",
    "SiigoReadOnlyError",
    "TransporteSiigo",
    "TransporteUrllib",
]
