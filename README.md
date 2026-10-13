# solidworks-mcp

English | [简体中文](README.zh-CN.md)

MCP server that drives a **running** SOLIDWORKS session over its COM API — it
does not launch SOLIDWORKS, register an add-in or touch the network.

192 tools, covering SOLIDWORKS itself plus the modules it bundles; third-party
vendor add-ins are out of scope. Covered vs not covered:
[COVERAGE.md](COVERAGE.md).

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

```powershell
uv tool install --from git+https://github.com/Slacker-LLC/solidworks-mcp solidworks-mcp-server
```

The command is `solidworks-mcp`; the distribution is `solidworks-mcp-server`.
Host configuration — Claude:

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

To run from a checkout instead, point the host at the venv `python.exe` with
`args = ['C:\path\to\solidworks-mcp\server.py']`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SW_MCP_OUTPUT_ROOT` | `~/Documents/solidworks-mcp` | Everything the server writes stays under here. |
| `SW_MCP_TEMPLATE_DIR` | auto-discovered | Where to find `.prtdot` / `.asmdot` / `.drwdot` templates. |
| `SW_MCP_DEMO_TOOLS` | unset | `1` adds the basketball demo tools, which degrade tool selection. |
| `SW_MCP_SESSION_PID` | unset | Attach to a specific existing instance at start-up. |

Lengths are `_mm`, angles `_deg`. Geometry is passed as a declarative
`selection` object, for example:

```jsonc
{ "selection": { "edges": [4, 6, 9] } }
{ "selection": { "face_edges": [2] } }
{ "selection": { "planes": ["front"] } }
{ "selection": { "sketch_segments": [0, 1] } }
```

Indices are snapshots of the current model — re-list after any geometry change.

## Tools

- **Session and documents** — `solidworks_status`, `get_active_document_info`,
  `create_new_document`, `open_document`, `save_document`,
  `save_active_document`, `export_document`, `rebuild_document`,
  `set_appearance`, `set_material`, `list_open_documents`, `activate_document`,
  `close_document`, `list_solidworks_sessions`, `select_solidworks_session`
- **Reference geometry and curves** — `list_reference_planes`, `create_plane`,
  `create_axis`, `create_reference_points`, `list_reference_points`,
  `create_coordinate_system`, `list_coordinate_systems`,
  `create_curve_through_points`, `get_curve_points`, `set_curve_points`,
  `composite_curve`, `create_helix`
- **Sketching** — `create_sketch`, `create_3d_sketch`, `edit_sketch`,
  `close_sketch`, `list_sketches`, `list_sketch_segments`, `list_sketch_points`,
  `get_sketch_status`, `draw_line`, `draw_centerline`, `draw_circle`,
  `draw_rectangle`, `draw_arc`, `draw_3point_arc`, `draw_ellipse`,
  `draw_polygon`, `draw_slot`, `draw_point`, `draw_spline`, `sketch_fillet`,
  `sketch_chamfer`, `sketch_trim`, `sketch_offset`, `sketch_mirror`,
  `convert_entities`, `set_construction_geometry`, `add_relation`,
  `add_dimension`, `set_dimension`, `list_dimensions`, `add_3d_dimension`
- **Features** — `list_features`, `boss_extrude`, `cut_extrude`, `revolve`,
  `fillet`, `chamfer`, `shell`, `draft`, `rib`, `simple_hole`, `sweep`, `loft`,
  `linear_pattern`, `circular_pattern`, `mirror_feature`, `delete_feature`,
  `rename_feature`, `set_feature_suppression`
- **Inspection** — `capture_screenshot` (returns the view as an image),
  `list_faces`, `list_edges`, `list_vertices`, `list_bodies`,
  `get_mass_properties`, `get_bounding_box`, `measure`, `check_errors`,
  `set_view`
- **Direct editing** — `move_faces`, `delete_faces`, `replace_faces`
- **Multibody and surfaces** — `scale_bodies`, `move_copy_bodies`,
  `combine_bodies`, `delete_bodies`, `mid_surface`, `get_mid_surface_data`,
  `preview_surface_trim`, `trim_surface`, `get_surface_trim_data`,
  `boundary_surface`, `get_boundary_feature_data`, `wrap_sketch`,
  `get_wrap_data`, `set_wrap_parameters`, `dome`, `get_dome_data`,
  `set_dome_parameters`, `surface_sweep`, `delete_surface_holes`,
  `surface_extrude`, `planar_surface`, `surface_revolve`, `surface_loft`,
  `ruled_surface`, `extend_surface`, `untrim_surface`, `fill_surface`,
  `cut_with_surface`, `offset_surface`, `knit_surfaces`, `thicken_surface`,
  `list_surface_bodies`
- **Sheet metal and weldments** — `sheet_metal_base_flange`,
  `list_sheet_metal_features`, `get_sheet_metal_parameters`,
  `set_sheet_metal_parameters`, `set_flat_pattern`, `export_flat_pattern`,
  `create_weldment`, `list_weldment_profiles`,
  `get_weldment_profile_configurations`, `insert_structural_member`,
  `list_cut_list`, `update_cut_list`
- **Assemblies** — `list_components`, `insert_component`, `add_mate`,
  `list_mates`, `set_component_fixed`, `set_component_visibility`,
  `set_component_suppression`, `set_component_configuration`
- **Drawings** — `create_drawing`, `list_sheets`, `add_sheet`, `activate_sheet`,
  `insert_standard_views`, `insert_model_view`, `insert_projected_view`,
  `insert_section_view`, `insert_detail_view`, `list_drawing_views`,
  `activate_drawing_view`, `create_drawing_sketch`, `set_drawing_view`,
  `insert_model_annotations`, `auto_dimension_view`, `insert_center_marks`,
  `insert_centerlines`, `add_note`
- **Configurations, properties, equations, materials** — `list_configurations`,
  `create_configuration`, `activate_configuration`, `delete_configuration`,
  `list_custom_properties`, `get_custom_property`, `set_custom_property`,
  `delete_custom_property`, `list_equations`, `add_equation`, `set_equation`,
  `delete_equation`, `evaluate_equations`, `list_materials`
- **Motion** — `list_motion_studies`, `create_motion_study`,
  `activate_motion_study`, `duplicate_motion_study`, `delete_motion_study`,
  `set_motion_study_type`, `set_motion_study_timing`, `list_motion_features`,
  `add_motion_gravity`, `add_motion_motor`, `add_motion_force`,
  `add_motion_spring`, `add_motion_damper`, `add_motion_contact`,
  `solve_motion_study`, `get_motion_study_results`,
  `set_motion_study_animation`, `control_motion_study_playback`,
  `export_motion_study_frames`

## Example

```jsonc
create_new_document   { "kind": "part" }
create_sketch         { "plane": "front", "name": "Base" }
draw_rectangle        { "x1_mm": 10, "y1_mm": 10, "x2_mm": 70, "y2_mm": 50 }
add_dimension         { "selection": { "sketch_segments": [0] }, "kind": "horizontal",
                        "value_mm": 80, "place_x_mm": 40, "place_y_mm": -10 }
close_sketch          {}
boss_extrude          { "depth_mm": 20, "name": "BasePad" }
list_edges            { "curve_type": "line", "min_length_mm": 19 }
fillet                { "radius_mm": 5, "selection": { "edges": [0, 1, 2, 3] } }
shell                 { "thickness_mm": 2, "selection": { "faces": [4] } }
capture_screenshot    { "view": "isometric" }
get_mass_properties   {}
```

## Limitations

- One COM apartment: calls are serialised, and a modal dialog blocks the server.
- Topology indices are snapshots; re-list them after any geometry change.
- Motion needs the ADAMS add-in to solve, and motion elements exist only on
  assembly documents.
- `circular_pattern` cannot pattern a feature that built a separate body.
- Drawing view names are localised; use the names `list_drawing_views` returns.

## Testing

```powershell
python -m unittest discover -s tests -p 'test_*.py'     # 225 offline checks
python tests/live_p0_regression.py                      # live, per feature domain
python tools/verify_install.py --install <dir> --tool-count 192 --scratch
```

CI runs the offline suite on Windows across Python 3.10–3.13. Tool conventions
and the traps worth knowing are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout

| Module | Contents |
| --- | --- |
| `sw_core.py` | COM attachment, units, feature tree, topology, selection engine, registry |
| `sw_file.py` | Session, documents, save, export, appearance, material |
| `sw_refgeom.py` | Reference planes and axes |
| `sw_sketch.py` | Sketches, geometry, editing, relations, dimensions |
| `sw_feature.py` | Solid features |
| `sw_inspect.py` | Topology, measurement, mass properties, screenshots |
| `sw_assembly.py` | Components and mates |
| `sw_drawing.py` | Sheets, views, model items, dimensions, notes |
| `sw_manage.py` | Documents, configurations, properties, equations, materials |
| `sw_multibody.py` | Multibody, surfaces, helixes |
| `sw_boundary.py` / `sw_wrap.py` / `sw_dome.py` | Boundary surface, wrap, dome |
| `sw_sheetmetal.py` / `sw_weldment.py` | Sheet metal and weldments |
| `sw_motion.py` | Motion studies, payloads, solve, animation |
| `sw_geometry.py` | XYZ curves and composite curves |
| `tests/` | Offline unit tests and per-domain live regressions |
| `tools/` | Type-library probe, API inventory, coverage report, install acceptance |
| `server.py` | Registry assembly and stdio dispatch |

## License

Apache License 2.0 — see [LICENSE](LICENSE). Copyright 2026 JIALE LIU.
