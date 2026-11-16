"""KnowledgePackage 及证据关系的封闭纯记录协议。"""
from __future__ import annotations

import copy
import re

from tools.wiki_runtime.contracts import ContractError, canonical_json, digest

_HASH = re.compile(r'^[0-9a-f]{64}$')


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


def _hash(value, location):
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ContractError(f'{location}: 应为 SHA-256 小写十六进制')
    return value


def _integer(value, location, minimum=0):
    if type(value) is not int or value < minimum:
        raise ContractError(f'{location}: 应为不小于 {minimum} 的整数')
    return value


def _strings(value, location):
    if type(value) is not list or any(not isinstance(item, str) or not item for item in value):
        raise ContractError(f'{location}: 应为字符串数组且元素非空')
    if len(set(value)) != len(value):
        raise ContractError(f'{location}: 不允许重复项')
    return value


def _lines(value, location, extra=()):
    _record(value, ('start_line', 'end_line') + tuple(extra), location)
    start = _integer(value['start_line'], f'{location}.start_line', 1)
    end = _integer(value['end_line'], f'{location}.end_line', 1)
    if end < start:
        raise ContractError(f'{location}: 结束行不能早于开始行')


def parse_source(record):
    fields = ('source_id', 'locator', 'version', 'content_digest', 'readable_range')
    _record(record, fields, 'Source')
    for field in ('source_id', 'locator', 'version'):
        _text(record[field], f'Source.{field}')
    _hash(record['content_digest'], 'Source.content_digest')
    readable = record['readable_range']
    _lines(readable, 'Source.readable_range', ('complete',))
    if type(readable['complete']) is not bool:
        raise ContractError('Source.readable_range.complete: 应为布尔值')
    return record


def source_digest(record):
    return digest(parse_source(record))


def parse_evidence(record):
    fields = ('evidence_id', 'source_id', 'source_version', 'source_digest',
              'locator', 'excerpt', 'extraction_state')
    _record(record, fields, 'Evidence')
    for field in ('evidence_id', 'source_id', 'source_version', 'excerpt'):
        _text(record[field], f'Evidence.{field}')
    _hash(record['source_digest'], 'Evidence.source_digest')
    _lines(record['locator'], 'Evidence.locator')
    if record['extraction_state'] not in ('complete', 'partial', 'failed'):
        raise ContractError('Evidence.extraction_state: 未知状态')
    return record


def evidence_digest(record):
    return digest(parse_evidence(record))


def parse_claim(record):
    _record(record, ('claim_id', 'text', 'conditions', 'attribution', 'evidence_status'), 'Claim')
    _text(record['claim_id'], 'Claim.claim_id')
    _text(record['text'], 'Claim.text')
    _strings(record['conditions'], 'Claim.conditions')
    _text(record['attribution'], 'Claim.attribution')
    if record['evidence_status'] not in ('supported', 'contradicted', 'disputed', 'unverified'):
        raise ContractError('Claim.evidence_status: 未知状态')
    return record


def claim_digest(record):
    return digest(parse_claim(record))


def parse_evidence_claim_relation(record):
    fields = ('evidence_id', 'evidence_digest', 'claim_id', 'relation', 'conditions',
              'verification_status')
    _record(record, fields, 'EvidenceClaimRelation')
    _text(record['evidence_id'], 'EvidenceClaimRelation.evidence_id')
    _hash(record['evidence_digest'], 'EvidenceClaimRelation.evidence_digest')
    _text(record['claim_id'], 'EvidenceClaimRelation.claim_id')
    if record['relation'] not in ('supports', 'contradicts', 'qualifies'):
        raise ContractError('EvidenceClaimRelation.relation: 未知关系')
    _strings(record['conditions'], 'EvidenceClaimRelation.conditions')
    if record['verification_status'] not in ('verified', 'pending', 'rejected'):
        raise ContractError('EvidenceClaimRelation.verification_status: 未知状态')
    return record


def evidence_claim_relation_digest(record):
    return digest(parse_evidence_claim_relation(record))


def parse_conflict(record):
    fields = ('conflict_id', 'claim_ids', 'evidence_ids', 'status', 'resolution')
    _record(record, fields, 'Conflict')
    _text(record['conflict_id'], 'Conflict.conflict_id')
    _strings(record['claim_ids'], 'Conflict.claim_ids')
    _strings(record['evidence_ids'], 'Conflict.evidence_ids')
    if record['status'] not in ('resolved', 'unresolved'):
        raise ContractError('Conflict.status: 未知状态')
    if record['status'] == 'resolved':
        _text(record['resolution'], 'Conflict.resolution')
    elif record['resolution'] is not None:
        raise ContractError('Conflict.resolution: 未解决冲突不得伪造解决结论')
    return record


def conflict_digest(record):
    return digest(parse_conflict(record))


def parse_existing_knowledge_relation(record):
    fields = ('claim_id', 'target', 'relation', 'reason')
    _record(record, fields, 'ExistingKnowledgeRelation')
    _text(record['claim_id'], 'ExistingKnowledgeRelation.claim_id')
    _text(record['target'], 'ExistingKnowledgeRelation.target')
    if record['relation'] not in ('related', 'supports', 'contradicts', 'qualifies', 'supersedes'):
        raise ContractError('ExistingKnowledgeRelation.relation: 未知关系')
    _text(record['reason'], 'ExistingKnowledgeRelation.reason')
    return record


def parse_knowledge_package(record):
    fields = ('package_id', 'version', 'content_digest', 'sources', 'evidence', 'claims',
              'relations', 'conflicts', 'existing_knowledge')
    _record(record, fields, 'KnowledgePackage')
    _text(record['package_id'], 'KnowledgePackage.package_id')
    _integer(record['version'], 'KnowledgePackage.version', 1)
    _hash(record['content_digest'], 'KnowledgePackage.content_digest')
    parsers = {
        'sources': parse_source, 'evidence': parse_evidence, 'claims': parse_claim,
        'relations': parse_evidence_claim_relation, 'conflicts': parse_conflict,
        'existing_knowledge': parse_existing_knowledge_relation,
    }
    id_fields = {
        'sources': 'source_id', 'evidence': 'evidence_id', 'claims': 'claim_id',
        'conflicts': 'conflict_id',
    }
    for field, parser in parsers.items():
        if type(record[field]) is not list:
            raise ContractError(f'KnowledgePackage.{field}: 应为数组')
        for index, item in enumerate(record[field]):
            try:
                parser(item)
            except ContractError as exc:
                raise ContractError(f'KnowledgePackage.{field}[{index}]: {exc}') from exc
        if field in id_fields:
            identities = [item[id_fields[field]] for item in record[field]]
            if len(set(identities)) != len(identities):
                raise ContractError(f'KnowledgePackage.{field}: ID 重复')
    sources = {item['source_id']: item for item in record['sources']}
    evidence_by_id = {item['evidence_id']: item for item in record['evidence']}
    evidence_ids = set(evidence_by_id)
    claim_ids = {item['claim_id'] for item in record['claims']}
    for evidence in record['evidence']:
        source = sources.get(evidence['source_id'])
        if source is None:
            raise ContractError('KnowledgePackage.evidence: 引用未知 Source')
        if (evidence['source_version'], evidence['source_digest']) != (
            source['version'], source['content_digest']
        ):
            raise ContractError('KnowledgePackage.evidence: 来源版本或摘要绑定失效')
        locator = evidence['locator']
        readable = source['readable_range']
        if (locator['start_line'] < readable['start_line']
                or locator['end_line'] > readable['end_line']):
            raise ContractError('KnowledgePackage.evidence: 定位超出来源可读范围')
    relation_identities = set()
    for relation in record['relations']:
        if relation['evidence_id'] not in evidence_ids or relation['claim_id'] not in claim_ids:
            raise ContractError('KnowledgePackage.relations: 引用未知 Evidence 或 Claim')
        if relation['evidence_digest'] != evidence_digest(evidence_by_id[relation['evidence_id']]):
            raise ContractError('KnowledgePackage.relations: Evidence 内容摘要绑定失效')
        identity = (relation['evidence_id'], relation['claim_id'], relation['relation'])
        if identity in relation_identities:
            raise ContractError('KnowledgePackage.relations: 关系重复')
        relation_identities.add(identity)
    for conflict in record['conflicts']:
        if not set(conflict['claim_ids']) <= claim_ids or not set(conflict['evidence_ids']) <= evidence_ids:
            raise ContractError('KnowledgePackage.conflicts: 引用未知 Claim 或 Evidence')
    for relation in record['existing_knowledge']:
        if relation['claim_id'] not in claim_ids:
            raise ContractError('KnowledgePackage.existing_knowledge: 引用未知 Claim')
    body = {field: record[field] for field in fields if field != 'content_digest'}
    if record['content_digest'] != digest(body):
        raise ContractError('KnowledgePackage.content_digest: 与包内容不匹配')
    return record


def knowledge_package_digest(record):
    return parse_knowledge_package(record)['content_digest']


def build_package(source_refs, claim_refs, conflict_refs):
    fields = ('package_id', 'version', 'sources', 'evidence', 'relations', 'existing_knowledge')
    _record(source_refs, fields, 'KnowledgePackage.source_refs')
    body = {
        'package_id': source_refs['package_id'], 'version': source_refs['version'],
        'sources': copy.deepcopy(source_refs['sources']),
        'evidence': copy.deepcopy(source_refs['evidence']),
        'claims': copy.deepcopy(claim_refs),
        'relations': copy.deepcopy(source_refs['relations']),
        'conflicts': copy.deepcopy(conflict_refs),
        'existing_knowledge': copy.deepcopy(source_refs['existing_knowledge']),
    }
    return parse_knowledge_package(dict(body, content_digest=digest(body)))


def parse_package_ref(record):
    _record(record, ('package_id', 'version', 'digest'), 'KnowledgePackageRef')
    _text(record['package_id'], 'KnowledgePackageRef.package_id')
    _integer(record['version'], 'KnowledgePackageRef.version', 1)
    _hash(record['digest'], 'KnowledgePackageRef.digest')
    return record


def package_ref(record):
    parse_knowledge_package(record)
    return {
        'package_id': record['package_id'], 'version': record['version'],
        'digest': knowledge_package_digest(record),
    }


def package_binding_matches(record, package):
    try:
        parse_knowledge_package(package)
        reference = parse_package_ref(record['package_ref'] if 'package_ref' in record else record)
    except (ContractError, KeyError, TypeError):
        return False
    return reference == package_ref(package)
