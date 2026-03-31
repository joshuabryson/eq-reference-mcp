"""Unit parsing and conversion using Pint.

Note: Pint's default registry handles most engineering units (BTU, slug, ksi, psi,
lbf, etc.). If you encounter an unrecognized unit, you can extend the registry with
`ureg.define(...)` — see Pint docs for custom unit definitions.
"""

import re
import pint

ureg = pint.UnitRegistry()
Q_ = ureg.Quantity

# Map dimension categories to SI base units
DIMENSION_TO_SI = {
    "length": "m", "mass": "kg", "temperature": "K", "pressure": "Pa",
    "force": "N", "energy": "J", "power": "W", "velocity": "m/s",
    "area": "m^2", "volume": "m^3", "density": "kg/m^3",
    "dynamicViscosity": "Pa*s", "kinematicViscosity": "m^2/s",
    "thermalConductivity": "W/(m*K)", "specificHeat": "J/(kg*K)",
    "specificEnergy": "J/kg", "specificEntropy": "J/(kg*K)",
    "angle": "rad", "frequency": "Hz", "molarMass": "kg/mol",
    "speed": "m/s", "acceleration": "m/s^2",
    "momentOfInertia": "kg*m^2", "torque": "N*m",
    "electricCurrent": "A", "voltage": "V", "resistance": "ohm",
    "capacitance": "F", "inductance": "H",
}


def parse_value_with_unit(value) -> tuple[float, str | None]:
    """Parse a value that may include a unit string.

    Examples:
        parse_value_with_unit(200) → (200.0, None)
        parse_value_with_unit("100 kPa") → (100000.0, "Pa")
        parse_value_with_unit("72 degF") → (295.37, "K")
        parse_value_with_unit("0.5 m^2") → (0.5, "m^2")

    Returns (si_value, si_unit_string) — value converted to SI.
    """
    if isinstance(value, (int, float)):
        return float(value), None

    s = str(value).strip()

    # Try to parse as plain number first
    try:
        return float(s), None
    except ValueError:
        pass

    # Parse with Pint
    try:
        q = ureg.parse_expression(s)
        if hasattr(q, 'units'):
            si = q.to_base_units()
            return si.magnitude, str(si.units)
        return float(q), None
    except Exception:
        raise ValueError(f"Cannot parse value with unit: '{value}'")


def convert_to_si(value: float, unit_str: str) -> tuple[float, str]:
    """Convert a value with explicit unit string to SI base units.

    Returns (si_value, si_unit_string).
    """
    q = Q_(value, unit_str)
    si = q.to_base_units()
    return si.magnitude, str(si.units)


def get_si_unit(dimension_category: str) -> str | None:
    """Map a dimension category to its SI unit string."""
    return DIMENSION_TO_SI.get(dimension_category)


def format_result(value: float, dimension_category: str | None = None) -> dict:
    """Format a numeric result with its SI unit."""
    unit = DIMENSION_TO_SI.get(dimension_category, "") if dimension_category else ""
    return {"value": value, "unit": unit}
