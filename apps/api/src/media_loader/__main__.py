import uvicorn

from .api import create_app
from .config import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        proxy_headers=False,
    )
