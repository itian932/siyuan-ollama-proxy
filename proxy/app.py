import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

UPSTREAM_BASE = os.getenv("UPSTREAM_BASE", "http://ollama:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3:8b")

# 是否自动拉取模型：1/true/yes/on 开启
AUTO_PULL = os.getenv("AUTO_PULL", "0").strip().lower() in {"1", "true", "yes", "on"}

# models 列表缓存，减少 /api/tags 频率
MODELS_CACHE_TTL_SEC = int(os.getenv("MODELS_CACHE_TTL_SEC", "10"))
_models_cache: set[str] = set()
_models_cache_ts: float = 0.0

app = FastAPI()


def _normalize_model(raw: str) -> str:
    """
    兼容各种“被拼坏”的 model 值：
      deepseek-r1:latest/chat/completions  -> deepseek-r1:latest
      deepseek-r1:latest%2Fchat%2Fcompletions -> deepseek-r1:latest
    """
    m = (raw or "").strip()
    if not m:
        return ""
    # 有些客户端会把路径拼进 model 值里，直接取第一个 '/' 前面的部分
    if "/" in m:
        m = m.split("/", 1)[0].strip()
    return m


def _pick_model(request: Request) -> str:
    """
    规则：
    1) 有 ?model=xxx -> 使用它（强制覆盖 body 内 model）
    2) 没有 ?model= -> 用 DEFAULT_MODEL
    """
    m_q = request.query_params.get("model")
    m = _normalize_model(m_q) if m_q else ""
    return m or DEFAULT_MODEL


def _apply_model(payload: Any, model: str, force: bool) -> Any:
    """
    force=True: 无条件覆盖 payload['model']
    force=False: 仅当 payload 没有 model 时补齐
    """
    if not isinstance(payload, dict):
        return payload
    if force:
        payload["model"] = model
    else:
        payload.setdefault("model", model)
    return payload


async def _fetch_local_models(client: httpx.AsyncClient) -> set[str]:
    # Ollama 列出本地模型：GET /api/tags
    r = await client.get(f"{UPSTREAM_BASE}/api/tags", timeout=30)
    r.raise_for_status()
    data = r.json()
    names = set()
    for m in data.get("models", []):
        name = m.get("name")
        if name:
            names.add(name)
    return names


async def _has_model(client: httpx.AsyncClient, model: str) -> bool:
    global _models_cache, _models_cache_ts
    now = time.time()
    if now - _models_cache_ts > MODELS_CACHE_TTL_SEC:
        _models_cache = await _fetch_local_models(client)
        _models_cache_ts = now
    return model in _models_cache


async def _pull_model(client: httpx.AsyncClient, model: str) -> None:
    # 拉取模型：POST /api/pull
    # stream=False：等待拉取完成后再继续（会阻塞这一请求）
    r = await client.post(
        f"{UPSTREAM_BASE}/api/pull",
        json={"model": model, "stream": False},
        timeout=None,
    )
    r.raise_for_status()
    # 刷新缓存
    global _models_cache_ts
    _models_cache_ts = 0.0


async def _ensure_model(model: str) -> None:
    if not AUTO_PULL:
        return
    async with httpx.AsyncClient() as client:
        if not await _has_model(client, model):
            await _pull_model(client, model)


# 兼容一些客户端用 GET 探测接口，避免 405 影响“可用性判断”
@app.get("/v1/chat/completions")
async def chat_completions_probe():
    return {
        "ok": True,
        "note": "Use POST /v1/chat/completions. Proxy is alive.",
        "default_model": DEFAULT_MODEL,
        "auto_pull": AUTO_PULL,
    }


@app.get("/v1/models")
async def models():
    # 优先透传上游 /v1/models（如存在）
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{UPSTREAM_BASE}/v1/models")
        if r.status_code == 200:
            return r.json()

    # fallback：至少返回默认模型
    return {
        "object": "list",
        "data": [{"id": DEFAULT_MODEL, "object": "model", "owned_by": "ollama"}],
    }


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_v1(path: str, request: Request):
    upstream_url = f"{UPSTREAM_BASE}/v1/{path}"

    # 1) 选模型：?model= 优先，否则 DEFAULT_MODEL
    model = _pick_model(request)

    # 2) 如果开启 AUTO_PULL，则确保模型已存在（没有就 pull）
    #    只要你传了 ?model=xxx，就能实现“动态切换+自动拉取”
    await _ensure_model(model)

    # 3) headers：删掉 content-length 等，避免 “Too much data for declared Content-Length”
    headers = dict(request.headers)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    headers.pop("host", None)

    # 4) query：透传，但把 model 参数剥掉（避免污染上游）
    params = dict(request.query_params)
    params.pop("model", None)

    body_bytes = await request.body()

    json_payload: Dict[str, Any] | None = None
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type.lower() and body_bytes:
        try:
            json_payload = await request.json()

            # 关键：只要用户提供了 ?model=，就强制覆盖 body 里可能存在的 model
            force = "model" in request.query_params
            json_payload = _apply_model(json_payload, model, force=force)

            body_bytes = b""
        except Exception:
            json_payload = None

    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.request(
            method=request.method,
            url=upstream_url,
            params=params,
            headers=headers,
            content=body_bytes if json_payload is None else None,
            json=json_payload,
        )

        # 5) 流式透传（SSE / chunked）
        ct = r.headers.get("content-type", "")
        if "text/event-stream" in ct.lower():
            async def gen():
                async for chunk in r.aiter_bytes():
                    yield chunk

            resp_headers = dict(r.headers)
            resp_headers.pop("content-encoding", None)
            return StreamingResponse(gen(), status_code=r.status_code, headers=resp_headers)

        resp_headers = dict(r.headers)
        resp_headers.pop("content-encoding", None)
        return Response(content=await r.aread(), status_code=r.status_code, headers=resp_headers)
