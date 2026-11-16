"""v1 运行时契约。详见同目录 README.md；校验不授予权限。"""
from .core import (
    VERSION, ContractError, validate, validate_path, resolve_path,
    canonical_json, digest, bytes_digest, candidate_digest,
    validate_transition, bindings_match, load_schema,
)

__all__ = [
    'VERSION', 'ContractError', 'validate', 'validate_path', 'resolve_path',
    'canonical_json', 'digest', 'bytes_digest', 'candidate_digest',
    'validate_transition', 'bindings_match', 'load_schema',
]
