"""T10 受限工具网关原型；不把同权限 Python 对象当作 OS 安全边界。"""
from .gateway import Gateway, PermissionDenied
from .preflight import inspect_deployment

__all__ = ['Gateway', 'PermissionDenied', 'inspect_deployment']
