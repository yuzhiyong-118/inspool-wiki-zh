"""只读候选叠加视图；路径检查不是操作系统权限隔离。"""
from .view import CandidateError, CandidateView

__all__ = ['CandidateError', 'CandidateView']
