"""Equation solver using SymPy (symbolic) with SciPy fallback (numeric)."""

import sympy
from scipy.optimize import fsolve
from eq_reference.units import parse_value_with_unit


class SolveResult:
    """Result from solving an equation."""
    def __init__(self, solve_for: str, value: float, unit: str | None = None,
                 equation_used: str | None = None, all_variables: dict | None = None):
        self.solve_for = solve_for
        self.value = value
        self.unit = unit
        self.equation_used = equation_used
        self.all_variables = all_variables or {}

    def to_dict(self) -> dict:
        return {
            "solve_for": self.solve_for,
            "value": self.value,
            "unit": self.unit,
            "equation_used": self.equation_used,
            "all_variables": self.all_variables,
        }


class Solver:
    """Solves equations symbolically (SymPy) with numeric fallback (SciPy)."""

    def solve(self, expression: str, solve_for: str, known_values: dict,
              lhs: str | None = None) -> SolveResult:
        """
        Solve an equation for a target variable.

        Args:
            expression: Right-hand side expression string (e.g., "P / A")
            solve_for: Variable name to solve for
            known_values: Dict of variable_name -> value (number or "100 kPa" string)
            lhs: Left-hand side variable (if equation is lhs = expression).
                 If None, the equation is expression = 0.

        Returns:
            SolveResult with the solution.

        Raises:
            ValueError: If equation cannot be solved or inputs are invalid.
        """
        # Parse known values, converting units to SI
        parsed_knowns = {}
        all_vars = {}
        for var_name, val in known_values.items():
            si_val, si_unit = parse_value_with_unit(val)
            parsed_knowns[var_name] = si_val
            all_vars[var_name] = {"value": si_val, "unit": si_unit}

        # Build sympy equation
        # Create symbols for all variables
        all_symbol_names = set(parsed_knowns.keys()) | {solve_for}
        if lhs and lhs not in all_symbol_names:
            all_symbol_names.add(lhs)

        symbols = {name: sympy.Symbol(name) for name in all_symbol_names}

        # Convert Calculator/SwiftLatexParser format to SymPy format
        expression = self._to_sympy_format(expression)

        try:
            rhs_expr = sympy.sympify(expression, locals=symbols)
        except Exception as e:
            raise ValueError(f"Cannot parse expression '{expression}': {e}")

        # Build equation: lhs = rhs
        if lhs:
            lhs_converted = self._to_sympy_format(lhs)
            lhs_expr = symbols.get(lhs, sympy.sympify(lhs_converted, locals=symbols))
            equation = sympy.Eq(lhs_expr, rhs_expr)
        else:
            equation = sympy.Eq(rhs_expr, 0)

        target_sym = symbols[solve_for]

        # Try symbolic solve
        result = self._symbolic_solve(equation, target_sym, symbols, parsed_knowns)

        if result is None:
            # Fallback to numeric
            result = self._numeric_solve(equation, target_sym, symbols, parsed_knowns)

        if result is None:
            raise ValueError(
                f"Could not solve for '{solve_for}'. Check that enough variables "
                f"are provided and the equation is valid."
            )

        all_vars[solve_for] = {"value": result, "unit": None}

        eq_str = f"{lhs} = {expression}" if lhs else expression
        return SolveResult(
            solve_for=solve_for,
            value=result,
            unit=None,
            equation_used=eq_str,
            all_variables=all_vars,
        )

    def _symbolic_solve(self, equation, target, symbols, knowns) -> float | None:
        """Try exact symbolic solve."""
        try:
            # Substitute known values
            substituted = equation
            for name, val in knowns.items():
                if name in symbols:
                    substituted = substituted.subs(symbols[name], val)

            solutions = sympy.solve(substituted, target)

            if not solutions:
                return None

            # Take the first real solution
            for sol in solutions:
                val = complex(sol)
                if val.imag == 0:
                    return float(val.real)

            # If all complex, return the first real part
            return float(complex(solutions[0]).real)
        except Exception:
            return None

    @staticmethod
    def _to_sympy_format(expr: str) -> str:
        """Convert Calculator/SwiftLatexParser algebraic format to SymPy format.

        Key differences:
        - ^ → ** (exponentiation)
        - sqrt(x) is fine (SymPy supports it)
        - sin/cos/tan etc. are fine
        """
        import re
        # Replace ^ with ** for exponentiation
        # But be careful not to replace inside variable names
        result = re.sub(r'\^', '**', expr)
        return result

    def _numeric_solve(self, equation, target, symbols, knowns,
                       initial_guess: float = 1.0, max_iter: int = 200) -> float | None:
        """Fallback numeric solve using scipy fsolve."""
        try:
            # Convert equation to a function of the target variable
            # Substitute all knowns
            expr = equation.lhs - equation.rhs
            for name, val in knowns.items():
                if name in symbols:
                    expr = expr.subs(symbols[name], val)

            func = sympy.lambdify(target, expr, modules=["numpy"])

            solution, info, ier, msg = fsolve(
                func, initial_guess, full_output=True, maxfev=max_iter
            )

            if ier == 1:  # converged
                return float(solution[0])
            return None
        except Exception:
            return None
