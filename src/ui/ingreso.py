"""Pantalla de ingreso y panel de seguridad.

La sesión vive en ``st.session_state``, que Streamlit guarda **en el servidor**
y asocia a la pestaña del navegador: la identidad nunca viaja en el navegador
del usuario ni se puede falsificar desde allá. Cerrar la pestaña o reiniciar el
servidor termina la sesión.
"""

from __future__ import annotations

import datetime as dt
import html
from typing import Any

import pandas as pd
import streamlit as st

from src import autenticacion as auth


CLAVE_SESION = "usuario_sesion"
CLAVE_REVISION = "acceso_revision"


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
                         "ingreso_", "activacion_"))
    ]:
        st.session_state.pop(clave, None)


def _fecha_visible(valor: Any) -> str:
    if not valor:
        return "—"
    try:
        return dt.datetime.fromisoformat(str(valor)).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(valor)


def render_ingreso() -> None:
    """Pantalla de ingreso. No muestra nada de la cartera hasta autenticar."""

    st.markdown(
        '<div class="eyebrow">NOVASALUM</div>'
        '<h1 style="margin:0">Ingreso</h1>'
        '<div class="page-subtitle">Cartera y recaudo · acceso restringido</div>',
        unsafe_allow_html=True,
    )
    st.write("")

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
        st.info(str(exc))
    pendiente = credencial is None

    columna, _ = st.columns([1.2, 1])
    with columna:
        with st.form("ingreso_novasalum"):
            usuario = st.text_input("Usuario", key="ingreso_usuario", disabled=pendiente)
            clave = st.text_input("Contraseña", type="password", key="ingreso_clave", disabled=pendiente)
            entrar = st.form_submit_button(
                "Entrar", type="primary", use_container_width=True, disabled=pendiente
            )
        if entrar and not pendiente:
            try:
                identidad = auth.autenticar(usuario, clave, credencial=credencial)
            except auth.ErrorAcceso as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(
                    "No fue posible verificar el ingreso "
                    f"({type(exc).__name__}). Revisa la conexión con la base de datos."
                )
            else:
                st.session_state[CLAVE_SESION] = identidad
                st.session_state[CLAVE_REVISION] = credencial.revision
                # La contraseña no debe quedar en memoria de sesión.
                st.session_state.pop("ingreso_clave", None)
                st.rerun()
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
