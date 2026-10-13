"""Pantalla de ingreso y panel de seguridad.

La sesión vive en ``st.session_state``, que Streamlit guarda **en el servidor**
y asocia a la pestaña del navegador: la identidad nunca viaja en el navegador
del usuario ni se puede falsificar desde allá. Cerrar la pestaña o reiniciar el
servidor termina la sesión.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import html
import secrets
import time
from typing import Any

import pandas as pd
import streamlit as st

from src import autenticacion as auth


CLAVE_SESION = "usuario_sesion"
CLAVE_REVISION = "acceso_revision"

# Un doble clic o dos Enter seguidos en «Ingresar» llegan como dos
# reejecuciones con el mismo formulario. La segunda no vuelve a verificar: si
# llega dentro de esta ventana con los mismos datos, repite el resultado de la
# primera. Sin esto, un doble clic con la contraseña equivocada contaba dos
# intentos fallidos.
CLAVE_ULTIMO_INTENTO = "ingreso_ultimo_intento"
VENTANA_INTENTO_REPETIDO = 2.0
MENSAJE_CREDENCIALES = "Usuario o contraseña incorrectos."
# Los datos del intento se recuerdan por su HMAC con una llave aleatoria de
# este proceso: la contraseña nunca queda en la sesión, ni cifrada.
_SELLO_INTENTOS = secrets.token_bytes(32)


def _huella_intento(usuario: str, clave: str) -> str:
    return hmac.new(
        _SELLO_INTENTOS, (usuario + "\0" + clave).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _intento_repetido(huella: str) -> str | None:
    """Mensaje del intento idéntico que acaba de fallar, si lo hubo."""

    anterior = st.session_state.get(CLAVE_ULTIMO_INTENTO)
    if not isinstance(anterior, tuple) or len(anterior) != 3:
        return None
    huella_anterior, terminado_en, mensaje = anterior
    if huella_anterior == huella and time.monotonic() - terminado_en < VENTANA_INTENTO_REPETIDO:
        return str(mensaje)
    return None


def _leer_credencial() -> auth.CredencialConfigurada:
    try:
        return auth.credencial_desde_secretos(st.secrets)
    except auth.ErrorAcceso:
        raise
    except Exception:
        raise auth.ErrorAcceso("Configura el usuario y la contraseña en los Secrets de Streamlit.") from None


def usuario_actual() -> auth.Usuario | None:
    """Quién está usando la aplicación en esta sesión, si ya ingresó."""

    valor = st.session_state.get(CLAVE_SESION)
    if not isinstance(valor, auth.Usuario):
        return None
    try:
        credencial = _leer_credencial()
    except auth.ErrorAcceso:
        cerrar_sesion()
        return None
    if valor.usuario != credencial.usuario or st.session_state.get(CLAVE_REVISION) != credencial.revision:
        cerrar_sesion()
        return None
    return valor


def cerrar_sesion() -> None:
    """Termina la sesión y borra todo rastro de trabajo en pantalla."""

    st.session_state.pop(CLAVE_SESION, None)
    st.session_state.pop(CLAVE_REVISION, None)
    # Se limpian filtros y formularios para que la siguiente persona no herede
    # la pantalla de la anterior.
    for clave in [
        k for k in st.session_state
        if k.startswith(("filtro_", "abono_", "factura_", "editar_factura_",
                         "dialogo_", "detalle_cliente_", "siigo_", "vista",
                         "ingreso_", "activacion_", "orden_", "exportar_"))
    ]:
        st.session_state.pop(clave, None)


def _fecha_visible(valor: Any) -> str:
    if not valor:
        return "—"
    try:
        return dt.datetime.fromisoformat(str(valor)).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(valor)


def _mensaje_campos_vacios(usuario: str, clave: str) -> str | None:
    if not usuario.strip() and not clave:
        return "Escribe tu usuario y tu contraseña."
    if not usuario.strip():
        return "Escribe tu usuario."
    if not clave:
        return "Escribe tu contraseña."
    return None


def _verificar_ingreso(
    usuario: str, clave: str, credencial: auth.CredencialConfigurada
) -> str | None:
    """Intenta ingresar. Devuelve el mensaje de error, o ``None`` si entró."""

    huella = _huella_intento(usuario, clave)
    repetido = _intento_repetido(huella)
    if repetido is not None:
        return repetido
    try:
        identidad = auth.autenticar(usuario, clave, credencial=credencial)
    except auth.ErrorAcceso as exc:
        mensaje = str(exc)
        # ``autenticar`` agrega cuántos intentos quedan, pero solo cuando la
        # cuenta existe: en pantalla se muestra lo mismo exista o no, para que
        # nadie pueda averiguar qué usuarios son reales.
        if mensaje.startswith(MENSAJE_CREDENCIALES):
            mensaje = MENSAJE_CREDENCIALES
    except Exception as exc:
        mensaje = (
            "No fue posible verificar el ingreso "
            f"({type(exc).__name__}). Revisa la conexión con la base de datos."
        )
    else:
        st.session_state[CLAVE_SESION] = identidad
        st.session_state[CLAVE_REVISION] = credencial.revision
        st.session_state.pop(CLAVE_ULTIMO_INTENTO, None)
        return None
    st.session_state[CLAVE_ULTIMO_INTENTO] = (huella, time.monotonic(), mensaje)
    return mensaje


def render_ingreso() -> None:
    """Pantalla de ingreso. No muestra nada de la cartera hasta autenticar.

    Una sola tarjeta centrada con el nombre, los dos campos y el botón. La
    autenticación, el bloqueo por intentos y la sesión son los de
    ``src.autenticacion``; aquí solo se dibuja. El campo de contraseña trae el
    ojo de mostrar/ocultar de Streamlit y Enter envía el formulario. Los
    estilos de la tarjeta viven en ``src.ui.styles`` bajo ``st-key-ingreso_tarjeta``.
    """

    # Descarta enlaces y borradores de la activación anterior.
    if "activar" in st.query_params:
        del st.query_params["activar"]
    for key in list(st.session_state):
        if key.startswith("activacion_") or key == "cuenta_recien_creada":
            st.session_state.pop(key, None)
    try:
        credencial = _leer_credencial()
    except auth.ErrorAcceso as exc:
        credencial = None
        aviso_configuracion = str(exc)
    pendiente = credencial is None

    with st.container(key="ingreso_tarjeta"):
        st.markdown(
            '<div class="brand"><span class="brand-mark">◈</span>NOVASALUM</div>'
            '<div class="ingreso-lema">Gestión de cartera empresarial</div>'
            '<h2 class="ingreso-titulo">Ingreso</h2>'
            '<div class="ingreso-ayuda">Acceso restringido. Ingresa con tu usuario y contraseña.</div>',
            unsafe_allow_html=True,
        )
        if pendiente:
            st.info(aviso_configuracion)
        with st.form("ingreso_novasalum", border=False, enter_to_submit=True):
            usuario = st.text_input(
                "Usuario", key="ingreso_usuario", autocomplete="username", disabled=pendiente,
            )
            clave = st.text_input(
                "Contraseña", type="password", key="ingreso_clave",
                autocomplete="current-password", disabled=pendiente,
            )
            entrar = st.form_submit_button(
                "Ingresar", type="primary", width="stretch", disabled=pendiente
            )
        if entrar and not pendiente:
            error = _mensaje_campos_vacios(usuario, clave)
            if error is None:
                error = _verificar_ingreso(usuario, clave, credencial)
            if error is None:
                # La contraseña no debe quedar en memoria de sesión.
                st.session_state.pop("ingreso_clave", None)
                st.rerun()
            st.error(error)
        st.caption(
            f"Tras {auth.MAX_INTENTOS} intentos fallidos la cuenta se bloquea "
            f"durante {auth.MINUTOS_BLOQUEO} minutos."
        )


def render_identidad_lateral() -> bool:
    """Muestra quién ingresó y el botón de salir. Devuelve si pidió salir."""

    identidad = usuario_actual()
    if identidad is None:
        return False
    st.markdown(
        f'<div class="activity"><strong>{html.escape(identidad.nombre)}</strong>'
        f'<br><span style="color:#64748b">{html.escape(identidad.rol)}</span></div>',
        unsafe_allow_html=True,
    )
    return st.button("Cerrar sesión", use_container_width=True, key="boton_salir")


def render_seguridad() -> None:
    """Panel de vigilancia: intentos de ingreso, alertas y cuentas."""

    identidad = usuario_actual()
    if identidad is None:
        return
    st.markdown(
        '<div class="surface-title">Seguridad y accesos</div>'
        '<div class="surface-subtitle">Quién entra, quién lo intenta y qué cuentas existen.</div>',
        unsafe_allow_html=True,
    )
    st.write("")

    try:
        resumen = auth.resumen_seguridad()
    except Exception as exc:
        st.error(f"No fue posible leer el registro de accesos ({type(exc).__name__}).")
        return

    if resumen["alerta"]:
        st.error(
            f"⚠️ **Posible intento de acceso no autorizado.** {resumen['motivo']}.",
        )
    else:
        st.success("Sin señales de intentos de acceso no autorizados.")

    tarjetas = st.columns(3)
    tarjetas[0].metric("Ingresos correctos (24 h)", resumen["ingresos_ultimo_dia"])
    tarjetas[1].metric("Intentos fallidos (24 h)", resumen["fallos_ultimo_dia"])
    tarjetas[2].metric("Fallidos en la última hora", resumen["fallos_ultima_hora"])

    if resumen["cuentas_bloqueadas"]:
        st.write("")
        st.markdown("##### Cuentas bloqueadas ahora mismo")
        for cuenta in resumen["cuentas_bloqueadas"]:
            fila, boton = st.columns([3, 1], vertical_alignment="center")
            with fila:
                st.markdown(
                    f"**{html.escape(cuenta['usuario'])}** · bloqueada hasta "
                    f"{_fecha_visible(cuenta['bloqueado_hasta'])}"
                )
            with boton:
                if identidad is not None and identidad.es_admin:
                    if st.button(
                        "Desbloquear",
                        key=f"desbloquear_{cuenta['usuario']}",
                        use_container_width=True,
                    ):
                        auth.desbloquear(cuenta["usuario"])
                        st.rerun()

    st.write("")
    st.markdown("##### Intentos de ingreso (últimas 24 horas)")
    intentos = auth.intentos_recientes(horas=24)
    if not intentos:
        st.caption("No hay intentos registrados en las últimas 24 horas.")
    else:
        tabla = pd.DataFrame([
            {
                "Cuándo": _fecha_visible(i["creado_en"]),
                "Usuario": i["usuario"],
                "Resultado": "Entró" if int(i["exitoso"]) else "Falló",
                "Motivo": {
                    "OK": "Ingreso correcto",
                    "NO_EXISTE": "El usuario no existe",
                    "CLAVE_INCORRECTA": "Contraseña incorrecta",
                    "CLAVE_INCORRECTA_BLOQUEA": "Contraseña incorrecta · bloqueó la cuenta",
                    "BLOQUEADO": "Intentó estando bloqueada",
                    "INACTIVO": "Cuenta desactivada",
                    "USUARIO_INVALIDO": "Usuario con formato inválido",
                }.get(str(i["motivo"]), str(i["motivo"])),
            }
            for i in intentos
        ])
        st.dataframe(tabla, width="stretch", hide_index=True)

    st.write("")
    st.markdown("##### Cuenta de acceso")
    st.write(f"Usuario: {identidad.usuario}")
    st.caption("El usuario y la contraseña se administran desde los Secrets de Streamlit.")


__all__ = [
    "CLAVE_SESION",
    "cerrar_sesion",
    "render_identidad_lateral",
    "render_ingreso",
    "render_seguridad",
    "usuario_actual",
]
