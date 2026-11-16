import unittest

from tools.tests import test_learning_book_i3 as i3
from tools.learning_book.contracts import DeliveryError


class PreparationTests(unittest.TestCase):
    setUp=i3.DeliveryTests.setUp
    package=i3.DeliveryTests.package
    publish=i3.DeliveryTests.publish
    create=i3.DeliveryTests.create

    def template(self):
        return [dict(question_id='q1',topic='source',question_type='choice',difficulty='easy',
                     reference_question='Which? A/B/C/D',reference_answer='C; source explanation')]

    def test_prepared_replay_uses_saved_response_and_checks_input_identity(self):
        self.create()
        result=self.app.prepare_quiz('activity-1','quiz-1','main','q',self.template(),1)
        self.assertEqual(result['status'],'succeeded',result)
        from tools.learning_book.contracts import decode_json
        sent=next(r[3] for r in self.fake.requests if r[0]=='POST' and r[1]=='/api/books/regenerate-block')
        self.assertEqual(decode_json(sent)['params_override']['num_questions'],1)
        writes=self.fake.writes()
        self.assertEqual(self.app.prepare_quiz('activity-1','quiz-1','main','q',self.template(),1)['status'],'succeeded')
        self.assertEqual(writes,self.fake.writes())
        changed=self.template();changed[0]['reference_answer']='D'
        with self.assertRaises(DeliveryError):
            self.app.prepare_quiz('activity-1','quiz-1','main','q',changed,1)

    def test_invalid_templates_and_stale_revision(self):
        self.create()
        before=len(self.fake.requests)
        with self.assertRaises(DeliveryError):
            self.app.prepare_quiz('activity-1','invalid','main','q',[],1)
        self.assertEqual(len(self.fake.requests),before)
        result=self.app.prepare_quiz('activity-1','stale','main','q',self.template(),2)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.fake.writes('/api/books/regenerate-block'),0)


if __name__=='__main__':unittest.main()
