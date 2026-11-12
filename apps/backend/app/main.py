"""The FastAPI app: modules, error filter, CORS and docs.

Run it with `python -m app` (see `__main__.py`), or `uvicorn --factory app.main:create_app`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.app_module import AppModule
from app.filters.http_exception_filter import HttpExceptionFilter
from app.guards.admin_guard import ADMIN_HEADER
from app.modules.admin import admin_controller
from app.modules.approval import approval_controller
from app.modules.auth import auth_controller
from app.modules.flutterwave import flutterwave_controller
from app.modules.bill import bill_controller, payee_controller
from app.modules.control import control_controller
from app.modules.demo import demo_controller
from app.modules.health_checker import health_checker_controller
from app.modules.limit import limit_controller
from app.modules.payment import payment_controller
from app.modules.plan import plan_controller
from app.modules.state import state_controller
from app.modules.stub import stub_controller
from app.modules.suggestion import suggestion_controller
from app.modules.telegram import telegram_controller
from app.modules.telemetry import telemetry_controller
from app.modules.turnlog import turnlog_controller
from app.modules.voice import voice_controller
from app.modules.wallet import wallet_controller
from app.setup_swagger import SwaggerSetup

CONTROLLERS = (
    health_checker_controller,
    state_controller,
    bill_controller,
    plan_controller,
    payment_controller,
    limit_controller,
    wallet_controller,
    suggestion_controller,
    telemetry_controller,
    voice_controller,
    telegram_controller,
    auth_controller,
    turnlog_controller,
    stub_controller,
    control_controller,
    approval_controller,
    demo_controller,
    payee_controller,
    flutterwave_controller,
    admin_controller,
)


def create_app(module: Optional[AppModule] = None) -> FastAPI:
    module = module or AppModule.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # No-op without a bot token: the loop reports and claims nothing.
        stop = (
            module.reminders.start(module.config.reminder_tick_seconds)
            if module.config.reminders_enabled
            else None
        )
        # Only when a rail is configured: offline there is nothing to settle.
        money_stop = (
            module.treasury.start(module.config.money.money_tick_seconds)
            if module.vaults.enabled
            or module.flutterwave is not None
            or module.deposits.methods()["crypto"]
            else None
        )
        watching = any(module.deposits.methods().values())
        if watching:
            module.deposits.start_watching()
        yield
        if watching:
            module.deposits.stop_watching()
        for event in (stop, money_stop):
            if event is not None:
                event.set()

    app = FastAPI(lifespan=lifespan, **SwaggerSetup.options(module.config.version,
                                                          enabled=module.config.docs_enabled))
    app.state.module = module
    # Wide open, so the dashboard works from any dev port and any deployed domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", ADMIN_HEADER],
    )
    HttpExceptionFilter.register(app)
    for controller in CONTROLLERS:
        app.include_router(controller.router)
    SwaggerSetup.install(app)
    return app
