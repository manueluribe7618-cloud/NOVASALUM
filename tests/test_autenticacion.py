"""Reglas de acceso: contraseñas, bloqueo por intentos y vigilancia.

Cada prueba corresponde a una forma concreta de entrar sin permiso. Si alguna
falla, la puerta quedó abierta.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest

from src import autenticacion as auth
from src import database as db


CLAVE = "MiClaveSegura123"


class BaseTemporal(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        auth.crear_usuario("martin", CLAVE, nombre="Martín", ruta=self.ruta)


class ContrasenasTests(BaseTemporal):
    def test_la_contrasena_nunca_se_guarda_en_claro(self) -> None:
        guardado = auth.hash_clave(CLAVE)
        self.assertNotIn(CLAVE, guardado)
        self.assertTrue(guardado.startswith("scrypt$"))

    def test_la_misma_contrasena_produce_hashes_distintos(self) -> None:
        """Cada una lleva su propia sal: no se pueden atacar todas a la vez."""

        self.assertNotEqual(auth.hash_clave(CLAVE), auth.hash_clave(CLAVE))

    def test_verifica_la_correcta_y_rechaza_las_demas(self) -> None:
        guardado = auth.hash_clave(CLAVE)
        self.assertTrue(auth.verificar_clave(CLAVE, guardado))
        self.assertFalse(auth.verificar_clave(CLAVE + "x", guardado))
        self.assertFalse(auth.verificar_clave("", guardado))

    def test_un_hash_corrupto_no_deja_entrar_ni_revienta(self) -> None:
        for basura in ("", "x", "scrypt$mal", "$$$$$", "otro$1$2$3$a$b"):
            self.assertFalse(auth.verificar_clave(CLAVE, basura), basura)

    def test_rechaza_contrasenas_debiles(self) -> None:
        for debil in ("1234", "1234567", "12345678", "password", "novasalum"):
            with self.assertRaises(auth.ErrorAcceso, msg=debil):
                auth.revisar_fortaleza(debil)

    def test_el_usuario_no_distingue_mayusculas_ni_espacios(self) -> None:
        identidad = auth.autenticar("  MARTIN  ", CLAVE, ruta=self.ruta)
        self.assertEqual(identidad.usuario, "martin")

    def test_rechaza_usuarios_con_formato_invalido(self) -> None:
        for malo in ("", "ab", "con espacio", "a" * 41, "correo@dominio.com"):
            with self.assertRaises(auth.ErrorAcceso, msg=malo):
                auth.normalizar_usuario(malo)


class IngresoTests(BaseTemporal):
    def test_entra_con_la_clave_correcta(self) -> None:
        identidad = auth.autenticar("martin", CLAVE, ruta=self.ruta)
        self.assertEqual(identidad.nombre, "Martín")
        self.assertTrue(identidad.es_admin)

    def test_no_entra_con_clave_incorrecta(self) -> None:
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("martin", "otraClave123", ruta=self.ruta)

    def test_no_entra_un_usuario_inexistente(self) -> None:
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("fantasma", CLAVE, ruta=self.ruta)

    def test_el_mensaje_no_revela_si_el_usuario_existe(self) -> None:
        """Decirlo permitiría averiguar qué cuentas hay para luego atacarlas."""

        try:
            auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        except auth.ErrorAcceso as exc:
            con_usuario_real = str(exc)
        try:
            auth.autenticar("fantasma", "claveMala123", ruta=self.ruta)
        except auth.ErrorAcceso as exc:
            con_usuario_falso = str(exc)
        self.assertTrue(con_usuario_real.startswith("Usuario o contraseña incorrectos"))
        self.assertTrue(con_usuario_falso.startswith("Usuario o contraseña incorrectos"))

    def test_una_cuenta_desactivada_no_entra(self) -> None:
        with db._transaccion(self.ruta) as conexion:
            conexion.execute("UPDATE usuarios SET activo = 0 WHERE usuario = 'martin'")
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("martin", CLAVE, ruta=self.ruta)

    def test_no_se_pueden_crear_dos_usuarios_iguales(self) -> None:
        with self.assertRaises(auth.ErrorAcceso):
            auth.crear_usuario("MARTIN", CLAVE, ruta=self.ruta)


class BloqueoPorIntentosTests(BaseTemporal):
    def test_el_contador_de_intentos_se_guarda_de_verdad(self) -> None:
        """Regresión: el error se lanzaba dentro de la transacción y el
        ``rollback`` borraba el conteo, así que el bloqueo nunca ocurría."""

        restantes = []
        for _ in range(auth.MAX_INTENTOS - 1):
            try:
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
            except auth.ErrorAcceso as exc:
                restantes.append(str(exc))
        # Los mensajes deben ir descontando, no repetir siempre el mismo número.
        self.assertIn("4 intento(s)", restantes[0])
        self.assertIn("1 intento(s)", restantes[-1])

    def test_bloquea_al_llegar_al_limite(self) -> None:
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        cuenta = auth.listar_usuarios(self.ruta)[0]
        self.assertEqual(int(cuenta["intentos_fallidos"]), auth.MAX_INTENTOS)
        self.assertIsNotNone(cuenta["bloqueado_hasta"])

    def test_estando_bloqueado_ni_la_clave_correcta_entra(self) -> None:
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        with self.assertRaises(auth.ErrorAcceso) as contexto:
            auth.autenticar("martin", CLAVE, ruta=self.ruta)
        self.assertIn("bloquead", str(contexto.exception).casefold())

    def test_un_ingreso_correcto_borra_los_intentos_fallidos(self) -> None:
        for _ in range(auth.MAX_INTENTOS - 1):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        auth.autenticar("martin", CLAVE, ruta=self.ruta)
        self.assertEqual(int(auth.listar_usuarios(self.ruta)[0]["intentos_fallidos"]), 0)

    def test_el_bloqueo_expira_solo(self) -> None:
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        # Se adelanta el reloj poniendo el fin del bloqueo en el pasado.
        pasado = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat()
        with db._transaccion(self.ruta) as conexion:
            conexion.execute(
                "UPDATE usuarios SET bloqueado_hasta = ? WHERE usuario = 'martin'",
                (pasado,),
            )
        self.assertEqual(auth.autenticar("martin", CLAVE, ruta=self.ruta).usuario, "martin")

    def test_desbloquear_devuelve_el_acceso(self) -> None:
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        auth.desbloquear("martin", ruta=self.ruta)
        self.assertEqual(auth.autenticar("martin", CLAVE, ruta=self.ruta).usuario, "martin")

    def test_cambiar_la_clave_exige_la_anterior(self) -> None:
        with self.assertRaises(auth.ErrorAcceso):
            auth.cambiar_clave("martin", "claveEquivocada", "NuevaClave456", ruta=self.ruta)
        auth.cambiar_clave("martin", CLAVE, "NuevaClave456", ruta=self.ruta)
        self.assertEqual(
            auth.autenticar("martin", "NuevaClave456", ruta=self.ruta).usuario, "martin"
        )
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("martin", CLAVE, ruta=self.ruta)


class VigilanciaTests(BaseTemporal):
    def test_cada_intento_queda_registrado(self) -> None:
        auth.autenticar("martin", CLAVE, ruta=self.ruta)
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        with self.assertRaises(auth.ErrorAcceso):
            auth.autenticar("fantasma", "loQueSea123", ruta=self.ruta)
        intentos = auth.intentos_recientes(ruta=self.ruta)
        self.assertEqual(len(intentos), 3)
        motivos = {i["motivo"] for i in intentos}
        self.assertEqual(motivos, {"OK", "CLAVE_INCORRECTA", "NO_EXISTE"})

    def test_la_alerta_se_enciende_con_una_cuenta_bloqueada(self) -> None:
        resumen = auth.resumen_seguridad(ruta=self.ruta)
        self.assertFalse(resumen["alerta"])
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        resumen = auth.resumen_seguridad(ruta=self.ruta)
        self.assertTrue(resumen["alerta"])
        self.assertIn("martin", resumen["motivo"])
        self.assertEqual([c["usuario"] for c in resumen["cuentas_bloqueadas"]], ["martin"])

    def test_la_alerta_se_enciende_por_volumen_de_intentos(self) -> None:
        """Alguien probando contraseñas contra usuarios inventados."""

        for numero in range(auth.UMBRAL_ALERTA):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar(f"intruso{numero}", "probando123", ruta=self.ruta)
        resumen = auth.resumen_seguridad(ruta=self.ruta)
        self.assertTrue(resumen["alerta"])
        self.assertGreaterEqual(resumen["fallos_ultima_hora"], auth.UMBRAL_ALERTA)

    def test_el_resumen_cuenta_los_fallos_por_usuario(self) -> None:
        for _ in range(3):
            with self.assertRaises(auth.ErrorAcceso):
                auth.autenticar("martin", "claveMala123", ruta=self.ruta)
        resumen = auth.resumen_seguridad(ruta=self.ruta)
        porcentaje = {f["usuario"]: int(f["fallos"]) for f in resumen["fallos_por_usuario"]}
        self.assertEqual(porcentaje["martin"], 3)

    def test_listar_usuarios_no_expone_la_contrasena(self) -> None:
        for cuenta in auth.listar_usuarios(self.ruta):
            self.assertNotIn("clave_hash", cuenta)


class CostoDeAtaqueTests(unittest.TestCase):
    def test_verificar_una_clave_es_deliberadamente_lento(self) -> None:
        """Si fuera instantáneo, probar millones de claves sería práctico."""

        guardado = auth.hash_clave(CLAVE)
        inicio = time.perf_counter()
        auth.verificar_clave("claveIncorrecta", guardado)
        transcurrido = time.perf_counter() - inicio
        self.assertGreater(transcurrido, 0.005, "el hash es demasiado barato")


if __name__ == "__main__":
    unittest.main()
