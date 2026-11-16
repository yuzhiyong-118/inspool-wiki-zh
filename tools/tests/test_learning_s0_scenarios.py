"""S0 贯穿场景的结构、阶段边界和既有负向协议验证。"""
import json
from pathlib import Path
import unittest

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'learning_s0' / 'scenarios.json'
SHARED_PROTOCOLS = {
    'task_runtime': 'Task Runtime',
    'invocation': 'Invocation',
    'knowledge_package': 'KnowledgePackage',
    'readiness': 'Readiness',
    'authorization': 'Authorization',
    'executor': 'Executor',
    'budget_ledger': 'Invocation',
    'acceptance_record': 'Executor first complete WAL',
}
REQUIRED_MARKERS = {
    'invocation_replay_binding', 'invocation_unknown_conservative', 'ownership_old_generation',
    'acceptance_current_authorization_readiness_credentials', 'terminal_replay_no_new_work',
    'accepted_recovery_without_lease', 'recovered_not_applied',
    'package_version_invalidates_bindings', 'rubric_calibration_misuse', 'candidate_ab_complete',
}


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        cls.scenarios = {item['scenario_id']: item for item in cls.fixture['scenarios']}

    def test_scenario_records_have_required_structure(self):
        self.assertEqual(self.fixture['fixture_version'], '1.0')
        self.assertEqual(set(self.scenarios), {
            'normal-text', 'external-correction', 'cross-session-recovery',
        })
        required = {
            'scenario_id', 'fixture_version', 'input_digest', 'steps', 'expected_state',
            'required_evidence_layers', 'allowed_side_effects', 'stage_ownership',
            'protocol_identity_ref', 'negative_protocol_markers', 'business_acceptance',
        }
        for scenario_id, scenario in self.scenarios.items():
            with self.subTest(scenario=scenario_id):
                self.assertTrue(required <= set(scenario))
                self.assertEqual(scenario['fixture_version'], '1.0')
                self.assertRegex(scenario['input_digest'], r'^[0-9a-f]{64}$')
                self.assertEqual(scenario['protocol_identity_ref'], 'shared-v1')
                self.assertFalse(scenario['business_acceptance'])
                self.assertTrue(scenario['steps'])
                self.assertEqual(set(scenario['required_evidence_layers']),
                                 {'script', 'semantic_review', 'real_host', 'owner'})
                self.assertTrue(scenario['stage_ownership'])

    def test_every_step_has_stage_evidence_side_effects_and_honest_acceptance(self):
        evidence_fields = {'script', 'semantic_review', 'real_host', 'owner'}
        for scenario_id, scenario in self.scenarios.items():
            for step in scenario['steps']:
                with self.subTest(scenario=scenario_id, step=step['step_id']):
                    self.assertIn(step['stage'], {'S0', 'S1', 'S2', 'S3', 'S4', 'S5'})
                    self.assertTrue(step['action'])
                    self.assertTrue(step['expected_state'])
                    self.assertEqual(set(step['required_evidence']), evidence_fields)
                    self.assertIsInstance(step['allowed_side_effects'], list)
                    self.assertIsInstance(step['currently_verifiable'], bool)
                    if step['currently_verifiable']:
                        self.assertEqual(step['stage'], 'S0')
                        self.assertEqual(step['acceptance_status'], 'passed')
                    else:
                        self.assertEqual(step['acceptance_status'], 'not_passed')
                    if step['stage'] != 'S0':
                        self.assertFalse(step['currently_verifiable'])
                        self.assertEqual(step['acceptance_status'], 'not_passed')

    def test_normal_text_flow_separates_ingest_and_approve(self):
        scenario = self.scenarios['normal-text']
        actions = [step['action'] for step in scenario['steps']]
        self.assertEqual(actions, [
            'persist_source', 'build_source_evidence_claim_package', 'render_short_lesson',
            'calibrate_and_independently_assess', 'compile_final_candidate_and_complete_coverage',
            'certify_readiness', 'authorize_ingest_and_execute',
            'independently_authorize_approve_and_execute', 'run_s0_negative_protocols',
        ])
        ingest = scenario['steps'][6]
        approve = scenario['steps'][7]
        self.assertEqual(ingest['operation'], 'ingest')
        self.assertEqual(approve['operation'], 'approve')
        self.assertNotEqual(ingest['operation_id'], approve['operation_id'])
        self.assertNotEqual(ingest['authorization_id'], approve['authorization_id'])
        self.assertFalse(approve['preissued_by_ingest'])
        self.assertTrue(any('actual approve context' in item
                            for item in approve['required_evidence']['owner']))
        self.assertEqual(scenario['expected_state'], 'processed_after_separate_approve')
        steps = {step['action']: step for step in scenario['steps']}
        for action in ['render_short_lesson', 'calibrate_and_independently_assess',
                       'authorize_ingest_and_execute']:
            with self.subTest(invocation_step=action):
                self.assertIn('Invocation', steps[action]['protocols'])

    def test_external_correction_has_independent_capture_and_no_batch_smuggling(self):
        scenario = self.scenarios['external-correction']
        self.assertEqual([step['action'] for step in scenario['steps']], [
            'authorize_independent_capture_import', 'collect_temporary_material', 'register_conflict',
            'persist_correction_source', 'bind_evidence_claim_and_propagate_dependencies',
            'invalidate_affected_learning_objectives', 'relearn_affected_objectives',
            'bind_g3_actual_input_refs', 'persist_knowledge', 'run_s0_negative_protocols',
        ])
        steps = {step['action']: step for step in scenario['steps']}
        capture = steps['authorize_independent_capture_import']
        self.assertEqual(capture['protocols'], ['CollectionAuthorization', 'Task Runtime'])
        self.assertNotIn('Readiness', capture['protocols'])
        self.assertNotIn('CandidatePreview', capture['protocols'])
        self.assertEqual(steps['bind_evidence_claim_and_propagate_dependencies']['stage'], 'S2')
        self.assertEqual(steps['invalidate_affected_learning_objectives']['stage'], 'S3')
        boundary = scenario['capture_boundary']
        self.assertTrue(boundary['independent_authorization'])
        self.assertEqual(boundary['authorization_protocol'], 'CollectionAuthorization')
        self.assertFalse(boundary['advances_original_batch'])
        self.assertFalse(boundary['joins_original_ingest_group'])
        self.assertEqual(boundary['on_later_ingest_failure'], 'retain_legal_capture')
        self.assertFalse(boundary['temporary_directory_is_evidence_substitute'])
        g3 = next(step for step in scenario['steps'] if step['action'] == 'bind_g3_actual_input_refs')
        self.assertEqual(g3['input_refs_kind'], 'persistent_raw_paths')
        self.assertFalse(g3['evidence_metadata_substitute'])
        self.assertTrue(g3['input_refs'])

    def test_cross_session_preserves_budget_and_executor_result_semantics(self):
        scenario = self.scenarios['cross-session-recovery']
        steps = {step['action']: step for step in scenario['steps']}
        self.assertEqual(set(steps), {
            'restore_task_and_run', 'inherit_invocation_budget_and_replay',
            'reject_late_old_generation_submission', 'rebuild_transaction_for_unrelated_library_change',
            'invalidate_related_evidence_locally', 'recover_accepted_executor_transaction_without_old_lease',
            'merge_recovered_as_not_applied', 'run_s0_negative_protocols',
        })
        invocation = steps['inherit_invocation_budget_and_replay']
        self.assertFalse(invocation['new_ledger'])
        self.assertFalse(invocation['new_charge_on_success_replay'])
        self.assertFalse(invocation['unknown_retry'])
        self.assertFalse(invocation['unknown_refund'])
        self.assertFalse(steps['reject_late_old_generation_submission']['renew_release_business_submit_valid'])
        unrelated = steps['rebuild_transaction_for_unrelated_library_change']
        self.assertTrue(unrelated['transaction_rebuilt'])
        self.assertTrue(unrelated['learning_evidence_reused'])
        related = steps['invalidate_related_evidence_locally']
        self.assertFalse(related['learning_evidence_reused'])
        self.assertEqual(related['invalidation_scope'], 'affected_objectives_only')
        recovery = steps['recover_accepted_executor_transaction_without_old_lease']
        self.assertTrue(recovery['accepted'])
        self.assertFalse(recovery['requires_old_lease'])
        recovered = steps['merge_recovered_as_not_applied']
        self.assertFalse(recovered['applied'])
        self.assertFalse(recovered['authorization_consumed'])

    def test_all_scenarios_share_single_runtime_budget_and_acceptance_identities(self):
        identity = self.fixture['protocol_identity']
        self.assertEqual(identity['identity_id'], 'shared-v1')
        for field, value in SHARED_PROTOCOLS.items():
            self.assertEqual(identity[field], value)
        self.assertEqual(identity['budget_ledger'], identity['invocation'])
        allowed = set(SHARED_PROTOCOLS.values()) | {
            'Source', 'Evidence', 'Claim', 'EvidenceClaimRelation', 'CoverageDisposition',
            'CandidatePreview', 'Objective', 'Rubric', 'RubricTemplate', 'Evaluator', 'Assessment',
            'Calibration', 'ReviewCredential', 'ExecutionOwnership', 'ExecutionResultBinding',
            'CollectionAuthorization',
        }
        required = {'Task Runtime', 'Invocation', 'KnowledgePackage', 'Readiness',
                    'Authorization', 'Executor'}
        for scenario_id, scenario in self.scenarios.items():
            self.assertEqual(scenario['protocol_identity_ref'], identity['identity_id'])
            present = {protocol for step in scenario['steps'] for protocol in step['protocols']}
            self.assertTrue(required <= present)
            for step in scenario['steps']:
                with self.subTest(scenario=scenario_id, step=step['step_id']):
                    self.assertTrue(set(step['protocols']) <= allowed)
                    self.assertNotIn('stage_runtime', step)
                    self.assertNotIn('secondary_budget', step)
                    self.assertNotIn('secondary_acceptance_record', step)

    def test_negative_protocol_markers_execute_existing_task1_task2_checks(self):
        found = {}
        for scenario in self.scenarios.values():
            for marker in scenario['negative_protocol_markers']:
                self.assertEqual(marker['acceptance_status'], 'passed')
                self.assertEqual(marker['stage'], 'S0')
                found[marker['marker_id']] = marker['verification_test']
        self.assertEqual(set(found), REQUIRED_MARKERS)
        results = {}
        for marker_id, test_name in found.items():
            with self.subTest(marker=marker_id):
                if test_name not in results:
                    suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
                    result = unittest.TestResult()
                    suite.run(result)
                    results[test_name] = result
                result = results[test_name]
                self.assertEqual(result.testsRun, 1)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_s0_does_not_claim_unimplemented_business_or_real_side_effects(self):
        for scenario_id, scenario in self.scenarios.items():
            with self.subTest(scenario=scenario_id):
                self.assertFalse(scenario['business_acceptance'])
                self.assertTrue(all(not effect.get('executed', False)
                                    for effect in scenario['allowed_side_effects']))
                future = [step for step in scenario['steps'] if step['stage'] != 'S0']
                self.assertTrue(future)
                self.assertTrue(all(step['acceptance_status'] == 'not_passed' for step in future))


if __name__ == '__main__':
    unittest.main()
