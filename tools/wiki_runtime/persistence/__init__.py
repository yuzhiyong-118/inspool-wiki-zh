"""Wiki 候选预览与覆盖校验的私有协议。"""
from .protocol import (
    candidate_preview_digest, compile_candidate, coverage_disposition_digest,
    coverage_spec_digest, parse_candidate_change, parse_candidate_preview,
    parse_coverage_disposition, parse_coverage_spec, validate_candidate_coverage,
    validate_final_coverage,
)

__all__ = [
    'candidate_preview_digest', 'compile_candidate', 'coverage_disposition_digest',
    'coverage_spec_digest', 'parse_candidate_change', 'parse_candidate_preview',
    'parse_coverage_disposition', 'parse_coverage_spec', 'validate_candidate_coverage',
    'validate_final_coverage',
]
