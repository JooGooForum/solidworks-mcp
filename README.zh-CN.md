# solidworks-mcp

[English](README.md) | 简体中文

通过 COM API 驱动**正在运行**的 SOLIDWORKS 会话的 MCP 服务器。它连接你已经打开的
会话，不启动 SOLIDWORKS、不注册插件、不访问网络。

212 个工具。已覆盖与未覆盖清单：[COVERAGE.zh-CN.md](COVERAGE.zh-CN.md)。

## 环境要求

Windows、已安装且**正在运行**的 SOLIDWORKS、Python 3.10+。

## 安装

```powershell
git clone https://github.com/Slacker-LLC/solidworks-mcp.git
cd solidworks-mcp
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
```

命令是 `solidworks-mcp`，发行包是 `solidworks-mcp-server`。

Claude：

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

## 配置

### 钣金工作流

`list_sheet_metal_profiles` 用于解析 `standard_2026` 配置及其 **2026 plaat** 模板。可将 `SW_MCP_SHEETMETAL_TEMPLATE` 设为准确的 `.prtdot` 路径，或把模板放在 `SW_MCP_TEMPLATE_DIR` 下。创建板件和面板时必须明确提供板厚、内折弯半径及 `dimension_mode`（`flat_blank` 或 `finished_outer`）；工具只创建未保存文档，不会调用 PDM。

`create_sheet_metal_panel` 使用语义化的 `left`、`right`、`bottom`、`top` 边线法兰声明。可选的褶边、折断角、闭合角和角释放引用这些边，而不是短暂的拓扑索引；工作流会在每个特征之后重新解析原生拓扑，并在读回不符或重建错误时停止。

受保护的编辑前必须先检查现有零件。编辑令牌绑定当前文档、配置、特征更新戳、持久面/边拓扑、特征状态和边界框。所有受保护的原生应用工具都公开 `edit_token`；活动零件已有保存路径时必须提供。草图对齐会报告模型空间方向、间隙、现有关系和准确的持久引用；应用时必须回传这些引用，并且只添加直接原生共线关系，不会改用转换几何。展开图抑制、原生展开/折叠特征和特征树回滚是不同操作。DXF 导出会解析生成文件的实体段；当零件含折弯且请求折弯线时，必须读到折弯图层实体。

完整的工具、契约、尺寸模式与安全边界说明见[钣金工作流工具包](docs/SHEET_METAL_WORKFLOWS.zh-CN.md)。

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `SW_MCP_OUTPUT_ROOT` | `~/Documents/solidworks-mcp` | 服务器写出的所有文件都在此目录下。 |
| `SW_MCP_TEMPLATE_DIR` | 自动发现 | `.prtdot` / `.asmdot` / `.drwdot` 模板目录。 |
| `SW_MCP_SHEETMETAL_TEMPLATE` | 未设置 | **2026 plaat** 配置使用的准确 `.prtdot` 路径。 |
| `SW_MCP_DEMO_TOOLS` | 未设置 | 设为 `1` 会加入降低工具选择质量的演示工具。 |
| `SW_MCP_SESSION_PID` | 未设置 | 连接指定的已有实例。 |

长度以 `_mm` 结尾，角度以 `_deg` 结尾。几何通过 `selection` 对象传入
（`{"edges": [4, 6, 9]}`、`{"planes": ["front"]}`）；索引对应当前模型，几何变化后需
重新列举。

### 精确指定文档模板

`create_new_document` 和 `create_drawing` 接受可选的绝对或相对
`template_path`。显式路径必须指向一个存在且可读的模板，并且扩展名必须与请求的文档
类型匹配；路径解析后会原样传给 `ISldWorks.NewDocument`。显式模板请求失败时绝不回退
到其他模板。

```json
{"kind": "part", "template_path": "C:\\CAD\\Templates\\Machined Part.PRTDOT"}
```

```json
{"template_path": "C:\\CAD\\Templates\\A4 Landscape.DRWDOT", "first_angle": true}
```

省略 `template_path` 时，连接器保持原有优先顺序：先使用 SOLIDWORKS 配置的默认模板，
再通过 `SW_MCP_TEMPLATE_DIR` 和标准模板位置自动发现。结果会将选择来源标记为
`explicit`、`solidworks_default` 或 `discovered`，并验证实际创建的文档类型。
SOLIDWORKS 无法可靠回读零件和装配体的来源模板路径，因此结果会明确说明这一限制，
而不会声称已经完成原生来源验证。工程图结果还会在 SOLIDWORKS 可提供时回读当前图纸
尺寸、比例、投影方式和图框格式路径。

当请求投影方式、比例或纸张大小等工程图覆盖项时，`create_drawing` 会保留模板继承的
图框格式路径，并在 `SetupSheet5` 之后进行验证；模板自带的辅助图纸不会被移除。
`auto_dimension_view` 会先激活并显式选择指定的工程图视图，再调用
`IDrawingDoc.AutoDimension`，并仅报告该目标视图新增的尺寸数量，而不是整个文档的总数。

### 工程图注解图层

`insert_model_annotations`、`auto_dimension_view`、`insert_center_marks`、
`insert_centerlines` 和 `add_note` 创建的注解默认使用 SOLIDWORKS 的
**按标准（Per Standard）**状态。连接器会临时选择原生图层管理器中的
`-Per Standard-` 状态，操作完成后恢复之前的当前图层，并回读文档标准实际分配的图层，
而不会重新分配该图层。现有注解（包括工程图模板提供的标题栏内容）不会被更改。

## 测试

```powershell
python -m unittest discover -s tests -p 'test_*.py'     # 离线
python tests/live_p0_regression.py                      # 实机，需 SOLIDWORKS 运行
```

贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)，发布流程见 [RELEASING.md](RELEASING.md)。

## 许可证

Apache License 2.0 —— 见 [LICENSE](LICENSE) 与[简体中文说明](LICENSE.zh-CN.md)。版权 2026 JIALE LIU。

