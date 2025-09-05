## yooztech_mcp_api_request —— 基于 MCP 的通用 API 请求工具

该 MCP 服务器用于向真实后端 API 发起请求，帮助前端/AI 获取最真实的接口返回；包含：
- `init_config(project_root=None, overwrite=false, tokens=None, fmt="yaml")`：在项目根创建配置文件，存储鉴权信息
- `api_request(method, url, params=None, headers=None, body=None, project_root=None, timeout_seconds=30)`：读取配置并发起请求，返回基本信息与完整响应

### 在 Cursor 中配置
在 Cursor 的设置中添加 MCP Server（示例）：

```json
{
  "mcpServers": {
    "yooztech_mcp_api_request": {
      "command": "yooztech_mcp_api_request",
      "args": []
    }
  }
}
```

如不想全局安装，可使用 `uvx` 方式：

```json
{
  "mcpServers": {
    "yooztech_mcp_api_request": {
      "command": "uvx",
      "args": ["yooztech_mcp_api_request"]
    }
  }
}
```

### 脚本与入口
- 控制台脚本：`yooztech_mcp_api_request`（见 `pyproject.toml` 的 `[project.scripts]`）

### 开发
- 依赖安装：`pip install -r requirements.txt`
- 运行：`yooztech_mcp_api_request`

### 配置文件
- 默认文件名（写入项目根目录）：`.mcp_api_request.yml`（或 `.json` 当 `fmt=json`）
- 文件结构：列表，每项为 `{type, key, value}`
  - `type`: `header` | `param`
  - `key`: token 的字段名
  - `value`: token 的值

示例（YAML）：

```yaml
- type: header
  key: Authorization
  value: Bearer xxxxxx
- type: param
  key: access_token
  value: xxxxxx
```

或（JSON）：

```json
[
  {"type":"header","key":"Authorization","value":"Bearer xxxxxx"},
  {"type":"param","key":"access_token","value":"xxxxxx"}
]
```

### 使用流程
1) 初始化（生成空值模板）：
```json
{"tool":"init_config","args":{"overwrite":false}}
```
执行后会在项目根创建 `.mcp_api_request.yml`（或 `.json`），其中示例条目的 `value` 为空。请手动编辑为你的真实 token；空值项在请求时不会发送。

2) 发起请求：
```json
{
  "tool":"api_request",
  "args":{
    "method":"GET",
    "url":"https://api.example.com/users",
    "params":{"page":1},
    "headers":{"X-Debug":"1"}
  }
}
```

### 许可证
- MIT（见 `LICENSE`）
