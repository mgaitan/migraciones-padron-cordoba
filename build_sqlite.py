# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pandas>=2.2.0",
#     "python-dateutil>=2.9.0",
#     "nameparser>=1.1.3",
# ]
# ///
"""
ETL para normalizar padrones CSV/TSV/pipe a SQLite.

Salidas:
- padron.sqlite con tablas: personas, elecciones, secciones.
"""
from __future__ import annotations

import csv
import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from dateutil import parser as dateparser
from nameparser import HumanName


@dataclass
class RowContext:
    anio: int
    fuente: str


def detect_reader(path: Path) -> Tuple[str, Iterable[List[str]]]:
    """
    Detecta delimitador y devuelve nombre del delimiter + iterador de filas.
    Para 2017 (pipe en una sola columna) detectamos y separamos manualmente.
    """
    with path.open("r", encoding="utf-8", newline="") as fh:
        sample = fh.readline()
    # 2017: viene con pipes dentro pero guardado como CSV simple
    if "|" in sample and sample.count("|") > 3:
        def gen():
            with path.open("r", encoding="utf-8", newline="") as fh:
                for line in fh:
                    yield [field.strip() for field in line.rstrip("\n").split("|")]
        return "pipe", gen()
    # TSV
    if "\t" in sample:
        delimiter = "\t"
    else:
        delimiter = ";" if ";" in sample else ","

    def gen():
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            for row in reader:
                yield [col.strip() for col in row]

    return delimiter, gen()


def clean_int(value: str | int | float | None) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", "")
    if s.isdigit():
        return int(s)
    try:
        return int(float(s))
    except Exception:
        return None


def split_nombre(full: str) -> tuple[str | None, str | None, str | None]:
    if not full:
        return None, None, None
    n = HumanName(full)
    apellido = " ".join(part for part in [n.last] if part).strip() or None
    nombres = " ".join(part for part in [n.first, n.middle] if part).strip() or None
    comp = " ".join([apellido or "", nombres or ""]).strip() or None
    return apellido, nombres, comp


def parse_fecha(s: str | None) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        dt = dateparser.parse(s, dayfirst=True, yearfirst=False)
        return dt.date().isoformat()
    except Exception:
        return None


def split_named_code(value: str | None) -> tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    parts = [p.strip() for p in value.split("-", 1)]
    if len(parts) == 2:
        code, name = parts
    else:
        code, name = parts[0], None
    code = code.zfill(3) if code.isdigit() and len(code) < 3 else code
    return code, name


def yield_rows(path: Path) -> Iterable[tuple[RowContext, List[str]]]:
    stem = path.name
    anio = int(stem.split("-")[0].split("_")[0])
    delim, rows = detect_reader(path)
    for row in rows:
        if not row:
            continue
        yield RowContext(anio=anio, fuente=stem), row


def map_row(ctx: RowContext, row: List[str]) -> tuple[dict, dict, Optional[dict]]:
    """
    Devuelve (persona, eleccion, seccion?) dicts listos para DataFrame.
    Campos ausentes quedan en None.
    """
    anio = ctx.anio
    fuente = ctx.fuente
    persona: dict = {
        "dni": None,
        "apellido": None,
        "nombres": None,
        "nombre_completo": None,
        "sexo": None,
        "clase": None,
        "fecha_nac": None,
    }
    eleccion: dict = {
        "anio": anio,
        "dni": None,
        "seccion": None,
        "circuito": None,
        "mesa": None,
        "orden": None,
        "domicilio": None,
        "tipodni": None,
        "profesion": None,
        "analf": None,
        "ejemplar": None,
        "fuente": fuente,
    }
    seccion_row: Optional[dict] = None

    def set_names(apellido: Optional[str], nombres: Optional[str], full: Optional[str] = None):
        persona["apellido"] = persona["apellido"] or (apellido.strip() if apellido else None)
        persona["nombres"] = persona["nombres"] or (nombres.strip() if nombres else None)
        persona["nombre_completo"] = persona["nombre_completo"] or (
            full.strip() if full else None
        )

    # Map según año
    if anio in (2011, 2013):
        # positions align con 2013 headers
        dni = clean_int(row[1] if len(row) > 1 else None)
        apellido = row[3] if len(row) > 3 else None
        nombres = row[4] if len(row) > 4 else None
        clase = clean_int(row[2] if len(row) > 2 else None)
        domicilio = row[6] if len(row) > 6 else None
        tipodni = row[7] if len(row) > 7 else None
        seccion = row[8] if len(row) > 8 else None
        circuito = row[9] if len(row) > 9 else None
        mesa = row[10] if len(row) > 10 else None
        sexo = (row[11] if len(row) > 11 else None) or None
        ejemplar = row[12] if len(row) > 12 else None
        orden = clean_int(row[15] if len(row) > 15 else None)
        profesion = row[5] if len(row) > 5 else None
        analf = row[13] if len(row) > 13 else None
        persona["dni"] = dni
        persona["clase"] = clase
        persona["sexo"] = sexo or None
        set_names(apellido, nombres, None)
        eleccion.update(
            dict(
                dni=dni,
                seccion=seccion,
                circuito=circuito,
                mesa=mesa,
                orden=orden,
                domicilio=domicilio,
                tipodni=tipodni,
                profesion=profesion,
                analf=analf,
                ejemplar=ejemplar,
            )
        )
    elif anio == 2015:
        dni = clean_int(row[0] if len(row) > 0 else None)
        clase = clean_int(row[1] if len(row) > 1 else None)
        apellido = row[2] if len(row) > 2 else None
        nombres = row[3] if len(row) > 3 else None
        profesion = row[4] if len(row) > 4 else None
        domicilio = row[5] if len(row) > 5 else None
        analf = row[6] if len(row) > 6 else None
        tipodni = row[7] if len(row) > 7 else None
        seccion = row[8] if len(row) > 8 else None
        circuito = row[9] if len(row) > 9 else None
        mesa = row[10] if len(row) > 10 else None
        sexo = row[11] if len(row) > 11 else None
        orden = clean_int(row[13] if len(row) > 13 else None)
        persona["dni"] = dni
        persona["clase"] = clase
        persona["sexo"] = sexo or None
        set_names(apellido, nombres, None)
        eleccion.update(
            dict(
                dni=dni,
                seccion=seccion.strip() if seccion else None,
                circuito=circuito.strip() if circuito else None,
                mesa=str(mesa).strip() if mesa else None,
                orden=orden,
                domicilio=domicilio,
                tipodni=tipodni,
                profesion=profesion,
                analf=analf,
            )
        )
    elif anio == 2017:
        dni = clean_int(row[1] if len(row) > 1 else None)
        clase = clean_int(row[2] if len(row) > 2 else None)
        apellido = row[3] if len(row) > 3 else None
        nombres = row[4] if len(row) > 4 else None
        domicilio = row[6] if len(row) > 6 else None
        tipodni = row[7] if len(row) > 7 else None
        seccion = row[8] if len(row) > 8 else None
        circuito = row[9] if len(row) > 9 else None
        mesa = row[10] if len(row) > 10 else None
        sexo = row[11] if len(row) > 11 else None
        ejemplar = row[12] if len(row) > 12 else None
        analf = row[17] if len(row) > 17 else None
        fecha_nac = parse_fecha(row[18] if len(row) > 18 else None)
        persona["dni"] = dni
        persona["clase"] = clase
        persona["sexo"] = sexo or None
        persona["fecha_nac"] = fecha_nac
        set_names(apellido, nombres, None)
        eleccion.update(
            dict(
                dni=dni,
                seccion=seccion,
                circuito=circuito,
                mesa=mesa,
                orden=None,
                domicilio=domicilio,
                tipodni=tipodni,
                analf=analf,
                ejemplar=ejemplar,
            )
        )
    elif anio == 2025:
        full = row[1] if len(row) > 1 else None
        apellido, nombres, comp = split_nombre(full or "")
        dni = clean_int(row[3] if len(row) > 3 else None)
        clase = clean_int(row[5] if len(row) > 5 else None)
        orden = clean_int(row[0] if len(row) > 0 else None)
        domicilio = row[2] if len(row) > 2 else None
        tipodni = row[4] if len(row) > 4 else None  # en este dataset tipodni viene en 'ejemplar'
        seccion_code, seccion_name = split_named_code(row[6] if len(row) > 6 else None)
        circuito_code, circuito_name = split_named_code(row[7] if len(row) > 7 else None)
        mesa = row[8] if len(row) > 8 else None
        persona["dni"] = dni
        persona["clase"] = clase
        persona["sexo"] = None
        set_names(apellido, nombres, comp or full)
        eleccion.update(
            dict(
                dni=dni,
                seccion=seccion_code,
                circuito=circuito_code,
                mesa=mesa,
                orden=orden,
                domicilio=domicilio,
                tipodni=tipodni,
                ejemplar=None,
            )
        )
        seccion_row = dict(
            anio=anio,
            seccion=seccion_code,
            seccion_nombre=seccion_name,
            circuito=circuito_code,
            circuito_nombre=circuito_name,
        )
    else:
        raise ValueError(f"No mapping for year {anio}")

    # Si no hay apellido/nombres pero hay nombre_completo, dividir
    if not persona["apellido"] and not persona["nombres"] and persona["nombre_completo"]:
        ap, no, comp = split_nombre(persona["nombre_completo"])
        set_names(ap, no, comp)
    if not persona["nombre_completo"] and (persona["apellido"] or persona["nombres"]):
        combined = " ".join(
            part for part in [persona["apellido"], persona["nombres"]] if part
        ).strip()
        persona["nombre_completo"] = combined or None

    return persona, eleccion, seccion_row


def merge_personas(entries: list[dict]) -> list[dict]:
    by_dni: dict[int, dict] = {}
    for p in entries:
        dni = p.get("dni")
        if dni is None:
            continue
        existing = by_dni.setdefault(dni, {k: None for k in p.keys()})
        for k, v in p.items():
            if existing.get(k) is None and v:
                existing[k] = v
    return list(by_dni.values())


def create_tables(conn: sqlite3.Connection):
    conn.execute("DROP TABLE IF EXISTS personas")
    conn.execute("DROP TABLE IF EXISTS elecciones")
    conn.execute("DROP TABLE IF EXISTS secciones")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS personas (
            dni INTEGER PRIMARY KEY,
            apellido TEXT,
            nombres TEXT,
            nombre_completo TEXT,
            sexo TEXT,
            clase INTEGER,
            fecha_nac TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elecciones (
            anio INTEGER,
            dni INTEGER,
            seccion TEXT,
            circuito TEXT,
            mesa TEXT,
            orden INTEGER,
            domicilio TEXT,
            tipodni TEXT,
            profesion TEXT,
            analf TEXT,
            ejemplar TEXT,
            fuente TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS secciones (
            anio INTEGER,
            seccion TEXT,
            seccion_nombre TEXT,
            circuito TEXT,
            circuito_nombre TEXT,
            PRIMARY KEY (anio, seccion, circuito)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elecciones_dni_anio ON elecciones(dni, anio)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elecciones_seccion ON elecciones(seccion)")


def upsert_batches(
    conn: sqlite3.Connection,
    personas_batch: list[dict],
    elecciones_batch: list[dict],
    secciones_batch: list[dict],
):
    if personas_batch:
        conn.executemany(
            """
            INSERT INTO personas (dni, apellido, nombres, nombre_completo, sexo, clase, fecha_nac)
            VALUES (:dni, :apellido, :nombres, :nombre_completo, :sexo, :clase, :fecha_nac)
            ON CONFLICT(dni) DO UPDATE SET
                apellido=COALESCE(excluded.apellido, personas.apellido),
                nombres=COALESCE(excluded.nombres, personas.nombres),
                nombre_completo=COALESCE(excluded.nombre_completo, personas.nombre_completo),
                sexo=COALESCE(excluded.sexo, personas.sexo),
                clase=COALESCE(excluded.clase, personas.clase),
                fecha_nac=COALESCE(excluded.fecha_nac, personas.fecha_nac)
            """,
            personas_batch,
        )
        personas_batch.clear()
    if elecciones_batch:
        conn.executemany(
            """
            INSERT INTO elecciones (anio, dni, seccion, circuito, mesa, orden, domicilio, tipodni, profesion, analf, ejemplar, fuente)
            VALUES (:anio, :dni, :seccion, :circuito, :mesa, :orden, :domicilio, :tipodni, :profesion, :analf, :ejemplar, :fuente)
            """,
            elecciones_batch,
        )
        elecciones_batch.clear()
    if secciones_batch:
        conn.executemany(
            """
            INSERT INTO secciones (anio, seccion, seccion_nombre, circuito, circuito_nombre)
            VALUES (:anio, :seccion, :seccion_nombre, :circuito, :circuito_nombre)
            ON CONFLICT(anio, seccion, circuito) DO UPDATE SET
                seccion_nombre=COALESCE(excluded.seccion_nombre, secciones.seccion_nombre),
                circuito_nombre=COALESCE(excluded.circuito_nombre, secciones.circuito_nombre)
            """,
            secciones_batch,
        )
        secciones_batch.clear()


def main():
    parser = argparse.ArgumentParser(description="Normaliza padrones a SQLite.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Directorio donde buscar archivos (*.*sv). Default: directorio del script.",
    )
    parser.add_argument(
        "--glob",
        default="*.*sv",
        help="Patrón glob para archivos de entrada. Default: *.*sv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Ruta de salida de la base SQLite. Default: <input-dir>/padron.sqlite",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100_000,
        help="Cantidad de filas a acumular antes de volcar a SQLite (por tabla).",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_db = args.output or (input_dir / "padron.sqlite")

    personas_batch: list[dict] = []
    elecciones_batch: list[dict] = []
    secciones_batch: list[dict] = []
    personas_count = elecciones_count = secciones_count = 0

    with sqlite3.connect(output_db) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=OFF;")
        create_tables(conn)
        for path in sorted(input_dir.glob(args.glob)):
            for ctx, row in yield_rows(path):
                persona, eleccion, seccion = map_row(ctx, row)
                if persona["dni"] is None:
                    continue
                personas_batch.append(persona)
                elecciones_batch.append(eleccion)
                personas_count += 1
                elecciones_count += 1
                if seccion:
                    secciones_batch.append(seccion)
                    secciones_count += 1
                if (
                    len(personas_batch) >= args.batch_size
                    or len(elecciones_batch) >= args.batch_size
                    or len(secciones_batch) >= args.batch_size
                ):
                    upsert_batches(conn, personas_batch, elecciones_batch, secciones_batch)
        # flush final
        upsert_batches(conn, personas_batch, elecciones_batch, secciones_batch)

    print(
        f"Filas procesadas: personas={personas_count}, elecciones={elecciones_count}, secciones={secciones_count}"
    )
    print(f"DB creada en {output_db}")


if __name__ == "__main__":
    main()
