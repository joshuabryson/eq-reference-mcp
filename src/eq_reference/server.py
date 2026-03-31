"""eq-reference MCP server — engineering equations, tables, solver, and interpolation."""

import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from eq_reference.data import ensure_databases
from eq_reference.db import EquationDB
from eq_reference.solver import Solver
from eq_reference.interpolator import Interpolator

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("eq-reference")

mcp = FastMCP("eq-reference")
db: EquationDB | None = None
solver = Solver()
interpolator = Interpolator()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search(
    query: str,
    subject: str | None = None,
    topic: str | None = None,
    dimension: str | None = None,
    limit: int = 10,
) -> str:
    """Search engineering equations by keyword, subject, topic, or variable dimension.

    Returns equation summaries (name, subject, topic, variables, solvability).
    Use get_equation(id) for full details including notes and cross-references.

    Args:
        query: Search term — matches equation names, variable names, and notes.
        subject: Filter by subject ID (e.g., "thermodynamics", "fluid-mechanics").
            Available subjects: dynamics, fluid-mechanics, gas-dynamics, heat-transfer,
            mechanical-engineering-design, mechanics-of-materials, physics,
            systemdynamics, thermodynamics, trigometric-identities.
        topic: Filter by topic ID (e.g., "thermodynamics/entropy").
            Use browse(subject=...) to discover topic IDs.
        dimension: Filter by variable dimension (e.g., "pressure", "temperature").
        limit: Maximum results to return (1-50, default 10).
    """
    results = db.search(query, subject=subject, topic=topic, dimension=dimension,
                        limit=min(limit, 50))
    return json.dumps(results, indent=2)


@mcp.tool()
def get_equation(id: str) -> str:
    """Get complete details for an engineering equation by its UUID.

    Returns: name, subject, topic, variables (with units and descriptions),
    derivation/application/assumptions notes, related equations with relationship
    types, and algebraic expression (if available for solving).

    The algebraic_expression field contains:
    - lhs/rhs: the equation sides using algebraic_symbol names
    - variable_symbols: ordered list of symbols — this is the positional order
      used by solve(values=[...])

    Omits display-only fields like LaTeX to save tokens.

    Args:
        id: The equation UUID (returned by search or browse).
    """
    eq = db.get_equation(id)
    if eq is None:
        return json.dumps({"error": f"Equation '{id}' not found."})

    # Reshape into clean response
    result = {
        "id": eq["id"],
        "name": eq["name"],
        "subject": eq["subject_title"],
        "topic": eq["topic_title"],
        "source_reference": eq["source_reference"],
        "is_solvable": bool(eq["is_solvable"]),
        "variables": eq["variables"],
        "notes": {
            "derivation": eq.get("notes_derivation"),
            "application": eq.get("notes_application"),
            "assumptions": eq.get("notes_assumptions"),
        },
        "cross_references": eq["cross_references"],
    }

    # Include algebraic expression if available
    alg = db.get_algebraic_expression(id)
    if alg:
        result["algebraic_expression"] = alg

    return json.dumps(result, indent=2)


@mcp.tool()
def browse(subject: str | None = None, topic: str | None = None) -> str:
    """Browse the engineering equations catalog.

    - No arguments: list all subjects with topic and equation counts.
    - subject only: list topics in that subject with equation counts.
    - subject + topic: list equations in that topic (summary format).

    Subject IDs: dynamics, fluid-mechanics, gas-dynamics, heat-transfer,
    mechanical-engineering-design, mechanics-of-materials, physics,
    systemdynamics, thermodynamics, trigometric-identities.

    Args:
        subject: Subject ID to browse into.
        topic: Topic ID (requires subject) to list equations.
    """
    if topic:
        return json.dumps(db.list_equations(topic), indent=2)
    elif subject:
        return json.dumps(db.list_topics(subject), indent=2)
    else:
        return json.dumps(db.list_subjects(), indent=2)


@mcp.tool()
def lookup_table(
    id: str | None = None,
    subject: str | None = None,
    search: str | None = None,
) -> str:
    """Search or retrieve engineering reference tables (material properties,
    flow functions, thermodynamic state tables, etc.).

    - id: get full table detail (metadata, columns, materials with data).
    - subject: list tables for a subject.
    - search: full-text search across table titles and material names.

    The response includes a "columns" array where each column has:
    - "property": the column name used as lookup_column in interpolate()
    - "units": the unit string (NOT part of the column name)

    Args:
        id: Table UUID for full detail.
        subject: Subject ID to list tables.
        search: Search query for table titles and material names.
    """
    if id:
        table = db.get_table(id)
        if table is None:
            return json.dumps({"error": f"Table '{id}' not found."})
        return json.dumps(table, indent=2, default=_json_default)
    elif search:
        return json.dumps(db.search_tables(search), indent=2)
    elif subject:
        return json.dumps(db.list_tables(subject), indent=2)
    else:
        return json.dumps(db.list_tables(), indent=2)


@mcp.tool()
def get_material(table_id: str, material_name: str | None = None) -> str:
    """Get material property data from a reference table.

    Returns column headers with units and numeric values.
    Omit material_name to list all materials in the table.

    Args:
        table_id: UUID of the reference table.
        material_name: Name of a specific material (optional).
    """
    materials = db.get_material(table_id, material_name)
    if not materials:
        if material_name:
            # Show available materials
            all_mats = db.get_material(table_id)
            names = [m["name"] for m in all_mats]
            return json.dumps({
                "error": f"Material '{material_name}' not found.",
                "available_materials": names,
            }, indent=2)
        return json.dumps({"error": f"No materials found for table '{table_id}'."})

    # Include column headers for context
    table = db.get_table(table_id)
    result = {
        "table_title": table["title"] if table else table_id,
        "columns": table["columns"] if table else [],
        "materials": materials,
    }
    return json.dumps(result, indent=2, default=_json_default)


@mcp.tool()
def interpolate(
    table_id: str,
    material_name: str,
    lookup_column: str,
    lookup_value: str | float,
    return_columns: list[str] | None = None,
) -> str:
    """Interpolate property values from a reference table at a specific condition.

    Performs linear interpolation between the two nearest data rows.
    Useful for looking up thermodynamic properties at non-tabulated states.

    IMPORTANT: Column names use only the "property" field from the table's
    columns array — do NOT include units. For example, use "T" not "T, R".
    Use lookup_table(id=...) to see available column names.

    Material name matching is case-insensitive and supports partial matches.

    Example: Ideal-gas properties of nitrogen at 4312 R:
        interpolate(table_id="...", material_name="Nitrogen",
                    lookup_column="T", lookup_value=4312)

    Args:
        table_id: UUID of the reference table (from lookup_table or search).
        material_name: Name of the material/substance in the table.
            Case-insensitive, supports partial matching.
        lookup_column: Column name to interpolate on — use the "property" field
            from the table's columns array (e.g., "T", "P", "\\overline{h}").
            Do NOT include units in the column name.
        lookup_value: Numeric value to interpolate at (in the column's native units).
        return_columns: Specific property columns to return (default: all).
    """
    table = db.get_table(table_id)
    if table is None:
        return json.dumps({"error": f"Table '{table_id}' not found."})

    # Find the material
    target_mat = None
    for mat in table["materials"]:
        if mat["name"].lower() == material_name.lower():
            target_mat = mat
            break

    if target_mat is None:
        # Partial match
        for mat in table["materials"]:
            if material_name.lower() in mat["name"].lower():
                target_mat = mat
                break

    if target_mat is None:
        names = [m["name"] for m in table["materials"]]
        return json.dumps({
            "error": f"Material '{material_name}' not found.",
            "available_materials": names,
        }, indent=2)

    try:
        result = interpolator.interpolate(
            columns=table["columns"],
            material_data=target_mat["data"],
            lookup_column=lookup_column,
            lookup_value=lookup_value,
            return_columns=return_columns,
        )
        result.material = target_mat["name"]
        return json.dumps(result.to_dict(), indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def solve(
    expression: str | None = None,
    equation_id: str | None = None,
    solve_for: str = "",
    known_values: dict | None = None,
    values: list | None = None,
) -> str:
    """Solve an equation for a missing variable given known values.

    Provide either an expression string OR an equation_id from the catalog.
    Values can include units (e.g., "100 kPa", "200 N", "0.5 m^2").
    Values without units are assumed to be in SI.

    Two input modes:

    1. Named variables (original): provide solve_for and known_values dict.
    2. Positional values: provide equation_id and a values list whose positions
       map to the equation's variable order. Mark exactly one slot as the
       unknown using any of: null, "?", "", or " ". The unknown slot becomes
       solve_for automatically.
       Example: values=[1, 21, "?", 4.6, 85, 23]

    The variable order for positional mode comes from the algebraic_expression's
    variable_symbols list in get_equation(). If the wrong number of values is
    provided, the error response includes the expected variable order with names.

    Args:
        expression: Math expression (e.g., "P/A", "m*a", "0.5*rho*v**2").
        equation_id: UUID of a cataloged equation (alternative to expression).
        solve_for: Variable name (algebraic_symbol) to solve for.
            Not needed when using positional values mode.
        known_values: Dict of algebraic_symbol → value (number or string with units).
            Keys must match the algebraic_symbol from get_equation() variables.
        values: Positional value list matching the equation's variable order.
            Use null, "?", "", or " " for the unknown variable to solve for.
            The order matches algebraic_expression.variable_symbols from get_equation().
    """
    # --- Positional values mode ---
    if values is not None:
        if not equation_id:
            return json.dumps({
                "error": "equation_id is required when using positional values."
            })

        alg = db.get_algebraic_expression(equation_id)
        if alg is None:
            eq = db.get_equation(equation_id)
            if eq is None:
                return json.dumps({"error": f"Equation '{equation_id}' not found."})
            return json.dumps({
                "error": f"Equation '{eq['name']}' has not been parsed for solving yet."
            })

        var_symbols = alg.get("variable_symbols", [])
        if len(values) != len(var_symbols):
            var_info = db.get_variables(equation_id)
            var_names = {v["algebraic_symbol"]: v["long_name"] for v in var_info}
            legend = [f"  {i}: {sym} ({var_names.get(sym, sym)})"
                      for i, sym in enumerate(var_symbols)]
            return json.dumps({
                "error": f"Expected {len(var_symbols)} values, got {len(values)}.",
                "variable_order": legend,
            }, indent=2)

        # Identify the unknown slot(s)
        _BLANK = {None, "?", "", " ", "null"}
        unknown_indices = [
            i for i, v in enumerate(values)
            if v is None or (isinstance(v, str) and v.strip() in _BLANK)
        ]

        if len(unknown_indices) != 1:
            return json.dumps({
                "error": f"Exactly one unknown is required, found {len(unknown_indices)}. "
                         "Mark the unknown with null, \"?\", \"\", or \" \"."
            })

        solve_for = var_symbols[unknown_indices[0]]
        known_values = {}
        for i, v in enumerate(values):
            if i == unknown_indices[0]:
                continue
            known_values[var_symbols[i]] = v

        lhs = alg["lhs"]
        expr = alg["rhs"]

        try:
            result = solver.solve(expr, solve_for, known_values, lhs=lhs)
            return json.dumps(result.to_dict(), indent=2)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    # --- Named variables mode (original) ---
    if not solve_for:
        return json.dumps({"error": "solve_for parameter is required."})
    if known_values is None:
        known_values = {}

    lhs = None
    expr = expression

    # Handle "expression = rhs" format (e.g., "F = m*a")
    if expr and "=" in expr:
        parts = expr.split("=", 1)
        lhs = parts[0].strip()
        expr = parts[1].strip()

    # If solve_for variable isn't in the expression, treat it as the lhs
    # e.g., solve(expression="m*a", solve_for="F") → F = m*a
    if expr and lhs is None and solve_for:
        import re
        # Check if solve_for appears as a variable in the expression
        if not re.search(r'\b' + re.escape(solve_for) + r'\b', expr):
            lhs = solve_for

    # If equation_id provided, look up the algebraic expression
    if equation_id and not expression:
        alg = db.get_algebraic_expression(equation_id)
        if alg is None:
            eq = db.get_equation(equation_id)
            if eq is None:
                return json.dumps({"error": f"Equation '{equation_id}' not found."})
            return json.dumps({
                "error": f"Equation '{eq['name']}' has not been parsed for solving yet."
            })
        lhs = alg["lhs"]
        expr = alg["rhs"]

    if not expr:
        return json.dumps({
            "error": "Provide either 'expression' or 'equation_id'."
        })

    try:
        result = solver.solve(expr, solve_for, known_values, lhs=lhs)
        return json.dumps(result.to_dict(), indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("eq-reference://catalog")
def catalog() -> str:
    """Engineering equations catalog: subjects, topic counts, equation counts,
    available variable dimensions, table counts, and material counts."""
    return json.dumps(db.catalog(), indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_default(obj):
    """Handle non-serializable types in JSON output."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
    return str(obj)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    global db
    eq_path, tb_path = ensure_databases()
    db = EquationDB(str(eq_path), str(tb_path))
    logger.info("eq-reference MCP server started")
    logger.info(f"  Equations: {eq_path}")
    logger.info(f"  Tables: {tb_path}")
    mcp.run()


if __name__ == "__main__":
    main()
