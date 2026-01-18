from fastapi import APIRouter
from app.api.v1.endpoints import users, uploads, invoices, extraction, extraction_stream, validation_checklist, validation, validation_stream, resolver, reporter, settings

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
api_router.include_router(extraction.router, prefix="/extraction", tags=["extraction"])
api_router.include_router(extraction_stream.router, prefix="/extraction", tags=["extraction-stream"])
api_router.include_router(validation_checklist.router, prefix="/validation-checklist", tags=["validation-checklist"])
api_router.include_router(validation.router, prefix="/validation", tags=["validation"])
api_router.include_router(validation_stream.router, prefix="/validation", tags=["validation-stream"])
api_router.include_router(resolver.router, prefix="/resolver", tags=["resolver"])
api_router.include_router(reporter.router, prefix="/reporter", tags=["reporter"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])






