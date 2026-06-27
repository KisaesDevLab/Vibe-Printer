from .jobs import router as jobs_router
from .print import router as print_router
from .printers import router as printers_router

__all__ = ["print_router", "printers_router", "jobs_router"]
