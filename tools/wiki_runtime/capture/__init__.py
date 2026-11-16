"""离线候选资料采集；不登记 raw、不授予写入权限。"""
from .adapters import ADAPTERS, capabilities, capture, identify, validate_package

__all__ = ['ADAPTERS', 'capabilities', 'capture', 'identify', 'validate_package']
