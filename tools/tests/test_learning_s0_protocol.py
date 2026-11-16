"""S0 私有核心协议的正反例；只使用合成记录，不实现真实运行时。"""
import copy
import inspect
import json
from pathlib import Path
import unittest

from tools.wiki_runtime.contracts import ContractError, digest
from tools.wiki_runtime.runtime import (
    INVOCATION_PORT_CONSUMERS, InvocationPort, acceptance_check, admission_digest,
    authorization_digest, check_execution_ownership, execution_ownership_digest,
    execution_result_binding_digest, invocation_digest, invocation_spec_digest,
    lookup_terminal, new_invocation, parse_admission, parse_authorization,
    parse_execution_ownership, parse_execution_result_binding, parse_invocation,
    parse_invocation_spec, parse_readiness, parse_review_credential, parse_run,
    parse_task, plan_executor_acceptance, project_execution_result, readiness_digest,
    replay_invocation, review_credential_digest, run_digest, task_digest,
    transition_invocation,
)

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'learning_s0' / 'protocol_records.json'


def fixture():
    return json.loads(FIXTURES.read_text(encoding='utf-8'))


def rebind_candidate(context, admission):
    from tools.wiki_runtime.contracts import candidate_digest
    public_digest = candidate_digest(context['candidate'])
    context['candidate_digest'] = public_digest
    context['authorization']['candidate_digest'] = public_digest
    context['readiness']['candidate_digest'] = public_digest
    admission['candidate_digest'] = public_digest
    context['understanding_records'][0]['assessor_review']['scope']['candidate_digest'] = public_digest
    context['final_review_credential']['scope']['candidate_digest'] = public_digest
    context['review_credentials'] = [
        copy.deepcopy(context['understanding_records'][0]['assessor_review']),
        copy.deepcopy(context['final_review_credential']),
    ]
    for requirement in context['readiness']['required_credentials']:
        credential = next(item for item in context['review_credentials']
                          if item['credential_id'] == requirement['credential_ref'])
        requirement['credential_digest'] = review_credential_digest(credential)
    rebound = readiness_digest(context['readiness'])
    context['authorization']['readiness_digest'] = rebound
    admission['readiness_digest'] = rebound


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = fixture()

    def setUp(self):
        self.valid = copy.deepcopy(self.records['valid'])
        self.invalid = copy.deepcopy(self.records['invalid'])
        self.context = copy.deepcopy(self.valid['executor_context'])
        self.context['readiness'] = copy.deepcopy(self.valid['readiness'])
        self.context['authorization'] = copy.deepcopy(self.valid['authorization'])
        self.context['review_credentials'] = copy.deepcopy(self.valid['review_credentials'])
        self.admission = copy.deepcopy(self.valid['admission'])

    def test_every_record_has_a_parser_and_stable_digest(self):
        cases = [
            ('task', parse_task, task_digest),
            ('run', parse_run, run_digest),
            ('invocation_spec', parse_invocation_spec, invocation_spec_digest),
            ('invocation', parse_invocation, invocation_digest),
            ('ownership', parse_execution_ownership, execution_ownership_digest),
            ('readiness', parse_readiness, readiness_digest),
            ('authorization', parse_authorization, authorization_digest),
            ('admission', parse_admission, admission_digest),
        ]
        for name, parser, digest_function in cases:
            with self.subTest(record=name):
                record = self.valid[name]
                self.assertIs(parser(record), record)
                value = digest_function(record)
                self.assertRegex(value, r'^[0-9a-f]{64}$')
                self.assertEqual(value, digest_function(dict(reversed(list(record.items())))))
        for index, credential in enumerate(self.valid['review_credentials']):
            with self.subTest(record='review_credential', index=index):
                self.assertIs(parse_review_credential(credential), credential)
                self.assertRegex(review_credential_digest(credential), r'^[0-9a-f]{64}$')
        for name, record in self.valid['execution_results'].items():
            with self.subTest(record='execution_result', state=name):
                self.assertIs(parse_execution_result_binding(record), record)
                self.assertRegex(execution_result_binding_digest(record), r'^[0-9a-f]{64}$')

    def test_records_are_closed_and_run_has_no_authoritative_budget(self):
        for name, parser in [('task', parse_task), ('run', parse_run), ('invocation', parse_invocation)]:
            record = copy.deepcopy(self.valid[name])
            record['authoritative_budget'] = {}
            with self.subTest(record=name), self.assertRaises(ContractError):
                parser(record)
        with self.assertRaises(ContractError):
            parse_readiness(self.invalid['unauthorized_readiness'])
        readiness = copy.deepcopy(self.valid['readiness'])
        readiness['authorization'] = self.valid['authorization']
        with self.assertRaises(ContractError):
            parse_readiness(readiness)

    def test_invocation_binds_atomic_checks_and_reservation(self):
        invocation = copy.deepcopy(self.valid['invocation'])
        self.assertEqual(invocation['reservation']['budget'],
                         invocation['spec']['requested_budget'])
        self.assertEqual(set(invocation['limit_check']),
                         {'task', 'run', 'concurrency', 'final_review_reserve'})
        for check in invocation['limit_check']:
            record = copy.deepcopy(invocation)
            record['limit_check'][check] = 'skipped'
            with self.subTest(check=check), self.assertRaises(ContractError):
                parse_invocation(record)
        record = copy.deepcopy(invocation)
        record['spec_digest'] = '0' * 64
        with self.assertRaises(ContractError):
            parse_invocation(record)
        record = copy.deepcopy(invocation)
        record['reservation']['budget']['model_calls'] = 2
        with self.assertRaises(ContractError):
            parse_invocation(record)

    def test_successful_replay_returns_saved_result_without_new_usage(self):
        record = copy.deepcopy(self.valid['invocation'])
        before = invocation_digest(record)
        result = replay_invocation(record, self.valid['invocation_spec'])
        self.assertEqual(result, {'output': 'candidate-ok'})
        self.assertEqual(invocation_digest(record), before)
        self.assertEqual(record['settlement']['actual_usage']['tokens'], 120)
        result['output'] = 'changed-by-caller'
        self.assertEqual(record['result']['output'], 'candidate-ok')

    def test_replay_rejects_different_spec_and_cross_task_or_run(self):
        for name in ['different_input_spec', 'cross_task_spec', 'cross_run_spec']:
            with self.subTest(case=name), self.assertRaises(ContractError):
                replay_invocation(self.valid['invocation'], self.invalid[name])
        cross_runtime_task = copy.deepcopy(self.valid['invocation_spec'])
        cross_runtime_task['task_id'] = 'task-other'
        with self.assertRaises(ContractError):
            replay_invocation(self.valid['invocation'], cross_runtime_task)

    def test_invocation_lifecycle_reserves_sends_returns_and_settles_once(self):
        initial = new_invocation(self.valid['invocation_spec'])
        self.assertEqual(initial['send_state'], 'not_sent')
        self.assertEqual(initial['reservation']['state'], 'reserved')
        self.assertEqual(initial['settlement']['state'], 'unsettled')
        sent = transition_invocation(initial, 'send')
        self.assertEqual(initial['send_state'], 'not_sent')
        returned = transition_invocation(sent, 'result', result={'output': 'candidate-ok'})
        settled = transition_invocation(returned, 'settle', actual_usage={
            'requests': 1, 'pages': 2, 'input_bytes': 512, 'model_calls': 1,
            'active_seconds': 8.5, 'repairs': 0, 'appeals': 0, 'tokens': 120,
        })
        self.assertEqual(settled, self.valid['invocation'])
        for action in ['send', 'result', 'unknown', 'settle', 'release']:
            with self.subTest(action=action), self.assertRaises(ContractError):
                transition_invocation(settled, action, result={'output': 'again'},
                                      actual_usage={'model_calls': 1}, proof_not_sent=True)

    def test_unknown_never_resends_replays_or_releases_reservation(self):
        record = new_invocation(self.valid['invocation_spec'])
        record = transition_invocation(record, 'send')
        unknown = transition_invocation(record, 'unknown')
        self.assertEqual(unknown['result_state'], 'unknown')
        self.assertEqual(unknown['reservation']['state'], 'reserved')
        with self.assertRaises(ContractError):
            replay_invocation(unknown, self.valid['invocation_spec'])
        for action in ['send', 'release']:
            with self.subTest(action=action), self.assertRaises(ContractError):
                transition_invocation(unknown, action, proof_not_sent=True)
        settled = transition_invocation(unknown, 'settle', actual_usage={
            'requests': 1, 'pages': 2, 'input_bytes': 512, 'model_calls': 1,
            'active_seconds': 10.0, 'repairs': 0, 'appeals': 0, 'tokens': None,
        })
        self.assertEqual(settled['reservation']['state'], 'reserved')
        self.assertIsNone(settled['settlement']['actual_usage']['tokens'])

    def test_only_proven_unsent_invocation_can_release(self):
        record = new_invocation(self.valid['invocation_spec'])
        with self.assertRaises(ContractError):
            transition_invocation(record, 'release')
        released = transition_invocation(record, 'release', proof_not_sent=True)
        self.assertEqual(released['reservation']['state'], 'released')
        self.assertEqual(released['settlement']['state'], 'released')
        with self.assertRaises(ContractError):
            transition_invocation(released, 'send')

    def test_all_roles_share_one_minimal_invocation_port(self):
        class FakePort:
            def invoke(self, spec, call, timeout):
                return call()

            def replay(self, spec):
                return None

            def remaining_run_time(self, run_id):
                return 1.0

        self.assertEqual(INVOCATION_PORT_CONSUMERS,
                         ('Worker', 'Reviewer', 'RuleAuditor', 'ExecutorG3'))
        port = FakePort()
        self.assertIsInstance(port, InvocationPort)
        for consumer in INVOCATION_PORT_CONSUMERS:
            with self.subTest(consumer=consumer):
                spec = copy.deepcopy(self.valid['invocation_spec'])
                spec['role'] = consumer
                parse_invocation_spec(spec)
        self.assertEqual(list(inspect.signature(InvocationPort.invoke).parameters),
                         ['self', 'spec', 'call', 'timeout'])
        self.assertFalse(hasattr(InvocationPort, 'reserve_call'))

    def test_budget_units_include_pages_and_actual_nullable_tokens(self):
        spec = copy.deepcopy(self.valid['invocation_spec'])
        spec['requested_budget']['pages'] = 2
        parse_invocation_spec(spec)
        record = transition_invocation(new_invocation(spec), 'send')
        record = transition_invocation(record, 'result', result={'output': 'ok'})
        usage = copy.deepcopy(self.valid['invocation']['settlement']['actual_usage'])
        usage['pages'] = 2
        usage['tokens'] = None
        settled = transition_invocation(record, 'settle', actual_usage=usage)
        self.assertEqual(settled['settlement']['actual_usage']['pages'], 2)
        self.assertIsNone(settled['settlement']['actual_usage']['tokens'])
        with self.assertRaises(ContractError):
            spec['requested_budget']['tokens'] = None
            parse_invocation_spec(spec)

    def test_collection_authorization_is_restricted_and_separate_from_ingest(self):
        from tools.wiki_runtime.runtime import (
            collection_authorization_digest, parse_collection_authorization,
            validate_collection_authorization,
        )
        record = {
            'authorization_ref': 'collection-1', 'action': 'capture',
            'learning_task_id': 'task-learning-1', 'operation_id': 'capture-operation-1',
            'scope_digest': '5' * 64, 'rules_digest': '6' * 64, 'state': 'issued',
        }
        self.assertIs(parse_collection_authorization(record), record)
        self.assertRegex(collection_authorization_digest(record), r'^[0-9a-f]{64}$')
        expected = {
            'action': 'capture', 'learning_task_id': 'task-learning-1',
            'operation_id': 'capture-operation-1', 'scope_digest': '5' * 64,
            'rules_digest': '6' * 64,
        }
        self.assertTrue(validate_collection_authorization(record, **expected))
        for action in ['import']:
            record['action'] = action
            self.assertTrue(validate_collection_authorization(
                record, **dict(expected, action=action)))
        for invalid in ['ingest', 'approve']:
            record['action'] = invalid
            with self.subTest(action=invalid), self.assertRaises(ContractError):
                parse_collection_authorization(record)
        record = copy.deepcopy(self.valid['authorization'])
        record['action'] = 'capture'
        with self.assertRaises(ContractError):
            parse_collection_authorization(record)

    def test_acceptance_rederives_credentials_instead_of_trusting_empty_readiness(self):
        self.assertTrue(acceptance_check(self.context, self.admission))
        readiness = copy.deepcopy(self.context['readiness'])
        readiness['required_credentials'] = []
        rebound = digest(readiness)
        context = copy.deepcopy(self.context)
        context['readiness'] = readiness
        context['authorization']['readiness_digest'] = rebound
        admission = copy.deepcopy(self.admission)
        admission['readiness_digest'] = rebound
        self.assertFalse(acceptance_check(context, admission))

    def test_acceptance_rechecks_assessment_assessor_reviewer_and_every_objective(self):
        self.assertTrue(acceptance_check(self.context, self.admission))
        mutations = ['assessment_content', 'assessor_content', 'reviewer_content',
                     'missing_assessor', 'new_required_objective']
        for mutation in mutations:
            context = copy.deepcopy(self.context)
            if mutation == 'assessment_content':
                context['understanding_records'][0]['assessment']['response_evidence']['content_digest'] = '1' * 64
            elif mutation == 'assessor_content':
                context['understanding_records'][0]['assessor_review']['content_digest'] = '1' * 64
            elif mutation == 'reviewer_content':
                context['final_review_credential']['content_digest'] = '1' * 64
            elif mutation == 'missing_assessor':
                del context['understanding_records'][0]['assessor_review']
            else:
                context['candidate_preview']['coverage'][1]['teaching_disposition'] = 'reuse_objective'
            with self.subTest(mutation=mutation):
                self.assertFalse(acceptance_check(context, self.admission))

    def test_public_candidate_identity_flows_through_readiness_admission_and_result(self):
        from tools.wiki_runtime.contracts import candidate_digest, validate
        from tools.wiki_runtime.persistence import candidate_preview_digest
        from tools.wiki_runtime.runtime import validate_execution_result_binding
        candidate = self.valid['candidate']
        validate('candidate', candidate)
        public_digest = candidate_digest(candidate)
        self.assertNotEqual(public_digest, candidate_preview_digest(self.context['candidate_preview']))
        self.assertEqual(self.context['readiness']['candidate_digest'], public_digest)
        self.assertEqual(self.admission['candidate_digest'], public_digest)
        for credential in self.context['review_credentials']:
            self.assertEqual(credential['scope']['candidate_digest'], public_digest)
        for result in self.valid['execution_results'].values():
            validate_execution_result_binding(result, self.admission)
        self.assertTrue(acceptance_check(self.context, self.admission))

    def test_cross_task_rubric_review_is_rejected_after_full_rebinding(self):
        from tools.wiki_runtime.learning.artifact_protocol import assessment_digest
        context = copy.deepcopy(self.context)
        record = context['understanding_records'][0]
        record['rubric_review']['learning_task_id'] = 'task-other'
        record['assessment']['rubric_review_digest'] = review_credential_digest(
            record['rubric_review'])
        content_digest = assessment_digest(record['assessment'])
        record['assessor_review']['content_digest'] = content_digest
        context['review_credentials'][0] = copy.deepcopy(record['assessor_review'])
        readiness = context['readiness']
        readiness['required_credentials'][0]['content_digest'] = content_digest
        readiness['required_credentials'][0]['credential_digest'] = review_credential_digest(
            record['assessor_review'])
        readiness['assessments_digest'] = digest([content_digest])
        rebound = readiness_digest(readiness)
        context['authorization']['readiness_digest'] = rebound
        admission = copy.deepcopy(self.admission)
        admission['readiness_digest'] = rebound
        self.assertFalse(acceptance_check(context, admission))

    def test_actual_candidate_changes_must_match_coverage_after_full_rebinding(self):
        for mutation in ('path', 'action', 'source'):
            context = copy.deepcopy(self.context)
            admission = copy.deepcopy(self.admission)
            change = context['candidate']['changes'][0]
            if mutation == 'path':
                change['path'] = 'wiki/uncovered.md'
            else:
                change['action'] = 'move'
                change['source'] = 'raw/unprocessed/a.md'
                change['source_sha256'] = 'a' * 64
                if mutation == 'source':
                    from tools.wiki_runtime.persistence import coverage_spec_digest
                    planned = context['candidate_preview']['candidate_changes'][0]
                    planned['action'] = 'move'
                    planned['source'] = 'raw/unprocessed/other.md'
                    preview = context['candidate_preview']
                    coverage = {
                        'candidate_id': preview['candidate_id'],
                        'candidate_changes': preview['candidate_changes'],
                        'dispositions': preview['coverage'],
                    }
                    coverage_digest = coverage_spec_digest(coverage)
                    context['final_review_credential']['content_digest'] = coverage_digest
                    context['readiness']['coverage_digest'] = coverage_digest
                    context['readiness']['required_credentials'][1]['content_digest'] = coverage_digest
            rebind_candidate(context, admission)
            with self.subTest(mutation=mutation):
                self.assertFalse(acceptance_check(context, admission))

    def test_candidate_operation_must_match_execution_and_authorization(self):
        context = copy.deepcopy(self.context)
        admission = copy.deepcopy(self.admission)
        for target in (context, context['authorization'], admission):
            target['operation_id'] = 'operation-other'
        self.assertFalse(acceptance_check(context, admission))

    def test_count_budgets_require_nonnegative_integers(self):
        for field in ('requests', 'pages', 'input_bytes', 'model_calls', 'repairs', 'appeals'):
            spec = copy.deepcopy(self.valid['invocation_spec'])
            spec['requested_budget'][field] = 0.25
            with self.subTest(field=field), self.assertRaises(ContractError):
                parse_invocation_spec(spec)
        spec = copy.deepcopy(self.valid['invocation_spec'])
        spec['requested_budget']['active_seconds'] = 0.25
        parse_invocation_spec(spec)

    def test_old_generation_cannot_renew_release_or_submit(self):
        ownership = self.valid['ownership']
        common = {
            'task_id': 'task-1', 'learning_task_id': 'task-learning-1',
            'owner': 'worker-host-1', 'now': 100.0,
        }
        for action in ['renew', 'release', 'business_submit']:
            with self.subTest(action=action, generation='old'):
                self.assertFalse(check_execution_ownership(
                    ownership, action=action, generation=1, **common))
            with self.subTest(action=action, generation='current'):
                self.assertTrue(check_execution_ownership(
                    ownership, action=action, generation=2, **common))
        self.assertFalse(check_execution_ownership(
            ownership, action='business_submit', generation=2, now=1000.0,
            task_id='task-1', learning_task_id='task-learning-1', owner='worker-host-1'))

    def test_accepted_recovery_does_not_require_old_lease(self):
        ownership = self.valid['ownership']
        self.assertTrue(check_execution_ownership(
            ownership, action='recover', task_id='task-1', learning_task_id='task-learning-1',
            owner='expired-owner', generation=1, now=5000.0, accepted=True))
        self.assertFalse(check_execution_ownership(
            ownership, action='recover', task_id='task-1', learning_task_id='task-learning-1',
            owner='worker-host-1', generation=1, now=100.0, accepted=False))

    def test_review_credentials_require_independence_and_complete_scope(self):
        credential = self.valid['review_credentials'][0]
        for field, value in [('independent', False), ('role', 'Worker'), ('invocation_id', '')]:
            record = copy.deepcopy(credential)
            record[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                parse_review_credential(record)
        changed = copy.deepcopy(credential)
        changed['scope']['candidate_digest'] = '5' * 64
        self.assertNotEqual(review_credential_digest(credential), review_credential_digest(changed))

    def test_acceptance_requires_every_complete_binding(self):
        self.assertTrue(acceptance_check(self.context, self.admission))
        for field in self.admission:
            admission = copy.deepcopy(self.admission)
            if field == 'created_generation':
                admission[field] = 1
            elif field.endswith('_digest'):
                admission[field] = '6' * 64
            else:
                admission[field] = 'wrong'
            with self.subTest(binding=field):
                self.assertFalse(acceptance_check(self.context, admission))
        self.assertFalse(acceptance_check(
            self.context, self.invalid['wrong_generation_admission']))

    def test_acceptance_rejects_revoked_missing_stale_and_wrong_credentials(self):
        context = copy.deepcopy(self.context)
        context['authorization'] = self.invalid['revoked_authorization']
        self.assertFalse(acceptance_check(context, self.admission))
        context = copy.deepcopy(self.context)
        del context['authorization']
        self.assertFalse(acceptance_check(context, self.admission))
        context = copy.deepcopy(self.context)
        context['readiness'] = self.invalid['stale_readiness']
        self.assertFalse(acceptance_check(context, self.admission))
        for index in range(len(self.valid['review_credentials'])):
            context = copy.deepcopy(self.context)
            del context['review_credentials'][index]
            with self.subTest(missing=index):
                self.assertFalse(acceptance_check(context, self.admission))
        context = copy.deepcopy(self.context)
        context['review_credentials'][0]['learning_task_id'] = 'task-learning-other'
        self.assertFalse(acceptance_check(context, self.admission))

    def test_terminal_lookup_precedes_new_review_and_budget(self):
        for state in ['applied', 'recovered']:
            context = copy.deepcopy(self.context)
            context['terminal_results'] = [self.valid['execution_results'][state]]
            context['authorization']['state'] = 'revoked'
            with self.subTest(state=state):
                found = lookup_terminal(context, self.admission)
                self.assertEqual(found['state'], state)
                decision = plan_executor_acceptance(context, self.admission)
                self.assertEqual(decision['kind'], 'terminal')
                self.assertEqual(decision['result']['state'], state)
                self.assertFalse(decision['new_review'])
                self.assertFalse(decision['new_budget'])
        self.assertIsNone(lookup_terminal(self.context, self.admission))
        self.assertEqual(plan_executor_acceptance(self.context, self.admission)['kind'], 'proceed')

    def test_terminal_lookup_refuses_wrong_identity_binding(self):
        context = copy.deepcopy(self.context)
        context['terminal_results'] = [self.invalid['wrong_binding']]
        with self.assertRaises(ContractError):
            lookup_terminal(context, self.admission)

    def test_result_projection_distinguishes_applied_recovered_and_incomplete(self):
        applied = project_execution_result(self.valid['execution_results']['applied'])
        self.assertTrue(applied['accepted'])
        self.assertTrue(applied['terminal'])
        self.assertTrue(applied['applied'])
        self.assertTrue(applied['authorization_consumed'])
        recovered = project_execution_result(self.valid['execution_results']['recovered'])
        self.assertTrue(recovered['accepted'])
        self.assertTrue(recovered['terminal'])
        self.assertFalse(recovered['applied'])
        self.assertFalse(recovered['authorization_consumed'])
        for state in ['prepared', 'applying', 'recovery_required']:
            result = self.valid['execution_results'][state]
            projection = project_execution_result(result)
            with self.subTest(state=state):
                self.assertEqual(result['recovery_status'], 'required')
                self.assertTrue(projection['accepted'])
                self.assertFalse(projection['terminal'])
                self.assertFalse(projection['applied'])
                self.assertFalse(projection['authorization_consumed'])
        conflict = project_execution_result(self.valid['execution_results']['conflict'])
        self.assertTrue(conflict['manual_reconciliation'])
        self.assertEqual(conflict['state'], 'recovery_required')
        ordinary = project_execution_result(self.valid['execution_results']['recovery_required'])
        self.assertFalse(ordinary['manual_reconciliation'])

    def test_invalid_state_and_conflict_as_public_state_are_refused(self):
        for name in ['conflict_state', 'wrong_state_binding']:
            with self.subTest(case=name), self.assertRaises(ContractError):
                parse_execution_result_binding(self.invalid[name])


if __name__ == '__main__':
    unittest.main()
