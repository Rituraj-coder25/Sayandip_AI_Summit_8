from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.post("/daily-brief")
async def generate_daily_brief(request: Request):
    from ..core.analyst.daily_brief import DailyBriefGenerator
    from ..database import AsyncSessionLocal

    generator = DailyBriefGenerator(request.app.state.redis, request.app.state.engine._llm)
    async with AsyncSessionLocal() as db:
        brief = await generator.generate(db)
        await db.commit()
    return {"id": brief.id, "date": brief.date, "content": brief.content}


@router.get("/daily-brief/latest")
async def get_latest_brief(request: Request):
    from sqlalchemy import desc, select

    from ..database import AsyncSessionLocal
    from ..models.daily_brief import DailyBrief

    async with AsyncSessionLocal() as db:
        query = select(DailyBrief).order_by(desc(DailyBrief.generated_at)).limit(1)
        result = await db.execute(query)
        brief = result.scalar_one_or_none()

    if not brief:
        return {"error": "No brief generated yet. POST /api/v1/reports/daily-brief to generate."}
    return {"id": brief.id, "date": brief.date, "content": brief.content, "generated_at": brief.generated_at.isoformat()}


@router.get("/daily-brief/{date}")
async def get_brief_by_date(date: str, request: Request):
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models.daily_brief import DailyBrief

    async with AsyncSessionLocal() as db:
        query = select(DailyBrief).where(DailyBrief.date == date)
        result = await db.execute(query)
        brief = result.scalar_one_or_none()

    if not brief:
        return {"error": f"No brief found for {date}"}
    return {"id": brief.id, "date": brief.date, "content": brief.content}


@router.get("/pdf")
async def get_report_pdf(request: Request, date: str | None = None):
    from sqlalchemy import desc, select

    from ..database import AsyncSessionLocal
    from ..models.daily_brief import DailyBrief

    async with AsyncSessionLocal() as db:
        query = select(DailyBrief).order_by(desc(DailyBrief.generated_at)).limit(1)
        if date:
            query = select(DailyBrief).where(DailyBrief.date == date).limit(1)
        result = await db.execute(query)
        brief = result.scalar_one_or_none()

    if not brief:
        return {"error": "No daily brief found"}
    return {
        "brief_id": brief.id,
        "date": brief.date,
        "content": brief.content,
        "sections": brief.sections or {},
        "format": "json",
        "message": "PDF generation hook is scaffolded; wire WeasyPrint rendering here for binary export.",
    }