import csv
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "padron_full.sqlite"
OUTPUT_DIR = Path(__file__).resolve().parent

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

YEAR_PAIRS = None  # If None, computed from data


def get_years(cur):
    cur.execute("SELECT DISTINCT anio FROM elecciones ORDER BY anio")
    return [row[0] for row in cur.fetchall()]


def normalize_seccion(sec: str) -> str:
    """Normalize seccion codes to drop leading zeros (match elecciones table)."""
    try:
        return str(int(sec))
    except Exception:
        return sec


def load_seccion_names(cur):
    """Return dict[seccion] -> seccion_nombre using names available (2025 padron)."""
    cur.execute(
        """
        SELECT seccion, MIN(seccion_nombre) AS nombre
        FROM secciones
        GROUP BY seccion
        """
    )
    return {normalize_seccion(sec): nombre for sec, nombre in cur.fetchall()}


def write_sizes(cur):
    out_path = OUTPUT_DIR / "seccion_sizes.csv"
    cur.execute(
        """
        SELECT e.anio, e.seccion, COUNT(*) AS total
        FROM elecciones e
        GROUP BY e.anio, e.seccion
        ORDER BY e.anio, total DESC
        """
    )
    rows_raw = cur.fetchall()
    names = load_seccion_names(cur)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "seccion", "seccion_nombre", "total"])
        for year, seccion, total in rows_raw:
            norm = normalize_seccion(seccion)
            writer.writerow([year, seccion, names.get(norm, ""), total])
    print(f"Wrote {len(rows_raw)} seccion size rows to {out_path}")


def write_links(cur, pairs):
    out_path = OUTPUT_DIR / "migration_links.csv"
    names = load_seccion_names(cur)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "from_year",
                "to_year",
                "from_seccion",
                "from_seccion_nombre",
                "to_seccion",
                "to_seccion_nombre",
                "count",
            ]
        )
        total_rows = 0
        for y1, y2 in pairs:
            print(f"Processing {y1}->{y2}…", flush=True)
            cur.execute(
                """
                /*
                Esta consulta SQL tiene como objetivo principal identificar y cuantificar la "migración"
                de votantes entre diferentes secciones electorales a lo largo de dos años específicos.
                Es decir, busca cuántas personas votaron en una sección 'A' en el primer año (e1.anio)
                y luego votaron en una sección 'B' en el segundo año (e2.anio).

                Desglose de la consulta:

                1.  SELECT: Define las columnas que se retornarán:
                    -   `e1.seccion AS from_seccion`: La sección electoral donde votó la persona en el primer año.
                    -   `e2.seccion AS to_seccion`: La sección electoral donde votó la misma persona en el segundo año.
                    -   `COUNT(*) AS count`: El número total de personas que hicieron esa transición específica de 'from_seccion' a 'to_seccion'.

                2.  FROM y JOIN: Especifica las tablas y cómo se relacionan:
                    -   `FROM elecciones e1 INDEXED BY idx_elecciones_dni_anio`: Se selecciona la tabla `elecciones` y se le da el alias `e1`.
                        La cláusula `INDEXED BY` sugiere al optimizador de SQLite utilizar el índice `idx_elecciones_dni_anio` para esta tabla,
                        lo cual es crucial para un rendimiento eficiente en búsquedas por DNI y año. Esto corresponde al "año de origen".
                    -   `JOIN elecciones e2 INDEXED BY idx_elecciones_dni_anio`: Se une la misma tabla `elecciones` de nuevo, esta vez con el alias `e2`.
                        También se sugiere el mismo índice para `e2`. Esto corresponde al "año de destino".
                    -   `ON e1.dni = e2.dni AND e2.anio = ?`: Esta es la condición de unión.
                        -   `e1.dni = e2.dni`: Asegura que estamos comparando los registros de la *misma persona* (identificada por su DNI) en ambos años.
                        -   `e2.anio = ?`: Filtra los registros de `e2` para que correspondan únicamente al segundo año (el valor del primer `?` en los parámetros).

                3.  WHERE: Filtra los registros antes de la unión completa:
                    -   `e1.anio = ?`: Limita los registros de la tabla `e1` al primer año de interés (el valor del segundo `?` en los parámetros).
                        Esto establece el "año de origen" para la comparación.

                4.  GROUP BY: Agrupa los resultados para contar:
                    -   `GROUP BY e1.seccion, e2.seccion`: Agrupa todas las filas que tienen la misma combinación de sección de origen (`e1.seccion`)
                        y sección de destino (`e2.seccion`). `COUNT(*)` entonces opera sobre estos grupos.

                5.  ORDER BY: Organiza la salida:
                    -   `ORDER BY count DESC`: Ordena los resultados finales de forma descendente basándose en la columna `count`.
                        Esto significa que las combinaciones de secciones con la mayor cantidad de votantes migrando aparecerán primero.

                En resumen, la consulta busca pares de secciones (origen -> destino) y cuenta cuántos votantes específicos
                se movieron de la primera sección en el año `y1` a la segunda sección en el año `y2`.
                */
                SELECT
                    e1.seccion AS from_seccion,
                    e2.seccion AS to_seccion,
                    COUNT(*) AS count
                FROM elecciones e1 INDEXED BY idx_elecciones_dni_anio
                JOIN elecciones e2 INDEXED BY idx_elecciones_dni_anio
                    ON e1.dni = e2.dni AND e2.anio = ?
                WHERE e1.anio = ?
                GROUP BY e1.seccion, e2.seccion
                ORDER BY count DESC
                """,
                (y2, y1),
            )
            rows = []
            for from_seccion, to_seccion, count in cur.fetchall():
                rows.append(
                    (
                        y1,
                        y2,
                        from_seccion,
                        names.get(normalize_seccion(from_seccion), ""),
                        to_seccion,
                        names.get(normalize_seccion(to_seccion), ""),
                        count,
                    )
                )
            writer.writerows(rows)
            total_rows += len(rows)
            print(f"  {len(rows)} link rows written")
    print(f"Wrote {total_rows} link rows to {out_path}")


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    years = get_years(cur)
    if YEAR_PAIRS:
        pairs = YEAR_PAIRS
    else:
        pairs = list(zip(years, years[1:]))
    print(f"Years: {years}")
    write_sizes(cur)
    write_links(cur, pairs)


if __name__ == "__main__":
    main()
