"""输出、学习计划、评估与校准的纯记录协议。"""
from __future__ import annotations

import copy
import re

from tools.wiki_runtime.contracts import ContractError, canonical_json, digest
from tools.wiki_runtime.evidence import parse_package_ref
from tools.wiki_runtime.runtime import parse_review_credential, review_credential_digest

_HASH = re.compile(r'^[0-9a-f]{64}$')
_EVIDENCE_FOR_OBJECTIVE = {
    'concept': 'independent_explanation',
    'mechanism': 'independent_explanation',
    'procedure': 'worked_procedure',
    'transfer': 'transfer_response',
    'integrated_reasoning': 'integrated_response',
}


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


def _hash(value, location):
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ContractError(f'{location}: 应为 SHA-256 小写十六进制')
    return value


def _integer(value, location, minimum=1):
    if type(value) is not int or value < minimum:
        raise ContractError(f'{location}: 应为不小于 {minimum} 的整数')
    return value


def _strings(value, location):
    if type(value) is not list or any(not isinstance(item, str) or not item for item in value):
        raise ContractError(f'{location}: 应为字符串数组且元素非空')
    if len(set(value)) != len(value):
        raise ContractError(f'{location}: 不允许重复项')
    return value


def parse_output_artifact(record):
    fields = ('artifact_id', 'package_ref', 'output_type', 'content', 'evidence_map', 'quality')
    _record(record, fields, 'OutputArtifact')
    _text(record['artifact_id'], 'OutputArtifact.artifact_id')
    parse_package_ref(record['package_ref'])
    _text(record['output_type'], 'OutputArtifact.output_type')
    _text(record['content'], 'OutputArtifact.content')
    if type(record['evidence_map']) is not list:
        raise ContractError('OutputArtifact.evidence_map: 应为数组')
    for index, item in enumerate(record['evidence_map']):
        _record(item, ('claim_id', 'evidence_ids'), f'OutputArtifact.evidence_map[{index}]')
        _text(item['claim_id'], f'OutputArtifact.evidence_map[{index}].claim_id')
        _strings(item['evidence_ids'], f'OutputArtifact.evidence_map[{index}].evidence_ids')
    _record(record['quality'], ('standard', 'status'), 'OutputArtifact.quality')
    _text(record['quality']['standard'], 'OutputArtifact.quality.standard')
    if record['quality']['status'] not in ('unreviewed', 'passed', 'failed'):
        raise ContractError('OutputArtifact.quality.status: 未知状态')
    return record


def output_artifact_digest(record):
    return digest(parse_output_artifact(record))


def parse_knowledge_revision_request(record):
    fields = ('request_id', 'package_ref', 'output_type', 'change_kind', 'reason', 'quality_standard')
    _record(record, fields, 'KnowledgeRevisionRequest')
    _text(record['request_id'], 'KnowledgeRevisionRequest.request_id')
    parse_package_ref(record['package_ref'])
    _text(record['output_type'], 'KnowledgeRevisionRequest.output_type')
    if record['change_kind'] not in ('new_fact', 'conclusion_change', 'scope_expansion'):
        raise ContractError('KnowledgeRevisionRequest.change_kind: 未知修订类型')
    _text(record['reason'], 'KnowledgeRevisionRequest.reason')
    _text(record['quality_standard'], 'KnowledgeRevisionRequest.quality_standard')
    return record


def knowledge_revision_request_digest(record):
    return digest(parse_knowledge_revision_request(record))


def render(package_ref, output_type, output_policy):
    parse_package_ref(package_ref)
    fields = ('artifact_id', 'content', 'evidence_map', 'quality_standard', 'semantic_change', 'reason')
    _record(output_policy, fields, 'OutputPolicy')
    _text(output_type, 'OutputPolicy.output_type')
    _text(output_policy['artifact_id'], 'OutputPolicy.artifact_id')
    _text(output_policy['quality_standard'], 'OutputPolicy.quality_standard')
    change = output_policy['semantic_change']
    if change not in ('none', 'new_fact', 'conclusion_change', 'scope_expansion'):
        raise ContractError('OutputPolicy.semantic_change: 未知类型')
    if change == 'none':
        if output_policy['reason'] != '':
            raise ContractError('OutputPolicy.reason: 无语义变化时理由必须为空')
        return parse_output_artifact({
            'artifact_id': output_policy['artifact_id'], 'package_ref': copy.deepcopy(package_ref),
            'output_type': output_type, 'content': output_policy['content'],
            'evidence_map': copy.deepcopy(output_policy['evidence_map']),
            'quality': {'standard': output_policy['quality_standard'], 'status': 'unreviewed'},
        })
    return parse_knowledge_revision_request({
        'request_id': f"revision-{output_policy['artifact_id']}",
        'package_ref': copy.deepcopy(package_ref), 'output_type': output_type,
        'change_kind': change, 'reason': output_policy['reason'],
        'quality_standard': output_policy['quality_standard'],
    })


def parse_rubric(record):
    fields = ('rubric_id', 'version', 'package_ref', 'objective_id', 'criteria', 'evidence_digest')
    _record(record, fields, 'Rubric')
    _text(record['rubric_id'], 'Rubric.rubric_id')
    _integer(record['version'], 'Rubric.version')
    parse_package_ref(record['package_ref'])
    _text(record['objective_id'], 'Rubric.objective_id')
    _strings(record['criteria'], 'Rubric.criteria')
    _hash(record['evidence_digest'], 'Rubric.evidence_digest')
    return record


def rubric_digest(record):
    return digest(parse_rubric(record))


def parse_objective(record):
    fields = ('objective_id', 'objective_type', 'required_evidence', 'prerequisite_objectives',
              'rubric_id', 'rubric_version', 'rubric_digest', 'pass_condition', 'core')
    _record(record, fields, 'Objective')
    _text(record['objective_id'], 'Objective.objective_id')
    objective_type = record['objective_type']
    if objective_type not in _EVIDENCE_FOR_OBJECTIVE:
        raise ContractError('Objective.objective_type: 未知目标类型')
    if record['required_evidence'] != _EVIDENCE_FOR_OBJECTIVE[objective_type]:
        raise ContractError('Objective.required_evidence: 与目标类型不匹配')
    _strings(record['prerequisite_objectives'], 'Objective.prerequisite_objectives')
    _text(record['rubric_id'], 'Objective.rubric_id')
    _integer(record['rubric_version'], 'Objective.rubric_version')
    _hash(record['rubric_digest'], 'Objective.rubric_digest')
    _text(record['pass_condition'], 'Objective.pass_condition')
    if type(record['core']) is not bool:
        raise ContractError('Objective.core: 应为布尔值')
    return record


def objective_digest(record):
    return digest(parse_objective(record))


def parse_rubric_template(record):
    fields = ('template_id', 'version', 'content_digest', 'applicable_objective_types')
    _record(record, fields, 'RubricTemplate')
    _text(record['template_id'], 'RubricTemplate.template_id')
    _integer(record['version'], 'RubricTemplate.version')
    _hash(record['content_digest'], 'RubricTemplate.content_digest')
    _strings(record['applicable_objective_types'], 'RubricTemplate.applicable_objective_types')
    if not set(record['applicable_objective_types']) <= set(_EVIDENCE_FOR_OBJECTIVE):
        raise ContractError('RubricTemplate.applicable_objective_types: 未知目标类型')
    return record


def rubric_template_digest(record):
    return digest(parse_rubric_template(record))


def parse_evaluator(record):
    _record(record, ('evaluator_id', 'version', 'config_digest'), 'Evaluator')
    _text(record['evaluator_id'], 'Evaluator.evaluator_id')
    _integer(record['version'], 'Evaluator.version')
    _hash(record['config_digest'], 'Evaluator.config_digest')
    return record


def evaluator_digest(record):
    return digest(parse_evaluator(record))


def parse_calibration(record):
    fields = ('calibration_id', 'suite_digest', 'rubric_template_id', 'rubric_template_version',
              'rubric_template_digest', 'evaluator_id', 'evaluator_version', 'evaluator_digest',
              'objective_types', 'result', 'valid')
    _record(record, fields, 'Calibration')
    _text(record['calibration_id'], 'Calibration.calibration_id')
    _hash(record['suite_digest'], 'Calibration.suite_digest')
    _text(record['rubric_template_id'], 'Calibration.rubric_template_id')
    _integer(record['rubric_template_version'], 'Calibration.rubric_template_version')
    _hash(record['rubric_template_digest'], 'Calibration.rubric_template_digest')
    _text(record['evaluator_id'], 'Calibration.evaluator_id')
    _integer(record['evaluator_version'], 'Calibration.evaluator_version')
    _hash(record['evaluator_digest'], 'Calibration.evaluator_digest')
    _strings(record['objective_types'], 'Calibration.objective_types')
    if not set(record['objective_types']) <= set(_EVIDENCE_FOR_OBJECTIVE):
        raise ContractError('Calibration.objective_types: 未知目标类型')
    if record['result'] not in ('pass', 'fail'):
        raise ContractError('Calibration.result: 未知结果')
    if type(record['valid']) is not bool:
        raise ContractError('Calibration.valid: 应为布尔值')
    return record


def calibration_digest(record):
    return digest(parse_calibration(record))


def parse_assessment(record):
    fields = (
        'assessment_id', 'package_ref', 'objective_id', 'objective_digest', 'rubric_id',
        'rubric_version', 'rubric_digest', 'rubric_template_id', 'rubric_template_version',
        'rubric_template_digest', 'evaluator_id', 'evaluator_version', 'evaluator_digest',
        'calibration_digest', 'rubric_review_digest', 'response_evidence', 'result', 'valid',
    )
    _record(record, fields, 'Assessment')
    _text(record['assessment_id'], 'Assessment.assessment_id')
    parse_package_ref(record['package_ref'])
    for field in ('objective_id', 'rubric_id', 'rubric_template_id', 'evaluator_id'):
        _text(record[field], f'Assessment.{field}')
    for field in ('rubric_version', 'rubric_template_version', 'evaluator_version'):
        _integer(record[field], f'Assessment.{field}')
    for field in ('objective_digest', 'rubric_digest', 'rubric_template_digest', 'evaluator_digest',
                  'calibration_digest', 'rubric_review_digest'):
        _hash(record[field], f'Assessment.{field}')
    response = record['response_evidence']
    response_fields = ('evidence_id', 'content_digest', 'evidence_type', 'independent',
                       'assistance', 'conditions')
    _record(response, response_fields, 'Assessment.response_evidence')
    _text(response['evidence_id'], 'Assessment.response_evidence.evidence_id')
    _hash(response['content_digest'], 'Assessment.response_evidence.content_digest')
    _text(response['evidence_type'], 'Assessment.response_evidence.evidence_type')
    if type(response['independent']) is not bool:
        raise ContractError('Assessment.response_evidence.independent: 应为布尔值')
    if response['assistance'] not in ('none', 'hinted', 'corrected'):
        raise ContractError('Assessment.response_evidence.assistance: 未知辅助状态')
    _strings(response['conditions'], 'Assessment.response_evidence.conditions')
    if record['result'] not in ('pass', 'partial', 'fail'):
        raise ContractError('Assessment.result: 未知结果')
    if type(record['valid']) is not bool:
        raise ContractError('Assessment.valid: 应为布尔值')
    return record


def assessment_digest(record):
    return digest(parse_assessment(record))


def assessment_l2_valid(assessment, context):
    try:
        parse_assessment(assessment)
        objective = parse_objective(context['objective'])
        rubric = parse_rubric(context['rubric'])
        template = parse_rubric_template(context['rubric_template'])
        evaluator = parse_evaluator(context['evaluator'])
        calibration = parse_calibration(context['calibration'])
        review = parse_review_credential(context['rubric_review'])
        assessor = parse_review_credential(context['assessor_review'])
        learning_task_id = context['learning_task_id']
        _text(learning_task_id, 'LearningContext.learning_task_id')
    except (ContractError, KeyError, TypeError):
        return False
    if not assessment['valid'] or assessment['result'] != 'pass':
        return False
    if (assessment['objective_id'], assessment['objective_digest']) != (
        objective['objective_id'], objective_digest(objective)
    ):
        return False
    if (objective['rubric_id'], objective['rubric_version'], objective['rubric_digest']) != (
        rubric['rubric_id'], rubric['version'], rubric_digest(rubric)
    ):
        return False
    if (assessment['rubric_id'], assessment['rubric_version'], assessment['rubric_digest']) != (
        rubric['rubric_id'], rubric['version'], rubric_digest(rubric)
    ) or rubric['objective_id'] != objective['objective_id']:
        return False
    if assessment['package_ref'] != rubric['package_ref']:
        return False
    if (assessment['rubric_template_id'], assessment['rubric_template_version'],
        assessment['rubric_template_digest']) != (
        template['template_id'], template['version'], rubric_template_digest(template)
    ):
        return False
    if (assessment['evaluator_id'], assessment['evaluator_version'], assessment['evaluator_digest']) != (
        evaluator['evaluator_id'], evaluator['version'], evaluator_digest(evaluator)
    ):
        return False
    if (assessment['calibration_digest'] != calibration_digest(calibration)
            or not calibration['valid'] or calibration['result'] != 'pass'
            or objective['objective_type'] not in template['applicable_objective_types']
            or objective['objective_type'] not in calibration['objective_types']
            or not set(calibration['objective_types']) <= set(template['applicable_objective_types'])):
        return False
    calibration_binding = (
        calibration['rubric_template_id'], calibration['rubric_template_version'],
        calibration['rubric_template_digest'], calibration['evaluator_id'],
        calibration['evaluator_version'], calibration['evaluator_digest'],
    )
    if calibration_binding != (
        template['template_id'], template['version'], rubric_template_digest(template),
        evaluator['evaluator_id'], evaluator['version'], evaluator_digest(evaluator),
    ):
        return False
    response = assessment['response_evidence']
    if (not response['independent'] or response['assistance'] != 'none'
            or response['evidence_type'] != objective['required_evidence']):
        return False
    if (assessment['rubric_review_digest'] != review_credential_digest(review)
            or review['role'] != 'Reviewer' or not review['valid'] or review['result'] != 'pass'
            or review['learning_task_id'] != learning_task_id
            or review['content_digest'] != rubric_digest(rubric)
            or review['evidence_digest'] != rubric['evidence_digest']):
        return False
    scope = review['scope']
    if (scope['kind'] != 'lesson_rubric' or scope['objective_ids'] != [objective['objective_id']]
            or scope['candidate_digest'] != assessment['package_ref']['digest']
            or scope['package_ref'] != assessment['package_ref']):
        return False
    assessor_scope = assessor['scope']
    return (
        assessor['role'] == 'Assessor' and assessor['valid'] and assessor['result'] == 'pass'
        and assessor['learning_task_id'] == learning_task_id
        and assessor['content_digest'] == assessment_digest(assessment)
        and assessor_scope['kind'] == 'understanding_assessment'
        and assessor_scope['objective_ids'] == [objective['objective_id']]
        and assessor_scope['package_ref'] == assessment['package_ref']
    )


def parse_learning_plan(record):
    _record(record, ('plan_id', 'package_ref', 'objectives'), 'LearningPlan')
    _text(record['plan_id'], 'LearningPlan.plan_id')
    parse_package_ref(record['package_ref'])
    if type(record['objectives']) is not list:
        raise ContractError('LearningPlan.objectives: 应为数组')
    for objective in record['objectives']:
        parse_objective(objective)
    identities = [objective['objective_id'] for objective in record['objectives']]
    if len(set(identities)) != len(identities):
        raise ContractError('LearningPlan.objectives: 目标重复')
    by_id = {objective['objective_id']: objective for objective in record['objectives']}
    visiting = set()
    visited = set()

    def visit(objective_id):
        if objective_id in visiting:
            raise ContractError('LearningPlan.objectives: 内部前置目标不得成环')
        if objective_id in visited:
            return
        visiting.add(objective_id)
        for prerequisite in by_id[objective_id]['prerequisite_objectives']:
            if prerequisite in by_id:
                visit(prerequisite)
        visiting.remove(objective_id)
        visited.add(objective_id)

    for objective_id in by_id:
        visit(objective_id)
    return record


def learning_plan_digest(record):
    return digest(parse_learning_plan(record))


def prepare(package_ref, objective_specs):
    parse_package_ref(package_ref)
    if type(objective_specs) is not list:
        raise ContractError('LearningPlan.objective_specs: 应为数组')
    return parse_learning_plan({
        'plan_id': f"plan-{package_ref['package_id']}-v{package_ref['version']}",
        'package_ref': copy.deepcopy(package_ref), 'objectives': copy.deepcopy(objective_specs),
    })
