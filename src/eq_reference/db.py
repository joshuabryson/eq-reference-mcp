"""SQLite query layer for equations and tables databases."""

import json
import math
import sqlite3
from pathlib import Path


def _fts_quote(query: str) -> str:
    """Quote an FTS5 query so special characters (hyphens, colons) are treated as literals."""
    # Wrap each token in double quotes to escape FTS operators
    tokens = query.split()
    return " ".join(f'"{t}"' for t in tokens)


def _parse_float_json(raw: str) -> list:
    """Parse JSON that may contain "Infinity", "-Infinity", "NaN" string values.

    The Swift encoder writes non-conforming floats as those literal strings.
    We replace them with Python float equivalents before decoding.
    """
    if raw is None:
        return []
    patched = raw.replace('"Infinity"', "1e308").replace('"-Infinity"', "-1e308").replace('"NaN"', "null")
    data = json.loads(patched)
    # Recursively walk and convert any remaining oddities
    def _walk(obj):
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        if obj is None:
            return float("nan")
        return obj
    return _walk(data)


class EquationDB:
    """Read-only query interface over the equations and tables SQLite databases."""

    def __init__(self, equations_path: str, tables_path: str):
        self._eq = sqlite3.connect(equations_path, check_same_thread=False)
        self._eq.row_factory = sqlite3.Row

        self._tb = sqlite3.connect(tables_path, check_same_thread=False)
        self._tb.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # Equations
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        subject: str | None = None,
        topic: str | None = None,
        dimension: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search over equations. Returns summary dicts."""
        sql = """
            SELECT e.id, e.name, e.source_reference, e.is_solvable, e.sort_order,
                   t.id AS topic_id, t.title AS topic_title,
                   s.id AS subject_id, s.title AS subject_title,
                   fts.variable_names
            FROM equations_fts fts
            JOIN equations e ON e.id = fts.equation_id
            JOIN topics t ON t.id = e.topic_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE equations_fts MATCH ?
        """
        params: list = [_fts_quote(query)]

        if subject:
            sql += " AND s.id = ?"
            params.append(subject)
        if topic:
            sql += " AND t.id = ?"
            params.append(topic)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = self._eq.execute(sql, params).fetchall()
        results = [self._equation_summary(r) for r in rows]

        # Optional post-filter by dimension (requires variable join)
        if dimension:
            ids = [r["id"] for r in results]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                dim_sql = f"""
                    SELECT DISTINCT equation_id FROM variables
                    WHERE equation_id IN ({placeholders}) AND dimension_category = ?
                """
                matching = {
                    r["equation_id"]
                    for r in self._eq.execute(dim_sql, ids + [dimension]).fetchall()
                }
                results = [r for r in results if r["id"] in matching]

        return results

    def get_equation(self, equation_id: str) -> dict | None:
        """Full equation detail: fields, variables, cross-refs, algebraic expression."""
        row = self._eq.execute(
            """
            SELECT e.*, t.title AS topic_title, s.id AS subject_id, s.title AS subject_title
            FROM equations e
            JOIN topics t ON t.id = e.topic_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE e.id = ?
            """,
            (equation_id,),
        ).fetchone()

        if row is None:
            return None

        d = dict(row)
        d["variables"] = self.get_variables(equation_id)
        d["cross_references"] = self.get_cross_references(equation_id)

        # Parse algebraic variables JSON
        if d.get("alg_variables"):
            try:
                d["alg_variables"] = json.loads(d["alg_variables"])
            except (json.JSONDecodeError, TypeError):
                pass

        return d

    def list_subjects(self) -> list[dict]:
        """All subjects with topic_count and equation_count."""
        rows = self._eq.execute(
            """
            SELECT s.id, s.title, s.sort_order,
                   COUNT(DISTINCT t.id) AS topic_count,
                   COUNT(e.id) AS equation_count
            FROM subjects s
            LEFT JOIN topics t ON t.subject_id = s.id
            LEFT JOIN equations e ON e.topic_id = t.id
            GROUP BY s.id
            ORDER BY s.sort_order
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def list_topics(self, subject_id: str) -> list[dict]:
        """Topics in a subject with equation_count, ordered by sort_order."""
        rows = self._eq.execute(
            """
            SELECT t.id, t.title, t.sort_order,
                   COUNT(e.id) AS equation_count
            FROM topics t
            LEFT JOIN equations e ON e.topic_id = t.id
            WHERE t.subject_id = ?
            GROUP BY t.id
            ORDER BY t.sort_order
            """,
            (subject_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_equations(self, topic_id: str) -> list[dict]:
        """Equations in a topic (summary format), ordered by sort_order."""
        rows = self._eq.execute(
            """
            SELECT e.id, e.name, e.source_reference, e.is_solvable, e.sort_order,
                   t.id AS topic_id, t.title AS topic_title,
                   s.id AS subject_id, s.title AS subject_title,
                   COALESCE(
                       (SELECT GROUP_CONCAT(v.long_name, ', ')
                        FROM variables v WHERE v.equation_id = e.id), ''
                   ) AS variable_names
            FROM equations e
            JOIN topics t ON t.id = e.topic_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE e.topic_id = ?
            ORDER BY e.sort_order
            """,
            (topic_id,),
        ).fetchall()
        return [self._equation_summary(r) for r in rows]

    def get_variables(self, equation_id: str) -> list[dict]:
        """All variables for an equation."""
        rows = self._eq.execute(
            """
            SELECT algebraic_symbol, latex_symbol, long_name, description,
                   dimension_category, default_unit_id
            FROM variables
            WHERE equation_id = ?
            """,
            (equation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_cross_references(self, equation_id: str) -> list[dict]:
        """Cross-refs with target equation names resolved."""
        rows = self._eq.execute(
            """
            SELECT cr.target_equation_id, cr.relationship, cr.note,
                   e.name AS target_name
            FROM cross_references cr
            LEFT JOIN equations e ON e.id = cr.target_equation_id
            WHERE cr.source_equation_id = ?
            """,
            (equation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_algebraic_expression(self, equation_id: str) -> dict | None:
        """Return {lhs, rhs, variable_symbols} or None if not solvable."""
        row = self._eq.execute(
            "SELECT alg_lhs, alg_rhs, alg_variables, is_solvable FROM equations WHERE id = ?",
            (equation_id,),
        ).fetchone()

        if row is None or not row["is_solvable"]:
            return None

        variables = []
        if row["alg_variables"]:
            try:
                variables = json.loads(row["alg_variables"])
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "lhs": row["alg_lhs"],
            "rhs": row["alg_rhs"],
            "variable_symbols": variables,
        }

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def search_tables(self, query: str, limit: int = 10) -> list[dict]:
        """FTS search on tables. Returns table summaries."""
        rows = self._tb.execute(
            """
            SELECT DISTINCT t.id, t.title, t.table_number, t.kind,
                   t.subject_id, t.authors, t.edition, t.sort_order
            FROM tables_fts fts
            JOIN materials m ON m.table_id = fts.table_id
            JOIN tables t ON t.id = fts.table_id
            WHERE tables_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (_fts_quote(query), limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_tables(self, subject_id: str | None = None) -> list[dict]:
        """List tables, optionally filtered by subject."""
        if subject_id:
            rows = self._tb.execute(
                """
                SELECT id, title, table_number, kind, subject_id, authors, edition, sort_order
                FROM tables WHERE subject_id = ? ORDER BY sort_order
                """,
                (subject_id,),
            ).fetchall()
        else:
            rows = self._tb.execute(
                "SELECT id, title, table_number, kind, subject_id, authors, edition, sort_order FROM tables ORDER BY sort_order"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_table(self, table_id: str) -> dict | None:
        """Full table detail including columns and materials with data."""
        row = self._tb.execute("SELECT * FROM tables WHERE id = ?", (table_id,)).fetchone()
        if row is None:
            return None

        d = dict(row)

        # Parse columns JSON
        if d.get("columns_json"):
            try:
                d["columns"] = json.loads(d["columns_json"])
            except (json.JSONDecodeError, TypeError):
                d["columns"] = []
        else:
            d["columns"] = []

        # Fetch materials
        mat_rows = self._tb.execute(
            "SELECT * FROM materials WHERE table_id = ? ORDER BY sort_order",
            (table_id,),
        ).fetchall()

        materials = []
        for mr in mat_rows:
            md = dict(mr)
            if md.get("data_json"):
                md["data"] = _parse_float_json(md["data_json"])
            else:
                md["data"] = []
            materials.append(md)

        d["materials"] = materials
        return d

    def get_material(self, table_id: str, material_name: str | None = None) -> list[dict]:
        """Materials from a table. If material_name given, filter to that one."""
        if material_name:
            rows = self._tb.execute(
                "SELECT * FROM materials WHERE table_id = ? AND name = ? ORDER BY sort_order",
                (table_id, material_name),
            ).fetchall()
        else:
            rows = self._tb.execute(
                "SELECT * FROM materials WHERE table_id = ? ORDER BY sort_order",
                (table_id,),
            ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("data_json"):
                d["data"] = _parse_float_json(d["data_json"])
            else:
                d["data"] = []
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def catalog(self) -> dict:
        """Return catalog: subjects with counts, dimensions, totals."""
        subjects = self.list_subjects()

        total_equations = sum(s["equation_count"] for s in subjects)
        total_topics = sum(s["topic_count"] for s in subjects)

        # Distinct dimension categories
        dim_rows = self._eq.execute(
            "SELECT DISTINCT dimension_category FROM variables WHERE dimension_category IS NOT NULL ORDER BY dimension_category"
        ).fetchall()
        dimensions = [r["dimension_category"] for r in dim_rows]

        # Solvable count
        solvable_row = self._eq.execute(
            "SELECT COUNT(*) AS cnt FROM equations WHERE is_solvable = 1"
        ).fetchone()

        # Table counts
        table_count_row = self._tb.execute("SELECT COUNT(*) AS cnt FROM tables").fetchone()
        material_count_row = self._tb.execute("SELECT COUNT(*) AS cnt FROM materials").fetchone()

        return {
            "subjects": subjects,
            "dimensions": dimensions,
            "total_subjects": len(subjects),
            "total_topics": total_topics,
            "total_equations": total_equations,
            "solvable_equations": solvable_row["cnt"],
            "total_tables": table_count_row["cnt"],
            "total_materials": material_count_row["cnt"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _equation_summary(row: sqlite3.Row) -> dict:
        """Convert a row to a summary dict (no latex)."""
        return {
            "id": row["id"],
            "name": row["name"],
            "subject_id": row["subject_id"],
            "subject_title": row["subject_title"],
            "topic_id": row["topic_id"],
            "topic_title": row["topic_title"],
            "variable_names": row["variable_names"],
            "source_reference": row["source_reference"],
            "is_solvable": bool(row["is_solvable"]),
        }
