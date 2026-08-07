"""5.3 금융 정보 수집 API"""
from fastapi import APIRouter

from app.services import market_service

router = APIRouter()


@router.get("/deposits")
async def get_deposit_products():
    """예금 상품 목록"""
    return await market_service.fetch_deposit_products()


@router.get("/savings")
async def get_savings_products():
    """적금 상품 목록"""
    return await market_service.fetch_savings_products()


@router.get("/base-rate")
async def get_base_rate():
    """기준금리 조회"""
    return {"base_rate": await market_service.get_base_rate()}
