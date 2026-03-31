# eq-reference-mcp

MCP server for searching, browsing, solving, and interpolating engineering equations and reference tables.

Provides Claude (and other MCP clients) with access to 3,388 engineering equations across 10 subjects and 94 reference tables with 1,048 materials covering thermodynamics, fluid mechanics, heat transfer, dynamics, and more.

## Features

- **Search** equations by keyword, subject, topic, or variable dimension
- **Browse** the full catalog: subjects, topics, equations
- **Solve** equations for any variable with unit-aware input (e.g., "100 kPa")
- **Interpolate** reference table data at arbitrary conditions (e.g., saturated water properties at T=150.5°C)
- **Look up** material properties from reference tables

## Installation

```bash
pip install eq-reference-mcp
```

On first run, the server downloads the equation and table databases (~6MB) to `~/.cache/eq-reference/`.

## Configuration

### Claude Code

```bash
claude mcp add eq-reference -- eq-reference-mcp
```

### Claude Desktop

Add to your Claude Desktop config (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "eq-reference": {
      "command": "eq-reference-mcp"
    }
  }
}
```

### Local Development

Point at your own database files instead of downloading:

```bash
export EQ_REFERENCE_EQUATIONS_DB=/path/to/equations.sqlite
export EQ_REFERENCE_TABLES_DB=/path/to/tables.sqlite
```

## Tools

| Tool | Description |
|------|-------------|
| `search` | Full-text search across equations by name, variables, notes |
| `get_equation` | Get complete equation details (variables, notes, cross-references) |
| `browse` | Navigate the subject/topic/equation hierarchy |
| `lookup_table` | Search or retrieve reference tables |
| `get_material` | Get material property data from a table |
| `interpolate` | Linear interpolation on table data at specific conditions |
| `solve` | Solve equations for unknown variables with unit support |

## Examples

Ask Claude things like:

- "Find equations related to entropy"
- "What variables does Bernoulli's equation use?"
- "Solve F = ma for acceleration given F = 200 N and m = 50 kg"
- "What is the specific enthalpy of saturated water at 150°C?"
- "Show me thermal conductivity of copper"
- "Browse thermodynamics topics"

## Subjects Covered

- Dynamics
- Fluid Mechanics
- Gas Dynamics
- Heat Transfer
- Mechanical Engineering Design
- Mechanics of Materials
- Physics
- System Dynamics
- Thermodynamics
- Trigonometric Identities

## License

MIT
