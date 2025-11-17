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
