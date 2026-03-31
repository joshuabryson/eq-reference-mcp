"""Database file management — locate bundled or cached .sqlite files."""

import os
import sys
import json
import urllib.request
from pathlib import Path
from importlib.resources import files

# Fallback download URL if databases aren't bundled
RELEASE_BASE_URL = "https://github.com/joshuabryson/eq-reference-mcp/releases/latest/download"

CACHE_DIR = Path.home() / ".cache" / "eq-reference"
VERSION_FILE = CACHE_DIR / "version.json"


def _bundled_databases() -> tuple[Path, Path] | None:
    """Return paths to bundled databases, or None if not found."""
    try:
        data_dir = files("eq_reference") / "data"
        eq = data_dir / "equations.sqlite"
        tb = data_dir / "tables.sqlite"
        # importlib.resources may return traversable objects; resolve to real paths
        eq_path = Path(str(eq))
        tb_path = Path(str(tb))
        if eq_path.exists() and tb_path.exists():
            return eq_path, tb_path
    except Exception:
        pass
    return None


def ensure_databases() -> tuple[Path, Path]:
    """Return paths to equations.sqlite and tables.sqlite.

    Resolution order:
    1. Environment variable overrides
    2. Bundled databases (shipped inside the package)
    3. Cached downloads in ~/.cache/eq-reference/
    4. Download from GitHub release
    """

    # 1. Environment variable overrides
    eq_env = os.environ.get("EQ_REFERENCE_EQUATIONS_DB")
    tb_env = os.environ.get("EQ_REFERENCE_TABLES_DB")
    if eq_env and tb_env:
        eq = Path(eq_env)
        tb = Path(tb_env)
        if eq.exists() and tb.exists():
            return eq, tb

    # 2. Bundled databases
    bundled = _bundled_databases()
    if bundled:
        return bundled

    # 3. Cached downloads
    eq_cached = CACHE_DIR / "equations.sqlite"
    tb_cached = CACHE_DIR / "tables.sqlite"
    if eq_cached.exists() and tb_cached.exists():
        return eq_cached, tb_cached

    # 4. Download
    print("Downloading engineering equations databases...", file=sys.stderr)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        _download(f"{RELEASE_BASE_URL}/equations.sqlite", eq_cached)
        _download(f"{RELEASE_BASE_URL}/tables.sqlite", tb_cached)

        VERSION_FILE.write_text(json.dumps({
            "version": "0.1.0",
            "source": RELEASE_BASE_URL,
        }))

        print("Download complete.", file=sys.stderr)
    except Exception as e:
        print(f"Failed to download databases: {e}", file=sys.stderr)
        print("Set EQ_REFERENCE_EQUATIONS_DB and EQ_REFERENCE_TABLES_DB environment variables to use local files.", file=sys.stderr)
        raise SystemExit(1)

    return eq_cached, tb_cached


def _download(url: str, dest: Path):
    """Download a file from URL to destination path."""
    print(f"  Downloading {url}...", file=sys.stderr)
    urllib.request.urlretrieve(url, dest)


def update_databases():
    """Force re-download of databases."""
    eq_cached = CACHE_DIR / "equations.sqlite"
    tb_cached = CACHE_DIR / "tables.sqlite"

    for f in [eq_cached, tb_cached, VERSION_FILE]:
        if f.exists():
            f.unlink()

    return ensure_databases()
