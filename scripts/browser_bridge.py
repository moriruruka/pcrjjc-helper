"""本机浏览器查询服务：给 pcrjjc 一个「让页面自己签名」的查询入口。

为什么需要它：pcrdfans 的匿名接口经常超时或返回 103/601，普通请求很难稳定拿到结果；
用真实浏览器打开它自己的 `/battle?id=...` 页面，页面会自动发起带签名的请求，
我们把这个响应截下来就行——签名、Cookie、指纹都由浏览器解决。

窗口默认**不可见**：浏览器以 headless 模式启动；需要登录时用 `--login`
开一次有头窗口，登录完把 profile 留下，之后一直 headless。

用法：

    # 1) 首次登录（会弹一次 Edge 窗口，登录完关掉即可）
    python scripts/browser_bridge.py --login

    # 2) 起服务（默认 127.0.0.1:6191，窗口不可见）
    python scripts/browser_bridge.py --port 6191

    # 3) 自检
    curl http://127.0.0.1:6191/health
    curl -X POST http://127.0.0.1:6191/search -H "Content-Type: application/json" \
         -d '{"def":[100701,107101,100501],"region":1}'

然后把 AstrBot 插件里的 `browser_endpoint` 填成 `http://127.0.0.1:6191`。

依赖：`pip install playwright` + `python -m playwright install msedge`（或用系统自带 Edge）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

BATTLE = "https://pcrdfans.com/battle"
DEFAULT_PORT = 6191
DEFAULT_PROFILE = Path(os.environ.get("PCRJJC_BROWSER_PROFILE", Path.home() / ".pcrjjc" / "browser_profile"))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class Browser:
    """一个常驻的 Edge 上下文，查询串行，避免同时开多个页面。"""

    def __init__(self, profile: Path, headless: bool = True) -> None:
        self.profile = profile
        self.headless = headless
        self.pw = None
        self.ctx = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        if self.ctx is not None:
            return
        from playwright.async_api import async_playwright

        self.profile.mkdir(parents=True, exist_ok=True)
        self.pw = await async_playwright().start()
        self.ctx = await self.pw.chromium.launch_persistent_context(
            str(self.profile),
            channel="msedge",
            headless=self.headless,
            locale="zh-CN",
            user_agent=UA,
            args=["--disable-blink-features=AutomationControlled"],
        )

    async def logged_in(self) -> bool:
        if self.ctx is None:
            return False
        try:
            cookies = await self.ctx.cookies("https://pcrdfans.com")
        except Exception:  # noqa: BLE001
            return False
        return any(c.get("name") == "token" and c.get("value") for c in cookies)

    async def search(self, ids: list[int], region: int = 1, wait: float = 45.0) -> dict:
        async with self.lock:
            await self.start()
            query = "&".join(f"id={i}" for i in ids[:5])
            if region and region != 1:
                query += f"&region={region}"
            page = await self.ctx.new_page()
            holder: dict = {}

            async def on_response(resp) -> None:
                if resp.url.rstrip("/").endswith("/x/v1/search") and resp.request.method == "POST":
                    try:
                        holder["json"] = await resp.json()
                    except Exception as exc:  # noqa: BLE001
                        holder["err"] = f"decode: {exc}"

            page.on("response", on_response)
            try:
                await page.goto(f"{BATTLE}?{query}", wait_until="domcontentloaded", timeout=45_000)
                deadline = time.monotonic() + wait
                while time.monotonic() < deadline and "json" not in holder and "err" not in holder:
                    await asyncio.sleep(0.4)
            except Exception as exc:  # noqa: BLE001
                holder.setdefault("err", f"导航失败：{exc}")
            finally:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
            if "json" not in holder:
                raise RuntimeError(holder.get("err") or "没等到 pcrdfans 的查询响应（可能没登录或网站很慢）")
            return holder["json"]

    async def close(self) -> None:
        for closer in (
            lambda: self.ctx.close() if self.ctx else None,
            lambda: self.pw.stop() if self.pw else None,
        ):
            try:
                await closer() or asyncio.sleep(0)
            except Exception:  # noqa: BLE001
                pass
        self.ctx = None
        self.pw = None


async def serve(args: argparse.Namespace) -> None:
    from aiohttp import web

    browser = Browser(args.profile, headless=True)
    await browser.start()

    async def health(_request):
        return web.json_response({"ok": True, "logged_in": await browser.logged_in()})

    async def search(request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        ids = [int(x) for x in (body.get("def") or []) if str(x).isdigit()][:5]
        if not ids:
            return web.json_response({"ok": False, "error": "def 为空"}, status=400)
        region = int(body.get("region") or 1)
        try:
            payload = await browser.search(ids, region, wait=args.wait)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc)[:300]}, status=502)
        if isinstance(payload, dict) and payload.get("code") in (103, 601):
            return web.json_response(
                {"ok": False, "error": "作业网要求登录：先跑 `python scripts/browser_bridge.py --login`"},
                status=502,
            )
        return web.json_response({"ok": True, "data": payload})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/search", search)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()
    print(f"[bridge] 监听 http://{args.host}:{args.port}（headless，窗口不可见）", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await browser.close()


async def login(args: argparse.Namespace) -> int:
    """开一次有头窗口，让用户手动登录；登录后 profile 里就有 cookie 了。"""

    browser = Browser(args.profile, headless=False)
    await browser.start()
    page = await browser.ctx.new_page()
    await page.goto("https://pcrdfans.com/battle", wait_until="domcontentloaded", timeout=60_000)
    print("[bridge] 请在弹出的窗口里登录；检测到登录后会自动关闭（最多等 5 分钟）", flush=True)
    ok = False
    for _ in range(300):
        if await browser.logged_in():
            ok = True
            break
        await asyncio.sleep(1)
    await browser.close()
    print("[bridge] 登录成功，profile 已保存" if ok else "[bridge] 没检测到登录，可重试", flush=True)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pcrdfans 本机浏览器查询服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--wait", type=float, default=45.0, help="等待页面响应的秒数")
    parser.add_argument("--login", action="store_true", help="开一次有头窗口登录")
    args = parser.parse_args(argv)

    if args.login:
        return asyncio.run(login(args))
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
