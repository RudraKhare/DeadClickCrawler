# routes/api.py
from fastapi import APIRouter, Depends, HTTPException, Query
from services.test_service import TestService
from config.settings import Config
from typing import Optional

router = APIRouter()

# In-memory storage for last results (for demo; replace with DB/cache in prod)
last_results = None

def get_test_service():
    return TestService(Config)

@router.post('/run-test')
def run_test(
    url: Optional[str] = None,
    wait_time: int = Query(5, description="Seconds to wait after page load before scanning"),
    strictness: str = Query('normal', description="Detection strictness: normal, loose, strict"),
    service: TestService = Depends(get_test_service)
):
    global last_results
    try:
        last_results = service.run_and_report(url, wait_time=wait_time, strictness=strictness)
        return {"status": "success", "summary": last_results.get('summary', {}), "report": last_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/results')
def get_results():
    if last_results is None:
        raise HTTPException(status_code=404, detail="No results available. Run a test first.")
    return last_results

@router.get('/status')
def status():
    return {"status": "ok"} 