from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import SavedSession
from app.schemas.schemas import SavedSessionOut

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=list[SavedSessionOut])
async def get_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SavedSession).order_by(SavedSession.created_at.desc()).limit(50)
    )
    sessions = result.scalars().all()

    return [
        SavedSessionOut(
            id=str(s.id),
            title=s.title,
            resultId=str(s.result_id),
            createdAt=s.created_at,
        )
        for s in sessions
    ]


@router.delete("/history/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SavedSession).where(SavedSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    await db.delete(session)
    await db.commit()
    return {"ok": True}
