"""S0 知识包、学习产物与候选覆盖协议；全部使用内存合成记录。"""
import copy
import inspect
import unittest

from tools.wiki_runtime.contracts import ContractError, candidate_digest as public_candidate_digest
from tools.wiki_runtime.evidence import (
    build_package, evidence_digest, knowledge_package_digest, package_binding_matches,
    package_ref, parse_evidence, parse_knowledge_package, parse_package_ref,
)
from tools.wiki_runtime.learning.artifact_protocol import (
    assessment_digest, assessment_l2_valid, calibration_digest, evaluator_digest,
    learning_plan_digest, objective_digest, output_artifact_digest, parse_assessment,
    parse_calibration, parse_evaluator, parse_knowledge_revision_request, parse_learning_plan,
    parse_objective, parse_output_artifact, parse_rubric, parse_rubric_template, prepare,
    render, rubric_digest, rubric_template_digest,
)
from tools.wiki_runtime.persistence import (
    candidate_preview_digest, compile_candidate, coverage_disposition_digest,
    coverage_spec_digest, parse_candidate_preview, parse_coverage_disposition,
    parse_coverage_spec, validate_final_coverage,
)

A = 'a' * 64
B = 'b' * 64
C = 'c' * 64
D = 'd' * 64
E = 'e' * 64
F = 'f' * 64


class ModuleProtocolTests(unittest.TestCase):
    def setUp(self):
        self.source_refs = {
            'package_id': 'package-1',
            'version': 1,
            'sources': [{
                'source_id': 'source-1', 'locator': 'synthetic/source-1', 'version': 'source-v1',
                'content_digest': A,
                'readable_range': {'start_line': 1, 'end_line': 20, 'complete': True},
            }],
            'evidence': [
                {
                    'evidence_id': 'evidence-1', 'source_id': 'source-1',
                    'source_version': 'source-v1', 'source_digest': A,
                    'locator': {'start_line': 1, 'end_line': 3},
                    'excerpt': '证据一', 'extraction_state': 'complete',
                },
                {
                    'evidence_id': 'evidence-2', 'source_id': 'source-1',
                    'source_version': 'source-v1', 'source_digest': A,
                    'locator': {'start_line': 4, 'end_line': 5},
                    'excerpt': '证据二', 'extraction_state': 'complete',
                },
            ],
            'relations': [
                {
                    'evidence_id': 'evidence-1', 'claim_id': 'claim-a', 'relation': 'supports',
                    'conditions': ['condition-x'], 'verification_status': 'verified',
                },
                {
                    'evidence_id': 'evidence-1', 'claim_id': 'claim-b', 'relation': 'contradicts',
                    'conditions': ['condition-x'], 'verification_status': 'verified',
                },
                {
                    'evidence_id': 'evidence-2', 'claim_id': 'claim-a', 'relation': 'qualifies',
                    'conditions': ['condition-y'], 'verification_status': 'verified',
                },
            ],
            'existing_knowledge': [{
                'claim_id': 'claim-a', 'target': 'wiki/concepts/existing',
                'relation': 'related', 'reason': '连接既有概念',
            }],
        }
        evidence_by_id = {item['evidence_id']: item for item in self.source_refs['evidence']}
        for relation in self.source_refs['relations']:
            relation['evidence_digest'] = evidence_digest(evidence_by_id[relation['evidence_id']])
        self.claims = [
            {'claim_id': 'claim-a', 'text': '主张 A', 'conditions': ['condition-x'],
             'attribution': 'source', 'evidence_status': 'supported'},
            {'claim_id': 'claim-b', 'text': '主张 B', 'conditions': ['condition-x'],
             'attribution': 'source', 'evidence_status': 'disputed'},
        ]
        self.conflicts = [
            {'conflict_id': 'conflict-resolved', 'claim_ids': ['claim-a', 'claim-b'],
             'evidence_ids': ['evidence-1', 'evidence-2'], 'status': 'resolved',
             'resolution': '条件不同'},
            {'conflict_id': 'conflict-open', 'claim_ids': ['claim-a', 'claim-b'],
             'evidence_ids': ['evidence-1'], 'status': 'unresolved', 'resolution': None},
        ]
        self.package = build_package(self.source_refs, self.claims, self.conflicts)
        self.package_ref = package_ref(self.package)
        self.rubric = {
            'rubric_id': 'rubric-lesson-1', 'version': 1, 'package_ref': self.package_ref,
            'objective_id': 'objective-core', 'criteria': ['解释机制', '说明条件'],
            'evidence_digest': B,
        }
        self.objective = {
            'objective_id': 'objective-core', 'objective_type': 'mechanism',
            'required_evidence': 'independent_explanation',
            'prerequisite_objectives': ['external-foundation'], 'rubric_id': 'rubric-lesson-1',
            'rubric_version': 1, 'rubric_digest': rubric_digest(self.rubric),
            'pass_condition': '独立解释机制和必要条件', 'core': True,
        }
        self.template = {
            'template_id': 'template-independent-1', 'version': 2, 'content_digest': C,
            'applicable_objective_types': ['mechanism', 'transfer'],
        }
        self.evaluator = {
            'evaluator_id': 'evaluator-1', 'version': 3, 'config_digest': D,
        }
        self.calibration = {
            'calibration_id': 'calibration-1', 'suite_digest': E,
            'rubric_template_id': 'template-independent-1', 'rubric_template_version': 2,
            'rubric_template_digest': rubric_template_digest(self.template),
            'evaluator_id': 'evaluator-1', 'evaluator_version': 3,
            'evaluator_digest': evaluator_digest(self.evaluator),
            'objective_types': ['mechanism'], 'result': 'pass', 'valid': True,
        }
        self.rubric_review = {
            'credential_id': 'rubric-review-1', 'learning_task_id': 'task-1',
            'invocation_id': 'invocation-rubric-review-1', 'role': 'Reviewer',
            'identity': 'independent-reviewer', 'independent': True,
            'content_digest': rubric_digest(self.rubric), 'evidence_digest': B,
            'dependencies_digest': C, 'rules_digest': D, 'prompt_digest': F,
            'validator_version': 'rubric-review-v1', 'review_config_digest': A,
            'scope': {'kind': 'lesson_rubric', 'objective_ids': ['objective-core'],
                      'candidate_digest': knowledge_package_digest(self.package),
                      'package_ref': self.package_ref},
            'result': 'pass', 'valid': True,
        }
        self.assessment = {
            'assessment_id': 'assessment-1', 'package_ref': self.package_ref,
            'objective_id': 'objective-core', 'objective_digest': objective_digest(self.objective),
            'rubric_id': 'rubric-lesson-1', 'rubric_version': 1,
            'rubric_digest': rubric_digest(self.rubric),
            'rubric_template_id': 'template-independent-1', 'rubric_template_version': 2,
            'rubric_template_digest': rubric_template_digest(self.template),
            'evaluator_id': 'evaluator-1', 'evaluator_version': 3,
            'evaluator_digest': evaluator_digest(self.evaluator),
            'calibration_digest': calibration_digest(self.calibration),
            'rubric_review_digest': '0' * 64,
            'response_evidence': {
                'evidence_id': 'response-1', 'content_digest': F,
                'evidence_type': 'independent_explanation', 'independent': True,
                'assistance': 'none', 'conditions': ['condition-x', 'new-scenario'],
            },
            'result': 'pass', 'valid': True,
        }
        from tools.wiki_runtime.runtime import review_credential_digest
        self.assessment['rubric_review_digest'] = review_credential_digest(self.rubric_review)
        self.learning_context = {
            'learning_task_id': 'task-1',
            'objective': self.objective, 'rubric': self.rubric, 'rubric_template': self.template,
            'evaluator': self.evaluator, 'calibration': self.calibration,
            'rubric_review': self.rubric_review,
        }
        self.plan = prepare(self.package_ref, [self.objective])
        self.coverage_spec = {
            'candidate_id': 'candidate-1',
            'candidate_changes': [
                {'change_id': 'change-a', 'candidate_path': 'wiki/a.md', 'action': 'write',
                 'source': None, 'claim_id': 'claim-a'},
                {'change_id': 'change-b', 'candidate_path': 'wiki/b.md', 'action': 'write',
                 'source': None, 'claim_id': 'claim-b'},
                {'change_id': 'change-c', 'candidate_path': 'wiki/index.md', 'action': 'write',
                 'source': None, 'claim_id': None},
            ],
            'dispositions': [
                {'change_id': 'change-a', 'candidate_path': 'wiki/a.md', 'claim_id': 'claim-a',
                 'evidence_disposition': 'supported', 'teaching_disposition': 'required_objective',
                 'objective_ref': 'objective-core', 'reason': '核心机制必须独立理解'},
                {'change_id': 'change-b', 'candidate_path': 'wiki/b.md', 'claim_id': 'claim-b',
                 'evidence_disposition': 'disputed', 'teaching_disposition': 'optional_extension',
                 'objective_ref': 'objective-optional', 'reason': '非核心可选争议拓展'},
                {'change_id': 'change-c', 'candidate_path': 'wiki/index.md', 'claim_id': None,
                 'evidence_disposition': 'mechanical', 'teaching_disposition': 'non_teaching',
                 'objective_ref': None, 'reason': '仅机械索引变更'},
            ],
        }
        self.preview = compile_candidate(self.package_ref, self.coverage_spec, 'baseline-1')
        self.candidate = {
            'contract_version': '1.0', 'operation_id': 'operation-1',
            'changes': [{
                'action': 'write', 'path': path, 'payload_path': f'payload/{path}',
                'sha256': A, 'precondition': {'kind': 'absent'},
            } for path in ('wiki/a.md', 'wiki/b.md', 'wiki/index.md')],
        }
        self.learning_context['assessor_review'] = self.make_assessor_review()
        self.understanding_records = [dict(self.learning_context, assessment=self.assessment)]

    def test_module_signatures_match_stage_contract(self):
        self.assertEqual(list(inspect.signature(build_package).parameters),
                         ['source_refs', 'claim_refs', 'conflict_refs'])
        self.assertEqual(list(inspect.signature(render).parameters),
                         ['package_ref', 'output_type', 'output_policy'])
        self.assertEqual(list(inspect.signature(prepare).parameters), ['package_ref', 'objective_specs'])
        self.assertEqual(list(inspect.signature(compile_candidate).parameters),
                         ['package_ref', 'coverage_spec', 'baseline_ref'])

    def test_knowledge_package_is_closed_versioned_and_stable(self):
        self.assertIs(parse_knowledge_package(self.package), self.package)
        self.assertEqual(knowledge_package_digest(self.package), self.package['content_digest'])
        self.assertEqual(knowledge_package_digest(self.package),
                         knowledge_package_digest(dict(reversed(list(self.package.items())))))
        self.assertEqual(self.package_ref, {
            'package_id': 'package-1', 'version': 1,
            'digest': knowledge_package_digest(self.package),
        })
        parse_package_ref(self.package_ref)
        changed = copy.deepcopy(self.package)
        changed['unexpected'] = True
        with self.assertRaises(ContractError):
            parse_knowledge_package(changed)
        changed = copy.deepcopy(self.package)
        changed['claims'][0]['text'] = '未重新摘要的修改'
        with self.assertRaises(ContractError):
            parse_knowledge_package(changed)

    def test_evidence_relations_are_not_single_value_evidence_state(self):
        relations = self.package['relations']
        self.assertEqual([item['relation'] for item in relations],
                         ['supports', 'contradicts', 'qualifies'])
        self.assertEqual(relations[0]['evidence_id'], relations[1]['evidence_id'])
        self.assertNotEqual(relations[0]['claim_id'], relations[1]['claim_id'])
        evidence = copy.deepcopy(self.package['evidence'][0])
        evidence['relation'] = 'supports'
        with self.assertRaises(ContractError):
            parse_evidence(evidence)
        self.assertEqual({item['status'] for item in self.package['conflicts']},
                         {'resolved', 'unresolved'})
        self.assertTrue(self.package['existing_knowledge'])

    def test_package_rejects_broken_source_claim_and_conflict_references(self):
        cases = [
            ('relations', 0, 'claim_id', 'missing-claim'),
            ('relations', 0, 'evidence_id', 'missing-evidence'),
            ('evidence', 0, 'source_digest', B),
            ('conflicts', 0, 'status', 'resolved'),
        ]
        for field, index, key, value in cases:
            refs = copy.deepcopy(self.source_refs)
            claims = copy.deepcopy(self.claims)
            conflicts = copy.deepcopy(self.conflicts)
            target = refs if field in refs else {'conflicts': conflicts}
            target[field][index][key] = value
            if field == 'conflicts' and key == 'status':
                target[field][index]['resolution'] = None
            with self.subTest(field=field, key=key), self.assertRaises(ContractError):
                build_package(refs, claims, conflicts)

    def test_evidence_locator_must_be_inside_source_readable_range(self):
        from tools.wiki_runtime.evidence import evidence_digest
        for boundary in ('below', 'above'):
            refs = copy.deepcopy(self.source_refs)
            if boundary == 'below':
                refs['sources'][0]['readable_range']['start_line'] = 5
            else:
                refs['evidence'][0]['locator'] = {'start_line': 100, 'end_line': 110}
                for relation in refs['relations']:
                    if relation['evidence_id'] == 'evidence-1':
                        relation['evidence_digest'] = evidence_digest(refs['evidence'][0])
            with self.subTest(boundary=boundary), self.assertRaises(ContractError):
                build_package(refs, self.claims, self.conflicts)

    def test_all_outputs_learning_and_candidate_share_package_binding(self):
        artifacts = [render(self.package_ref, kind, self.output_policy(kind))
                     for kind in ['lesson', 'article', 'video_script']]
        for artifact in artifacts:
            parse_output_artifact(artifact)
            self.assertTrue(package_binding_matches(artifact, self.package))
        parse_learning_plan(self.plan)
        parse_candidate_preview(self.preview)
        self.assertTrue(package_binding_matches(self.plan, self.package))
        self.assertTrue(package_binding_matches(self.preview, self.package))
        changed_refs = copy.deepcopy(self.source_refs)
        changed_refs['version'] = 2
        changed = build_package(changed_refs, self.claims, self.conflicts)
        for bound in artifacts + [self.plan, self.preview]:
            with self.subTest(bound=bound.get('artifact_id', bound.get('plan_id', 'candidate'))):
                self.assertFalse(package_binding_matches(bound, changed))

    def output_policy(self, output_type):
        return {
            'artifact_id': f'artifact-{output_type}', 'content': f'{output_type} 内容',
            'evidence_map': [{'claim_id': 'claim-a', 'evidence_ids': ['evidence-1']}],
            'quality_standard': f'{output_type}-quality-v1',
            'semantic_change': 'none', 'reason': '',
        }

    def test_new_semantics_return_revision_request_without_mutating_package(self):
        before = knowledge_package_digest(self.package)
        for change in ['new_fact', 'conclusion_change', 'scope_expansion']:
            policy = self.output_policy('lesson')
            policy['semantic_change'] = change
            policy['reason'] = '输出引入了包外语义'
            with self.subTest(change=change):
                request = render(self.package_ref, 'lesson', policy)
                self.assertIs(parse_knowledge_revision_request(request), request)
                self.assertEqual(request['change_kind'], change)
                self.assertEqual(request['package_ref'], self.package_ref)
                self.assertEqual(knowledge_package_digest(self.package), before)

    def test_new_output_type_needs_only_expression_and_quality_standard(self):
        artifact = render(self.package_ref, 'audio_script', self.output_policy('audio_script'))
        self.assertEqual(artifact['output_type'], 'audio_script')
        self.assertEqual(artifact['quality']['standard'], 'audio_script-quality-v1')
        self.assertRegex(output_artifact_digest(artifact), r'^[0-9a-f]{64}$')
        policy = self.output_policy('audio_script')
        policy['quality_standard'] = ''
        with self.assertRaises(ContractError):
            render(self.package_ref, 'audio_script', policy)

    def test_learning_records_are_separate_and_digest_bound(self):
        for record, parser, digest_function in [
            (self.objective, parse_objective, objective_digest),
            (self.rubric, parse_rubric, rubric_digest),
            (self.template, parse_rubric_template, rubric_template_digest),
            (self.evaluator, parse_evaluator, evaluator_digest),
            (self.calibration, parse_calibration, calibration_digest),
            (self.assessment, parse_assessment, assessment_digest),
            (self.plan, parse_learning_plan, learning_plan_digest),
        ]:
            with self.subTest(record=record.get('objective_id', record.get('plan_id', 'record'))):
                self.assertIs(parser(record), record)
                self.assertRegex(digest_function(record), r'^[0-9a-f]{64}$')
        self.assertNotIn('rubric', self.objective)
        self.assertNotIn('assessments', self.plan)

    def test_objective_prerequisites_are_bound_and_plan_rejects_self_dependency(self):
        objective = copy.deepcopy(self.objective)
        objective['prerequisite_objectives'] = ['external-foundation']
        parse_objective(objective)
        plan = prepare(self.package_ref, [objective])
        self.assertEqual(plan['objectives'][0]['prerequisite_objectives'], ['external-foundation'])
        changed = copy.deepcopy(objective)
        changed['prerequisite_objectives'] = ['other-foundation']
        self.assertNotEqual(objective_digest(objective), objective_digest(changed))
        objective['prerequisite_objectives'] = ['objective-core']
        with self.assertRaises(ContractError):
            prepare(self.package_ref, [objective])
        objective['prerequisite_objectives'] = ['external-foundation', 'external-foundation']
        with self.assertRaises(ContractError):
            parse_objective(objective)

    def make_independent_opinion(self, credential_id, role, content_digest, kind, objectives):
        return {
            'credential_id': credential_id, 'learning_task_id': 'task-1',
            'invocation_id': f'invocation-{credential_id}', 'role': role,
            'identity': f'independent-{role}', 'independent': True,
            'content_digest': content_digest, 'evidence_digest': B,
            'dependencies_digest': C, 'rules_digest': D, 'prompt_digest': F,
            'validator_version': 'opinion-v1', 'review_config_digest': A,
            'scope': {'kind': kind, 'objective_ids': objectives,
                      'candidate_digest': public_candidate_digest(self.candidate),
                      'package_ref': self.package_ref},
            'result': 'pass', 'valid': True,
        }

    def make_assessor_review(self):
        return self.make_independent_opinion(
            'assessor-opinion-1', 'Assessor', assessment_digest(self.assessment),
            'understanding_assessment', ['objective-core'])

    def make_final_review(self):
        coverage = {
            'candidate_id': self.preview['candidate_id'],
            'candidate_changes': self.preview['candidate_changes'],
            'dispositions': self.preview['coverage'],
        }
        return self.make_independent_opinion(
            'final-reviewer-1', 'Reviewer', coverage_spec_digest(coverage),
            'final_candidate_coverage', ['objective-core', 'objective-optional'])

    def test_claim_attribution_and_relation_bind_evidence_version(self):
        refs = copy.deepcopy(self.source_refs)
        claims = copy.deepcopy(self.claims)
        for claim, attribution in zip(claims, ['source', 'source']):
            claim['attribution'] = attribution
        evidence_by_id = {item['evidence_id']: item for item in refs['evidence']}
        for relation in refs['relations']:
            relation['evidence_digest'] = evidence_digest(evidence_by_id[relation['evidence_id']])
        package = build_package(refs, claims, self.conflicts)
        self.assertEqual(package['claims'][0]['attribution'], 'source')
        refs['evidence'][0]['excerpt'] = '证据内容已变化'
        with self.assertRaises(ContractError):
            build_package(refs, claims, self.conflicts)

    def test_learning_plan_rejects_internal_cycles_but_allows_external_prerequisites(self):
        first = copy.deepcopy(self.objective)
        second = copy.deepcopy(self.objective)
        first['objective_id'] = 'objective-a'
        first['prerequisite_objectives'] = ['objective-b', 'external-foundation']
        second['objective_id'] = 'objective-b'
        second['prerequisite_objectives'] = ['objective-a']
        with self.assertRaises(ContractError):
            prepare(self.package_ref, [first, second])
        second['prerequisite_objectives'] = ['external-foundation']
        prepare(self.package_ref, [first, second])

    def test_rubric_review_requires_reviewer_and_objective_actual_rubric_binding(self):
        from tools.wiki_runtime.runtime import review_credential_digest
        context = copy.deepcopy(self.learning_context)
        assessment = copy.deepcopy(self.assessment)
        context['rubric_review']['role'] = 'Assessor'
        assessment['rubric_review_digest'] = review_credential_digest(context['rubric_review'])
        self.assertFalse(assessment_l2_valid(assessment, context))
        context = copy.deepcopy(self.learning_context)
        assessment = copy.deepcopy(self.assessment)
        context['objective']['rubric_id'] = 'other-rubric'
        assessment['objective_digest'] = objective_digest(context['objective'])
        self.assertFalse(assessment_l2_valid(assessment, context))

    def test_assessment_requires_independent_assessor_opinion_on_exact_content(self):
        context = dict(self.learning_context, assessor_review=self.make_assessor_review())
        self.assertTrue(assessment_l2_valid(self.assessment, context))
        missing = copy.deepcopy(context)
        del missing['assessor_review']
        self.assertFalse(assessment_l2_valid(self.assessment, missing))
        unrelated = copy.deepcopy(context)
        unrelated['assessor_review']['content_digest'] = A
        self.assertFalse(assessment_l2_valid(self.assessment, unrelated))

    def test_certify_readiness_derives_coverage_assessments_and_reviewers(self):
        from tools.wiki_runtime.runtime import certify_readiness
        assessor = self.make_assessor_review()
        reviewer = self.make_final_review()
        records = [dict(self.learning_context, assessment=self.assessment,
                        assessor_review=assessor)]
        readiness = certify_readiness(
            self.candidate, self.preview, records, reviewer, learning_task_id='task-1',
            raw_batch_id='batch-1', evidence_digest=B, dependencies_digest=C, rules_digest=D)
        self.assertEqual(readiness['candidate_digest'], public_candidate_digest(self.candidate))
        self.assertNotEqual(readiness['candidate_digest'], candidate_preview_digest(self.preview))
        self.assertRegex(readiness['coverage_digest'], r'^[0-9a-f]{64}$')
        self.assertRegex(readiness['assessments_digest'], r'^[0-9a-f]{64}$')
        self.assertEqual({item['role'] for item in readiness['required_credentials']},
                         {'Assessor', 'Reviewer'})
        self.assertNotIn('authorization', readiness)
        with self.assertRaises(ContractError):
            certify_readiness(
                self.candidate, self.preview, [], reviewer, learning_task_id='task-1',
                raw_batch_id='batch-1', evidence_digest=B, dependencies_digest=C, rules_digest=D)
        wrong_reviewer = copy.deepcopy(reviewer)
        wrong_reviewer['content_digest'] = A
        with self.assertRaises(ContractError):
            certify_readiness(
                self.candidate, self.preview, records, wrong_reviewer, learning_task_id='task-1',
                raw_batch_id='batch-1', evidence_digest=B, dependencies_digest=C, rules_digest=D)

    def test_cross_task_rubric_review_is_rejected_after_full_rebinding(self):
        from tools.wiki_runtime.runtime import certify_readiness, review_credential_digest
        context = copy.deepcopy(self.learning_context)
        context['rubric_review']['learning_task_id'] = 'task-other'
        assessment = copy.deepcopy(self.assessment)
        assessment['rubric_review_digest'] = review_credential_digest(context['rubric_review'])
        assessor = self.make_independent_opinion(
            'assessor-opinion-1', 'Assessor', assessment_digest(assessment),
            'understanding_assessment', ['objective-core'])
        records = [dict(context, assessment=assessment, assessor_review=assessor)]
        self.assertFalse(assessment_l2_valid(assessment, records[0]))
        with self.assertRaises(ContractError):
            certify_readiness(
                self.candidate, self.preview, records, self.make_final_review(),
                learning_task_id='task-1', raw_batch_id='batch-1', evidence_digest=B,
                dependencies_digest=C, rules_digest=D)

    def test_template_and_calibration_must_both_apply_to_objective_type(self):
        for template_types, calibration_types in [
            (['concept'], ['mechanism']),
            (['mechanism'], ['mechanism', 'concept']),
        ]:
            context = copy.deepcopy(self.learning_context)
            assessment = copy.deepcopy(self.assessment)
            context['rubric_template']['applicable_objective_types'] = template_types
            context['calibration']['objective_types'] = calibration_types
            template_digest = rubric_template_digest(context['rubric_template'])
            context['calibration']['rubric_template_digest'] = template_digest
            assessment['rubric_template_digest'] = template_digest
            assessment['calibration_digest'] = calibration_digest(context['calibration'])
            with self.subTest(template=template_types, calibration=calibration_types):
                self.assertFalse(assessment_l2_valid(assessment, context))

    def test_assessment_l2_requires_all_actual_versions_and_digests(self):
        self.assertTrue(assessment_l2_valid(self.assessment, self.learning_context))
        for field in ['objective_digest', 'rubric_digest', 'rubric_template_digest',
                      'evaluator_digest', 'calibration_digest', 'rubric_review_digest']:
            assessment = copy.deepcopy(self.assessment)
            assessment[field] = '1' * 64
            with self.subTest(binding=field):
                self.assertFalse(assessment_l2_valid(assessment, self.learning_context))
        for field in ['rubric_version', 'rubric_template_version', 'evaluator_version']:
            assessment = copy.deepcopy(self.assessment)
            assessment[field] += 1
            with self.subTest(version=field):
                self.assertFalse(assessment_l2_valid(assessment, self.learning_context))

    def test_l2_requires_applicable_calibration_independent_response_and_rubric_review(self):
        self.assertTrue(assessment_l2_valid(self.assessment, self.learning_context))
        for field, value in [('independent', False), ('assistance', 'hinted'),
                             ('evidence_type', 'worked_procedure')]:
            assessment = copy.deepcopy(self.assessment)
            assessment['response_evidence'][field] = value
            with self.subTest(response=field):
                self.assertFalse(assessment_l2_valid(assessment, self.learning_context))
        for target in ['calibration', 'rubric_review']:
            context = copy.deepcopy(self.learning_context)
            del context[target]
            with self.subTest(missing=target):
                self.assertFalse(assessment_l2_valid(self.assessment, context))
        context = copy.deepcopy(self.learning_context)
        context['calibration']['objective_types'] = ['concept']
        self.assertFalse(assessment_l2_valid(self.assessment, context))
        context = copy.deepcopy(self.learning_context)
        context['rubric_review']['valid'] = False
        self.assertFalse(assessment_l2_valid(self.assessment, context))

    def test_unrelated_template_calibration_cannot_replace_lesson_evidence_review(self):
        context = copy.deepcopy(self.learning_context)
        context['rubric_review']['content_digest'] = A
        self.assertFalse(assessment_l2_valid(self.assessment, context))
        context = copy.deepcopy(self.learning_context)
        context['rubric_review']['scope']['kind'] = 'unrelated_template'
        self.assertFalse(assessment_l2_valid(self.assessment, context))

    def test_coverage_spec_is_planning_only_and_preview_has_no_readiness(self):
        parse_coverage_spec(self.coverage_spec)
        self.assertEqual(self.preview['state'], 'preview')
        self.assertNotIn('readiness', self.preview)
        self.assertNotIn('assessments', self.preview)
        self.assertRegex(coverage_spec_digest(self.coverage_spec), r'^[0-9a-f]{64}$')
        self.assertRegex(candidate_preview_digest(self.preview), r'^[0-9a-f]{64}$')
        for forbidden in ['assessment', 'assessments', 'review_credential', 'readiness', 'passed']:
            spec = copy.deepcopy(self.coverage_spec)
            spec[forbidden] = {'result': 'pass'} if forbidden != 'passed' else True
            with self.subTest(forbidden=forbidden), self.assertRaises(ContractError):
                parse_coverage_spec(spec)

    def test_required_and_reuse_need_l2_but_optional_and_non_teaching_do_not(self):
        self.assertTrue(validate_final_coverage(self.preview, self.understanding_records))
        self.assertFalse(validate_final_coverage(self.preview, []))
        spec = copy.deepcopy(self.coverage_spec)
        spec['dispositions'][0]['teaching_disposition'] = 'reuse_objective'
        preview = compile_candidate(self.package_ref, spec, 'baseline-1')
        self.assertTrue(validate_final_coverage(preview, self.understanding_records))
        self.assertFalse(validate_final_coverage(preview, []))
        spec = copy.deepcopy(self.coverage_spec)
        spec['candidate_changes'] = spec['candidate_changes'][1:]
        spec['dispositions'] = spec['dispositions'][1:]
        preview = compile_candidate(self.package_ref, spec, 'baseline-1')
        self.assertTrue(validate_final_coverage(preview, []))

    def test_candidate_ab_requires_coverage_for_both_a_and_b(self):
        spec = copy.deepcopy(self.coverage_spec)
        del spec['dispositions'][1]
        with self.assertRaises(ContractError):
            compile_candidate(self.package_ref, spec, 'baseline-1')
        preview = copy.deepcopy(self.preview)
        del preview['coverage'][1]
        self.assertFalse(validate_final_coverage(preview, self.understanding_records))

    def test_unknown_duplicate_and_unreasoned_coverage_are_rejected(self):
        unknown = copy.deepcopy(self.coverage_spec['dispositions'][0])
        unknown['change_id'] = 'change-unknown'
        duplicate = copy.deepcopy(self.coverage_spec['dispositions'][0])
        for name, disposition in [('unknown', unknown), ('duplicate', duplicate)]:
            spec = copy.deepcopy(self.coverage_spec)
            spec['dispositions'].append(disposition)
            with self.subTest(case=name), self.assertRaises(ContractError):
                parse_coverage_spec(spec)
        spec = copy.deepcopy(self.coverage_spec)
        spec['dispositions'][0]['reason'] = ''
        with self.assertRaises(ContractError):
            parse_coverage_spec(spec)
        for disposition in self.coverage_spec['dispositions']:
            parse_coverage_disposition(disposition)
            self.assertRegex(coverage_disposition_digest(disposition), r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
