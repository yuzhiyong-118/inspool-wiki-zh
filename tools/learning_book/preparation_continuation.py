"""同活动、同上传内容的准备重新核验链；保留原创建事实。"""
from __future__ import annotations

from .contracts import DeliveryError, canonical, decode_json, digest, identifier
from .evidence_store import atomic
from .preparation_provenance import load_provenance, save_provenance
from tools.wiki_runtime.isolation.gateway import _check_chain

MAX_CONTINUATIONS = 32


def _need(ok):
    if not ok:
        raise DeliveryError('preparation_continuation_invalid', '准备续接链不一致或范围改变', 'conflict')


def review_request(mapping, origin, current, new_binding, new_ref, revision, reason):
    value = {'schema':'learning-preparation-continuation-request/1',
        'activityId':mapping['activityId'], 'bookId':mapping['bookId'], 'scope':mapping['scope'],
        'originRequestId':origin['requestId'], 'fromBinding':current['binding'],
        'toBinding':new_binding, 'fromRef':current['provenanceRef'], 'toRef':new_ref,
        'previousDigest':current['headDigest'], 'expectedRevision':revision, 'reason':reason}
    return dict(value, requestDigest=digest(value))


def _review(observation, request):
    _need(type(observation) is dict and set(observation) == {'schema','id','requestDigest',
        'reviewedBy','recordedAt','decision','reason','assurance'})
    _need(observation['schema'] == 'learning-preparation-continuation-review/1'
        and observation['assurance'] == 'operator_supplied'
        and observation['decision'] == 'reviewed_for_scope'
        and observation['requestDigest'] == request['requestDigest'])
    _need(all(type(observation[k]) is str and 0 < len(observation[k].strip()) <= 4000
              for k in ('id','reviewedBy','recordedAt','reason')))


def _compatible(old, new):
    # 本操作续接依赖更新，不偷换已上传内容或学习方向。
    _need(old['manifest'] == new['manifest'] and old['binding']['intent'] == new['binding']['intent'])
    _need(all(old['brief'][k] == new['brief'][k] for k in
        ('learnerId','goals','included','excluded','pacing','prerequisites')))


def active_preparation(store, mapping, origin):
    binding = origin['semantic'].get('knowledgePreparation')
    ref = origin['semantic'].get('preparationProvenanceRef')
    _need(binding is not None and ref is not None)
    load_provenance(store, ref, binding)
    current = {'binding':binding, 'provenanceRef':ref, 'originRef':ref,
               'headDigest':None, 'records':[]}
    directory = store.root/'preparation-continuations'/digest(mapping['activityId'])
    _check_chain(directory, missing=True)
    if not directory.exists(): return current
    names = sorted(directory.iterdir())
    _need(len(names) <= MAX_CONTINUATIONS)
    for index,path in enumerate(names, 1):
        _need(path.name == f'{index:06d}.json')
        _check_chain(path)
        with path.open('rb') as stream: data = stream.read(256 * 1024 + 1)
        _need(len(data) <= 256 * 1024)
        row = decode_json(data)
        _need(set(row) == {'schema','id','sequence','request','review','recordDigest'})
        _need(row['schema'] == 'learning-preparation-continuation/1' and row['sequence'] == index
            and row['recordDigest'] == digest({k:v for k,v in row.items() if k != 'recordDigest'}))
        rr = row['request']
        rebuilt = review_request(mapping, origin, current, rr['toBinding'], rr['toRef'],
                                 rr['expectedRevision'], rr['reason'])
        _need(rr == rebuilt and type(rr['expectedRevision']) is int and rr['expectedRevision'] >= 1)
        _review(row['review'], rr)
        _compatible(load_provenance(store, current['provenanceRef'], current['binding']),
                    load_provenance(store, rr['toRef'], rr['toBinding']))
        current.update(binding=rr['toBinding'], provenanceRef=rr['toRef'], headDigest=row['recordDigest'])
        current['records'].append(row)
    return current


def prepare_continuation(store, mapping, origin, guard, key, revision, reason, observation=None):
    identifier(key, 'continuationId')
    _need(type(revision) is int and revision > 0 and type(reason) is str and 0 < len(reason.strip()) <= 4000)
    current = active_preparation(store, mapping, origin)
    binding, package, _, archive = guard.checked(include_provenance=True)
    _compatible(load_provenance(store, current['provenanceRef'], current['binding']), archive)
    ref = save_provenance(store, archive)
    # 已接受的同ID可重读；不同输入不能覆盖旧续接事实。
    for row in current['records']:
        if row['id'] == key:
            rr = row['request']
            _need(rr['toBinding'] == binding and rr['toRef'] == ref and rr['expectedRevision'] == revision
                  and rr['reason'] == reason and (observation is None or row['review'] == observation))
            return {'status':'succeeded','record':row,'replayed':True,'productionPostPerformed':False}
    _need(binding != current['binding'] and len(current['records']) < MAX_CONTINUATIONS)
    rr = review_request(mapping, origin, current, binding, ref, revision, reason)
    if observation is None:
        return {'status':'needs_review','reviewRequest':rr,'productionPostPerformed':False}
    _review(observation, rr)
    body = {'schema':'learning-preparation-continuation/1', 'id':key,
        'sequence':len(current['records'])+1, 'request':rr, 'review':observation}
    row = dict(body, recordDigest=digest(body))
    target = store.root/'preparation-continuations'/digest(mapping['activityId'])/f"{row['sequence']:06d}.json"
    _check_chain(target, missing=True)
    atomic(target, canonical(row), immutable=True)
    return {'status':'succeeded','record':row,'replayed':False,'productionPostPerformed':False}
