from fastapi import APIRouter
from app.api.v1.endpoints import users, uploads, invoices, extraction, extraction_stream

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
api_router.include_router(extraction.router, prefix="/extraction", tags=["extraction"])
api_router.include_router(extraction_stream.router, prefix="/extraction", tags=["extraction-stream"])


