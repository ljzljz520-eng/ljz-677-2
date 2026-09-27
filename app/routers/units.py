"""缴费单位管理 API"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Unit

router = APIRouter(tags=["units"])


class UnitCreate(BaseModel):
    unit_code: str = Field(min_length=1, max_length=32)
    unit_name: str = Field(min_length=1, max_length=128)


def unit_to_dict(u: Unit) -> dict:
    return {"id": u.id, "unit_code": u.unit_code, "unit_name": u.unit_name}


@router.get("/units")
def list_units(db: Session = Depends(get_db)):
    units = db.query(Unit).order_by(Unit.unit_code).all()
    return {"total": len(units), "items": [unit_to_dict(u) for u in units]}


@router.post("/units", status_code=201)
def create_unit(body: UnitCreate, db: Session = Depends(get_db)):
    code = body.unit_code.strip()
    if db.query(Unit).filter(Unit.unit_code == code).first():
        raise HTTPException(409, f"单位编号已存在：{code}")
    unit = Unit(unit_code=code, unit_name=body.unit_name.strip())
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit_to_dict(unit)


@router.delete("/units/{unit_id}")
def delete_unit(unit_id: int, db: Session = Depends(get_db)):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(404, "单位不存在")
    db.delete(unit)
    db.commit()
    return {"ok": True}
