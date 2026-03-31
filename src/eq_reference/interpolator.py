"""Linear interpolation on reference table data."""

import math
import re
from eq_reference.units import parse_value_with_unit


class InterpolationResult:
    """Result from interpolating a table."""
    def __init__(self, material: str, lookup_column: str, lookup_value: float,
                 lookup_unit: str | None, properties: list[dict], note: str):
        self.material = material
        self.lookup_column = lookup_column
        self.lookup_value = lookup_value
        self.lookup_unit = lookup_unit
        self.properties = properties
        self.note = note

    def to_dict(self) -> dict:
        return {
            "material": self.material,
            "lookup": {
                "column": self.lookup_column,
                "value": self.lookup_value,
                "unit": self.lookup_unit,
            },
            "properties": self.properties,
            "interpolation_note": self.note,
        }


class Interpolator:
    """Linear interpolation on multi-row table data."""

    def interpolate(
        self,
        columns: list[dict],       # [{property, units, ...}]
        material_data: list[list],  # [[row0_col0, row0_col1, ...], ...]
        lookup_column: str,         # column property name to look up on
        lookup_value,               # value (number or "240.3 C" string)
        return_columns: list[str] | None = None,  # specific columns or all
    ) -> InterpolationResult:
        """
        Interpolate property values at a specific lookup value.

        Args:
            columns: Column definitions from the table
            material_data: 2D array of numeric data (rows x columns)
            lookup_column: Property name of the independent variable column
            lookup_value: Value to interpolate at (can include unit string)
            return_columns: Which columns to return (None = all except lookup)

        Returns:
            InterpolationResult with interpolated values.
        """
        # Find the lookup column index
        col_names = [c["property"] for c in columns]
        if lookup_column not in col_names:
            available = ", ".join(col_names)
            raise ValueError(
                f"Column '{lookup_column}' not found. Available columns: {available}"
            )
        lookup_idx = col_names.index(lookup_column)
        lookup_unit_str = columns[lookup_idx].get("units", "")

        # Parse the lookup value
        # If it's a plain number, use it directly; if it has units, extract the number
        # (table data is assumed to be in the table's own unit system)
        if isinstance(lookup_value, (int, float)):
            target = float(lookup_value)
        else:
            target = _extract_number(lookup_value)

        # Extract the lookup column values
        col_values = [row[lookup_idx] for row in material_data]

        # Validate range
        valid_values = [v for v in col_values if not (math.isnan(v) or math.isinf(v))]
        if not valid_values:
            raise ValueError("No valid data in the lookup column.")

        min_val, max_val = min(valid_values), max(valid_values)
        if target < min_val or target > max_val:
            raise ValueError(
                f"{lookup_column} = {target} is outside the table range "
                f"[{min_val}, {max_val}] {lookup_unit_str}"
            )

        # Find bracketing rows
        lower_idx, upper_idx = None, None
        for i, v in enumerate(col_values):
            if math.isnan(v) or math.isinf(v):
                continue
            if v <= target:
                if lower_idx is None or v > col_values[lower_idx]:
                    lower_idx = i
            if v >= target:
                if upper_idx is None or v < col_values[upper_idx]:
                    upper_idx = i

        if lower_idx is None or upper_idx is None:
            raise ValueError(
                f"Cannot find bracketing values for {lookup_column} = {target}"
            )

        # Determine which columns to return
        if return_columns:
            return_idxs = []
            for rc in return_columns:
                if rc in col_names:
                    return_idxs.append(col_names.index(rc))
                else:
                    raise ValueError(
                        f"Column '{rc}' not found. Available: {', '.join(col_names)}"
                    )
        else:
            return_idxs = [i for i in range(len(columns)) if i != lookup_idx]

        # Interpolate
        properties = []
        if lower_idx == upper_idx:
            # Exact match
            note = f"Exact match at {lookup_column} = {target} {lookup_unit_str}"
            for ci in return_idxs:
                properties.append({
                    "column": col_names[ci],
                    "value": material_data[lower_idx][ci],
                    "unit": columns[ci].get("units", ""),
                })
        else:
            # Linear interpolation
            x0 = col_values[lower_idx]
            x1 = col_values[upper_idx]
            frac = (target - x0) / (x1 - x0) if x1 != x0 else 0.0

            note = (f"Linear interpolation between {lookup_column} = {x0} "
                    f"and {x1} {lookup_unit_str}")

            for ci in return_idxs:
                y0 = material_data[lower_idx][ci]
                y1 = material_data[upper_idx][ci]
                if math.isnan(y0) or math.isnan(y1) or math.isinf(y0) or math.isinf(y1):
                    interp_val = float("nan")
                else:
                    interp_val = y0 + frac * (y1 - y0)
                properties.append({
                    "column": col_names[ci],
                    "value": round(interp_val, 6) if not math.isnan(interp_val) else None,
                    "unit": columns[ci].get("units", ""),
                })

        return InterpolationResult(
            material="",  # caller fills this in
            lookup_column=lookup_column,
            lookup_value=target,
            lookup_unit=lookup_unit_str,
            properties=properties,
            note=note,
        )


def _extract_number(value) -> float:
    """Extract the numeric part from a value like '240.3 C' or '15 MPa'."""
    s = str(value).strip()
    # Try parsing as plain float first
    try:
        return float(s)
    except ValueError:
        pass
    # Extract leading number
    match = re.match(r"([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)", s)
    if match:
        return float(match.group(1))
    raise ValueError(f"Cannot extract number from '{value}'")
