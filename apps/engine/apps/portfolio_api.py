"""Loopback-only portfolio research API. Run with uvicorn; no brokerage actions."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apps.research_api import router as research_router
from portfolio.custom import MarketDataError, PortfolioRequest, analyze_portfolio

app = FastAPI(title="Shprite Equity Lab", version="0.1.0")
app.include_router(research_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "research_only"}


@app.post("/api/portfolio/analyze")
def analyze(request: PortfolioRequest) -> dict:
    try:
        return analyze_portfolio(request)
    except MarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
