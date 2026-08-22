"""ATS parser registry — importing this module wires up all parsers."""
from .base import ATSParser, JobDetail, get_parser_for_url
from .greenhouse import GreenhouseParser
from .ashby import AshbyParser
from .lever import LeverParser
from .aijobs_detail import AiJobsDetailParser
from .workatastartup_detail import WorkAtAStartupDetailParser
from .generic import GenericParser

__all__ = [
    "ATSParser", "JobDetail", "get_parser_for_url",
    "GreenhouseParser", "AshbyParser", "LeverParser",
    "AiJobsDetailParser", "WorkAtAStartupDetailParser", "GenericParser",
]
