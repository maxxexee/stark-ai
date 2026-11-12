"""`python -m app` — the API on HOST:PORT (127.0.0.1:8000 by default)."""

from __future__ import annotations

import logging

import uvicorn

from app.common.logs import Logs
from app.main import create_app
from app.setup_swagger import SwaggerSetup

if __name__ == "__main__":
    Logs.setup()
    app = create_app()
    config = app.state.module.config
    logging.getLogger("stark").info("Stark API %s on http://%s:%s/",
                                    config.version, config.host, config.port)
    SwaggerSetup.announce(app, config.host, config.port)
    # `log_config=None`: uvicorn keeps the redacting handler `Logs.setup` installed.
    uvicorn.run(app, host=config.host, port=config.port, proxy_headers=True,
                log_config=None)
