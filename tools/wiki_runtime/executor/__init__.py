"""统一可恢复写入；可信 host 必须保护回调、执行器和 journal。"""
from .core import Executor, ExecutionError

__all__ = ['Executor', 'ExecutionError']
