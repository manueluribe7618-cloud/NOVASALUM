"""Pruebas de las reglas que no pueden fallar en la cartera manual."""

from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database as db
from src.formato import hoy_colombia


class CarteraManualTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "cartera.db"
        # Anclado al día real: con una fecha fija, los vencimientos a 30 días
        # quedaban en el pasado al llegar esa fecha y el estado derivado
        # pasaba a VENCIDA, rompiendo pruebas que nadie había tocado.
        self.hoy = date.today()
        db.inicializar(self.ruta)

    def tearDown(self) -> None:
        self.temporal.cleanup()

    def crear_factura(self, numero: str, fecha: date, subtotal: int = 100_000) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": numero,
                "fecha": fecha,
                "vencimiento": fecha + timedelta(days=30),
                "cliente": "Cliente de prueba SAS",
                "descripcion": "Servicio de prueba",
                "placas": "ABC123",
                "subtotal_cop": subtotal,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

    def test_fifo_aplica_primero_la_factura_mas_antigua(self) -> None:
        primera = self.crear_factura("100", self.hoy - timedelta(days=12), 100_000)
        segunda = self.crear_factura("101", self.hoy - timedelta(days=3), 100_000)
        pendientes = db.facturas_pendientes_cliente("NOVASA", 1, self.ruta)

        aplicaciones, sobrante = db.previsualizar_fifo(pendientes, 150_000)

        self.assertEqual(sobrante, 0)
        self.assertEqual(
            aplicaciones,
            [
                {"factura_id": primera, "monto_cop": 100_000},
                {"factura_id": segunda, "monto_cop": 50_000},
            ],
        )
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="TRX-1",
            monto_cop=150_000,
            aplicaciones=aplicaciones,
            ruta=self.ruta,
        )
        facturas = db.listar_facturas("NOVASA", ruta=self.ruta)
        self.assertEqual([fila["saldo_cop"] for fila in facturas], [0, 50_000])
        self.assertEqual([fila["estado"] for fila in facturas], ["PAGADA", "ABONADA"])

    def test_no_permite_aplicar_mas_del_saldo_real(self) -> None:
        factura = self.crear_factura("200", self.hoy, 90_000)
        with self.assertRaises(db.ErrorCartera):
            db.registrar_abono(
                empresa_codigo="NOVASA",
                cliente_id=1,
                fecha=self.hoy,
                referencia="TRX-2",
                monto_cop=100_000,
                aplicaciones=[{"factura_id": factura, "monto_cop": 100_000}],
                ruta=self.ruta,
            )
        self.assertEqual(db.listar_abonos("NOVASA", self.ruta), [])
        self.assertEqual(db.obtener_factura(factura, self.ruta)["saldo_cop"], 90_000)

    def test_no_permite_reducir_factura_por_debajo_de_abonos(self) -> None:
        factura = self.crear_factura("300", self.hoy, 100_000)
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="TRX-3",
            monto_cop=70_000,
            aplicaciones=[{"factura_id": factura, "monto_cop": 70_000}],
            ruta=self.ruta,
        )
        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura,
                {
                    "descripcion": "Editada",
                    "placas": "ABC123",
                    "subtotal_cop": 60_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                },
                self.ruta,
            )
        self.assertEqual(db.obtener_factura(factura, self.ruta)["saldo_cop"], 30_000)

    def test_editar_corrige_numero_y_fechas(self) -> None:
        factura = self.crear_factura("700", self.hoy)
        nueva_fecha = self.hoy - timedelta(days=5)
        nuevo_vencimiento = self.hoy + timedelta(days=45)

        db.actualizar_campos_factura(
            factura,
            {
                "numero": "701",
                "fecha": nueva_fecha,
                "vencimiento": nuevo_vencimiento,
                "descripcion": "Servicio de prueba",
                "placas": "ABC123",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

        editada = db.obtener_factura(factura, self.ruta)
        self.assertEqual(editada["factura"], "FEBA701")
        self.assertEqual(editada["fecha"], nueva_fecha.isoformat())
        self.assertEqual(editada["vencimiento"], nuevo_vencimiento.isoformat())

    def test_editar_sin_numero_ni_fechas_conserva_los_guardados(self) -> None:
        factura = self.crear_factura("710", self.hoy)

        db.actualizar_campos_factura(
            factura,
            {
                "descripcion": "Solo cambia el detalle",
                "placas": "ABC123",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

        editada = db.obtener_factura(factura, self.ruta)
        self.assertEqual(editada["factura"], "FEBA710")
        self.assertEqual(editada["fecha"], self.hoy.isoformat())
        self.assertEqual(
            editada["vencimiento"], (self.hoy + timedelta(days=30)).isoformat()
        )

    def test_editar_rechaza_numero_repetido_en_la_misma_empresa(self) -> None:
        self.crear_factura("720", self.hoy)
        factura = self.crear_factura("721", self.hoy)

        with self.assertRaises(db.ErrorCartera) as contexto:
            db.actualizar_campos_factura(
                factura,
                {
                    "numero": "720",
                    "descripcion": "Duplicada",
                    "placas": "ABC123",
                    "subtotal_cop": 100_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                },
                self.ruta,
            )
        self.assertIn("ya existe", str(contexto.exception))
        self.assertEqual(db.obtener_factura(factura, self.ruta)["factura"], "FEBA721")

    def test_editar_rechaza_vencimiento_anterior_a_la_emision(self) -> None:
        factura = self.crear_factura("730", self.hoy)

        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura,
                {
                    "fecha": self.hoy,
                    "vencimiento": self.hoy - timedelta(days=1),
                    "descripcion": "Fechas invertidas",
                    "placas": "ABC123",
                    "subtotal_cop": 100_000,
                    "iva_cop": 0,
                    "retefuente_cop": 0,
                    "ica_cop": 0,
                },
                self.ruta,
            )

    def test_el_descuento_resta_del_total_pero_no_de_los_impuestos(self) -> None:
        """Fórmula autorizada por el dueño: total = subtotal + IVA − ret − ICA − descuento.

        Como en su hoja de Excel: la retención se calcula sobre el subtotal
        bruto y el descuento solo baja el total pendiente.
        """

        factura = db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": "800",
                "fecha": self.hoy,
                "vencimiento": self.hoy + timedelta(days=30),
                "cliente": "Cliente de prueba SAS",
                "descripcion": "Con descuento",
                "placas": "TAV906",
                "subtotal_cop": 3_800_000,
                "iva_cop": 0,
                "retefuente_cop": 38_000,
                "ica_cop": 0,
                "descuento_cop": 1_400,
            },
            self.ruta,
        )
        fila = db.obtener_factura(factura, self.ruta)
        self.assertEqual(fila["descuento_cop"], 1_400)
        self.assertEqual(fila["total_cop"], 3_800_000 - 38_000 - 1_400)
        self.assertEqual(fila["saldo_cop"], 3_760_600)

    def test_sin_descuento_todo_sigue_igual_que_antes(self) -> None:
        factura = self.crear_factura("801", self.hoy, 100_000)
        fila = db.obtener_factura(factura, self.ruta)
        self.assertEqual(fila["descuento_cop"], 0)
        self.assertEqual(fila["total_cop"], 100_000)

    def test_el_descuento_no_puede_superar_el_subtotal(self) -> None:
        datos = {
            "empresa_codigo": "NOVASA", "prefijo": "FEBA", "numero": "802",
            "fecha": self.hoy, "cliente": "Cliente de prueba SAS",
            "descripcion": "x", "placas": "x",
            "subtotal_cop": 100_000, "iva_cop": 0, "retefuente_cop": 0,
            "ica_cop": 0, "descuento_cop": 100_001,
        }
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura(datos, self.ruta)

    def test_el_descuento_negativo_se_rechaza(self) -> None:
        datos = {
            "empresa_codigo": "NOVASA", "prefijo": "FEBA", "numero": "803",
            "fecha": self.hoy, "cliente": "Cliente de prueba SAS",
            "descripcion": "x", "placas": "x",
            "subtotal_cop": 100_000, "iva_cop": 0, "retefuente_cop": 0,
            "ica_cop": 0, "descuento_cop": -1,
        }
        with self.assertRaises(db.ErrorCartera):
            db.crear_factura(datos, self.ruta)

    def test_editar_puede_corregir_el_descuento(self) -> None:
        factura = self.crear_factura("804", self.hoy, 100_000)
        db.actualizar_campos_factura(
            factura,
            {
                "descripcion": "Con descuento nuevo", "placas": "ABC123",
                "subtotal_cop": 100_000, "iva_cop": 0, "retefuente_cop": 0,
                "ica_cop": 0, "descuento_cop": 10_000,
            },
            self.ruta,
        )
        fila = db.obtener_factura(factura, self.ruta)
        self.assertEqual(fila["descuento_cop"], 10_000)
        self.assertEqual(fila["total_cop"], 90_000)

    def test_editar_sin_enviar_descuento_conserva_el_guardado(self) -> None:
        factura = db.crear_factura(
            {
                "empresa_codigo": "NOVASA", "prefijo": "FEBA", "numero": "805",
                "fecha": self.hoy, "cliente": "Cliente de prueba SAS",
                "descripcion": "x", "placas": "x",
                "subtotal_cop": 100_000, "iva_cop": 0, "retefuente_cop": 0,
                "ica_cop": 0, "descuento_cop": 5_000,
            },
            self.ruta,
        )
        db.actualizar_campos_factura(
            factura,
            {
                "descripcion": "Solo el detalle", "placas": "x",
                "subtotal_cop": 100_000, "iva_cop": 0, "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )
        self.assertEqual(db.obtener_factura(factura, self.ruta)["descuento_cop"], 5_000)

    def test_el_descuento_no_puede_dejar_el_total_bajo_los_abonos(self) -> None:
        factura = self.crear_factura("806", self.hoy, 100_000)
        db.registrar_abono(
            empresa_codigo="NOVASA", cliente_id=1, fecha=self.hoy,
            referencia="TRX-806", monto_cop=95_000,
            aplicaciones=[{"factura_id": factura, "monto_cop": 95_000}],
            ruta=self.ruta,
        )
        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura,
                {
                    "descripcion": "x", "placas": "x",
                    "subtotal_cop": 100_000, "iva_cop": 0, "retefuente_cop": 0,
                    "ica_cop": 0, "descuento_cop": 10_000,
                },
                self.ruta,
            )

    def test_una_base_creada_antes_del_descuento_se_migra_sola(self) -> None:
        """Las facturas guardadas antes de existir la columna siguen leyéndose."""

        import sqlite3

        vieja = Path(self.temporal.name) / "vieja.db"
        # Se construye una base con la forma ANTERIOR del esquema, sin la
        # columna, y con una factura ya guardada.
        db.inicializar(vieja)
        conexion = sqlite3.connect(vieja)
        try:
            conexion.execute("ALTER TABLE facturas_manual DROP COLUMN descuento_cop")
            conexion.commit()
        finally:
            conexion.close()
        factura = self.crear_factura_en("900", vieja)
        fila = db.obtener_factura(factura, vieja)
        self.assertEqual(fila["descuento_cop"], 0)
        self.assertEqual(fila["total_cop"], 100_000)

    def crear_factura_en(self, numero: str, ruta) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": "NOVASA",
                "prefijo": "FEBA",
                "numero": numero,
                "fecha": self.hoy,
                "vencimiento": self.hoy + timedelta(days=30),
                "cliente": "Cliente de prueba SAS",
                "descripcion": "Servicio de prueba",
                "placas": "ABC123",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            ruta,
        )

    def test_factura_manual_no_registra_nit(self) -> None:
        factura = self.crear_factura("400", self.hoy)

        self.assertEqual(db.obtener_factura(factura, self.ruta)["nit"], "")

    def test_sugerencias_incluyen_clientes_pagados_y_no_repiten_razones_sociales(self) -> None:
        factura = self.crear_factura("500", self.hoy)
        db.registrar_abono(
            empresa_codigo="NOVASA",
            cliente_id=1,
            fecha=self.hoy,
            referencia="PAGO-TOTAL",
            monto_cop=100_000,
            aplicaciones=[{"factura_id": factura, "monto_cop": 100_000}],
            ruta=self.ruta,
        )
        self.assertEqual(db.clientes_con_saldo("NOVASA", self.ruta), [])
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Cliente de prueba SAS"])
        datos = dict(db.obtener_factura(factura, self.ruta))
        datos.update(empresa_codigo="LUAC", prefijo="LUA", numero="500")
        db.crear_factura(datos, self.ruta)
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Cliente de prueba SAS"])
        datos.update(numero="501", cliente="Alimentos de prueba SAS")
        db.crear_factura(datos, self.ruta)
        self.assertEqual(
            db.listar_nombres_clientes(self.ruta),
            ["Alimentos de prueba SAS", "Cliente de prueba SAS"],
        )

    def editar_con_cliente(self, factura: int, cliente: str) -> None:
        db.actualizar_campos_factura(
            factura,
            {
                "cliente": cliente,
                "descripcion": "Servicio de prueba",
                "placas": "ABC123",
                "subtotal_cop": 100_000,
                "iva_cop": 0,
                "retefuente_cop": 0,
                "ica_cop": 0,
            },
            self.ruta,
        )

    def test_editar_corrige_el_cliente_si_la_factura_no_tiene_abonos(self) -> None:
        factura = self.crear_factura("900", self.hoy)
        anterior = db.obtener_factura(factura, self.ruta)["cliente_id"]

        self.editar_con_cliente(factura, "Cliente Correcto SAS")

        editada = db.obtener_factura(factura, self.ruta)
        self.assertEqual(editada["cliente"], "Cliente Correcto SAS")
        self.assertNotEqual(editada["cliente_id"], anterior)
        evento = db.resumen_actividad(1, self.ruta)[0]
        self.assertEqual(evento["accion"], "ACTUALIZADA")
        detalle = json.loads(evento["detalle"])
        self.assertEqual(detalle["cliente_id_antes"], anterior)
        self.assertEqual(detalle["cliente_id_despues"], editada["cliente_id"])

    def test_editar_no_cambia_el_cliente_de_una_factura_con_abonos(self) -> None:
        factura = self.crear_factura("901", self.hoy)
        db.registrar_abono(
            empresa_codigo="NOVASA", cliente_id=1, fecha=self.hoy, referencia="PAGO",
            monto_cop=10_000, aplicaciones=[{"factura_id": factura, "monto_cop": 10_000}],
            ruta=self.ruta,
        )

        with self.assertRaises(db.ErrorCartera) as contexto:
            self.editar_con_cliente(factura, "Cliente Correcto SAS")
        self.assertIn("abonos", str(contexto.exception))
        self.assertEqual(db.obtener_factura(factura, self.ruta)["cliente"], "Cliente de prueba SAS")
        # Escribir la misma razón social con otra grafía no es un cambio.
        self.editar_con_cliente(factura, "CLIENTE  DE PRUEBA sas")
        self.assertEqual(db.obtener_factura(factura, self.ruta)["cliente_id"], 1)

    def test_un_importe_que_no_cabe_en_la_nube_se_rechaza_con_un_mensaje(self) -> None:
        """Supabase guarda el dinero en INTEGER: el tope es 2.147.483.647 pesos."""

        datos = {
            "empresa_codigo": "NOVASA", "prefijo": "FEBA", "numero": "910",
            "fecha": self.hoy, "cliente": "Cliente de prueba SAS",
            "iva_cop": 0, "retefuente_cop": 0, "ica_cop": 0,
        }
        for subtotal in (2_147_483_648, 10**22):
            with self.subTest(subtotal=subtotal):
                with self.assertRaises(db.ErrorCartera) as contexto:
                    db.crear_factura({**datos, "subtotal_cop": subtotal}, self.ruta)
                self.assertIn("demasiado grande", str(contexto.exception))
        with self.assertRaises(db.ErrorCartera) as contexto:
            db.crear_factura(
                {**datos, "subtotal_cop": 2_000_000_000, "iva_cop": 380_000_000}, self.ruta
            )
        self.assertIn("total", str(contexto.exception))
        self.assertEqual(db.listar_facturas(ruta=self.ruta), [])

        factura = db.crear_factura({**datos, "subtotal_cop": 2_147_483_647}, self.ruta)
        self.assertEqual(db.obtener_factura(factura, self.ruta)["total_cop"], 2_147_483_647)
        with self.assertRaises(db.ErrorCartera):
            db.actualizar_campos_factura(
                factura, {**datos, "subtotal_cop": 2_147_483_648}, self.ruta
            )
        with self.assertRaises(db.ErrorCartera):
            db.registrar_abono(
                empresa_codigo="NOVASA", cliente_id=1, fecha=self.hoy, referencia="X",
                monto_cop=2_500_000_000, aplicaciones=[], ruta=self.ruta,
            )
        self.assertEqual(db.listar_abonos(ruta=self.ruta), [])


class UnMismoClienteNoSeDuplica(unittest.TestCase):
    """La misma razón social con otras mayúsculas o espacios es el mismo cliente."""

    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        self.hoy = hoy_colombia()
        db.inicializar(self.ruta)

    def factura(self, empresa: str, numero: str, cliente: str, subtotal: int = 100_000) -> int:
        return db.crear_factura(
            {
                "empresa_codigo": empresa,
                "prefijo": db.EMPRESAS[empresa]["prefijo"],
                "numero": numero,
                "fecha": self.hoy,
                "cliente": cliente,
                "subtotal_cop": subtotal,
            },
            self.ruta,
        )

    def cliente_id(self, factura: int) -> int:
        return int(db.obtener_factura(factura, self.ruta)["cliente_id"])

    def test_otra_grafia_en_la_misma_empresa_es_el_mismo_cliente(self) -> None:
        primera = self.factura("LUAC", "1", "Transportes Andinos SAS", 300_000)
        segunda = self.factura("LUAC", "2", "  TRANSPORTES   ANDINOS sas ", 200_000)
        tildes = self.factura("LUAC", "3", "CONSTRUCCIÓN ÁVILA SAS")
        otra_tilde = self.factura("LUAC", "4", "Construcción Ávila SAS")

        self.assertEqual(self.cliente_id(primera), self.cliente_id(segunda))
        self.assertEqual(self.cliente_id(tildes), self.cliente_id(otra_tilde))
        clientes = db.clientes_con_saldo("LUAC", self.ruta)
        andinos = next(c for c in clientes if c["cliente"] == "Transportes Andinos SAS")
        self.assertEqual(andinos["saldo_cop"], 500_000)
        self.assertEqual(
            len(db.facturas_pendientes_cliente("LUAC", andinos["cliente_id"], self.ruta)), 2
        )

    def test_un_cliente_nuevo_se_guarda_sin_espacios_repetidos(self) -> None:
        factura = self.factura("MSU", "1", "Acme   Andina  SAS")
        self.assertEqual(db.obtener_factura(factura, self.ruta)["cliente"], "Acme Andina SAS")
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Acme Andina SAS"])

    def test_cada_empresa_conserva_su_propio_cliente(self) -> None:
        novasa = self.factura("NOVASA", "1", "Acme SAS")
        luac = self.factura("LUAC", "1", "ACME SAS")
        self.assertNotEqual(self.cliente_id(novasa), self.cliente_id(luac))
        self.assertEqual(db.listar_nombres_clientes(self.ruta), ["Acme SAS"])


class LosClientesRepetidosSeUnenAlIniciar(unittest.TestCase):
    """Una base que ya tiene el cliente partido se arregla sola en inicializar."""

    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "cartera.db"
        self.hoy = hoy_colombia()
        datos = {"fecha": self.hoy, "subtotal_cop": 1_000_000}
        self.lua1 = db.crear_factura(
            {**datos, "empresa_codigo": "LUAC", "prefijo": "LUA", "numero": "1",
             "cliente": "Obras y Maquinaria SAS"},
            self.ruta,
        )
        self.lua2 = db.crear_factura(
            {**datos, "empresa_codigo": "LUAC", "prefijo": "LUA", "numero": "2",
             "cliente": "Temporal SAS"},
            self.ruta,
        )
        self.feba = db.crear_factura(
            {**datos, "empresa_codigo": "NOVASA", "prefijo": "FEBA", "numero": "1",
             "cliente": "Solitario  SAS"},
            self.ruta,
        )
        self.original = int(db.obtener_factura(self.lua1, self.ruta)["cliente_id"])
        self.repetido = int(db.obtener_factura(self.lua2, self.ruta)["cliente_id"])
        db.registrar_abono(
            empresa_codigo="LUAC", cliente_id=self.repetido, fecha=self.hoy,
            referencia="PAGO-PARCIAL", monto_cop=400_000,
            aplicaciones=[{"factura_id": self.lua2, "monto_cop": 400_000}],
            ruta=self.ruta,
        )
        # Así quedaban las bases antes: el mismo cliente con otra grafía.
        with closing(sqlite3.connect(self.ruta)) as conexion:
            conexion.execute(
                "UPDATE clientes SET nombre = 'OBRAS  Y MAQUINARIA SAS' WHERE id = ?",
                (self.repetido,),
            )
            conexion.execute(
                "UPDATE clientes SET nombre = 'Solitario  SAS' WHERE empresa_codigo = 'NOVASA'"
            )
            conexion.commit()

    def filas(self, sql: str) -> list[tuple]:
        with closing(sqlite3.connect(self.ruta)) as conexion:
            return conexion.execute(sql).fetchall()

    def test_une_facturas_y_abonos_en_el_cliente_mas_antiguo(self) -> None:
        db.inicializar(self.ruta)

        self.assertEqual(
            self.filas("SELECT id, nombre FROM clientes WHERE empresa_codigo = 'LUAC'"),
            [(self.original, "Obras y Maquinaria SAS")],
        )
        self.assertEqual(
            self.filas("SELECT DISTINCT cliente_id FROM facturas_manual WHERE empresa_codigo = 'LUAC'"),
            [(self.original,)],
        )
        self.assertEqual(self.filas("SELECT cliente_id FROM abonos_manual"), [(self.original,)])
        # Los espacios repetidos también se corrigen, sin tocar otras empresas.
        self.assertEqual(
            self.filas("SELECT nombre FROM clientes WHERE empresa_codigo = 'NOVASA'"),
            [("Solitario SAS",)],
        )
        unificados = self.filas(
            "SELECT entidad_id, detalle FROM auditoria WHERE accion = 'UNIFICADO' ORDER BY id"
        )
        self.assertEqual(unificados[0][0], str(self.original))
        self.assertEqual(json.loads(unificados[0][1])["ids_unidos"], [self.repetido])

    def test_abono_aqui_alcanza_todas_las_facturas_del_cliente(self) -> None:
        clientes = db.clientes_con_saldo("LUAC", self.ruta)
        self.assertEqual(len(clientes), 1)
        self.assertEqual(clientes[0]["saldo_cop"], 1_600_000)
        pendientes = db.facturas_pendientes_cliente("LUAC", clientes[0]["cliente_id"], self.ruta)
        self.assertEqual({f["id"] for f in pendientes}, {self.lua1, self.lua2})
        aplicaciones, sobrante = db.previsualizar_fifo(pendientes, 1_600_000)
        db.registrar_abono(
            empresa_codigo="LUAC", cliente_id=clientes[0]["cliente_id"], fecha=self.hoy,
            referencia="PAGO-TOTAL", monto_cop=1_600_000, aplicaciones=aplicaciones,
            ruta=self.ruta,
        )
        self.assertEqual(sobrante, 0)
        self.assertEqual(db.clientes_con_saldo("LUAC", self.ruta), [])

    def test_volver_a_iniciar_no_repite_nada(self) -> None:
        db.inicializar(self.ruta)
        antes = self.filas("SELECT COUNT(*) FROM auditoria")
        db.inicializar(self.ruta)
        self.assertEqual(self.filas("SELECT COUNT(*) FROM auditoria"), antes)


class DatosDeDemostracion(unittest.TestCase):
    def test_en_la_nube_la_muestra_no_se_puede_cargar(self) -> None:
        nube = {"SUPABASE_DB_URL": "postgresql://u:p@host/db", "NOVASALUM_DB": ""}
        with patch.dict("os.environ", nube), \
                patch.object(db, "_conexion_pg", side_effect=AssertionError("sin red")):
            self.assertFalse(db.admite_demostracion())
            with self.assertRaises(db.ErrorCartera) as contexto:
                db.cargar_datos_demostracion()
        self.assertIn("nube", str(contexto.exception))

    def test_la_muestra_local_no_ocupa_numeros_reales(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "cartera.db"
            self.assertTrue(db.admite_demostracion(ruta))
            db.cargar_datos_demostracion(ruta)
            self.assertEqual({f["prefijo"] for f in db.listar_facturas(ruta=ruta)}, {"DEMO"})
            with self.assertRaises(db.ErrorCartera):
                db.cargar_datos_demostracion(ruta)
            for empresa, prefijo, numero in (("LUAC", "LUA", "208"), ("NOVASA", "FEBA", "1079")):
                db.crear_factura(
                    {"empresa_codigo": empresa, "prefijo": prefijo, "numero": numero,
                     "fecha": hoy_colombia(), "cliente": "Cliente real SAS",
                     "subtotal_cop": 100_000},
                    ruta,
                )
            self.assertEqual(len(db.listar_facturas(ruta=ruta)), 7)


if __name__ == "__main__":
    unittest.main()
