"""XBRL parser + PIT loader for NSE Ind-AS results filings (Task T1.3).

Parses NSE Ind-AS XBRL (both the pre-2025 ``in-bse-fin`` taxonomy and the 2025+
``in-capmkt`` / ``in-capmkt-ent`` taxonomies) into canonical line items and loads
them into ``statements_xbrl`` / ``xbrl_filings`` with point-in-time law.

Doctrine (do not deviate):
  * Values are scaled to **crore** (Lakhs -> /100). The rounding tag is primary;
    a screener cross-check overrides it (``scale_inferred=True``) when the
    rounding-derived revenue is off by a factor that would otherwise plant a 100x
    error. We never silently accept a 100x mismatch.
  * PIT: ``visible_from = filing_dt`` (the DATE the filing was made public), never
    the fetch time.
  * First-seen wins: an existing primary row is NEVER overwritten. A differing
    later value is appended to ``statements_xbrl_revisions`` and flips
    ``xbrl_filings.revised = True``.
  * Unknown tags are stored raw (``item = NULL``) -- never dropped, never guessed.
  * Contexts are parsed from the actual ``<period>`` (start/end/instant); the
    ``One*`` / ``Four*`` id prefix is only a tie-breaker.

No network here: the parser works on bytes, the loader on a DuckDB connection.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import duckdb
from lxml import etree

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
NS_BSE_FIN = "http://www.bseindia.com/xbrl/fin/2018-03-31/in-bse-fin"
NS_CAPMKT = "http://www.sebi.gov.in/xbrl/2025-01-31/in-capmkt"
NS_CAPMKT_ENT = "http://www.sebi.gov.in/xbrl/2025-01-31/in-capmkt-ent"
NS_XBRLI = "http://www.xbrl.org/2003/instance"
NS_XBRLDI = "http://xbrl.org/2006/xbrldi"

# taxonomy fin-namespace URI -> short label (order matters: ent before capmkt)
_TAXONOMIES = [
    ("in-capmkt-ent", NS_CAPMKT_ENT),
    ("in-capmkt", NS_CAPMKT),
    ("in-bse-fin", NS_BSE_FIN),
]

# ---------------------------------------------------------------------------
# Rounding -> multiplier to crore (1 crore = 1e7 INR)
# ---------------------------------------------------------------------------
#   Lakhs    : 1 lakh   = 1e5 INR -> /100 to crore  -> 0.01
#   Crores   : 1 crore  = 1e7 INR ->                -> 1.0
#   Millions : 1e6 INR                              -> 0.1
#   Thousands: 1e3 INR                              -> 1e-4
#   Absolute : 1 INR                                -> 1e-7
_ROUNDING_SCALE = {
    "lakhs": 0.01,
    "lakh": 0.01,
    "crores": 1.0,
    "crore": 1.0,
    "millions": 0.1,
    "million": 0.1,
    "thousands": 1e-4,
    "thousand": 1e-4,
    "absolute": 1e-7,
    "units": 1e-7,
    "unit": 1e-7,
    "actuals": 1e-7,
}
_CANDIDATE_SCALES = [0.01, 1.0, 0.1, 1e-4, 1e-7]
_SCALE_TOL = 0.20  # relative disagreement above which we override the rounding tag


# ---------------------------------------------------------------------------
# Canonical tag map  (MODULE-LEVEL DATA, not code -- grows without touching logic)
# ---------------------------------------------------------------------------
# XBRL localname -> canonical item. Multiple XBRL tags may map to one item; the
# stable P&L localnames are shared across in-bse-fin and in-capmkt.
CANONICAL_MAP: dict[str, str] = {
    # --- P&L (present in quarterly + annual) ---
    "RevenueFromOperations": "revenue",
    "RevenueFromOperationsGross": "revenue",
    "TotalRevenueFromOperations": "revenue",
    "IncomeFromOperations": "revenue",
    "OtherIncome": "other_income",
    "TotalIncome": "total_income",
    "Income": "total_income",
    "CostOfMaterialsConsumed": "cost_of_materials",
    "PurchasesOfStockInTrade": "purchases",
    "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade": "inventory_change",
    "EmployeeBenefitExpense": "employee_cost",
    "EmployeeBenefitsExpense": "employee_cost",
    "FinanceCosts": "finance_cost",
    "DepreciationAndAmortisationExpense": "depreciation",
    "DepreciationDepletionAndAmortisationExpense": "depreciation",
    "OtherExpenses": "other_expenses",
    "TotalExpenses": "total_expenses",
    "ProfitBeforeExceptionalItemsAndTax": "pbt_before_exceptional",
    "ProfitBeforeTax": "pbt",
    "TaxExpense": "tax",
    "TotalTaxExpense": "tax",
    "CurrentTax": "current_tax",
    "ProfitLoss": "pat",
    "ProfitAfterTax": "pat",
    "ProfitLossForPeriod": "pat",
    "BasicEarningsPerShare": "eps_basic",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_basic",
    "DilutedEarningsPerShare": "eps_diluted",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_diluted",
    # --- Balance sheet ---
    "ShareCapital": "equity_capital",
    "EquityShareCapital": "equity_capital",
    "PaidUpValueOfEquityShareCapital": "equity_capital",
    "Reserves": "reserves",
    "ReservesAndSurplus": "reserves",
    "OtherEquity": "reserves",
    "Inventories": "inventories",
    "TradeReceivables": "trade_receivables",
    "TradeReceivablesCurrent": "trade_receivables",
    "CashAndCashEquivalents": "cash",
    "CashAndBankBalances": "cash",
    "CurrentAssets": "current_assets",
    "TotalCurrentAssets": "current_assets",
    "Assets": "total_assets",
    "TotalAssets": "total_assets",
    "Goodwill": "goodwill",
    "CapitalWorkInProgress": "cwip",
    "PropertyPlantAndEquipment": "gross_block",
    "GrossBlock": "gross_block",
    "Borrowings": "borrowings",
    "BorrowingsCurrent": "borrowings_current",
    "CurrentBorrowings": "borrowings_current",
    "BorrowingsNoncurrent": "borrowings_noncurrent",
    "NoncurrentBorrowings": "borrowings_noncurrent",
    "LongTermBorrowings": "borrowings_noncurrent",
    # --- Cash flow ---
    "CashFlowsFromUsedInOperatingActivities": "cfo",
    "NetCashFlowsFromUsedInOperatingActivities": "cfo",
    "CashFlowsFromUsedInInvestingActivities": "cfi",
    "NetCashFlowsFromUsedInInvestingActivities": "cfi",
    "CashFlowsFromUsedInFinancingActivities": "cff",
    "NetCashFlowsFromUsedInFinancingActivities": "cff",
    # --- Auditor / governance (annual) ---
    "AuditorsFirmName": "auditor_name",
    "NameOfTheAuditor": "auditor_name",
    "NameOfAuditFirm": "auditor_name",
    "TypeOfAuditQualification": "auditor_opinion",
    "AuditorsOpinion": "auditor_opinion",
    "AuditQualification": "auditor_opinion",
    "TypeOfReviewObservation": "auditor_opinion",
    # --- Segments (dimensioned) ---
    "SegmentRevenue": "segment_revenue",
    "RevenueFromOperationsSegment": "segment_revenue",
    "SegmentResult": "segment_result",
    "SegmentAssets": "segment_assets",
}

# Bank / NBFC KPIs -- mapped ONLY when the filing is a bank (in-capmkt-ent or
# bank tags present). Kept separate so a non-bank tag collision can't leak these.
BANK_MAP: dict[str, str] = {
    "CET1Ratio": "cet1",
    "CommonEquityTier1CapitalRatio": "cet1",
    "CommonEquityTierOneCapitalRatio": "cet1",
    "CapitalAdequacyRatio": "car",
    "GrossNonPerformingAssets": "gnpa",
    "GrossNPA": "gnpa",
    "PercentageOfGrossNPA": "gnpa_pct",
    "NetNonPerformingAssets": "nnpa",
    "NetNPA": "nnpa",
    "PercentageOfNetNPA": "nnpa_pct",
    "ReturnOnAssets": "roa",
    "Advances": "advances",
    "GrossAdvances": "advances",
    "Deposits": "deposits",
    "TotalDeposits": "deposits",
    "ProvisionsAndContingencies": "provisions",
    "Provisions": "provisions",
    "InterestEarned": "interest_earned",
    "InterestIncome": "interest_earned",
}

# Tags whose presence alone marks a filing as a bank/NBFC.
_BANK_MARKERS = {"CET1Ratio", "CommonEquityTier1CapitalRatio", "GrossNonPerformingAssets",
                 "GrossNPA", "NetNonPerformingAssets", "Advances", "Deposits", "InterestEarned"}


def canonical_item(tag: str, is_bank: bool) -> Optional[str]:
    """Map an XBRL localname to a canonical item name. Returns None for unmapped
    tags (they are still stored raw with ``item = NULL``). Bank-specific tags map
    only when ``is_bank``."""
    if is_bank and tag in BANK_MAP:
        return BANK_MAP[tag]
    return CANONICAL_MAP.get(tag)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Context:
    id: str
    period_start: Optional[date]
    period_end: Optional[date]
    instant: Optional[date]
    kind: str            # 'D' (duration) | 'I' (instant)
    dims_key: str = ""


@dataclass
class Fact:
    tag: str             # localname
    context_ref: str
    raw: str             # raw lexical value/text as it appears in the XML
    value: Optional[float]   # parsed float when numeric, else None
    unit: str            # normalised label: 'INR' | 'INR/shares' | 'pure' | 'shares' | ''
    dims_key: str = ""

    @property
    def is_monetary(self) -> bool:
        return self.unit == "INR"


@dataclass
class ParsedXbrl:
    taxonomy: str
    is_bank: bool
    rounding: str
    basis: str                       # 'C' | 'S'
    facts: list[Fact] = field(default_factory=list)
    contexts: dict[str, Context] = field(default_factory=dict)

    def context(self, ref: str) -> Optional[Context]:
        return self.contexts.get(ref)


# ---------------------------------------------------------------------------
# Period classification
# ---------------------------------------------------------------------------
def period_kind(start: Optional[date], end: Optional[date]) -> str:
    """Classify a duration by its day-span: Q (~3mo), H (~6mo), 9M (~9mo),
    FY (~12mo). An instant (missing start or end) is 'I'."""
    if start is None or end is None:
        return "I"
    days = (end - start).days
    if days <= 115:
        return "Q"
    if days <= 210:
        return "H"
    if days <= 305:
        return "9M"
    return "FY"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _localname(qname_or_tag: str) -> str:
    """Localname from a '{uri}name' clark tag or a 'prefix:name' QName."""
    if qname_or_tag.startswith("{"):
        return qname_or_tag.split("}", 1)[1]
    if ":" in qname_or_tag:
        return qname_or_tag.split(":", 1)[1]
    return qname_or_tag


def _parse_date(txt: Optional[str]) -> Optional[date]:
    if not txt:
        return None
    try:
        return datetime.strptime(txt.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _dims_key_from_context(ctx_el) -> str:
    """Stable key from sorted (dimension, member) localname pairs on the context.
    Non-dimensioned contexts return ''."""
    pairs = []
    for member in ctx_el.iter(f"{{{NS_XBRLDI}}}explicitMember"):
        dim = _localname(member.get("dimension", ""))
        mem = _localname((member.text or "").strip())
        if dim:
            pairs.append(f"{dim}={mem}")
    return "|".join(sorted(pairs))


def _detect_taxonomy(root) -> tuple[str, str]:
    """Return (label, fin_namespace_uri). Prefers the most specific present."""
    uris = set(root.nsmap.values())
    # also union descendant namespaces (root nsmap usually holds them all)
    for label, uri in _TAXONOMIES:
        if uri in uris:
            return label, uri
    # fall back: sniff any element namespace matching a known taxonomy
    for el in root.iter():
        ns = etree.QName(el).namespace if isinstance(el.tag, str) else None
        for label, uri in _TAXONOMIES:
            if ns == uri:
                return label, uri
    return "unknown", ""


def _norm_unit(unit_el) -> str:
    """Normalise a <unit> definition to a label."""
    divide = unit_el.find(f"{{{NS_XBRLI}}}divide")
    if divide is not None:
        return "INR/shares"
    measure_el = unit_el.find(f"{{{NS_XBRLI}}}measure")
    measure = (measure_el.text or "").strip() if measure_el is not None else ""
    ml = _localname(measure).lower()
    if ml == "inr":
        return "INR"
    if ml == "pure":
        return "pure"
    if ml == "shares":
        return "shares"
    return measure or ""


def parse_xbrl(content: bytes) -> ParsedXbrl:
    """Parse XBRL bytes into a ParsedXbrl. Stores ALL facts raw -- an
    unrecognised tag is kept, never dropped."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser=parser)

    taxonomy, fin_ns = _detect_taxonomy(root)

    # --- contexts ---
    contexts: dict[str, Context] = {}
    for ctx in root.iter(f"{{{NS_XBRLI}}}context"):
        cid = ctx.get("id")
        if not cid:
            continue
        period = ctx.find(f"{{{NS_XBRLI}}}period")
        start = end = instant = None
        kind = "D"
        if period is not None:
            inst_el = period.find(f"{{{NS_XBRLI}}}instant")
            if inst_el is not None:
                instant = _parse_date(inst_el.text)
                kind = "I"
            else:
                start = _parse_date(period.findtext(f"{{{NS_XBRLI}}}startDate"))
                end = _parse_date(period.findtext(f"{{{NS_XBRLI}}}endDate"))
                kind = "I" if (start is None and end is None) else "D"
        contexts[cid] = Context(id=cid, period_start=start, period_end=end,
                                instant=instant, kind=kind,
                                dims_key=_dims_key_from_context(ctx))

    # --- units ---
    units: dict[str, str] = {}
    for unit in root.iter(f"{{{NS_XBRLI}}}unit"):
        uid = unit.get("id")
        if uid:
            units[uid] = _norm_unit(unit)

    # --- facts: every element in the taxonomy namespace with a contextRef ---
    facts: list[Fact] = []
    basis = ""
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        qn = etree.QName(el)
        if fin_ns and qn.namespace != fin_ns:
            continue
        ctx_ref = el.get("contextRef")
        if ctx_ref is None:
            continue
        tag = qn.localname
        raw = (el.text or "").strip()
        unit = units.get(el.get("unitRef", ""), "")
        value = _to_float(raw)
        ctx = contexts.get(ctx_ref)
        dims = ctx.dims_key if ctx else ""
        facts.append(Fact(tag=tag, context_ref=ctx_ref, raw=raw, value=value,
                          unit=unit, dims_key=dims))
        # basis detection from the nature-of-report tag
        if not basis and "standaloneconsolidated" in tag.lower():
            basis = _basis_from_text(raw)

    if not basis:
        basis = "S"

    localnames = {f.tag for f in facts}
    is_bank = taxonomy == "in-capmkt-ent" or bool(localnames & _BANK_MARKERS)

    rounding = _find_rounding(facts)
    return ParsedXbrl(taxonomy=taxonomy, is_bank=is_bank, rounding=rounding,
                      basis=basis, facts=facts, contexts=contexts)


def _to_float(raw: str) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _basis_from_text(txt: str) -> str:
    t = (txt or "").strip().lower()
    if t.startswith("cons"):
        return "C"
    if t.startswith("stand"):
        return "S"
    return ""


def _find_rounding(facts: list[Fact]) -> str:
    for f in facts:
        if f.tag in ("LevelOfRoundingUsedInFinancialStatements", "LevelOfRounding"):
            return f.raw
    return ""


# ---------------------------------------------------------------------------
# Auditor convenience readers (annual filings)
# ---------------------------------------------------------------------------
def auditor_name(parsed: ParsedXbrl) -> Optional[str]:
    for f in parsed.facts:
        if canonical_item(f.tag, parsed.is_bank) == "auditor_name" and f.raw:
            return f.raw
    return None


def auditor_opinion(parsed: ParsedXbrl) -> tuple[Optional[str], Optional[bool]]:
    """Return (opinion_text, modified). ``modified`` is True for a qualified/
    adverse/disclaimer opinion, False for an unmodified/unqualified one, None when
    no opinion tag is present."""
    for f in parsed.facts:
        if canonical_item(f.tag, parsed.is_bank) == "auditor_opinion" and f.raw:
            t = f.raw.lower()
            if any(w in t for w in ("unmodified", "unqualified", "clean")):
                return f.raw, False
            if any(w in t for w in ("qualified", "adverse", "disclaimer", "modified")):
                return f.raw, True
            return f.raw, None
    return None, None


# ---------------------------------------------------------------------------
# Scale inference (rounding tag primary, screener cross-check as anchor)
# ---------------------------------------------------------------------------
def _base_scale(rounding: str) -> float:
    return _ROUNDING_SCALE.get((rounding or "").strip().lower(), 0.01)


def _raw_revenue(parsed: ParsedXbrl) -> tuple[Optional[float], Optional[date]]:
    """Largest revenue fact (gross) and its context period_end -- the anchor for
    the screener cross-check."""
    best_v, best_end = None, None
    for f in parsed.facts:
        if canonical_item(f.tag, parsed.is_bank) != "revenue":
            continue
        if not f.is_monetary or f.value is None:
            continue
        if best_v is None or f.value > best_v:
            best_v = f.value
            ctx = parsed.context(f.context_ref)
            best_end = (ctx.period_end or ctx.instant) if ctx else None
    return best_v, best_end


def _screener_sales(con, symbol: str, period_end: Optional[date]) -> Optional[float]:
    """Screener revenue (crore) for a symbol/period from the long `statements`
    table. Prefers the annual P&L; matches the period_end when known."""
    where = ["symbol = ?", "line_item IN ('sales', 'revenue')"]
    params: list = [symbol]
    if period_end is not None:
        where.append("period_end = ?")
        params.append(period_end)
    sql = ("SELECT value FROM statements WHERE " + " AND ".join(where) +
           " ORDER BY CASE stmt WHEN 'pl_a' THEN 0 WHEN 'pl_q' THEN 1 ELSE 2 END LIMIT 1")
    try:
        row = con.execute(sql, params).fetchone()
    except duckdb.Error:
        return None
    return float(row[0]) if row and row[0] is not None else None


def infer_scale(con, symbol: str, parsed: ParsedXbrl) -> tuple[float, bool]:
    """Return (scale_to_cr, inferred). Primary = rounding tag. Cross-check the
    rounding-derived revenue against screener sales for the same period; if it is
    off by more than ~20%, fall back to the candidate scale that makes them agree
    and set inferred=True. Never silently accept a 100x mismatch."""
    base = _base_scale(parsed.rounding)
    raw_rev, rev_end = _raw_revenue(parsed)
    if raw_rev is None or raw_rev == 0:
        return base, False
    screener = _screener_sales(con, symbol, rev_end)
    if screener is None or screener <= 0:
        return base, False
    base_err = abs(raw_rev * base - screener) / screener
    if base_err <= _SCALE_TOL:
        return base, False
    # rounding tag disagrees -> pick the candidate scale that best matches screener
    best_scale, best_err = base, base_err
    for cand in _CANDIDATE_SCALES:
        err = abs(raw_rev * cand - screener) / screener
        if err < best_err:
            best_err, best_scale = err, cand
    if best_scale != base and best_err <= _SCALE_TOL:
        return best_scale, True
    # nothing agrees within tolerance: keep the rounding-derived scale, but do not
    # claim it was inferred.
    return base, False


# ---------------------------------------------------------------------------
# Loading  (PIT + first-seen-wins + revision logging)
# ---------------------------------------------------------------------------
def _filing_period_end(parsed: ParsedXbrl) -> Optional[date]:
    """The filing's primary reporting period end: latest duration end, else
    latest instant."""
    ends = [c.period_end for c in parsed.contexts.values() if c.kind == "D" and c.period_end]
    if ends:
        return max(ends)
    instants = [c.instant for c in parsed.contexts.values() if c.instant]
    return max(instants) if instants else None


def _values_differ(a: Optional[float], b: Optional[float],
                   ta: Optional[str], tb: Optional[str]) -> bool:
    if a is not None and b is not None:
        denom = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / denom > 1e-9
    if a is not None or b is not None:
        return True
    return (ta or "") != (tb or "")


def load_parsed_xbrl(con: duckdb.DuckDBPyConnection, symbol: str, parsed: ParsedXbrl,
                     filing_dt, source_url: str) -> dict:
    """Write canonical + raw facts into ``statements_xbrl`` (scaled to crore) and
    a row into ``xbrl_filings``. First-seen wins; differing later values append to
    ``statements_xbrl_revisions`` and flip ``xbrl_filings.revised``."""
    fdt = filing_dt.date() if isinstance(filing_dt, datetime) else filing_dt
    visible_from = fdt
    as_of = fdt
    fetched_at = datetime.now()
    filing_ts = filing_dt if isinstance(filing_dt, datetime) else datetime(fdt.year, fdt.month, fdt.day)

    scale_to_cr, scale_inferred = infer_scale(con, symbol, parsed)
    basis = parsed.basis

    n_canonical = n_raw = n_written = n_revisions = 0
    revised = False

    # The primary-key grain is (symbol, basis, period_end, kind, tag, dims_key) --
    # it does NOT include the period span, so a filing's current-period context and
    # its YTD/cumulative context (both duration, same end date) collide on one row.
    # Keep the SHORTEST-span duration (the as-reported figure for the period); the
    # YTD is redundant and derivable. Without this, the YTD fact would look like a
    # spurious "revision" of the current-period fact.
    chosen: dict[tuple, tuple] = {}   # pk_key -> (span_days, Fact, ctx)
    for f in parsed.facts:
        ctx = parsed.context(f.context_ref)
        if ctx is None:
            continue
        p_end = ctx.period_end if ctx.kind == "D" else ctx.instant
        if p_end is None:
            continue
        key = (basis, p_end, ctx.kind, f.tag, f.dims_key)
        if ctx.kind == "D" and ctx.period_start is not None:
            span = (p_end - ctx.period_start).days
        else:
            span = 0
        prior = chosen.get(key)
        if prior is None or span < prior[0]:
            chosen[key] = (span, f, ctx)

    for _key, (_span, f, ctx) in chosen.items():
        kind = ctx.kind
        p_end = ctx.period_end if kind == "D" else ctx.instant
        p_start = ctx.period_start if kind == "D" else None
        pk = period_kind(p_start, p_end) if kind == "D" else "I"
        item = canonical_item(f.tag, parsed.is_bank)

        # scale only pure monetary INR amounts; ratios/per-share/shares/text untouched
        if f.value is not None and f.is_monetary:
            value = f.value * scale_to_cr
            text_value = None
        elif f.value is not None:
            value = f.value
            text_value = None
        else:
            value = None
            text_value = f.raw or None

        if item:
            n_canonical += 1
        else:
            n_raw += 1

        existing = con.execute(
            "SELECT value, text_value FROM statements_xbrl WHERE symbol=? AND basis=? "
            "AND period_end=? AND kind=? AND tag=? AND dims_key=?",
            [symbol, basis, p_end, kind, f.tag, f.dims_key]).fetchone()

        if existing is None:
            con.execute(
                "INSERT INTO statements_xbrl (symbol, basis, period_end, period_start, kind, "
                "period_kind, tag, item, dims_key, value, text_value, unit, taxonomy, "
                "filing_dt, fetched_at, as_of, visible_from) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [symbol, basis, p_end, p_start, kind, pk, f.tag, item, f.dims_key,
                 value, text_value, f.unit, parsed.taxonomy, filing_ts, fetched_at,
                 as_of, visible_from])
            n_written += 1
        elif _values_differ(existing[0], value, existing[1], text_value):
            # first-seen wins: DO NOT overwrite the primary row. Append a revision
            # unless this exact value was already logged.
            dup = con.execute(
                "SELECT 1 FROM statements_xbrl_revisions WHERE symbol=? AND basis=? "
                "AND period_end=? AND kind=? AND tag=? AND dims_key=? "
                "AND ((value IS NULL AND ? IS NULL) OR value = ?) "
                "AND ((text_value IS NULL AND ? IS NULL) OR text_value = ?)",
                [symbol, basis, p_end, kind, f.tag, f.dims_key,
                 value, value, text_value, text_value]).fetchone()
            if dup is None:
                con.execute(
                    "INSERT INTO statements_xbrl_revisions (symbol, basis, period_end, kind, "
                    "tag, dims_key, value, text_value, filing_dt, fetched_at, source_url) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [symbol, basis, p_end, kind, f.tag, f.dims_key, value, text_value,
                     filing_ts, fetched_at, source_url])
                n_revisions += 1
                revised = True

    period_end = _filing_period_end(parsed)
    # re-derive sha/bytes cheaply is not possible here (no bytes); leave to caller.
    con.execute(
        "INSERT OR REPLACE INTO xbrl_filings (symbol, period_end, basis, xbrl_url, filing_dt, "
        "taxonomy, status, facts, rounding, scale_to_cr, scale_inferred, is_bank, revised, "
        "seq_id, sha256, bytes, fetched_at, error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [symbol, period_end, basis, source_url, filing_ts, parsed.taxonomy, "ok",
         len(parsed.facts), parsed.rounding, scale_to_cr, scale_inferred, parsed.is_bank,
         revised, None, None, None, fetched_at, None])

    return {
        "symbol": symbol,
        "basis": basis,
        "period_end": period_end,
        "facts": len(parsed.facts),
        "canonical": n_canonical,
        "raw": n_raw,
        "written": n_written,
        "revisions": n_revisions,
        "revised": revised,
        "scale_to_cr": scale_to_cr,
        "scale_inferred": scale_inferred,
        "is_bank": parsed.is_bank,
        "taxonomy": parsed.taxonomy,
    }


# ---------------------------------------------------------------------------
# PIT reader
# ---------------------------------------------------------------------------
def canonical_wide(con: duckdb.DuckDBPyConnection, symbol: str, as_of) -> dict:
    """Latest-visible canonical items for a symbol as of a date. Returns a dict
    keyed by period_kind (Q/H/9M/FY/I); each value is a dict of canonical item ->
    value for the MOST RECENT period_end of that kind (visible_from <= as_of),
    plus a ``period_end`` marker. Consolidated ('C') wins over standalone ('S')."""
    rows = con.execute(
        "SELECT period_kind, period_end, basis, item, value, text_value "
        "FROM statements_xbrl "
        "WHERE symbol = ? AND visible_from <= ? AND item IS NOT NULL",
        [symbol, as_of]).fetchall()

    # most recent period_end per kind
    latest: dict[str, date] = {}
    for pk, p_end, *_ in rows:
        if p_end is None:
            continue
        if pk not in latest or p_end > latest[pk]:
            latest[pk] = p_end

    out: dict[str, dict] = {}
    # basis rank: consolidated preferred
    def rank(b: str) -> int:
        return 0 if b == "C" else 1

    chosen: dict[tuple, tuple] = {}  # (pk, item) -> (rank, value/text)
    for pk, p_end, basis, item, value, text_value in rows:
        if p_end is None or latest.get(pk) != p_end:
            continue
        key = (pk, item)
        val = value if value is not None else text_value
        r = rank(basis)
        if key not in chosen or r < chosen[key][0]:
            chosen[key] = (r, val)

    for (pk, item), (_, val) in chosen.items():
        out.setdefault(pk, {"period_end": latest[pk]})[item] = val
    return out
