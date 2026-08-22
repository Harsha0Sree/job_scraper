"""Source adapter registry — importing this module wires up all adapters."""
from .base import SourceAdapter, get_adapter, register_adapter
from .startups_gallery import StartupsGalleryAdapter
from .hnhiring import HnHiringAdapter
from .no_wb import NoWbAdapter
from .aijobs import AiJobsAdapter
from .wellfound import WellfoundAdapter
from .workatastartup import WorkAtAStartupAdapter
from .grepjob import GrepJobAdapter

__all__ = [
    "SourceAdapter", "get_adapter", "register_adapter",
    "StartupsGalleryAdapter", "HnHiringAdapter", "NoWbAdapter",
    "AiJobsAdapter", "WellfoundAdapter", "WorkAtAStartupAdapter",
    "GrepJobAdapter",
]
