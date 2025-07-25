# main.py
import logging
import os
import sys
from services.test_service import TestService
from config.settings import Config

# --- FastAPI imports ---
from fastapi import FastAPI
from routes.api import router as api_router
import uvicorn

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s'
    )

def run_cli():
    service = TestService(Config)
    try:
        service.run_and_report()
    except KeyboardInterrupt:
        logging.warning('Test interrupted by user.')
    except Exception as e:
        logging.error(f'Test failed with error: {e}')

def run_api():
    app = FastAPI()
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Or specify ["http://localhost:3000"] for more security
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == '__main__':
    setup_logging()
    mode = os.getenv('MODE', 'api').lower()  # Default to API mode
    if len(sys.argv) > 1 and sys.argv[1] == 'cli':
        mode = 'cli'
    if mode == 'api':
        run_api()
    else:
        run_cli()

# Usage:
#   python main.py           # CLI mode (default)
#   python main.py api       # API server mode
#   MODE=api python main.py  # API server mode via env