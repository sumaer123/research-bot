"""FastAPI app: light-theme dashboard + read-only advisor API."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ...config import settings
from .. import queries as q
from ..md import render as md_render
from ..report import decision_onepager_md

app = FastAPI(title="eqr", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def db():
    try:
        con = q.open_ro()
    except duckdb.IOException as e:
        raise HTTPException(503, f"database busy (a refresh is writing): {e}")
    try:
        yield con
    finally:
        con.close()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, con=Depends(db)):
    from ...validate.claims import claim_state
    sleeves = [(sl, q.latest_ranks(con, sl), q.rank_changes(con, sl)) for sl in ("L", "S")]
    claims = {sl: {"state": (st := claim_state(con, sl))[0].value, "reasons": st[1]} for sl in ("L", "S")}
    return templates.TemplateResponse(request, "dashboard.html", {
        "regime": q.regime_now(con), "fr": q.freshness(con), "bts": q.backtests(con),
        "sleeves": sleeves, "claims": claims})


@app.get("/ranks", response_class=HTMLResponse)
def ranks(request: Request, sleeve: str = "L", as_of: Optional[str] = None, con=Depends(db)):
    d = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else None
    tbl = q.latest_ranks(con, sleeve.upper(), d, held_only=False)
    dates = [r[0] for r in con.execute("SELECT DISTINCT as_of FROM ranks WHERE sleeve = ? ORDER BY as_of DESC LIMIT 12", [sleeve.upper()]).fetchall()]
    return templates.TemplateResponse(request, "ranks.html", {"sleeve": sleeve.upper(), "tbl": tbl, "dates": dates})


@app.get("/symbol")
def symbol_redirect(s: str = Query(...)):
    return RedirectResponse(f"/symbol/{s.strip().upper()}")


@app.get("/symbol/{symbol}", response_class=HTMLResponse)
def symbol(request: Request, symbol: str, con=Depends(db)):
    p = q.symbol_page(con, symbol.upper())
    if not p["inst"] and p["px"].empty:
        raise HTTPException(404, f"unknown symbol {symbol}")
    return templates.TemplateResponse(request, "symbol.html", {
        "p": p, "svg": q.price_svg(p["px"], p["factors"]),
        "dossier_html": md_render(p["dossier"]["markdown"]) if p["dossier"] else ""})


@app.get("/decision/{symbol}.md")
def decision_markdown(symbol: str, con=Depends(db)):
    rating = q.latest_rating(con, symbol.upper())
    if not rating:
        raise HTTPException(404, f"no rating for {symbol}")
    # Get instrument name
    inst = con.execute("SELECT name FROM instruments WHERE symbol = ?", [symbol.upper()]).fetchone()
    name = inst[0] if inst else "?"
    # Get features for timing data
    feat = con.execute("SELECT mom_12_1, dist_52w_high, dma200_ratio FROM features WHERE symbol = ? ORDER BY as_of DESC LIMIT 1",
                       [symbol.upper()]).fetchone()
    feat_dict = {"mom_12_1": feat[0], "dist_52w_high": feat[1], "dma200_ratio": feat[2]} if feat else {}

    rating["name"] = name
    md_text = decision_onepager_md(rating, feat=feat_dict)
    return HTMLResponse(content=md_text, media_type="text/markdown")


@app.get("/decision/{symbol}", response_class=HTMLResponse)
def decision(request: Request, symbol: str, con=Depends(db)):
    rating = q.latest_rating(con, symbol.upper())
    if not rating:
        raise HTTPException(404, f"no rating for {symbol}")
    # Get instrument name
    inst = con.execute("SELECT name FROM instruments WHERE symbol = ?", [symbol.upper()]).fetchone()
    name = inst[0] if inst else "?"
    # Get features for timing data
    feat = con.execute("SELECT mom_12_1, dist_52w_high, dma200_ratio FROM features WHERE symbol = ? ORDER BY as_of DESC LIMIT 1",
                       [symbol.upper()]).fetchone()
    feat_dict = {"mom_12_1": feat[0], "dist_52w_high": feat[1], "dma200_ratio": feat[2]} if feat else {}

    rating["name"] = name
    md_text = decision_onepager_md(rating, feat=feat_dict)
    html_body = md_render(md_text)
    return templates.TemplateResponse(request, "report.html", {"run_id": symbol.upper(), "body": html_body})


@app.get("/ratings", response_class=HTMLResponse)
def ratings(request: Request, as_of: Optional[str] = None, verdict: Optional[str] = None,
            profile: Optional[str] = None, con=Depends(db)):
    as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else None
    tbl = q.ratings_table(con, as_of_date, verdict=verdict, profile=profile)
    # Get list of available as_of dates
    dates = [r[0] for r in con.execute("SELECT DISTINCT as_of FROM ratings ORDER BY as_of DESC LIMIT 20").fetchall()]
    return templates.TemplateResponse(request, "ratings.html", {
        "tbl": tbl, "as_of_list": dates})


@app.get("/ratings.csv")
def ratings_csv(as_of: Optional[str] = None, verdict: Optional[str] = None,
                profile: Optional[str] = None, con=Depends(db)):
    as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else None
    tbl = q.ratings_table(con, as_of_date, verdict=verdict, profile=profile)
    if tbl.empty:
        raise HTTPException(404, "no ratings found")
    output = io.StringIO()
    tbl.to_csv(output, index=False)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ratings.csv"})


@app.get("/backtests", response_class=HTMLResponse)
def backtests(request: Request, con=Depends(db)):
    return templates.TemplateResponse(request, "backtests.html", {"bts": q.backtests(con)})


@app.get("/backtests/{run_id}", response_class=HTMLResponse)
def backtest_report(request: Request, run_id: str, con=Depends(db)):
    row = con.execute("SELECT report_path FROM backtests WHERE run_id = ?", [run_id]).fetchone()
    if not row:
        raise HTTPException(404, "unknown run")
    p = Path(row[0]) / "report.md"
    body = md_render(p.read_text()) if p.exists() else "<p>report file missing</p>"
    return templates.TemplateResponse(request, "report.html", {"run_id": run_id, "body": body})


@app.get("/health")
def health(con=Depends(db)):
    fr = q.freshness(con)
    fails = fr["quality"][fr["quality"].status == "FAIL"].check_name.tolist() if len(fr["quality"]) else []
    return {"status": "ok" if (fr["session_age_days"] is not None and fr["session_age_days"] <= 4 and not fails) else "degraded",
            "last_session": str(fr["last_session"]), "session_age_days": fr["session_age_days"],
            "last_features": str(fr["last_features"]), "quality_failures": fails, "version": "0.1.0"}


def _auth(request: Request) -> None:
    token = settings().advisor_token
    if not token:
        raise HTTPException(503, "advisor API disabled: EQR_ADVISOR_TOKEN not set")
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(401, "bad token")


@app.get("/advisor/v1/evidence/{symbol}")
def advisor(symbol: str, request: Request, con=Depends(db)):
    _auth(request)
    return JSONResponse(json.loads(json.dumps(q.advisor_evidence(con, symbol.upper()), default=str)))


@app.get("/advisor/v1/ranks/{sleeve}")
def advisor_ranks(sleeve: str, request: Request, con=Depends(db)):
    _auth(request)
    tbl = q.latest_ranks(con, sleeve.upper(), held_only=False)
    if tbl.empty:
        return {"sleeve": sleeve.upper(), "as_of": None, "ranks": []}
    return json.loads(json.dumps({"sleeve": sleeve.upper(), "as_of": str(tbl.as_of.iloc[0].date()), "regime": tbl.regime.iloc[0],
                                  "ranks": tbl[["rank", "symbol", "score", "weight"]].to_dict("records")}, default=str))
