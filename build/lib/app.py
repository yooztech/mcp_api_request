#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml
from mcp.server.fastmcp import FastMCP


server = FastMCP("yooztech_mcp_api_request")


CONFIG_CANDIDATES: List[str] = [
    ".mcp_api_request.yml",
    ".mcp_api_request.yaml",
    ".mcp_api_request.json",
]


def _resolve_project_root(project_root: Optional[str]) -> Path:
    if project_root and isinstance(project_root, str) and project_root.strip():
        return Path(project_root).expanduser().resolve()
    return Path(os.getcwd()).resolve()


def _default_config_tokens() -> List[Dict[str, str]]:
    return [
        {"type": "header", "key": "auth", "value": "xxxxxx"},
    ]


def _choose_write_path(root: Path, fmt: str) -> Path:
    fmt_lower = (fmt or "yaml").strip().lower()
    if fmt_lower == "json":
        return root / ".mcp_api_request.json"
    return root / ".mcp_api_request.yml"


def _find_existing_config(root: Path) -> Optional[Path]:
    for name in CONFIG_CANDIDATES:
        p = root / name
        if p.is_file():
            return p
    return None


def _load_tokens_from_config(path: Path) -> List[Dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text or "[]")
    else:
        data = yaml.safe_load(text or "[]")
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("配置文件格式错误：根节点应为列表")
    tokens: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("配置文件项必须为对象，包含 type/key/value")
        t = str(item.get("type", "")).strip().lower()
        if t not in ("header", "param"):
            raise ValueError("配置项 type 仅支持 header 或 param")
        key = str(item.get("key", "")).strip()
        val = str(item.get("value", "")).strip()
        if not key:
            raise ValueError("配置项缺少 key")
        tokens.append({"type": t, "key": key, "value": val})
    return tokens


@server.tool()
async def init_config(
    project_root: Optional[str] = None,
    overwrite: bool = False,
    tokens: Optional[List[Dict[str, str]]] = None,
    fmt: str = "yaml",
) -> Dict[str, Any]:
    """初始化配置文件，写入到项目根目录。

    - 文件名：`.mcp_api_request.yml`（或 `.json`，当 fmt=json 时）
    - 内容：列表形式，每项包含 {type, key, value}
      - type: header|param
      - key: 鉴权字段名
      - value: 鉴权值
    """
    root = _resolve_project_root(project_root)
    path = _choose_write_path(root, fmt)

    if path.exists() and not overwrite:
        raise ValueError(f"配置文件已存在：{str(path)}，如需覆盖请设置 overwrite=true")

    # 始终写入包含空值的模板，指导用户手动编辑
    data: List[Dict[str, str]] = [
        {"type": "header", "key": "Authorization", "value": ""},
        {"type": "param", "key": "access_token", "value": ""},
    ]

    if path.suffix.lower() == ".json":
        content = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    path.write_text(content, encoding="utf-8")
    return {
        "path": str(path),
        "created": True,
        "count": len(data),
        "next_steps": [
            "打开上述文件，填入实际 token 值（空值项不会被发送）",
            "可保留或删除你不需要的项；可添加更多 {type,key,value} 条目",
        ],
    }


@server.tool()
async def api_request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    project_root: Optional[str] = None,
    timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    """读取配置并请求指定 API，返回基本信息与完整响应。

    - 从 `.mcp_api_request.yml/.yaml/.json` 读取鉴权配置
    - 自动将 type=header 的 token 加入请求头，将 type=param 的 token 加入查询参数
    - 用户传入的 headers/params 将覆盖同名的鉴权项
    - body 为 dict/list 时作为 JSON 发送；其余类型将作为原始内容发送
    """
    root = _resolve_project_root(project_root)
    cfg_path = _find_existing_config(root)
    if not cfg_path:
        raise ValueError(
            "未找到配置文件，请先运行 init_config 在项目根目录创建 .mcp_api_request.yml/.json"
        )

    tokens = _load_tokens_from_config(cfg_path)

    auth_headers: Dict[str, str] = {}
    auth_params: Dict[str, Any] = {}
    for item in tokens:
        value = str(item.get("value", ""))
        if value == "":
            # 空值项不发送
            continue
        if item["type"] == "header":
            auth_headers[item["key"]] = value
        elif item["type"] == "param":
            auth_params[item["key"]] = value

    final_headers: Dict[str, str] = {**auth_headers, **(headers or {})}
    final_params: Dict[str, Any] = {**auth_params, **(params or {})}

    send_json: Optional[Any] = None
    send_content: Optional[bytes | str] = None
    if body is not None:
        if isinstance(body, (dict, list)):
            send_json = body
        else:
            send_content = body

    method_upper = str(method or "").strip().upper()
    if not method_upper:
        raise ValueError("method 不能为空，例如 GET/POST/PUT/DELETE")

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method_upper,
            url,
            params=final_params or None,
            headers=final_headers or None,
            json=send_json,
            content=send_content,
        )

    content_type = resp.headers.get("content-type", "")
    body_text: Optional[str] = None
    body_json: Optional[Any] = None
    try:
        if "json" in content_type.lower():
            body_json = resp.json()
        else:
            body_text = resp.text
    except Exception:
        # 回退：若解析失败，返回原始文本
        body_text = resp.text

    result: Dict[str, Any] = {
        "request": {
            "method": method_upper,
            "url": url,
            "final_url": str(resp.url),
            "headers": final_headers,
            "params": final_params,
            "body_kind": "json" if send_json is not None else ("content" if send_content is not None else None),
        },
        "response": {
            "status_code": resp.status_code,
            "reason": getattr(resp, "reason_phrase", None),
            "elapsed_ms": int(resp.elapsed.total_seconds() * 1000) if resp.elapsed else None,
            "headers": dict(resp.headers),
            "content_type": content_type or None,
            "json": body_json,
            "text": body_text,
        },
    }
    return result


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
