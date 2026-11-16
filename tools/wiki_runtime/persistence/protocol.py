"""候选预览、规划覆盖与最终理解凭据校验的纯协议。"""
from __future__ import annotations

import copy

from tools.wiki_runtime.contracts import ContractError, canonical_json, digest
from tools.wiki_runtime.evidence import parse_package_ref
from tools.wiki_runtime.learning.artifact_protocol import assessment_l2_valid

_TEACHING_DISPOSITIONS = (
    'required_objective', 'reuse_objective', 'optional_extension', 'non_teaching',
)


def _record(value, fields, name):
    if type(value) is not dict:
        raise ContractError(f'{name}: 应为对象')
    canonical_json(value)
    if set(value) != set(fields):
        raise ContractError(f'{name}: 缺少或包含未知字段')
    return value


def _text(value, location):
    if not isinstance(value, str) or not value:
        raise ContractError(f'{location}: 必须是非空字符串')
    return value


def _nullable_text(value, location):
    if value is not None:
        _text(value, location)
    return value


def parse_coverage_disposition(record):
    fields = ('change_id', 'candidate_path', 'claim_id', 'evidence_disposition',
              'teaching_disposition', 'objective_ref', 'reason')
    _record(record, fields, 'CoverageDisposition')
    _text(record['change_id'], 'CoverageDisposition.change_id')
    _text(record['candidate_path'], 'CoverageDisposition.candidate_path')
    _nullable_text(record['claim_id'], 'CoverageDisposition.claim_id')
    if record['evidence_disposition'] not in (
        'supported', 'contradicted', 'qualified', 'disputed', 'mechanical', 'attributed',
    ):
        raise ContractError('CoverageDisposition.evidence_disposition: 未知处置')
    teaching = record['teaching_disposition']
    if teaching not in _TEACHING_DISPOSITIONS:
        raise ContractError('CoverageDisposition.teaching_disposition: 未知处置')
    _nullable_text(record['objective_ref'], 'CoverageDisposition.objective_ref')
    if teaching in ('required_objective', 'reuse_objective') and record['objective_ref'] is None:
        raise ContractError('CoverageDisposition.objective_ref: 必过或复用目标必须引用目标')
    if teaching == 'non_teaching' and record['objective_ref'] is not None:
        raise ContractError('CoverageDisposition.objective_ref: 非教学处置不得伪造目标')
    _text(record['reason'], 'CoverageDisposition.reason')
    return record


def coverage_disposition_digest(record):
    return digest(parse_coverage_disposition(record))


def parse_candidate_change(record):
    _record(record, ('change_id', 'candidate_path', 'action', 'source', 'claim_id'),
            'CandidateChange')
    _text(record['change_id'], 'CandidateChange.change_id')
    _text(record['candidate_path'], 'CandidateChange.candidate_path')
    if record['action'] not in ('write', 'delete', 'move'):
        raise ContractError('CandidateChange.action: 未知动作')
    if record['action'] == 'move':
        _text(record['source'], 'CandidateChange.source')
    elif record['source'] is not None:
        raise ContractError('CandidateChange.source: 非移动变更不得包含移动源')
    _nullable_text(record['claim_id'], 'CandidateChange.claim_id')
    return record


def validate_candidate_coverage(candidate, candidate_preview):
    from tools.wiki_runtime.contracts import validate
    validate('candidate', candidate)
    parse_candidate_preview(candidate_preview)
    actual = {change['path']: change for change in candidate['changes']}
    planned_list = candidate_preview['candidate_changes']
    planned = {change['candidate_path']: change for change in planned_list}
    if len(planned) != len(planned_list):
        raise ContractError('Coverage: 候选路径重复')
    if set(actual) != set(planned):
        raise ContractError('Coverage: 实际 Candidate 路径必须完整覆盖')
    for path, change in actual.items():
        expected = planned[path]
        if expected['action'] != change['action'] or expected['source'] != change.get('source'):
            raise ContractError('Coverage: 实际 Candidate 动作或移动源绑定不匹配')
    return candidate_preview


def _validate_coverage_changes(candidate_changes, dispositions):
    if type(candidate_changes) is not list or type(dispositions) is not list:
        raise ContractError('Coverage: 候选变更与处置必须为数组')
    for change in candidate_changes:
        parse_candidate_change(change)
    for disposition in dispositions:
        parse_coverage_disposition(disposition)
    changes = {change['change_id']: change for change in candidate_changes}
    if len(changes) != len(candidate_changes):
        raise ContractError('Coverage: 候选变更 ID 重复')
    coverage = {disposition['change_id']: disposition for disposition in dispositions}
    if len(coverage) != len(dispositions):
        raise ContractError('Coverage: 覆盖处置重复')
    if set(changes) != set(coverage):
        raise ContractError('Coverage: 候选变更必须完整覆盖且不得包含未知项')
    for change_id, change in changes.items():
        disposition = coverage[change_id]
        if (disposition['candidate_path'], disposition['claim_id']) != (
            change['candidate_path'], change['claim_id']
        ):
            raise ContractError('Coverage: 处置的位置或主张绑定不匹配')


def parse_coverage_spec(record):
    _record(record, ('candidate_id', 'candidate_changes', 'dispositions'), 'CoverageSpec')
    _text(record['candidate_id'], 'CoverageSpec.candidate_id')
    _validate_coverage_changes(record['candidate_changes'], record['dispositions'])
    return record


def coverage_spec_digest(record):
    return digest(parse_coverage_spec(record))


def parse_candidate_preview(record):
    fields = ('candidate_id', 'package_ref', 'baseline_ref', 'candidate_changes', 'coverage', 'state')
    _record(record, fields, 'CandidatePreview')
    _text(record['candidate_id'], 'CandidatePreview.candidate_id')
    parse_package_ref(record['package_ref'])
    _text(record['baseline_ref'], 'CandidatePreview.baseline_ref')
    _validate_coverage_changes(record['candidate_changes'], record['coverage'])
    if record['state'] != 'preview':
        raise ContractError('CandidatePreview.state: S2 只能生成 preview，不能生成 Readiness')
    return record


def candidate_preview_digest(record):
    return digest(parse_candidate_preview(record))


def compile_candidate(package_ref, coverage_spec, baseline_ref):
    parse_package_ref(package_ref)
    parse_coverage_spec(coverage_spec)
    _text(baseline_ref, 'CandidatePreview.baseline_ref')
    return parse_candidate_preview({
        'candidate_id': coverage_spec['candidate_id'], 'package_ref': copy.deepcopy(package_ref),
        'baseline_ref': baseline_ref,
        'candidate_changes': copy.deepcopy(coverage_spec['candidate_changes']),
        'coverage': copy.deepcopy(coverage_spec['dispositions']), 'state': 'preview',
    })


def validate_final_coverage(candidate_preview, understanding_records):
    try:
        parse_candidate_preview(candidate_preview)
        if type(understanding_records) is not list:
            return False
    except (ContractError, TypeError):
        return False
    for disposition in candidate_preview['coverage']:
        if disposition['teaching_disposition'] not in ('required_objective', 'reuse_objective'):
            continue
        objective_id = disposition['objective_ref']
        valid = False
        for record in understanding_records:
            if type(record) is not dict:
                continue
            assessment = record.get('assessment')
            if type(assessment) is not dict or assessment.get('objective_id') != objective_id:
                continue
            if assessment.get('package_ref') != candidate_preview['package_ref']:
                continue
            if assessment_l2_valid(assessment, record):
                valid = True
                break
        if not valid:
            return False
    return True
