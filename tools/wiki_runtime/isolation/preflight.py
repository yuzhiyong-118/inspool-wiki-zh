"""只读部署检查。当前没有实际受限 backend，永不签发强制隔离通过。"""
from pathlib import Path
import os

from .gateway import TOOLS


def inspect_deployment(root, *, tool_catalog=None, profile=None):
    """catalog 来自 host 实际注册表；profile 是部署意图，不能提供证据。

    不接受模型报告/verified/probe_result 作为实际系统隔离证明。
    os.access 只用作风险线索，不能用于证明 Windows ACL 拒写。
    """
    root = Path(root).absolute()
    problems = ['未部署并认证实际受限 backend；当前进程权限不能作为模型隔离证据']
    if profile is not None:
        expected = {'profile_version', 'backend', 'model_tools_only', 'executor_out_of_band'}
        if type(profile) is not dict or set(profile) != expected:
            problems.append('profile 字段不合法；自声明 verified/探针结果不被信任')
        elif profile != {'profile_version': '1.0', 'backend': 'restricted-tool-gateway',
                         'model_tools_only': True, 'executor_out_of_band': True}:
            problems.append('profile 尚未满足受限工具部署意图')
    catalog_ok = True
    if type(tool_catalog) is not dict or set(tool_catalog) != set(TOOLS):
        problems.append('缺少可信 host 的完整四角色实际工具注册表')
        catalog_ok = False
    else:
        for role, allowed in TOOLS.items():
            entries = tool_catalog[role]
            if type(entries) is not list or any(type(e) is not str for e in entries):
                catalog_ok = False
            elif len(entries) != len(set(entries)) or set(entries) != allowed:
                catalog_ok = False
        if not catalog_ok:
            problems.append('工具注册表存在额外/缺失/重复工具；禁止 shell、通用写入、批准和 Executor 工具')
    paths = ['AGENTS.md', 'wiki', 'raw', 'tools/wiki_runtime', '.wiki-runtime']
    writable_hints = [p for p in paths if (root / p).exists() and os.access(root / p, os.W_OK)]
    if writable_hints:
        problems.append('当前进程可写风险线索：' + ', '.join(writable_hints))
    return {
        'isolation_version': '1.0', 'status': 'not_verified',
        'enforced': False, 'may_apply': False,
        'tool_catalog_shape_valid': catalog_ok,
        'writable_hints': writable_hints,
        'problems': problems,
        'required_evidence': [
            '可信 host 从实际 transport 获取工具注册表，模型不能更换角色/session 或调用旁路工具',
            '在真实模型受限身份/进程中执行 shell 直写、规则/检查器/凭据写入及链接逃逸探针',
            '由受保护 host 核对探针前后文件字节与系统拒绝结果，覆盖所有模型入口',
            '受保护 Executor 独立身份成功写临时库，用户正常编辑及冲突恢复回归通过',
            '受限 backend 实现、版本、配置、探针工件和可信认证机制接受独立集成验收',
        ],
    }
