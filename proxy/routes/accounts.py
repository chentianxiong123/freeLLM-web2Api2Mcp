from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import accounts
from backends.deepseek_web.login import login as ds_login
import session as sess

router = APIRouter(tags=["accounts"])


@router.get("/api/accounts")
async def api_list_accounts():
    return {"accounts": accounts.list_accounts()}


@router.post("/api/accounts/add")
async def api_add_account(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    new_acc = accounts.add_account(
        label=body.get("label", ""),
        login_type=body.get("login_type", "email"),
        account=body.get("account", ""),
        password=body.get("password", ""),
    )
    result = ds_login(new_acc["login_type"], body.get("account", ""), body.get("password", ""))
    if result and result.get("token"):
        accounts.save_account_token(
            new_acc["id"],
            token=result.get("token", ""),
            session_id=result.get("session_id", ""),
            headers=result.get("headers", {}),
        )
        return {"ok": True, "account": new_acc, "logged_in": True}
    return {"ok": True, "account": new_acc, "logged_in": False, "message": "已添加但登录失败，请手动登录"}


@router.post("/api/accounts/delete/{acc_id}")
async def api_delete_account(acc_id: str):
    ok = accounts.delete_account(acc_id)
    return {"ok": ok, "id": acc_id}


@router.post("/api/accounts/activate/{acc_id}")
async def api_activate_account(acc_id: str):
    ok = accounts.activate_account(acc_id)
    if ok:
        acc = accounts.get_active_account()
        if acc:
            if acc.get("session_id"):
                sess.activate_session(acc["session_id"])
            # 自动切换 backend
            acc_backend = acc.get("backend", "deepseek")
            import config as _cfg
            _cfg.update_config(backend=acc_backend)
    return {"ok": ok, "id": acc_id}


@router.post("/api/accounts/login/{acc_id}")
async def api_login_account(acc_id: str, request: Request):
    target = accounts.get_account_by_id(acc_id)
    if not target:
        return JSONResponse(status_code=404, content={"ok": False, "error": "账号不存在"})

    result = ds_login(target["login_type"], target["account"], target["password"])
    if result and result.get("token"):
        accounts.save_account_token(
            acc_id,
            token=result.get("token", ""),
            session_id=result.get("session_id", ""),
            headers=result.get("headers", {}),
        )
        return {"ok": True, "message": "登录成功"}
    return JSONResponse(status_code=401, content={"ok": False, "error": "登录失败"})


@router.post("/api/accounts/import")
async def api_import_account():
    ok = accounts.import_from_config()
    return {"ok": ok, "message": "已导入" if ok else "无需导入（已存在或无数据）"}


@router.post("/api/accounts/qwen-token")
async def api_set_qwen_token(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    token = body.get("token", "")
    model = body.get("model", "qwen3.7-max")
    if not token:
        return JSONResponse(status_code=400, content={"ok": False, "error": "token 不能为空"})
    result = accounts.set_qwen_token(token, model)
    return {"ok": True, "account": result, "message": "Qwen token 已设置"}


@router.post("/api/accounts/update/{acc_id}")
async def api_update_account(acc_id: str, request: Request):
    """更新账号配置（token / model / session_id 等）。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    allowed = {"label", "token", "model", "session_id", "active", "backend"}
    patch = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not patch:
        return JSONResponse(status_code=400, content={"ok": False, "error": "没有可更新的字段"})
    result = accounts.update_account(acc_id, patch)
    if not result:
        return JSONResponse(status_code=404, content={"ok": False, "error": "账号不存在"})
    return {"ok": True, "account": result}
