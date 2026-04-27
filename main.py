from __future__ import annotations

import asyncio
import logging
import sys

from app import App


def setup_logging() -> None:
    import os
    import config

    # Check if DEBUG mode is enabled via environment variable
    debug_mode = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
    log_level = logging.DEBUG if debug_mode else logging.INFO

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if config.LOG_FILE:
        handlers.append(logging.FileHandler(config.LOG_FILE, encoding="utf-8"))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    if debug_mode:
        logging.info("DEBUG mode enabled - showing detailed logs")


async def main() -> None:
    setup_logging()
    try:
        app = App()
        await app.run()
    except Exception:
        logging.exception("Fatal error — bot crashed")
        raise


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
