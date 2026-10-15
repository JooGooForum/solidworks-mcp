# solidworks-mcp

English | [简体中文](README.zh-CN.md)

MCP server that drives a **running** SOLIDWORKS session over its COM API. It
attaches to the session you already have open; it does not launch SOLIDWORKS,
register an add-in or touch the network.

212 tools. Covered vs not covered: [COVERAGE.md](COVERAGE.md).

<!-- mcp-name: io.github.Slacker-LLC/solidworks-mcp -->

## Requirements

Windows, SOLIDWORKS installed and **already running**, Python 3.10+.

## Install

```powershell
git clone https://github.com/Slacker-LLC/solidworks-mcp.git
cd solidworks-mcp
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
```

The command is `solidworks-mcp`; the distribution is `solidworks-mcp-server`.

Claude:

```json
{
  "mcpServers": {
    "solidworks-mcp": {
      "command": "C:\\path\\to\\.venv\\Scripts\\solidworks-mcp.exe"
    }
  }
}
```

Codex CLI (`~/.codex/config.toml`):

```toml
[mcp_servers.solidworks-mcp]
command = 'C:\path\to\.venv\Scripts\solidworks-mcp.exe'
```

## Configuration

### Sheet-metal workflows

`list_sheet_metal_profiles` resolves the `standard_2026` profile and its **2026 plaat** template. Set `SW_MCP_SHEETMETAL_TEMPLATE` to the exact `.prtdot` path, or place the template under `SW_MCP_TEMPLATE_DIR`. Plate and panel creation requires explicit thickness, inside radius, and `dimension_mode` (`flat_blank` or `finished_outer`), creates an unsaved document, and never invokes PDM.

`create_sheet_metal_panel` accepts semantic `left`, `right`, `bottom`, and `top` edge-flange declarations. Optional hems, break corners, closed corners, and corner reliefs refer to those sides rather than transient topology indices; the workflow resolves native topology after each feature and stops on mismatched readback or rebuild errors.

Inspect existing parts before guarded edits. Edit tokens bind the current document, configuration, feature update stamps, persistent face/edge topology, feature state and bounds. Every guarded native apply schema exposes `edit_token`; it is required when the part already has a saved path. Sketch alignment reports model-space line directions, gaps, existing relations, and exact persistent references; apply must echo those references, adds a direct native collinear relation, and never substitutes converted geometry. Flat-pattern suppression, native unfold/fold features and feature-tree rollback are distinct operations. DXF export parses the resulting entity section and requires bend-layer entities when bend lines were requested for a part that contains bends.

For a complete description of the tools, contracts, dimensional modes, and safety boundaries, see [Sheet-metal workflow toolkit](docs/SHEET_METAL_WORKFLOWS.md).

| Variable | Default | Meaning |
| --- | --- | --- |
| `SW_MCP_OUTPUT_ROOT` | `~/Documents/solidworks-mcp` | Everything the server writes stays under here. |
| `SW_MCP_TEMPLATE_DIR` | auto-discovered | `.prtdot` / `.asmdot` / `.drwdot` template directory. |
| `SW_MCP_SHEETMETAL_TEMPLATE` | unset | Exact `.prtdot` path for the **2026 plaat** profile. |
| `SW_MCP_DEMO_TOOLS` | unset | `1` adds demo tools that degrade tool selection. |
| `SW_MCP_SESSION_PID` | unset | Attach to a specific existing instance. |

Lengths are `_mm`, angles `_deg`. Geometry is passed as a `selection` object
(`{"edges": [4, 6, 9]}`, `{"planes": ["front"]}`); indices describe the current
model, so re-list them after a geometry change.

### Exact document templates

`create_new_document` and `create_drawing` accept an optional absolute or
relative `template_path`. An explicit path must name an existing readable
template whose extension matches the requested document type; it is passed
unchanged after path resolution to `ISldWorks.NewDocument`. An explicit request
never falls back to another template.

```json
{"kind": "part", "template_path": "C:\\CAD\\Templates\\Machined Part.PRTDOT"}
```

```json
{"template_path": "C:\\CAD\\Templates\\A4 Landscape.DRWDOT", "first_angle": true}
```

When `template_path` is omitted, the connector retains its existing precedence:
the SOLIDWORKS configured default first, then discovery through
`SW_MCP_TEMPLATE_DIR` and the standard template locations. Results identify the
selection source as `explicit`, `solidworks_default`, or `discovered`, and verify
the resulting document type. SOLIDWORKS does not provide reliable originating
template-path readback for part and assembly documents, so the result reports
that limitation instead of claiming native source verification. Drawing results
also read back the active sheet size, scale, projection method, and sheet-format
path when SOLIDWORKS exposes it.

When drawing overrides such as projection, scale, or paper size are requested,
`create_drawing` preserves the sheet-format path inherited from the template and
verifies it after `SetupSheet5`. Template-provided auxiliary sheets are left
intact. `auto_dimension_view` activates and explicitly selects the requested
drawing view before calling `IDrawingDoc.AutoDimension`, then reports dimensions
added to that view rather than a document-wide count.

## Testing

```powershell
python -m unittest discover -s tests -p 'test_*.py'     # offline
python tests/live_p0_regression.py                      # live, SOLIDWORKS running
```

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md) · release process:
[RELEASING.md](RELEASING.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and the [Simplified Chinese note](LICENSE.zh-CN.md). Copyright 2026 JIALE LIU.

