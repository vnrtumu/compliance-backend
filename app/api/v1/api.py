from fastapi import APIRouter
from app.api.v1.endpoints import users, uploads, invoices

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
