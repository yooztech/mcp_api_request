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
    """在指定目录查找配置文件"""
    for name in CONFIG_CANDIDATES:
        p = root / name
        if p.is_file():
            return p
    return None


def _find_config_recursive(start_path: Path, max_depth: int = 5) -> Optional[Path]:
    """递归向上查找配置文件，最多向上查找 max_depth 层"""
    current = start_path.resolve()
    for _ in range(max_depth):
        config = _find_existing_config(current)
        if config:
            return config
        parent = current.parent
        if parent == current:
            # 已到达根目录
            break
        current = parent
    return None


def _smart_find_config(project_root: Optional[str] = None) -> Tuple[Optional[Path], List[str]]:
    """智能查找配置文件，返回 (配置文件路径, 搜索过的目录列表)"""
    searched_dirs: List[str] = []
    
    # 1. 如果指定了 project_root，优先在该目录查找
    if project_root and isinstance(project_root, str) and project_root.strip():
        root = Path(project_root).expanduser().resolve()
        searched_dirs.append(str(root))
        config = _find_existing_config(root)
        if config:
            return config, searched_dirs
    
    # 2. 尝试从环境变量获取项目根目录
    env_root = os.environ.get("MCP_API_REQUEST_PROJECT_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if root not in [Path(d) for d in searched_dirs]:
            searched_dirs.append(str(root))
            config = _find_existing_config(root)
            if config:
                return config, searched_dirs
    
    # 3. 从当前工作目录开始递归向上查找（限制在项目目录内）
    cwd = Path(os.getcwd()).resolve()
    if str(cwd) not in searched_dirs:
        searched_dirs.append(str(cwd))
    config = _find_config_recursive(cwd)
    if config:
        # 记录所有向上搜索过的目录
        parent = cwd.parent
        current = cwd
        for _ in range(5):
            if parent == current:
                break
            if str(parent) not in searched_dirs:
                searched_dirs.append(str(parent))
            if config.parent == parent:
                break
            current = parent
            parent = parent.parent
        return config, searched_dirs
    
    return None, searched_dirs


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
    
    注意：如果不指定 project_root，配置文件将创建在当前工作目录。
    也可以设置环境变量 MCP_API_REQUEST_PROJECT_ROOT 作为默认项目根目录。
    """
    root = _resolve_project_root(project_root)
    path = _choose_write_path(root, fmt)

    if path.exists() and not overwrite:
        # 检查是否能通过智能查找找到这个文件
        found_path, _ = _smart_find_config(project_root)
        raise ValueError(
            f"配置文件已存在：{str(path)}\n"
            f"如需覆盖请设置 overwrite=true\n"
            f"提示：该配置文件可被自动发现并使用。"
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
    
    # 验证能否通过智能查找找到刚创建的文件
    found_path, searched_dirs = _smart_find_config(project_root)
    auto_discoverable = found_path == path
    
    result = {
        "path": str(path),
        "created": True,
        "count": len(data),
        "auto_discoverable": auto_discoverable,
        "next_steps": [
            "打开上述文件，填入实际 token 值（空值项不会被发送）",
            "可保留或删除你不需要的项；可添加更多 {type,key,value} 条目",
        ],
    }
    
    if auto_discoverable:
        result["note"] = "✓ 配置文件位置正确，工具可以自动发现并使用"
    else:
        result["warning"] = (
            f"⚠ 配置文件创建在 {str(path)}，但可能无法被自动发现。\n"
            f"建议：设置环境变量 MCP_API_REQUEST_PROJECT_ROOT={str(root)} 或在调用时明确指定 project_root"
        )
    
    return result


@server.tool()
async def locate_config(project_root: Optional[str] = None) -> Dict[str, Any]:
    """定位配置文件的位置，用于调试和验证配置文件能否被找到。
    
    返回当前能找到的配置文件路径，以及搜索过的所有目录。
    """
    cfg_path, searched_dirs = _smart_find_config(project_root)
    
    result: Dict[str, Any] = {
        "config_found": cfg_path is not None,
        "searched_directories": searched_dirs,
    }
    
    if cfg_path:
        result["config_path"] = str(cfg_path)
        result["config_directory"] = str(cfg_path.parent)
        result["config_filename"] = cfg_path.name
        # 尝试读取配置内容统计
        try:
            tokens = _load_tokens_from_config(cfg_path)
            result["tokens_count"] = len(tokens)
            result["token_types"] = {
                "header": sum(1 for t in tokens if t.get("type") == "header"),
                "param": sum(1 for t in tokens if t.get("type") == "param"),
            }
        except Exception as e:
            result["config_error"] = str(e)
    else:
        result["message"] = (
            "未找到配置文件。请运行 init_config 创建配置文件，\n"
            "或设置环境变量 MCP_API_REQUEST_PROJECT_ROOT 指定项目根目录。"
        )
    
    # 提供环境变量信息
    env_root = os.environ.get("MCP_API_REQUEST_PROJECT_ROOT")
    if env_root:
        result["env_project_root"] = env_root
    
    result["current_working_directory"] = str(Path(os.getcwd()).resolve())
    
    return result


@server.tool()
async def api_request(
    method: Any = None,
    url: Any = None,
    params: Any = None,
    headers: Any = None,
    body: Any = None,
    project_root: Optional[str] = None,
    timeout_seconds: Any = 30.0,
    **extra_args: Any,
) -> Dict[str, Any]:
    """读取配置并请求指定 API，返回基本信息与完整响应。

    - 从 `.mcp_api_request.yml/.yaml/.json` 读取鉴权配置
    - 自动将 type=header 的 token 加入请求头，将 type=param 的 token 加入查询参数
    - 用户传入的 headers/params 将覆盖同名的鉴权项
    - body 为 dict/list 时作为 JSON 发送；其余类型将作为原始内容发送
    """
    # 兼容别名与上游 AI 可能传入的额外键
    if (method is None or str(method).strip() == "") and "method" in extra_args:
        method = extra_args.get("method")
    if (url is None or str(url).strip() == "") and "url" in extra_args:
        url = extra_args.get("url")
    if project_root is None:
        project_root = (
            extra_args.get("project_root")
            or extra_args.get("project root")
            or extra_args.get("projectRoot")
            or project_root
        )
    if timeout_seconds is None or (isinstance(timeout_seconds, str) and timeout_seconds.strip() == ""):
        timeout_seconds = 30.0
    # 处理别名超时键
    if isinstance(timeout_seconds, (int, float)):
        pass
    else:
        alias_to = (
            extra_args.get("timeout_seconds")
            or extra_args.get("timeout seconds")
            or extra_args.get("timeoutSeconds")
            or timeout_seconds
        )
        try:
            timeout_seconds = float(alias_to)
        except Exception:
            timeout_seconds = 30.0

    cfg_path, searched_dirs = _smart_find_config(project_root)
    if not cfg_path:
        searched_info = "\n  - ".join(searched_dirs)
        raise ValueError(
            f"未找到配置文件，已搜索以下目录：\n  - {searched_info}\n\n"
            "请在以上任一目录创建配置文件，或运行 init_config 工具初始化配置。\n"
            "提示：可设置环境变量 MCP_API_REQUEST_PROJECT_ROOT 指定默认项目根目录。"
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

    method_upper = str(method or "").strip().upper()
    if not method_upper:
        raise ValueError("method 不能为空，例如 GET/POST/PUT/DELETE")

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
