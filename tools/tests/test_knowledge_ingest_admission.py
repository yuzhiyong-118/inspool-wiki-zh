"""临时库正式事务验收；语义回包为合成，不代表真实内容或宿主身份认证。"""
import copy
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools.tests import test_knowledge_preparation_integration as integration
from tools.wiki_runtime.contracts import digest, canonical_json
from tools.wiki_runtime.executor import Executor, ExecutionError
from tools.wiki_runtime.host.supervisor import StandaloneHost, HostError
from tools.wiki_runtime.host.cli import _review_record
from tools.wiki_runtime.host import knowledge_ingest as host_ingest
from tools.wiki_runtime.runtime import knowledge_ingest as runtime
from tools.wiki_runtime.runtime.storage import RuntimeStore
from tools.wiki_runtime.runtime.service import RuntimeService
from tools.wiki_runtime.coordinator import Coordinator


def synthetic_review(envelope, *, timeout):
    rr=envelope['input']; refs=[]
    if not envelope['system'].startswith('你是独立内容审查者'): raise AssertionError('禁止Worker')
    for kind,key in [('original','originals'),('candidate','candidate_files')]:
        for path,text in rr[key].items():
            n=next(i+1 for i,line in enumerate(text.splitlines()) if line.strip())
            refs.append(f'{kind}:{path}#L{n}-L{n}')
    return dict(contract_version='1.0',**rr['bindings'],reviewer_id=envelope['reviewer_id'],
                result='recommend_pass',findings=[],evidence_refs=refs)


class KnowledgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.x=integration.CandidateAdoptionTests(); self.x.setUp();self.addCleanup(self.x.doCleanups)
        self.f=self.x.f;self.host=self.x.host;self.calls=[]
        def transport(envelope,*,timeout):
            self.calls.append(copy.deepcopy(envelope));return synthetic_review(envelope,timeout=timeout)
        self.host.transport=transport

    def adopt(self, *, call_timeout=60):
        f=self.f
        return self.host.adopt_knowledge_candidate('preview',f.k.context,f.knowledge,f.candidate,f.request,
            source_root=f.inbox,payload_root=f.payload,max_seconds=900,call_timeout=call_timeout)

    def admit(self):
        return self.host.admit_knowledge_candidate('preview',authorization_reason='测试宿主获准整理本批虚构规程；仅临时库',
                                                   sequence='knowledge_only')

    def files(self):
        return {p.relative_to(self.f.project).as_posix():p.read_bytes()
                for parent in ('wiki','raw') for p in (self.f.project/parent).rglob('*') if p.is_file()}

    def test_plain_ingest_final_G3_no_teaching_and_terminal_replay(self):
        self.adopt();before=self.files()
        self.assertEqual(self.host.apply_pending('preview')['status'],'knowledge_admission_required')
        self.assertEqual(self.admit()['status'],'admitted');self.assertEqual(before,self.files())
        record=self.host.load_pending('preview');a=runtime.load(self.host.runtime,'preview')
        # 同一实际准入不能换包、权限或学习/维护类型。
        for key in ('preparation_digest','authorization_digest','manifest_digest','candidate_digest'):
            bad=copy.deepcopy(a);bad[key]='0'*64
            with self.assertRaises((ValueError,ExecutionError)):runtime.bind(self.host.runtime,bad)
        with self.assertRaises(ValueError):runtime.parse_knowledge_admission(dict(a,confirmed=True))
        with self.assertRaises(ValueError):self.admit_wrong_order()
        self.assertEqual(self.calls,[])
        # 准入后才保存的负面意见也必须阻止新提交；恢复/终态另走原WAL。
        saved=self.host.load_pending('preview');negative=copy.deepcopy(saved)
        negative['knowledge']['opinion']={'result':'request_changes'}
        self.host._save_pending('preview',negative)
        with self.assertRaises(HostError):host_ingest.check_current_inputs(self.host,'preview',a)
        self.host._save_pending('preview',saved)
        # 范围外大文件既不能进入依赖也不能卡知识事务。
        outside=self.f.project/'references/large.bin';outside.parent.mkdir();outside.write_bytes(b'x'*(2*1024*1024))
        result=self.host.apply_pending('preview');self.assertEqual(result['status'],'applied',result)
        self.assertEqual(len(self.calls),1)
        self.assertIn('processing_status: pending_review',(self.f.project/self.f.raw_path).read_text(encoding='utf-8'))
        self.assertFalse((self.f.project/'raw/processed/规程.md').exists())
        self.assertFalse(self.host.runtime.store.read('SELECT * FROM learning_states'))
        self.assertFalse(self.host.runtime.store.read('SELECT * FROM readiness_records'))
        self.assertFalse(self.host.runtime.store.read('SELECT * FROM operation_admissions'))
        self.assertFalse(self.host.runtime.store.read('SELECT * FROM maintenance_bindings'))
        self.assertEqual(len(self.host.runtime.store.read('SELECT * FROM invocations')),1)
        after=self.files();outside.write_bytes(b'changed unrelated runtime')
        replay=self.host.apply_pending('preview');self.assertEqual(replay['status'],'applied')
        self.assertEqual(len(self.calls),1);self.assertEqual(after,self.files())
        inspected=_review_record(self.host,'preview');self.assertTrue(inspected['applied'])
        self.assertEqual(inspected['knowledgeAdmission']['state'],'applied')
        journal=json.loads(self.host.runtime.executor._journal('preview').read_bytes())
        self.assertEqual(journal['view_scope'],'knowledge_content')
        self.assertFalse(any(p.startswith('references/') for p in journal['baseline_files']))
        self.assertEqual(journal['steps'][-1]['path'],self.f.raw_path)
        forged=copy.deepcopy(result['execution']);forged['state']='recovered';forged['recovery_status']='recovered'
        with self.assertRaises(ExecutionError):runtime.reconcile(self.host.runtime,a,forged)
        with self.assertRaises((ValueError,ExecutionError)):
            self.host.runtime.build_admission(run_id=a['run_id'],operation_id='preview',manifest_digest=a['manifest_digest'],
                readiness_digest='0'*64,authorization_ref='fake')

    def test_consultation_reply_merges_concurrent_host_admission(self):
        self.adopt(call_timeout=300)
        events=[]
        def concurrent(envelope,*,timeout):
            if not events:
                events.append('consultation started before admit')
                child=subprocess.run([sys.executable,'-X','utf8','-B','-m','tools.wiki_runtime.cli','host',
                    'admit-knowledge','--root',str(self.f.project),'--state-dir',str(self.host.state_dir),
                    '--operation-id','preview','--authorization-reason','另一可信宿主的本次临时库授权',
                    '--sequence','knowledge_only'],cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,text=True,encoding='utf-8',timeout=240)
                self.assertEqual(child.returncode,0,child.stderr+child.stdout)
                self.assertEqual(json.loads(child.stdout)['status'],'admitted')
            return synthetic_review(envelope,timeout=timeout)
        self.host.transport=concurrent
        result=self.host.review_knowledge_candidate('preview')
        self.assertEqual(result['status'],'reviewed_for_transfer',result)
        saved=self.host.load_pending('preview');self.assertIn('authorization',saved['knowledge'])
        admission=runtime.load(self.host.runtime,'preview');host_ingest.validate_binding(saved,admission)
        self.assertEqual(self.host.apply_pending('preview')['status'],'applied')
        self.assertEqual(len(self.host.runtime.store.read('SELECT * FROM invocations')),2)

    def admit_wrong_order(self):
        return self.host.admit_knowledge_candidate('preview',authorization_reason='test',sequence='learn_first')

    def test_managed_capture_full_ingest_after_cutover(self):
        extracted=self.x.make_managed_raw()
        from tools.wiki_runtime.runtime.migration import freeze_legacy_entries,assert_runtime_creation_allowed
        freeze_legacy_entries(self.f.project,self.host.state_dir)
        self.adopt();self.admit()
        result=self.host.apply_pending('preview');self.assertEqual(result['status'],'applied',result)
        self.assertEqual(len(self.calls),1)
        self.assertIn(extracted.relative_to(self.f.project).as_posix(),self.calls[0]['input']['originals'])
        self.assertTrue(extracted.is_file());assert_runtime_creation_allowed(self.f.project,self.host.state_dir,'next')
        with self.assertRaises(HostError):self.host.approve_pending('preview')

    def test_revoked_admission_stops_before_write_and_does_not_reset(self):
        self.adopt();self.admit();before=self.files()
        self.assertEqual(self.host.revoke_pending('preview')['status'],'revoked')
        with self.assertRaises(ValueError):self.host.apply_pending('preview')
        self.assertEqual(before,self.files())
        self.assertEqual(len(self.calls),0)
        with self.assertRaises(ValueError):self.admit()
        self.assertEqual(before,self.files())

    def test_failed_G3_is_unknown_and_not_reissued_after_restart(self):
        self.adopt(call_timeout=0.2);self.admit();before=self.files();calls=[]
        def broken(envelope,*,timeout):
            calls.append(1);time.sleep(0.5)
            return synthetic_review(envelope,timeout=timeout)
        self.host.transport=broken
        with self.assertRaises(ExecutionError):self.host.apply_pending('preview')
        time.sleep(0.6) # 让迟到 transport 释放资源；其结果仍不能覆盖 unknown。
        self.host.close()
        restarted=StandaloneHost(self.f.project,self.host.state_dir,transport=broken);self.addCleanup(restarted.close)
        with self.assertRaises(ExecutionError):restarted.apply_pending('preview')
        self.assertEqual(calls,[1]);self.assertEqual(before,self.files())
        invocation=restarted.runtime.store.read('SELECT record_json FROM invocations')[0]
        self.assertEqual(json.loads(invocation['record_json'])['result_state'],'unknown')

    def test_sources_change_after_G3_cannot_refresh_binding_or_write(self):
        self.adopt();self.admit();before=self.files()
        def mutate(envelope,*,timeout):
            result=synthetic_review(envelope,timeout=timeout)
            self.f.k.source.write_text('changed external original\n',encoding='utf-8')
            return result
        self.host.transport=mutate
        with self.assertRaises((ValueError,ExecutionError)):self.host.apply_pending('preview')
        self.assertEqual(before,self.files())
        self.assertFalse(self.host.runtime.executor._journal('preview').exists())

    def test_new_content_file_and_frozen_payload_tamper_stop_before_G3(self):
        self.adopt();self.admit();before=self.files()
        added=self.f.project/'wiki/meta/new-dependency.md';added.write_text('# 新依赖\n',encoding='utf-8')
        with self.assertRaises((ValueError,RuntimeError)):self.host.apply_pending('preview')
        added.unlink()
        record=self.host.load_pending('preview');change=record['bundle']['candidate']['changes'][0]
        frozen=Path(record['bundle']['payload_root'])/change['payload_path']
        frozen.write_bytes(frozen.read_bytes()+b'changed\n')
        with self.assertRaises((ValueError,RuntimeError)):self.host.apply_pending('preview')
        self.assertEqual(before,self.files());self.assertEqual(self.calls,[])

    def test_revocation_during_G3_is_seen_at_final_acceptance(self):
        self.adopt();self.admit();before=self.files()
        def revoke(envelope,*,timeout):
            result=synthetic_review(envelope,timeout=timeout)
            self.host.revoke_pending('preview')
            return result
        self.host.transport=revoke
        with self.assertRaises(ValueError):self.host.apply_pending('preview')
        self.assertEqual(before,self.files())
        self.assertFalse(self.host.runtime.executor._journal('preview').exists())

    def test_ingest_cannot_mint_user_reviewed_at(self):
        f=self.f;f.values[f.raw_path]=f.values[f.raw_path].replace('processing_status: pending_review',
            'processing_status: pending_review\nreviewed_at: 2026-11-12')
        f.rebuild();self.adopt();self.admit();before=self.files()
        with self.assertRaisesRegex(ExecutionError,'reviewed_at'):self.host.apply_pending('preview')
        self.assertEqual(before,self.files());self.assertEqual(self.calls,[])

    def crash_child(self,event):
        # 真实进程退出而非异常；原 Runtime、WAL、payload 由独立进程读取。
        code='''import os,sys
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.host import knowledge_ingest as m
from tools.wiki_runtime.executor import Executor
from tools.tests.test_knowledge_ingest_admission import synthetic_review
def factory(*a,**kw):
 e=Executor(*a,**kw)
 def hit(event,index):
  if event==sys.argv[3] and (index in (-1,0)): os._exit(73)
 e.fault=hit
 return e
m.Executor=factory
h=StandaloneHost(sys.argv[1],sys.argv[2],transport=synthetic_review)
h.apply_pending('preview')
raise SystemExit(74)
'''
        self.host.close()
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(self.f.project),
            str(self.host.state_dir),event],capture_output=True,text=True,encoding='utf-8',timeout=300)
        self.assertEqual(result.returncode,73,result.stdout+result.stderr)

    def test_real_process_exit_mid_write_recovers_offline_and_preserves_originals(self):
        self.adopt();self.admit();before=self.files();self.crash_child('after_write')
        h=StandaloneHost(self.f.project,self.host.state_dir,offline=True);self.addCleanup(h.close)
        self.assertNotEqual(before,self.files())
        result=h.recover('preview');self.assertEqual(result['status'],'recovered',result)
        self.assertEqual(before,self.files());self.assertEqual(h.recover('preview')['status'],'recovered')

    def test_real_process_exit_before_active_recovers_without_new_authorization(self):
        self.adopt();self.admit();before=self.files();self.crash_child('after_prepare')
        h=StandaloneHost(self.f.project,self.host.state_dir,offline=True);self.addCleanup(h.close)
        h.revoke_pending('preview')
        self.assertEqual(h.recover('preview')['status'],'recovered');self.assertEqual(before,self.files())

    def test_real_process_exit_after_commit_returns_original_fact_without_G3(self):
        self.adopt();self.admit();self.crash_child('after_commit');after=self.files()
        h=StandaloneHost(self.f.project,self.host.state_dir,offline=True);self.addCleanup(h.close)
        self.assertEqual(h.apply_pending('preview')['status'],'applied')
        self.assertEqual(after,self.files());self.assertEqual(h.recover('preview')['status'],'applied')

    def test_recovery_conflict_preserves_user_edit(self):
        self.adopt();self.admit();self.crash_child('after_write')
        changed=self.f.project/self.f.candidate['changes'][0]['path'];changed.write_text('user edit\n',encoding='utf-8')
        h=StandaloneHost(self.f.project,self.host.state_dir,offline=True);self.addCleanup(h.close)
        result=h.recover('preview');self.assertEqual(result['execution']['recovery_status'],'conflict')
        self.assertEqual(changed.read_text(encoding='utf-8'),'user edit\n')


class RuntimeKnowledgeBoundaryTests(unittest.TestCase):
    """只验证真实 Runtime 协议／动态条件；不声称这些样例是已核验知识包。"""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.vault=self.root/'vault';self.vault.mkdir()
        (self.vault/'AGENTS.md').write_text('# 临时规则\n',encoding='utf-8')
        mapping=self.vault/'tools/wiki_runtime/contracts/rules.json';mapping.parent.mkdir(parents=True)
        mapping.write_text('{}',encoding='utf-8')
        self.r=RuntimeService(RuntimeStore(self.root/'state'));self.addCleanup(self.r.store.close)
        self.c=Coordinator(self.vault,self.root/'run',operation_id='unit',operation_type='ingest',task='unit',
            allowed_paths=['wiki/test.md'],input_refs=[],max_calls=2,max_seconds=300,call_timeout=30,
            runtime=self.r);self.addCleanup(self.c.close)
        self.a={'schema':runtime.SCHEMA,**self.c.runtime_ids,'operation_id':'unit',
            'workflow_id':self.c.workflow['workflow_id'],'policy_digest':self.c.policy['policy_digest'],
            'submission_epoch':1,'created_generation':1,'view_scope':'knowledge_content'}
        for field in ('manifest_digest','candidate_digest','dependencies_digest','rules_digest','mapping_digest',
                      'preparation_digest','authorization_digest'): self.a[field]='1'*64

    def test_closed_protocol_scope_and_cross_type_refusal(self):
        for extra in ({'view_scope':'whole_root'},{'schema':'other'}, {'independent':True}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                runtime.parse_knowledge_admission(dict(self.a,**extra))
        runtime.bind(self.r,self.a)
        with self.assertRaises(ValueError):self.r.store.mutate(lambda db:runtime.reject_cross_type(db,'unit'))
        runtime.bind(self.r,self.a)
        with self.assertRaises(ValueError):runtime.bind(self.r,dict(self.a,preparation_digest='2'*64))
        self.assertFalse(self.r.store.read('SELECT * FROM learning_states'))

    def test_current_task_run_generation_epoch_expiry_and_budget(self):
        runtime.bind(self.r,self.a);runtime.check_current(self.r,self.a)
        for table,key,field,value in [
            ('tasks','task_id','state','paused'),('runs','run_id','state','paused'),
            ('tasks','task_id','submission_epoch',2),('execution_ownerships','task_id','generation',2),
            ('execution_ownerships','task_id','expires_at',0)]:
            identity=self.a[key]
            original=self.r.store.read(f"SELECT record_json FROM {table}")[0]['record_json']
            changed=json.loads(original);changed[field]=value
            self.r.store.mutate(lambda db:db.execute(f'UPDATE {table} SET record_json=? WHERE {key}=?',
                                                      (json.dumps(changed),identity)))
            with self.subTest(table=table,field=field),self.assertRaises((ValueError,RuntimeError)):runtime.check_current(self.r,self.a)
            self.r.store.mutate(lambda db:db.execute(f'UPDATE {table} SET record_json=? WHERE {key}=?',(original,identity)))
        for table in ('task_finance','run_finance'):
            self.r.store.mutate(lambda db:db.execute(f"UPDATE {table} SET blocked=1,block_reason='synthetic budget exhausted'"))
            with self.subTest(table=table),self.assertRaises((ValueError,RuntimeError)):runtime.check_current(self.r,self.a)
            self.r.store.mutate(lambda db:db.execute(f'UPDATE {table} SET blocked=0,block_reason=NULL'))
        runtime.check_current(self.r,self.a)

    def test_policy_switch_invalidates_original_admission(self):
        runtime.bind(self.r,self.a)
        policy=copy.deepcopy(self.c.policy);policy.pop('policy_digest');policy['revision']=2
        policy['creation_reason']='synthetic new policy';policy['policy_digest']=digest(policy)
        self.r.switch_policy(self.a['task_id'],policy)
        with self.assertRaises((ValueError,RuntimeError)):runtime.check_current(self.r,self.a)

    def test_latest_negative_opinion_stops_current_input_check(self):
        manifest={'allowed_paths':['wiki/test.md']}
        auth={'schema':'knowledge-ingest-host-authorization/1','operation_id':'unit',
              'sequence':'knowledge_only','reason':'synthetic trusted-host action','allowed_paths':manifest['allowed_paths']}
        record={'config':{'operation_id':'unit'},'bundle':{'manifest':manifest},'knowledge':{
            'authorization':auth,'context':{},'prepared':{},'preparedDigest':'1'*64,'request':{},
            'source_root':'synthetic','baseline_scope':'knowledge_content','opinion':{'result':'request_changes'}}}
        a=dict(self.a,manifest_digest=digest(manifest),authorization_digest=digest(auth),
               preparation_digest=host_ingest.preparation_digest(record))
        host=SimpleNamespace(load_pending=lambda operation:copy.deepcopy(record))
        with patch.object(host_ingest,'verify_adoption') as verify:
            with self.assertRaises(HostError):host_ingest.check_current_inputs(host,'unit',a)
            verify.assert_not_called()
            record['knowledge']['opinion']=None
            host_ingest.check_current_inputs(host,'unit',a);verify.assert_called_once()

    def test_extension_survives_backup_and_restart(self):
        runtime.bind(self.r,self.a)
        self.r.store.backup(self.root/'backup')
        target=self.root/'restored/.wiki-runtime/learning';target.parent.mkdir(parents=True)
        shutil.copytree(self.root/'backup',target)
        restored=RuntimeService(RuntimeStore(self.root/'restored'));self.addCleanup(restored.store.close)
        self.assertEqual(runtime.load(restored,'unit'),self.a)
        runtime.check_current(restored,self.a)
        with self.assertRaises(Exception):
            self.r.store.mutate(lambda db:db.execute("UPDATE knowledge_ingest_admissions SET record_json='{}'"))


if __name__=='__main__': unittest.main()
