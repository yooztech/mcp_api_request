#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import ast
from typing import Any, Dict, List, Optional, Tuple, Union

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


def _choose_write_path(root: Path, fmt: str) -> Path:
    fmt_lower = (fmt or "yaml").strip().lower()
    if fmt_lower == "json":
        return root / ".mcp_api_request.json"
    return root / ".mcp_api_request.yml"


def _find_existing_config(root: Path) -> Optional[Path]:
    """在指定目录查找配置文件"""
    for name in CONFIG_CANDIDATES:
        p = root / name
        if p.is_file():
            return p
    return None


def _smart_find_config(project_root: str) -> Tuple[Optional[Path], Path]:
    """查找配置文件，使用和 init_config 完全相同的目录解析逻辑
    
    返回 (配置文件路径, 项目根目录路径)
    """
    # 使用和 init_config 完全相同的目录解析方法
    root = _resolve_project_root(project_root)
    
    # 在项目根目录查找配置文件
    config = _find_existing_config(root)
    
    return config, root


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


def _as_pairs(obj: Any) -> Optional[List[Tuple[str, Any]]]:
    if isinstance(obj, list):
        pairs: List[Tuple[str, Any]] = []
        for item in obj:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((str(item[0]), item[1]))
            elif isinstance(item, dict) and "key" in item and "value" in item:
                pairs.append((str(item["key"]), item["value"]))
            else:
                # 跳过无法识别的项
                continue
        return pairs
    return None


def _as_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if isinstance(obj, dict):
        # 统一 key 为字符串
        return {str(k): v for k, v in obj.items()}
    return None


def _normalize_headers(base_headers: Dict[str, str], user_headers: Any) -> Dict[str, str]:
    if user_headers is None:
        return dict(base_headers)
    if isinstance(user_headers, str):
        s = user_headers.strip()
        if s == "" or s.lower() in ("null", "none", "undefined"):
            return dict(base_headers)
        parsed: Any = None
        try:
            parsed = json.loads(s)
        except Exception:
            try:
                parsed = ast.literal_eval(s)
            except Exception:
                parsed = None
        if parsed is not None:
            return _normalize_headers(base_headers, parsed)
        return dict(base_headers)
    d = _as_dict(user_headers)
    if d is not None:
        return {**base_headers, **{str(k): str(v) for k, v in d.items()}}
    p = _as_pairs(user_headers)
    if p is not None:
        merged = dict(base_headers)
        for k, v in p:
            merged[str(k)] = str(v)
        return merged
    return dict(base_headers)


def _normalize_params(base_params: Dict[str, Any], user_params: Any) -> Dict[str, Any] | List[Tuple[str, Any]]:
    if user_params is None:
        return dict(base_params)
    if isinstance(user_params, str):
        s = user_params.strip()
        if s == "" or s.lower() in ("null", "none", "undefined"):
            return dict(base_params)
        parsed: Any = None
        try:
            parsed = json.loads(s)
        except Exception:
            try:
                parsed = ast.literal_eval(s)
            except Exception:
                parsed = None
        if parsed is not None:
            return _normalize_params(base_params, parsed)
        return dict(base_params)
    d = _as_dict(user_params)
    if d is not None:
        return {**base_params, **d}
    p = _as_pairs(user_params)
    if p is not None:
        # 顺序为 base 在前，user 覆盖在后（同键后者生效）
        seq: List[Tuple[str, Any]] = list(base_params.items())
        seq.extend(p)
        return seq
    return dict(base_params)


@server.tool()
async def init_config(
    project_root: str,
    fmt: str = "yaml",
) -> Dict[str, Any]:
    """初始化配置文件，写入到项目根目录。

    - project_root: 必填项，指定项目根目录的绝对路径
    - fmt: 配置文件格式，yaml 或 json，默认为 yaml
    - 文件名：`.mcp_api_request.yml`（或 `.json`，当 fmt=json 时）
    - 内容：列表形式，每项包含 {type, key, value}
      - type: header|param
      - key: 鉴权字段名
      - value: 鉴权值
    
    配置文件已存在时会拒绝创建，避免覆盖现有配置。
    """
    if not project_root or not isinstance(project_root, str) or not project_root.strip():
        raise ValueError("project_root 是必填项，必须提供项目根目录的绝对路径")
    
    root = _resolve_project_root(project_root)
    path = _choose_write_path(root, fmt)

    if path.exists():
        raise ValueError(
            f"配置文件已存在：{str(path)}\n"
            f"不能覆盖已有配置文件，请手动编辑或删除后重新创建"
        )

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
        "project_root": str(root),
        "created": True,
        "count": len(data),
        "next_steps": [
            "打开上述文件，填入实际 token 值（空值项不会被发送）",
            "可保留或删除你不需要的项；可添加更多 {type,key,value} 条目",
        ],
    }


@server.tool()
async def api_request(
    project_root: str,
    method: str,
    url: str,
    params: Any = None,
    headers: Any = None,
    body: Any = None,
    timeout_seconds: Any = 30.0,
    **extra_args: Any,
) -> Dict[str, Any]:
    """发送 HTTP API 请求，自动附加项目配置的鉴权信息。
    
    这个工具用于向任何 HTTP API 发送请求，会自动从项目配置文件中读取并添加鉴权信息（如 API Token、Authorization 头等）。
    
    必填参数：
    - project_root: 项目根目录的绝对路径，例如 "/home/user/my_project"
    - method: HTTP 请求方法，例如 "GET"、"POST"、"PUT"、"DELETE"
    - url: 完整的请求 URL，例如 "https://api.example.com/users"
    
    可选参数：
    - params: URL 查询参数，dict 格式，例如 {"page": 1, "limit": 10}
    - headers: 额外的请求头，dict 格式，例如 {"Content-Type": "application/json"}
    - body: 请求体，dict/list 会自动转为 JSON，字符串直接发送
    - timeout_seconds: 请求超时时间（秒），默认 30
    
    使用示例：
    1. GET 请求：
       api_request(project_root="/home/user/project", method="GET", url="https://api.example.com/users")
    
    2. POST 请求带 JSON 数据：
       api_request(project_root="/home/user/project", method="POST", url="https://api.example.com/users", 
                   body={"name": "张三", "age": 25})
    
    3. 带查询参数的 GET 请求：
       api_request(project_root="/home/user/project", method="GET", url="https://api.example.com/users",
                   params={"page": 1, "limit": 10})
    
    返回值包含完整的请求和响应信息，包括状态码、响应头、响应体等。
    """
    # 验证必填参数
    if not project_root or not isinstance(project_root, str) or not project_root.strip():
        raise ValueError("project_root 是必填项，必须提供项目根目录的绝对路径")
    
    if not method or not isinstance(method, str) or not method.strip():
        raise ValueError("method 是必填项，必须提供 HTTP 方法（如 GET、POST、PUT、DELETE）")
    
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("url 是必填项，必须提供完整的请求 URL")
    
    # 处理超时参数
    try:
        timeout_seconds = float(timeout_seconds)
    except Exception:
        timeout_seconds = 30.0

    cfg_path, root = _smart_find_config(project_root)
    
    if not cfg_path:
        raise ValueError(
            f"未找到配置文件，已在目录 {str(root)} 中查找。\n\n"
            "请先运行 init_config 工具初始化配置，或手动创建配置文件。\n"
            "配置文件名称: .mcp_api_request.yml 或 .mcp_api_request.json\n"
            f"提示: 配置文件应位于 {str(root)} 目录下"
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

    final_headers: Dict[str, str] = _normalize_headers(auth_headers, headers)
    final_params = _normalize_params(auth_params, params)

    send_json: Optional[Any] = None
    send_content: Optional[bytes | str] = None
    if body is not None:
        if isinstance(body, str):
            s = body.strip()
            if s == "" or s.lower() in ("null", "none", "undefined"):
                pass
            else:
                # 尝试解析 JSON/Python 字面量
                parsed: Any = None
                try:
                    parsed = json.loads(s)
                except Exception:
                    try:
                        parsed = ast.literal_eval(s)
                    except Exception:
                        parsed = None
                if isinstance(parsed, (dict, list)):
                    send_json = parsed
                elif parsed is not None:
                    send_content = str(parsed)
                else:
                    send_content = s
        else:
            if isinstance(body, (dict, list)):
                send_json = body
            else:
                send_content = str(body)
        if isinstance(body, (dict, list)):
            send_json = body
        else:
            send_content = str(body)

    method_upper = method.strip().upper()

    # 更安全的超时构造：连接/读取/写入/总时长
    try:
        to = float(timeout_seconds)
    except Exception:
        to = 30.0
    timeout = httpx.Timeout(to, connect=to, read=to, write=to)
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
