import json
import os
import sqlite3
import sys
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUERTO = int(os.environ.get("FACTURAS_PUERTO", "8414"))
CARPETA = Path(__file__).parent
BD = Path(os.environ.get("FACTURAS_BD", CARPETA / "facturas.db"))
HTML = CARPETA / "index.html"
PREFIJO = {"factura": "F", "presupuesto": "P"}
ESTADOS = {"factura": {"emitida", "pagada"}, "presupuesto": {"emitida", "aceptado", "rechazado"}}
CAMPOS_EMISOR = ("nombre", "nif", "direccion", "email", "telefono", "iban", "pie")
CAMPOS_CLIENTE = ("nombre", "nif", "direccion", "email")


class Error(Exception):
    pass


def conectar() -> sqlite3.Connection:
    c = sqlite3.connect(BD, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript("""
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS clientes (id INTEGER PRIMARY KEY, datos TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY,
            tipo TEXT NOT NULL CHECK (tipo IN ('factura', 'presupuesto')),
            estado TEXT NOT NULL DEFAULT 'borrador',
            serie TEXT,
            numero INTEGER,
            cliente_id INTEGER,
            datos TEXT NOT NULL,
            UNIQUE (tipo, serie, numero)
        );
    """)
    return c


def texto(d: dict, campos: tuple) -> dict:
    return {k: str(d.get(k, "")).strip()[:2000] for k in campos}


def leer(c: sqlite3.Connection) -> dict:
    fila = c.execute("SELECT valor FROM ajustes WHERE clave = 'emisor'").fetchone()
    return {
        "emisor": json.loads(fila["valor"]) if fila else texto({}, CAMPOS_EMISOR),
        "clientes": [{"id": f["id"], **json.loads(f["datos"])} for f in c.execute("SELECT * FROM clientes ORDER BY id")],
        "documentos": [
            {"id": f["id"], "tipo": f["tipo"], "estado": f["estado"], "cliente_id": f["cliente_id"],
             "codigo": f"{PREFIJO[f['tipo']]}{f['serie']}-{f['numero']:04d}" if f["numero"] else None,
             **json.loads(f["datos"])}
            for f in c.execute("SELECT * FROM documentos ORDER BY id DESC")
        ],
    }


def lineas_validas(lineas) -> list[dict]:
    salida = []
    for l in lineas if isinstance(lineas, list) else []:
        try:
            linea = {"concepto": str(l.get("concepto", "")).strip()[:500], "cantidad": float(l.get("cantidad", 0)),
                     "precio": float(l.get("precio", 0)), "iva": float(l.get("iva", 21))}
        except (TypeError, ValueError, AttributeError):
            raise Error("Hay una línea con un número que no es válido.")
        if linea["concepto"] or linea["precio"]:
            salida.append(linea)
    return salida


def guardar_documento(c: sqlite3.Connection, d: dict) -> int:
    tipo = d.get("tipo")
    if tipo not in PREFIJO:
        raise Error("Tipo de documento no válido.")
    cliente_id = d.get("cliente_id")
    if not c.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
        raise Error("Elige un cliente.")
    try:
        irpf = float(d.get("irpf") or 0)
    except (TypeError, ValueError):
        raise Error("La retención de IRPF no es un número.")
    datos = {
        "fecha": str(d.get("fecha") or date.today().isoformat())[:10],
        "vencimiento": str(d.get("vencimiento") or "")[:10],
        "lineas": lineas_validas(d.get("lineas")),
        "irpf": irpf,
        "notas": str(d.get("notas", "")).strip()[:2000],
    }
    if d.get("id"):
        fila = c.execute("SELECT estado FROM documentos WHERE id = ?", (d["id"],)).fetchone()
        if not fila:
            raise Error("Ese documento ya no existe.")
        if fila["estado"] != "borrador":
            raise Error("Un documento emitido no se puede modificar. Para corregir una factura, emite una rectificativa.")
        c.execute("UPDATE documentos SET tipo = ?, cliente_id = ?, datos = ? WHERE id = ?", (tipo, cliente_id, json.dumps(datos), d["id"]))
        return d["id"]
    return c.execute("INSERT INTO documentos (tipo, cliente_id, datos) VALUES (?, ?, ?)", (tipo, cliente_id, json.dumps(datos))).lastrowid


def emitir(c: sqlite3.Connection, id_: int):
    c.execute("BEGIN IMMEDIATE")
    try:
        fila = c.execute("SELECT * FROM documentos WHERE id = ?", (id_,)).fetchone()
        if not fila or fila["estado"] != "borrador":
            raise Error("Solo se emite un borrador.")
        datos = json.loads(fila["datos"])
        if not datos["lineas"]:
            raise Error("Añade al menos una línea.")
        emisor = c.execute("SELECT valor FROM ajustes WHERE clave = 'emisor'").fetchone()
        emisor = json.loads(emisor["valor"]) if emisor else {}
        if fila["tipo"] == "factura" and not (emisor.get("nombre") and emisor.get("nif")):
            raise Error("Rellena tu nombre y NIF en Mis datos antes de emitir una factura.")
        cliente = json.loads(c.execute("SELECT datos FROM clientes WHERE id = ?", (fila["cliente_id"],)).fetchone()["datos"])
        if fila["tipo"] == "factura" and not cliente.get("nif"):
            raise Error("Una factura completa lleva el NIF del cliente: añádelo en Clientes.")
        # Numeración correlativa por serie anual. La fecha de emisión manda la serie.
        serie = datos["fecha"][:4]
        ultima = c.execute("SELECT numero, datos FROM documentos WHERE tipo = ? AND serie = ? ORDER BY numero DESC LIMIT 1",
                           (fila["tipo"], serie)).fetchone()
        if fila["tipo"] == "factura" and ultima and json.loads(ultima["datos"])["fecha"] > datos["fecha"]:
            raise Error(f"La fecha es anterior a la de la última factura emitida ({json.loads(ultima['datos'])['fecha']}): "
                        "la numeración y las fechas tienen que ir en orden.")
        numero = (ultima["numero"] if ultima else 0) + 1
        # Se congelan los datos de emisor y cliente: cambiarlos después no altera lo emitido.
        datos.update(emisor=emisor, cliente=cliente)
        c.execute("UPDATE documentos SET estado = 'emitida', serie = ?, numero = ?, datos = ? WHERE id = ?",
                  (serie, numero, json.dumps(datos), id_))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def accion(c: sqlite3.Connection, ruta: str, d: dict):
    if ruta == "/api/emisor":
        c.execute("INSERT OR REPLACE INTO ajustes VALUES ('emisor', ?)", (json.dumps(texto(d, CAMPOS_EMISOR)),))
    elif ruta == "/api/cliente":
        datos = texto(d, CAMPOS_CLIENTE)
        if not datos["nombre"]:
            raise Error("El cliente necesita un nombre.")
        if d.get("id"):
            c.execute("UPDATE clientes SET datos = ? WHERE id = ?", (json.dumps(datos), d["id"]))
        else:
            return {"id": c.execute("INSERT INTO clientes (datos) VALUES (?)", (json.dumps(datos),)).lastrowid}
    elif ruta == "/api/cliente/borrar":
        if c.execute("SELECT 1 FROM documentos WHERE cliente_id = ?", (d.get("id"),)).fetchone():
            raise Error("Este cliente tiene documentos: no se puede borrar.")
        c.execute("DELETE FROM clientes WHERE id = ?", (d.get("id"),))
    elif ruta == "/api/documento":
        return {"id": guardar_documento(c, d)}
    elif ruta == "/api/documento/emitir":
        emitir(c, d.get("id"))
    elif ruta == "/api/documento/estado":
        fila = c.execute("SELECT tipo, estado FROM documentos WHERE id = ?", (d.get("id"),)).fetchone()
        if not fila or fila["estado"] == "borrador" or d.get("estado") not in ESTADOS[fila["tipo"]]:
            raise Error("Ese cambio de estado no es válido.")
        c.execute("UPDATE documentos SET estado = ? WHERE id = ?", (d["estado"], d["id"]))
    elif ruta == "/api/documento/borrar":
        if c.execute("DELETE FROM documentos WHERE id = ? AND estado = 'borrador'", (d.get("id"),)).rowcount == 0:
            raise Error("Solo se borran borradores: lo emitido se conserva.")
    elif ruta == "/api/documento/convertir":
        fila = c.execute("SELECT * FROM documentos WHERE id = ? AND tipo = 'presupuesto'", (d.get("id"),)).fetchone()
        if not fila:
            raise Error("Solo se convierte un presupuesto.")
        datos = json.loads(fila["datos"])
        nuevo = {k: datos[k] for k in ("lineas", "irpf", "notas")}
        nuevo["fecha"] = date.today().isoformat()
        nuevo["vencimiento"] = ""
        return {"id": c.execute("INSERT INTO documentos (tipo, cliente_id, datos) VALUES ('factura', ?, ?)",
                                (fila["cliente_id"], json.dumps(nuevo))).lastrowid}
    else:
        raise Error("No existe.")
    return {"ok": True}


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def responder(self, codigo: int, datos, tipo="application/json"):
        cuerpo = datos if isinstance(datos, bytes) else json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/":
            return self.responder(200, HTML.read_bytes(), "text/html")
        if self.path == "/api/datos":
            c = conectar()
            try:
                return self.responder(200, leer(c))
            finally:
                c.close()
        self.responder(404, {"error": "No existe"})

    def do_POST(self):
        # Solo desde la propia página: otra web abierta en el navegador no puede tocar tus facturas.
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PUERTO}", f"http://localhost:{PUERTO}"):
            return self.responder(403, {"error": "Origen no permitido"})
        tam = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
        try:
            d = json.loads(self.rfile.read(tam) or b"{}")
            if not isinstance(d, dict):
                raise Error("Petición no válida.")
            c = conectar()
            try:
                return self.responder(200, accion(c, self.path, d))
            finally:
                c.close()
        except (Error, json.JSONDecodeError) as e:
            self.responder(400, {"error": str(e) or "Petición no válida."})


def main():
    conectar().close()
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    url = f"http://127.0.0.1:{PUERTO}"
    print(f"Facturas y presupuestos en {url}  (Ctrl+C para cerrar)\nDatos en {BD.resolve()}: haz copia de este archivo.")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
