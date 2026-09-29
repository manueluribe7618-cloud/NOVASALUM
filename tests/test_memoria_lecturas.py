"""La memoria de lecturas: la app no vuelve a la base en cada clic y nunca
muestra datos viejos después de guardar.

Contra Supabase cada consulta es un viaje de red, y Streamlit reejecuta la
página entera en cada clic. Estas pruebas fijan el contrato: lo guardado desde
la aplicación se ve de inmediato, la memoria vence sola, cambia con el día y
el botón «Actualizar datos» la vacía.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from streamlit.testing.v1 import AppTest

from src import database as db
from src.ui import portfolio_analysis as pa


HOY = date.today()


def datos_factura(numero: str, **cambios) -> dict:
    datos = {
        "empresa_codigo": "NOVASA",
        "prefijo": "FEBA",
        "numero": numero,
        "fecha": HOY - timedelta(days=10),
        "vencimiento": HOY + timedelta(days=20),
        "cliente": "Transportes de Prueba SAS",
        "descripcion": "Servicio de prueba",
        "placas": "ABC123",
        "subtotal_cop": 1_000_000,
        "iva_cop": 0,
        "retefuente_cop": 0,
        "ica_cop": 0,
    }
    datos.update(cambios)
    return datos


class BaseTemporal(unittest.TestCase):
    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = Path(temporal.name) / "cartera.db"
        db.invalidar_lecturas()
        self.addCleanup(db.invalidar_lecturas)

    def contar_lecturas(self):
        """Cuenta cuántas veces se abre la base para leer."""

        return patch.object(db, "_lectura", wraps=db._lectura)

    def factura(self, factura_id: int, *, incluir_anuladas: bool = False) -> dict | None:
        filas = db.listar_facturas(incluir_anuladas=incluir_anuladas, ruta=self.ruta)
        return next((fila for fila in filas if fila["id"] == factura_id), None)


class LecturasRepetidas(BaseTemporal):
    def test_una_lectura_repetida_no_vuelve_a_la_base(self) -> None:
        db.crear_factura(datos_factura("100"), self.ruta)
        with self.contar_lecturas() as lectura:
            primera = db.listar_facturas(ruta=self.ruta)
            segunda = db.listar_facturas(ruta=self.ruta)
        self.assertEqual(lectura.call_count, 1)
        self.assertEqual(primera, segunda)

    def test_la_actividad_y_los_clientes_tambien_se_memorizan(self) -> None:
        db.crear_factura(datos_factura("100"), self.ruta)
        with self.contar_lecturas() as lectura:
            for _ in range(3):
                db.resumen_actividad(ruta=self.ruta)
                db.listar_nombres_clientes(ruta=self.ruta)
        self.assertEqual(lectura.call_count, 2)

    def test_cada_llamada_recibe_sus_propias_filas(self) -> None:
        db.crear_factura(datos_factura("100"), self.ruta)
        filas = db.listar_facturas(ruta=self.ruta)
        filas[0]["saldo_cop"] = -1
        filas.clear()
        de_nuevo = db.listar_facturas(ruta=self.ruta)
        self.assertEqual(len(de_nuevo), 1)
        self.assertEqual(de_nuevo[0]["saldo_cop"], 1_000_000)

    def test_bases_distintas_no_comparten_memoria(self) -> None:
        otra = self.ruta.with_name("otra.db")
        db.crear_factura(datos_factura("100"), self.ruta)
        db.crear_factura(datos_factura("200"), otra)
        db.crear_factura(datos_factura("201"), otra)
        self.assertEqual([f["numero"] for f in db.listar_facturas(ruta=self.ruta)], ["100"])
        self.assertEqual([f["numero"] for f in db.listar_facturas(ruta=otra)], ["200", "201"])

    def test_la_memoria_vence_sola(self) -> None:
        db.crear_factura(datos_factura("100"), self.ruta)
        with patch.object(db, "_VIGENCIA_LECTURAS_SEGUNDOS", 0.0), self.contar_lecturas() as lectura:
            db.listar_facturas(ruta=self.ruta)
            db.listar_facturas(ruta=self.ruta)
        self.assertEqual(lectura.call_count, 2)

    def test_a_medianoche_la_factura_pasa_a_vencida(self) -> None:
        """El estado depende del día: lo guardado ayer no sirve hoy."""

        ayer = HOY - timedelta(days=1)
        factura_id = db.crear_factura(
            datos_factura("100", fecha=ayer - timedelta(days=5), vencimiento=ayer), self.ruta
        )
        with patch.object(db, "hoy_colombia", return_value=ayer):
            self.assertEqual(self.factura(factura_id)["estado"], "PENDIENTE")
        with patch.object(db, "hoy_colombia", return_value=HOY):
            fila = self.factura(factura_id)
        self.assertEqual(fila["estado"], "VENCIDA")
        self.assertEqual(fila["dias_mora"], 1)

    def test_una_transaccion_sin_cambios_conserva_la_memoria(self) -> None:
        """``inicializar`` corre en cada clic en SQLite y no debe vaciarla."""

        db.crear_factura(datos_factura("100"), self.ruta)
        db.listar_facturas(ruta=self.ruta)
        db.inicializar(self.ruta)
        with self.contar_lecturas() as lectura:
            db.listar_facturas(ruta=self.ruta)
        self.assertEqual(lectura.call_count, 0)

    def test_una_escritura_durante_la_lectura_no_queda_guardada(self) -> None:
        """Si otra sesión guarda mientras se lee, esa lectura no se memoriza."""

        db.crear_factura(datos_factura("100"), self.ruta)
        original = db._filas_facturas

        def lectura_con_escritura_simultanea(*args, **kwargs):
            filas = original(*args, **kwargs)
            db.invalidar_lecturas()
            return filas

        with patch.object(db, "_filas_facturas", lectura_con_escritura_simultanea):
            db.listar_facturas(ruta=self.ruta)
        with self.contar_lecturas() as lectura:
            db.listar_facturas(ruta=self.ruta)
        self.assertEqual(lectura.call_count, 1)

    def test_lo_escrito_por_fuera_se_ve_al_actualizar(self) -> None:
        """Otro proceso escribió en la base: basta con vaciar la memoria."""

        factura_id = db.crear_factura(datos_factura("100"), self.ruta)
        self.assertEqual(self.factura(factura_id)["total_cop"], 1_000_000)
        with closing(sqlite3.connect(self.ruta)) as conexion:
            conexion.execute("UPDATE facturas_manual SET subtotal_cop = 2500000")
            conexion.commit()
        db.invalidar_lecturas()
        self.assertEqual(self.factura(factura_id)["total_cop"], 2_500_000)


class LoGuardadoSeVeDeInmediato(BaseTemporal):
    """Cada escritura se lee en la llamada siguiente, con la memoria llena."""

    def setUp(self) -> None:
        super().setUp()
        self.factura_id = db.crear_factura(datos_factura("100"), self.ruta)
        self.cliente_id = self.factura(self.factura_id)["cliente_id"]
        self.llenar_memoria()

    def llenar_memoria(self) -> None:
        db.listar_facturas(ruta=self.ruta)
        db.listar_facturas(incluir_anuladas=True, ruta=self.ruta)
        db.listar_facturas("NOVASA", ruta=self.ruta)
        db.listar_nombres_clientes(ruta=self.ruta)
        db.resumen_actividad(ruta=self.ruta)

    def test_crear_factura(self) -> None:
        nueva = db.crear_factura(datos_factura("101", cliente="Cliente Nuevo SAS"), self.ruta)
        self.assertIsNotNone(self.factura(nueva))
        self.assertIn("Cliente Nuevo SAS", db.listar_nombres_clientes(ruta=self.ruta))
        self.assertEqual(len(db.listar_facturas("NOVASA", ruta=self.ruta)), 2)

    def test_crear_factura_con_abono(self) -> None:
        nueva = db.crear_factura_con_abono(
            datos_factura("101"),
            {"monto_cop": 400_000, "fecha": HOY, "referencia": "RC-1"},
            self.ruta,
        )
        self.assertEqual(self.factura(nueva)["saldo_cop"], 600_000)

    def test_editar_factura(self) -> None:
        db.actualizar_campos_factura(
            self.factura_id,
            {"subtotal_cop": 1_500_000, "iva_cop": 0, "retefuente_cop": 0, "ica_cop": 0},
            self.ruta,
        )
        self.assertEqual(self.factura(self.factura_id)["total_cop"], 1_500_000)

    def test_anular_factura(self) -> None:
        db.anular_factura(self.factura_id, self.ruta)
        self.assertIsNone(self.factura(self.factura_id))
        anulada = self.factura(self.factura_id, incluir_anuladas=True)
        self.assertEqual(anulada["estado"], "ANULADA")

    def test_registrar_abono(self) -> None:
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=self.cliente_id,
            fecha=HOY,
            referencia="RC-2",
            monto_cop=1_000_000,
            aplicaciones=[{"factura_id": self.factura_id, "monto_cop": 1_000_000}],
            ruta=self.ruta,
        )
        self.assertEqual(self.factura(self.factura_id)["estado"], "PAGADA")
        self.assertEqual(db.clientes_con_saldo("NOVASA", ruta=self.ruta), [])
        self.assertEqual(db.resumen_actividad(ruta=self.ruta)[0]["accion"], "REGISTRADO")

    def test_guardar_revision_de_conciliacion(self) -> None:
        db.guardar_revision_conciliacion(
            empresa_codigo="NOVASA",
            factura_clave="FEBA100",
            estado="cuadra",
            observacion="",
            manual={},
            siigo={},
            ruta=self.ruta,
        )
        self.assertEqual(db.resumen_actividad(ruta=self.ruta)[0]["accion"], "REVISADA")

    def test_una_escritura_rechazada_no_deja_datos_viejos(self) -> None:
        antes = db.listar_facturas(ruta=self.ruta)
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura(datos_factura("100"), self.ruta)  # número repetido
        self.assertEqual(db.listar_facturas(ruta=self.ruta), antes)


class BotonActualizarDatos(unittest.TestCase):
    """«Actualizar datos» trae lo que se escribió por fuera de la aplicación."""

    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = Path(temporal.name) / "cartera.db"
        entorno = patch.dict("os.environ", {"NOVASALUM_DB": str(self.ruta)})
        entorno.start()
        self.addCleanup(entorno.stop)
        db.invalidar_lecturas()
        self.addCleanup(db.invalidar_lecturas)
        db.crear_factura(datos_factura("100"))

    @staticmethod
    def texto(app: AppTest) -> str:
        return " ".join(bloque.value for bloque in app.markdown)

    def test_el_boton_vacia_la_memoria(self) -> None:
        def vista():
            from src.views import manual

            manual.render_manual_portfolio("TODAS")

        app = AppTest.from_function(vista, default_timeout=60).run()
        self.assertFalse(app.exception, app.exception)
        self.assertIn("1.000.000", self.texto(app))
        with closing(sqlite3.connect(self.ruta)) as conexion:
            conexion.execute("UPDATE facturas_manual SET subtotal_cop = 2500000")
            conexion.commit()
        # Un clic cualquiera usa la memoria; el botón va a la base.
        app.run()
        self.assertIn("1.000.000", self.texto(app))
        app.button(key="actualizar_manual").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertIn("2.500.000", self.texto(app))
        self.assertNotIn("1.000.000", self.texto(app))


class ConexionCompartidaConSupabase(unittest.TestCase):
    """La conexión solo se prueba cuando lleva un rato quieta."""

    def setUp(self) -> None:
        entorno = patch.dict(
            "os.environ",
            {"SUPABASE_DB_URL": "postgresql://u:p@host:6543/db", "NOVASALUM_DB": ""},
        )
        entorno.start()
        self.addCleanup(entorno.stop)
        self.vieja = MagicMock(closed=False)
        self.nueva = MagicMock(closed=False)
        for parche in (
            patch.object(db, "_CONEXION_PG", self.vieja),
            patch.object(db, "_PG_RESPONDIO_EN", time.monotonic()),
            patch.object(psycopg, "connect", return_value=self.nueva),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    def test_una_conexion_recien_usada_no_se_prueba(self) -> None:
        adaptador = db._conexion_pg()
        self.vieja.execute.assert_not_called()
        psycopg.connect.assert_not_called()
        self.assertIs(adaptador._conexion, self.vieja)

    def test_una_conexion_quieta_se_prueba_antes_de_usarla(self) -> None:
        db._PG_RESPONDIO_EN = time.monotonic() - 60
        adaptador = db._conexion_pg()
        self.vieja.execute.assert_called_once_with("SELECT 1")
        psycopg.connect.assert_not_called()
        self.assertIs(adaptador._conexion, self.vieja)

    def test_si_la_prueba_falla_se_reconecta(self) -> None:
        db._PG_RESPONDIO_EN = time.monotonic() - 60
        self.vieja.execute.side_effect = psycopg.OperationalError("server closed the connection")
        adaptador = db._conexion_pg()
        psycopg.connect.assert_called_once()
        self.assertIs(adaptador._conexion, self.nueva)

    def test_una_conexion_que_psycopg_sabe_cerrada_se_renueva(self) -> None:
        self.vieja.closed = True
        adaptador = db._conexion_pg()
        self.vieja.execute.assert_not_called()
        psycopg.connect.assert_called_once()
        self.assertIs(adaptador._conexion, self.nueva)

    def test_cada_sentencia_cuenta_como_respuesta(self) -> None:
        db._PG_RESPONDIO_EN = 0.0
        db._ConexionPG(self.vieja).execute("SELECT ?", (1,))
        self.assertGreater(db._PG_RESPONDIO_EN, time.monotonic() - 5)

    def test_toda_transaccion_en_la_nube_vacia_la_memoria(self) -> None:
        for falla in (False, True):
            with self.subTest(falla=falla):
                antes = db._GENERACION_LECTURAS
                with patch.object(db, "_conexion_pg", return_value=db._ConexionPG(MagicMock())):
                    try:
                        with db._transaccion():
                            if falla:
                                raise db.ErrorCartera("rechazada")
                    except db.ErrorCartera:
                        pass
                self.assertGreater(db._GENERACION_LECTURAS, antes)


class GraficasMemorizadas(unittest.TestCase):
    FILAS = [
        {"empresa_codigo": "NOVASA", "fecha": str(HOY - timedelta(days=5)), "saldo_cop": 1_000_000},
        {"empresa_codigo": "LUAC", "fecha": str(HOY - timedelta(days=45)), "saldo_cop": 2_000_000},
    ]

    def setUp(self) -> None:
        pa._cached_portfolio_figures.clear()
        self.addCleanup(pa._cached_portfolio_figures.clear)

    def test_el_mismo_resumen_reutiliza_las_figuras(self) -> None:
        resumen = pa.aging_summary(self.FILAS)
        primeras = pa._cached_portfolio_figures(resumen)
        segundas = pa._cached_portfolio_figures(pa.aging_summary(self.FILAS))
        self.assertIs(primeras[0], segundas[0])
        self.assertIs(primeras[1], segundas[1])

    def test_otro_resumen_arma_graficas_nuevas_con_sus_cifras(self) -> None:
        primeras = pa._cached_portfolio_figures(pa.aging_summary(self.FILAS))
        otras = pa._cached_portfolio_figures(pa.aging_summary(self.FILAS[:1]))
        self.assertIsNot(primeras[0], otras[0])
        self.assertEqual(list(otras[0].data[0].values), [1_000_000])

    def test_portfolio_figures_sigue_entregando_figuras_propias(self) -> None:
        resumen = pa.aging_summary(self.FILAS)
        self.assertIsNot(pa.portfolio_figures(resumen)[0], pa.portfolio_figures(resumen)[0])


if __name__ == "__main__":
    unittest.main()
