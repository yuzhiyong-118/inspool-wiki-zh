"""有界不可变准备依据；只保存证据及引用，不复制原件或学习状态。"""
from __future__ import annotations

from pathlib import Path

from .contracts import DeliveryError, canonical, decode_json, digest, sha256
from .evidence_store import atomic
from tools.wiki_runtime.evidence.package_protocol import (parse_knowledge_package, package_ref,
    build_package, evidence_claim_relation_digest)
from tools.wiki_runtime.isolation.gateway import _check_chain

MAX_BYTES = 4 * 1024 * 1024


def verify_provenance(value, binding=None):
    def check(ok):
        if not ok: raise ValueError('provenance_binding')
    try:
        check(type(value) is dict and len(canonical(value)) <= MAX_BYTES)
        check(set(value) == {'schema', 'binding', 'mapping', 'brief', 'recognition', 'manifest', 'existingDocuments',
            'knowledge', 'projectionReview', 'sourceRetention', 'sourceOriginalsVerified', 'assurance'})
        check(value['schema'] == 'learning-preparation-provenance/1')
        check(value['sourceRetention'] == 'external' and value['sourceOriginalsVerified'] is False)
        check(value['assurance'] == 'operator_supplied_no_host_authentication')
        b, m, k = value['binding'], value['mapping'], value['knowledge']
        check(set(b) == {'schema','mappingDigest','intent','normalizedManifestDigest','assurance'}
            and b['schema']=='knowledge-preparation-binding/1'
            and b['assurance']=='operator_supplied_no_host_authentication')
        check(binding is None or b == binding)
        check(b['mappingDigest'] == digest(m) and b['intent'] == m['intent'])
        check(b['normalizedManifestDigest'] == m['prepareRef']['normalizedManifestDigest'] == digest(value['manifest']))
        check(m['prepareRef']['packageId'] == value['manifest']['packageId'])
        check(k['reportDigest'] == digest({x:y for x,y in k.items() if x != 'reportDigest'}))
        check(k['knowledgeState'] == 'reviewed_for_scope')
        parse_knowledge_package(k['package'])
        check(m['packageRef'] == package_ref(k['package']))
        kr, ko = k['reviewRequest'], k['reviewObservation']
        p, request = k['package'], k['request']
        check(build_package({'package_id':request['packageId'], 'version':request['version'],
            'sources':p['sources'], 'evidence':request['evidence'], 'relations':request['relations'],
            'existing_knowledge':request['existingKnowledge']}, request['claims'], request['conflicts']) == p)
        comparison = k['comparison']
        docs = value['existingDocuments']
        check(type(docs) is list and len(docs)<=5
            and len({d['locator'] for d in docs})==len(docs))
        for d in docs:
            check(set(d)=={'pageId','locator','byteDigest','bytes','text'} and type(d['text']) is str
                and sha256(d['text'].encode('utf-8'))==d['byteDigest']
                and len(d['text'].encode('utf-8'))==d['bytes'] and d['bytes']<=1024*1024)
        check([{key:d[key] for key in ('pageId','locator','byteDigest')} for d in docs]
              == comparison['documents'])
        check(comparison['comparisonDigest'] == digest({x:y for x,y in comparison.items() if x != 'comparisonDigest'}))
        scope = {'claimIds':[c['claim_id'] for c in p['claims']],
            'evidenceIds':[e['evidence_id'] for e in p['evidence']],
            'relationDigests':[evidence_claim_relation_digest(r) for r in p['relations']],
            'conflictIds':[c['conflict_id'] for c in p['conflicts']],
            'comparisonDigests':[digest(c) for c in p['existing_knowledge']],
            'sourceIds':[s['source_id'] for s in p['sources']],
            'documentLocators':[d['locator'] for d in comparison['documents']]}
        check(kr['packageRef'] == package_ref(p) and kr['contextDigest'] == k['contextDigest']
            and kr['comparisonRef'] == comparison['comparisonDigest'] and kr['scope'] == scope
            and kr['sourceObservationsDigest'] == digest(request['sourceObservations'])
            and kr['intent'] == request['intent'])
        check(kr['requestDigest'] == digest({x:y for x,y in kr.items() if x != 'requestDigest'}))
        check(ko['requestDigest'] == kr['requestDigest'] and ko['assurance'] == 'operator_supplied')
        check(m['reviewRef'] == {'id':ko['id'], 'digest':digest(ko)})
        from tools.wiki_runtime.evidence.knowledge import _review, _observations
        reviewed = _review(ko,kr,p,{'documents':docs},comparison)
        check(all(ref in reviewed['claims'] and reviewed['claims'][ref]['decision']=='reviewed_for_scope'
            for ref in scope['claimIds']))
        check(set(reviewed['relations']) == set(scope['relationDigests'])
              and set(reviewed['documents']) == set(scope['documentLocators']))
        check(_observations(request['sourceObservations'],{s['source_id']:s for s in p['sources']},
            {e['evidence_id']:e for e in p['evidence']}) == k['independence'])
        check({row['claimId'] for row in k['claimChecks']} == set(scope['claimIds'])
            and all(row['state']=='reviewed_for_scope' and not row['blockers'] and not row['pending']
                    for row in k['claimChecks']))
        sources = {s['source_id']:s for s in p['sources']}
        evidence = {e['evidence_id']:e for e in p['evidence']}
        checks = {row['claimId']:row for row in k['claimChecks']}
        for claim in p['claims']:
            cid = claim['claim_id']; supports = []; safe = []
            check(claim['evidence_status'] == 'supported')
            for conflict in [c for c in p['conflicts'] if cid in c['claim_ids']]:
                observed = reviewed['conflicts'].get(conflict['conflict_id'],{})
                check(conflict['status']=='resolved' and observed.get('decision')=='resolved_for_scope'
                      and cid in observed.get('safeClaimIds',[]))
                safe.append(conflict)
            for relation in [r for r in p['relations'] if r['claim_id']==cid]:
                observed = reviewed['relations'][evidence_claim_relation_digest(relation)]
                check(observed['decision'] != 'needs_evidence')
                if observed['decision'] != 'accepted': continue
                e = evidence[relation['evidence_id']]
                if relation['relation']=='supports':
                    check(sources[e['source_id']]['readable_range']['complete']
                        and e['extraction_state']=='complete' and relation['verification_status']=='verified'
                        and set(relation['conditions'])==set(claim['conditions'])
                        and reviewed['sources'].get(e['source_id'],{}).get('decision')=='reviewed_for_scope')
                    supports.append(e['evidence_id'])
                elif relation['relation']=='contradicts':
                    check(any(e['evidence_id'] in c['evidence_ids'] for c in safe))
                elif relation['relation']=='qualifies':
                    check(set(relation['conditions']) <= set(claim['conditions']))
            check(bool(supports) and supports == checks[cid]['supportEvidenceIds'])
            for old in [o for o in p['existing_knowledge'] if o['claim_id']==cid]:
                decision=reviewed['comparisons'].get(digest(old),{}).get('decision')
                check(decision not in (None,'unresolved','insufficient'))
                if old['relation'] in ('contradicts','supersedes'):
                    check(decision in ('condition_difference','version_change','corrects_old'))
        check(all(row['decision'] != 'needs_evidence' for row in reviewed['documents'].values()))
        brief, recog, review = value['brief'], value['recognition'], value['projectionReview']
        check(m['briefRef'] == {'briefId':brief['briefId'], 'version':brief['version'], 'digest':digest(brief)})
        check(m['recognitionRef'] == {'id':recog['id'], 'digest':digest(recog)})
        check(recog['briefRef'] == m['briefRef'] and recog['attributedAuthor'] == brief['learnerId']
            and recog['scope'] == {'goalIds':[g['goalId'] for g in brief['goals']],
                **{x:brief[x] for x in ('included','excluded','pacing')}}
            and recog['acceptedIntent'] == m['intent'] and recog['assurance']=='operator_supplied'
            and type(recog['statement']) is str
            and sha256(recog['statement'].encode('utf-8')) == recog['evidenceRef']['byteDigest'])
        check(m['projectionReviewRef'] == {'id':review['id'], 'digest':digest(review)})
        check(review['decision'] == 'reviewed_for_scope' and review['assurance'] == 'operator_supplied')
        check(review['artifactRefs'] == [{'artifactId':a['inputArtifactId'],'byteDigest':a['sha256']}
            for a in value['manifest']['inputArtifacts']])
        from .contracts import Package
        from tools.wiki_runtime.evidence.projection import _coverage
        _coverage(m,brief,k,Package(value['manifest'],{x:value['manifest'][x] for x in
            ('corpusId','corpusVersionId','sources','inputArtifacts')},{},{},Path('.')))
        core = {x:y for x,y in m.items() if x != 'projectionReviewRef'}
        rr = {'schema':'learning-projection-review-request/1', 'mappingDigest':digest(core),
            'artifactRefs':review['artifactRefs'], **{x:m[x] for x in
                ('briefRef','recognitionRef','packageRef','prepareRef')},
            'basisRefs':[m['reviewRef']],
            'purpose':'审实际上传全文、目标适切性、认可范围、新事实及判分依据；不等同实际生成课件I4。'}
        check(review['requestDigest'] == digest(rr) and review['basisRefs'] == rr['basisRefs'])
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise DeliveryError('preparation_provenance_invalid', '准备依据的结构、引用或摘要不一致', 'conflict') from exc
    return value


def save_provenance(store, value):
    verify_provenance(value)
    data = canonical(value)
    ref = {'path':'preparations/' + sha256(data) + '.json', 'sha256':sha256(data)}
    _check_chain(store.root / ref['path'], missing=True)
    atomic(store.root / ref['path'], data, immutable=True)
    return ref


def provenance_bytes(root, ref):
    if (type(ref) is not dict or set(ref) != {'path','sha256'} or type(ref['sha256']) is not str
            or ref['path'] != 'preparations/' + ref['sha256'] + '.json'
            or len(ref['sha256']) != 64 or any(c not in '0123456789abcdef' for c in ref['sha256'])):
        raise DeliveryError('preparation_provenance_ref', '准备依据定位无效', 'conflict')
    path = Path(root) / ref['path']
    _check_chain(path)
    with path.open('rb') as stream: data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or sha256(data) != ref['sha256']:
        raise DeliveryError('preparation_provenance_hash', '准备依据缺失或被替换', 'conflict')
    verify_provenance(decode_json(data))
    return data


def load_provenance(store, ref, binding=None):
    return verify_provenance(decode_json(provenance_bytes(store.root, ref)), binding)
