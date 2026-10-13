# Coverage: covered vs not covered

English | [简体中文](COVERAGE.zh-CN.md)

Goal: native coverage of SOLIDWORKS itself and the modules it ships or bundles.
Third-party vendor add-ins (JLC/嘉立创 and similar) are out of scope.

*Covered* means a dedicated tool with explicit units and selection rules that
reads the real result back and has been verified against a live session.
Anything weaker is listed as not covered. 192 tools are registered today; that
is a count, not a coverage claim.

## Core SOLIDWORKS

| Domain | Covered | Not covered |
| --- | --- | --- |
| Session and documents | Attach/status, active-document info, new part/assembly/drawing, open, save, save-as, activate, close, running-instance list and PID selection, rebuild with failing-feature report | DXF/DWG and PDF export, template pick by name, external references / pack-and-go, version upgrade |
| Reference geometry and curves | Planes (offset / angle / midplane / three points / parallel through point), axes, reference points (circle centres, midpoints, face centres, distance / percentage / even spacing, intersections, sketch points, projection onto a model face), coordinate systems, curves through XYZ points (create, read, edit), composite curves, helix | Projection onto a reference plane (native call returns empty here), projected curves, split lines, intersection curves |
| Sketches (2D and 3D) | Create / edit / close / list on planes or model faces, native 3D sketches, lines, centrelines, circles, rectangles, arcs, three-point arcs, ellipses, polygons, slots, points, splines (XYZ in 3D), fillet, chamfer, trim, offset, mirror, convert entities, construction geometry, relations, driving dimensions (2D and 3D X/Y/Z), sketch and point queries | Sketch text, blocks, sketch pictures, sketch patterns, repair sketch, working-plane orientation in 3D sketches, assembly Z directional dimension on this machine |
| Solid features | Boss/cut extrude (incl. through-all-both), revolve, fillet, chamfer, shell, draft, rib, simple hole, sweep, loft, linear and circular pattern, mirror, delete / rename / suppress, ordered feature list | Boundary boss/base, threads, hole wizard and hole series, split, indent, intersect, deform, flex, freeform, thin features, multi-thickness shell, draft analysis |
| Multibody and direct editing | Scale (uniform or X/Y/Z, about centroid or origin), move / copy / rotate bodies, combine (add, subtract, intersect), delete / keep bodies, move face (offset, translate, rotate), delete face with patch, replace face | Save bodies, split bodies, mirror bodies, delete-face fill and tangent-fill modes (created but not confirmed), import-geometry repair |
| Surfaces | Extruded, planar, revolved, lofted, swept, boundary, ruled and filled surfaces, extend, untrim, trim (preview, apply, data), knit, thicken, offset, mid-surface (create and data), surface-hole deletion, cut with surface, surface-body area listing | Mutual-trim knit variant, fill curvature continuity (not confirmed here), ruled reverse-normal (not confirmed here), mid-surface placement (ignored here), surface flatten, mesh BREP |
| Sheet metal | Base flange, parameter read/edit (thickness, bend radius, K-factor), flatten / fold, flat-pattern DXF export | Edge flange, miter flange, hem, jog, closed corner, corner relief, convert to sheet metal, forming tools, bend tables |
| Weldments | Weldment feature, profile listing, size configurations, structural members, cut-list read and update | Trim / extend members, end caps, gussets, weld beads, bounding box, structural systems |
| Assemblies and mates | Component insert / list / fix / visibility / suppression / configuration, add and list mates | Replace, delete, pattern and mirror components, virtual components, in-place editing, subassemblies, mate limits, mechanical mates (gear, screw, rack and pinion, cam, hinge, coupler), interference and clearance checks, explode, display states, section views |
| Drawings | Sheets, standard / model / projected / section / detail views, view sketches, model annotations, auto-dimension, centre marks and lines, notes, view move / scale / label | Auxiliary, broken-out, alternate-position and crop views, view alignment, BOM / hole / revision tables, tolerances, GD&T, surface finish, weld symbols, hole callouts, balloons, blocks, sheet formats |
| Configurations, properties, equations, materials | Configuration create / activate / delete / list, document and configuration custom properties (read, write, delete, type and resolved value), equations and global variables (add, set, delete, evaluate), material-library search, material and appearance assignment | Derived configurations, design tables, per-configuration feature and dimension control, display states, custom property tabs and property files |
| Inspection and measurement | Face / edge / vertex / body listing with filters (surface type, area, normal, curve type, length), mass properties, bounding box, measure, error report, screenshots, named views | Interference and clearance, curvature and draft analysis, thickness analysis, section properties, geometry validity and repair |
| Moulds | — | Parting lines, parting surfaces, shut-off surfaces, mould split, core, cavity |
| Data interchange | STEP, IGES, STL, Parasolid, 3MF and image export; flat-pattern DXF export; native part / assembly / drawing open | DXF/DWG and PDF import or export, drawing export to PDF/DXF/DWG, reference management |

## Bundled modules

| Module | Covered | Not covered |
| --- | --- | --- |
| Motion (22 tools) | Study create / duplicate / delete / activate / list / type / timing; motion-feature listing; gravity, linear and rotational motors, linear force and torque, linear/torsional/motion springs, linear/torsional dampers, 3D contact; native solve; result sampling (centre of mass, linear and angular velocity/acceleration, Euler angles); animation timeline; playback control; frame export (BMP/PNG) | Charts and CSV results, frame-rate read/write, image size and scale, motion event callbacks, AVI/JPG encoding, PhotoWorks renderer, real dynamics (needs the ADAMS solver), non-constant force functions, torsional-motion spring coil geometry, cross-document activation after solve |
| Simulation | — | Not inventoried: the local `cosworks.dll` type library fails to load (`-2147312566`) |
| CAM | — | Type library not found at the expected path; module presence not established |
| Routing | — | Inventoried (14 interfaces, 142 members); no tools |
| Costing | — | Inventoried (14 interfaces, 296 members); no tools |
| DimXpert | — | Inventoried (51 interfaces, 253 members); no tools |
| Inspection | — | Inventoried (5 interfaces, 162 members); no tools |
| Sustainability | — | Inventoried (9 interfaces, 102 members); no tools |
| DFMXpress | — | Inventoried (2 interfaces, 12 members); no tools |
| ScanTo3D | — | Inventoried (1 interface, 3 members); no tools |

## How a claim is checked

```powershell
python -m unittest discover -s tests -p 'test_*.py'          # 225 offline checks
python tests/live_p0_regression.py                           # live, per domain
python tools/verify_install.py --install <dir> --tool-count 192 --scratch
python tools/build_api_inventory.py --official-modules --output <file>
```

Live scripts touch only newly created documents and close them. The type-library
inventory finds gaps; it is not a coverage ratio, and reading a library proves
neither a licence nor an implementation. Per-batch measurements stay in the PR
history.

`main` is protected: pull requests with the four `offline` CI jobs, no direct
pushes, owner-merged. See [CONTRIBUTING.md](CONTRIBUTING.md).
