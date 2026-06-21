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
        if acc and acc.get("session_id"):
            sess.activate_session(acc["session_id"])
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
