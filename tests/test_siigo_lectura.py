"""Motor de lectura de Siigo, probado sin red y sin credenciales.

``ClienteSiigo`` acepta un transporte inyectable, así que toda la conversación
con el API se puede simular. Ninguna prueba de este archivo abre un socket.
"""

from __future__ import annotations

import datetime as dt
import unittest

from src.siigo import (
    ClienteSiigo,
    ConfiguracionSiigo,
    CredencialesSiigo,
    RespuestaHTTP,
)
from src.siigo_lectura import (
    LECTURA_DETALLE,
    LECTURA_FALLO,
    ParametrosLectura,
    leer_cartera,
)


HOY = dt.date(2026, 9, 11)


def _configuracion() -> ConfiguracionSiigo:
    credencial = CredencialesSiigo(
        usuario="usuario@empresa.com", access_key="clave", partner_id="NovaLogistics"
    )
    return ConfiguracionSiigo(
        empresas={"NOVASA": credencial, "LUAC": credencial, "MSU": credencial}
    )


class TransporteSimulado:
    """Simula el API: autenticación, listado paginado y detalle por factura."""

    def __init__(
        self,
        facturas_por_empresa: dict[str, list[str]],
        *,
        detalles_que_fallan: set[str] | None = None,
        empresas_que_fallan: set[str] | None = None,
    ) -> None:
        self.facturas_por_empresa = facturas_por_empresa
        self.detalles_que_fallan = detalles_que_fallan or set()
        self.empresas_que_fallan = empresas_que_fallan or set()
        self.llamadas: list[tuple[str, str]] = []
        self.empresa_actual = ""

    def request(self, method, url, *, headers, json, timeout):
        ruta = url.split("?")[0]
        self.llamadas.append((method, ruta))
        if ruta.endswith("/auth"):
            return RespuestaHTTP(200, {"access_token": "token", "expires_in": 3600})
        if self.empresa_actual in self.empresas_que_fallan:
            return RespuestaHTTP(500, {"message": "empresa caída"})
        if "/v1/invoices/" in ruta:
            identificador = ruta.rsplit("/", 1)[-1]
            if identificador in self.detalles_que_fallan:
                return RespuestaHTTP(500, {"message": "detalle no disponible"})
            return RespuestaHTTP(200, {
                "id": identificador,
                "name": f"FEBA{identificador}",
                "date": "2026-03-12",
                "due_date": "2026-04-11",
                "total": 810_000,
                "balance": 810_000,
                "customer": {"id": "c1", "identification": "900123456",
                             "name": "TMP IZAJES SAS", "branch_office": 0},
                "currency": {"code": "COP"},
                "items": [{"description": "Transporte", "price": 900_000, "quantity": 1}],
                "retentions": [{"type": "Retefuente", "value": 90_000}],
            })
        if "/v1/invoices" in ruta:
            ids = self.facturas_por_empresa.get(self.empresa_actual, [])
            return RespuestaHTTP(200, {
                "results": [{"id": i, "name": f"FEBA{i}"} for i in ids],
                "pagination": {"total_results": len(ids)},
            })
        return RespuestaHTTP(404, {"message": "no encontrado"})


def _fabrica(transporte: TransporteSimulado):
    def crear(empresa: str, configuracion: ConfiguracionSiigo) -> ClienteSiigo:
        transporte.empresa_actual = empresa
        return ClienteSiigo(
            empresa, configuracion, transporte=transporte, dormir=lambda _: None
        )
    return crear


class LecturaPorFacturaTests(unittest.TestCase):
    def test_consulta_cada_factura_individualmente(self) -> None:
        transporte = TransporteSimulado({"NOVASA": ["1001", "1002", "1003"]})
        reporte = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
            trabajadores=1,
        )
        detalles = [r for m, r in transporte.llamadas if "/v1/invoices/" in r]
        self.assertEqual(len(detalles), 3)
        self.assertEqual(reporte.total_facturas, 3)
        self.assertEqual(reporte.sin_detalle, 0)

    def test_solo_usa_get_salvo_la_autenticacion(self) -> None:
        transporte = TransporteSimulado({"NOVASA": ["1001"]})
        leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
        )
        for metodo, ruta in transporte.llamadas:
            if metodo == "POST":
                self.assertTrue(ruta.endswith("/auth"), ruta)
            else:
                self.assertEqual(metodo, "GET", ruta)

    def test_el_detalle_llena_lo_que_el_listado_no_trae(self) -> None:
        transporte = TransporteSimulado({"NOVASA": ["1001"]})
        reporte = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
        )
        fila = reporte.facturas.iloc[0]
        self.assertEqual(fila["subtotal_siigo"], 900_000)
        self.assertEqual(fila["retefuente_siigo"], 90_000)
        self.assertEqual(fila["saldo_siigo"], 810_000)
        self.assertEqual(fila["estado_siigo"], "VENCIDA")
        self.assertTrue(fila["lectura_completa"])
        self.assertEqual(fila["estado_lectura"], LECTURA_DETALLE)


class ToleranciaAFallosTests(unittest.TestCase):
    def test_una_factura_que_falla_no_tumba_el_lote(self) -> None:
        transporte = TransporteSimulado(
            {"NOVASA": ["1001", "1002", "1003"]}, detalles_que_fallan={"1002"}
        )
        reporte = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
            trabajadores=1,
        )
        self.assertEqual(reporte.total_facturas, 3)
        self.assertEqual(reporte.sin_detalle, 1)
        fallida = reporte.facturas[reporte.facturas["estado_lectura"] == LECTURA_FALLO]
        self.assertEqual(len(fallida), 1)
        self.assertEqual(fallida.iloc[0]["factura"], "FEBA1002")
        self.assertTrue(any("FEBA1002" in clave for clave in reporte.errores))

    def test_una_empresa_caida_no_impide_leer_las_otras(self) -> None:
        transporte = TransporteSimulado(
            {"NOVASA": ["1001"], "LUAC": ["2001"]}, empresas_que_fallan={"LUAC"}
        )
        reporte = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA", "LUAC"), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
        )
        self.assertEqual(reporte.total_facturas, 1)
        self.assertIn("LUAC", reporte.errores)
        self.assertEqual(set(reporte.facturas["empresa_codigo"]), {"NOVASA"})

    def test_periodo_sin_facturas_no_es_un_error(self) -> None:
        transporte = TransporteSimulado({"NOVASA": []})
        reporte = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
        )
        self.assertEqual(reporte.total_facturas, 0)
        self.assertEqual(reporte.errores, {})


class SupervisionTests(unittest.TestCase):
    def test_el_reporte_cuenta_lo_leido_por_empresa(self) -> None:
        transporte = TransporteSimulado(
            {"NOVASA": ["1001", "1002"]}, detalles_que_fallan={"1002"}
        )
        reporte = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
            trabajadores=1,
        )
        resumen = reporte.resumenes[0]
        self.assertEqual(resumen.facturas_en_periodo, 2)
        self.assertEqual(resumen.detalles_leidos, 1)
        self.assertEqual(resumen.detalles_fallidos, 1)
        self.assertGreater(resumen.llamadas, 0)

    def test_el_token_se_pide_una_sola_vez_por_empresa(self) -> None:
        transporte = TransporteSimulado({"NOVASA": ["1001", "1002", "1003", "1004"]})
        leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(transporte),
            hoy=HOY,
            trabajadores=4,
        )
        autenticaciones = [r for m, r in transporte.llamadas if r.endswith("/auth")]
        self.assertEqual(len(autenticaciones), 1)

    def test_leer_en_paralelo_devuelve_las_mismas_facturas(self) -> None:
        ids = [str(1000 + i) for i in range(12)]
        secuencial = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(TransporteSimulado({"NOVASA": ids})),
            hoy=HOY,
            trabajadores=1,
        )
        paralelo = leer_cartera(
            _configuracion(),
            ParametrosLectura(("NOVASA",), HOY, HOY),
            fabrica_cliente=_fabrica(TransporteSimulado({"NOVASA": ids})),
            hoy=HOY,
            trabajadores=6,
        )
        self.assertEqual(
            list(secuencial.facturas["factura"]), list(paralelo.facturas["factura"])
        )


class MuestraTests(unittest.TestCase):
    def test_la_muestra_no_lee_ninguna_base_de_datos(self) -> None:
        import sqlite3
        from unittest.mock import patch

        from src.siigo_muestra import cargar_muestra

        with patch.object(
            sqlite3, "connect", side_effect=AssertionError("la muestra no usa SQLite")
        ):
            reporte = cargar_muestra(hoy=HOY)
        self.assertGreater(reporte.total_facturas, 0)
        self.assertEqual(reporte.sin_detalle, 1)
        estados = set(reporte.facturas["estado_siigo"])
        self.assertIn("ANULADA", estados)
        self.assertIn("PAGADA", estados)


if __name__ == "__main__":
    unittest.main()
