# solidworks-mcp

[English](README.md) | 简体中文

通过 COM API 驱动**正在运行**的 SOLIDWORKS 会话的 MCP 服务器 —— 不启动
SOLIDWORKS、不注册插件、不访问网络。

192 个工具，覆盖 SolidWorks 本体与其随附模块；第三方厂商插件不在范围内。已覆盖与
未覆盖清单见 [COVERAGE.zh-CN.md](COVERAGE.zh-CN.md)。

## 环境要求

Windows、已安装且**正在运行**的 SOLIDWORKS、Python 3.10+。

## 安装

```powershell
git clone https://github.com/Slacker-LLC/solidworks-mcp.git
cd solidworks-mcp
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
```

```powershell
uv tool install --from git+https://github.com/Slacker-LLC/solidworks-mcp solidworks-mcp-server
```

命令是 `solidworks-mcp`，发行包是 `solidworks-mcp-server`。Claude 配置：

```json
{
  "mcpServers": {
    "solidworks-mcp": {
      "command": "C:\\path\\to\\.venv\\Scripts\\solidworks-mcp.exe"
    }
  }
}
```

Codex CLI（`~/.codex/config.toml`）：

```toml
[mcp_servers.solidworks-mcp]
command = 'C:\path\to\.venv\Scripts\solidworks-mcp.exe'
```

不安装、直接跑源码时，把宿主指向 venv 的 `python.exe`，并加
`args = ['C:\path\to\solidworks-mcp\server.py']`。

## 配置

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `SW_MCP_OUTPUT_ROOT` | `~/Documents/solidworks-mcp` | 服务器写出的所有文件都在此目录下。 |
| `SW_MCP_TEMPLATE_DIR` | 自动发现 | `.prtdot` / `.asmdot` / `.drwdot` 模板目录。 |
| `SW_MCP_DEMO_TOOLS` | 未设置 | 设为 `1` 会加入降低工具选择质量的篮球演示工具。 |
| `SW_MCP_SESSION_PID` | 未设置 | 启动时连接指定的已有实例。 |

长度以 `_mm` 结尾，角度以 `_deg` 结尾。几何通过声明式 `selection` 传入：

```jsonc
{ "selection": { "edges": [4, 6, 9] } }
{ "selection": { "face_edges": [2] } }
{ "selection": { "planes": ["front"] } }
{ "selection": { "sketch_segments": [0, 1] } }
```

索引是当前模型的快照，任何几何变化后都要重新列举。

## 工具

- **会话与文档** — `solidworks_status`, `get_active_document_info`,
  `create_new_document`, `open_document`, `save_document`,
  `save_active_document`, `export_document`, `rebuild_document`,
  `set_appearance`, `set_material`, `list_open_documents`, `activate_document`,
  `close_document`, `list_solidworks_sessions`, `select_solidworks_session`
- **参考几何与曲线** — `list_reference_planes`, `create_plane`,
  `create_axis`, `create_reference_points`, `list_reference_points`,
  `create_coordinate_system`, `list_coordinate_systems`,
  `create_curve_through_points`, `get_curve_points`, `set_curve_points`,
  `composite_curve`, `create_helix`
- **草图** — `create_sketch`, `create_3d_sketch`, `edit_sketch`,
  `close_sketch`, `list_sketches`, `list_sketch_segments`, `list_sketch_points`,
  `get_sketch_status`, `draw_line`, `draw_centerline`, `draw_circle`,
  `draw_rectangle`, `draw_arc`, `draw_3point_arc`, `draw_ellipse`,
  `draw_polygon`, `draw_slot`, `draw_point`, `draw_spline`, `sketch_fillet`,
  `sketch_chamfer`, `sketch_trim`, `sketch_offset`, `sketch_mirror`,
  `convert_entities`, `set_construction_geometry`, `add_relation`,
  `add_dimension`, `set_dimension`, `list_dimensions`, `add_3d_dimension`
- **特征** — `list_features`, `boss_extrude`, `cut_extrude`, `revolve`,
  `fillet`, `chamfer`, `shell`, `draft`, `rib`, `simple_hole`, `sweep`, `loft`,
  `linear_pattern`, `circular_pattern`, `mirror_feature`, `delete_feature`,
  `rename_feature`, `set_feature_suppression`
- **检查** — `capture_screenshot`（返回图像）、`list_faces`, `list_edges`,
  `list_vertices`, `list_bodies`, `get_mass_properties`, `get_bounding_box`,
  `measure`, `check_errors`, `set_view`
- **直接编辑** — `move_faces`, `delete_faces`, `replace_faces`
- **多实体与曲面** — `scale_bodies`, `move_copy_bodies`, `combine_bodies`,
  `delete_bodies`, `mid_surface`, `get_mid_surface_data`,
  `preview_surface_trim`, `trim_surface`, `get_surface_trim_data`,
  `boundary_surface`, `get_boundary_feature_data`, `wrap_sketch`,
  `get_wrap_data`, `set_wrap_parameters`, `dome`, `get_dome_data`,
  `set_dome_parameters`, `surface_sweep`, `delete_surface_holes`,
  `surface_extrude`, `planar_surface`, `surface_revolve`, `surface_loft`,
  `ruled_surface`, `extend_surface`, `untrim_surface`, `fill_surface`,
  `cut_with_surface`, `offset_surface`, `knit_surfaces`, `thicken_surface`,
  `list_surface_bodies`
- **钣金与焊件** — `sheet_metal_base_flange`, `list_sheet_metal_features`,
  `get_sheet_metal_parameters`, `set_sheet_metal_parameters`,
  `set_flat_pattern`, `export_flat_pattern`, `create_weldment`,
  `list_weldment_profiles`, `get_weldment_profile_configurations`,
  `insert_structural_member`, `list_cut_list`, `update_cut_list`
- **装配体** — `list_components`, `insert_component`, `add_mate`,
  `list_mates`, `set_component_fixed`, `set_component_visibility`,
  `set_component_suppression`, `set_component_configuration`
- **工程图** — `create_drawing`, `list_sheets`, `add_sheet`, `activate_sheet`,
  `insert_standard_views`, `insert_model_view`, `insert_projected_view`,
  `insert_section_view`, `insert_detail_view`, `list_drawing_views`,
  `activate_drawing_view`, `create_drawing_sketch`, `set_drawing_view`,
  `insert_model_annotations`, `auto_dimension_view`, `insert_center_marks`,
  `insert_centerlines`, `add_note`
- **配置、属性、方程、材料** — `list_configurations`, `create_configuration`,
  `activate_configuration`, `delete_configuration`, `list_custom_properties`,
  `get_custom_property`, `set_custom_property`, `delete_custom_property`,
  `list_equations`, `add_equation`, `set_equation`, `delete_equation`,
  `evaluate_equations`, `list_materials`
- **Motion** — `list_motion_studies`, `create_motion_study`,
  `activate_motion_study`, `duplicate_motion_study`, `delete_motion_study`,
  `set_motion_study_type`, `set_motion_study_timing`, `list_motion_features`,
  `add_motion_gravity`, `add_motion_motor`, `add_motion_force`,
  `add_motion_spring`, `add_motion_damper`, `add_motion_contact`,
  `solve_motion_study`, `get_motion_study_results`,
  `set_motion_study_animation`, `control_motion_study_playback`,
  `export_motion_study_frames`

## 示例

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

## 已知限制

- 单 COM 单元：调用串行，模态对话框会卡住服务器。
- 拓扑索引是快照，几何变化后必须重新列举。
- Motion 求解依赖 ADAMS 插件；运动元素只能在装配体文档创建。
- `circular_pattern` 无法阵列生成了独立实体的特征。
- 工程图视图名是本地化的，用 `list_drawing_views` 返回的名字。

## 测试

```powershell
python -m unittest discover -s tests -p 'test_*.py'     # 225 项离线检查
python tests/live_p0_regression.py                      # 实机，按功能域
python tools/verify_install.py --install <dir> --tool-count 192 --scratch
```

CI 在 Windows 上跑 Python 3.10–3.13 的离线套件。工具约定与常见坑见
[CONTRIBUTING.md](CONTRIBUTING.md)。

## 目录结构

| 模块 | 内容 |
| --- | --- |
| `sw_core.py` | COM 连接、单位、特征树、拓扑、选择引擎、注册表 |
| `sw_file.py` | 会话、文档、保存、导出、外观、材质 |
| `sw_refgeom.py` | 基准面与轴 |
| `sw_sketch.py` | 草图、几何、编辑、约束、尺寸 |
| `sw_feature.py` | 实体特征 |
| `sw_inspect.py` | 拓扑、测量、质量属性、截图 |
| `sw_assembly.py` | 组件与配合 |
| `sw_drawing.py` | 图纸、视图、模型项目、尺寸、注释 |
| `sw_manage.py` | 文档、配置、属性、方程、材料 |
| `sw_multibody.py` | 多实体、曲面、螺旋线 |
| `sw_boundary.py` / `sw_wrap.py` / `sw_dome.py` | 边界曲面、包覆、圆顶 |
| `sw_sheetmetal.py` / `sw_weldment.py` | 钣金与焊件 |
| `sw_motion.py` | Motion 算例、载荷、求解、动画 |
| `sw_geometry.py` | XYZ 曲线与组合曲线 |
| `tests/` | 离线单元测试与按功能域的实机回归 |
| `tools/` | 类型库探针、API 清点、覆盖报告、安装验收 |
| `server.py` | 注册表组装与 stdio 分发 |

## 许可证

Apache License 2.0 —— 见 [LICENSE](LICENSE)。版权 2026 JIALE LIU。
