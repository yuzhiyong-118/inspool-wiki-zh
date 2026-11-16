"""I4/I5只读携带准备依据：可搬运引用，不携带原件或第二套进度。"""
from .contracts import DeliveryError, decode_json, digest, sha256
from .evidence_store import atomic
from .preparation_provenance import provenance_bytes, verify_provenance


def _need(ok):
    if not ok: raise DeliveryError('handoff_preparation_invalid', '学习交接的准备依据不完整或不一致', 'conflict')


def _refs(preparation):
    refs = [preparation['originRef'], preparation['activeRef']]
    _need(type(preparation['continuations']) is list and len(preparation['continuations']) <= 32)
    for row in preparation['continuations']:
        refs += [row['request']['fromRef'], row['request']['toRef']]
    return {r['path']:r for r in refs}


def verify_mapping(mapping, lookup):
    from .preparation_continuation import _compatible, _review, review_request
    p = mapping['preparation']
    _need(p['status'] == 'available' and p['sourceOriginalsVerified'] is False)
    initial = verify_provenance(lookup(p['originRef']))
    current = {'binding':initial['binding'], 'provenanceRef':p['originRef'], 'headDigest':None}
    corpus = mapping['corpus']
    _need({k:initial['manifest'][k] for k in corpus} == corpus)
    origin = {'requestId':mapping['productionRequestId']}
    for i,row in enumerate(p['continuations'],1):
        _need(row['schema'] == 'learning-preparation-continuation/1' and row['sequence'] == i
              and row['recordDigest'] == digest({k:v for k,v in row.items() if k != 'recordDigest'}))
        r = row['request']
        _need(r == review_request(mapping, origin, current, r['toBinding'], r['toRef'],
                                 r['expectedRevision'], r['reason']))
        _review(row['review'], r)
        new = verify_provenance(lookup(r['toRef']), r['toBinding'])
        _compatible(lookup(current['provenanceRef']), new)
        current.update(binding=r['toBinding'], provenanceRef=r['toRef'], headDigest=row['recordDigest'])
    _need(p['binding'] == current['binding'] and p['activeRef'] == current['provenanceRef'])


def copy_preparation(store, mapping, destination):
    p = (mapping or {}).get('preparation')
    if not p or p['status'] != 'available': return None
    refs = _refs(p)
    raw = {name:provenance_bytes(store.root, ref) for name,ref in refs.items()}
    verify_mapping(mapping, lambda ref:decode_json(raw[ref['path']]))
    rows = []
    for i,(name,data) in enumerate(sorted(raw.items())):
        artifact = f'preparation/p{i}.json'
        atomic(destination/artifact, data, immutable=True)
        rows.append({'oldRef':name, 'artifact':artifact, 'sha256':sha256(data)})
    return {'schema':'learning-preparation-evidence/1', 'refMap':rows,
            'sourceOriginalsVerified':False}


def verify_preparation(handoff, safe_read):
    mapping = handoff.get('sources',{}).get('mapping') or {}
    p = mapping.get('preparation')
    evidence = handoff.get('preparationEvidence')
    if not p or p.get('status') != 'available':
        _need(evidence is None); return
    _need(type(evidence) is dict and set(evidence) == {'schema','refMap','sourceOriginalsVerified'}
          and evidence['schema'] == 'learning-preparation-evidence/1'
          and evidence['sourceOriginalsVerified'] is False)
    refs = _refs(p)
    _need(type(evidence['refMap']) is list and len(evidence['refMap']) == len(refs))
    values = {}
    artifacts = set()
    for row in evidence['refMap']:
        _need(set(row) == {'oldRef','artifact','sha256'} and row['oldRef'] in refs
              and row['oldRef'] not in values and row['artifact'] not in artifacts
              and row['artifact'].startswith('preparation/'))
        data = safe_read(row['artifact'])
        _need(sha256(data) == row['sha256'] == refs[row['oldRef']]['sha256'])
        values[row['oldRef']] = verify_provenance(decode_json(data))
        artifacts.add(row['artifact'])
    _need(mapping['activityId'] == handoff['activityId'] and mapping['bookId'] == handoff['bookId']
          and mapping['scope'] == handoff['backendScope'])
    verify_mapping(mapping, lambda ref:values[ref['path']])
