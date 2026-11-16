"""K4：知识准备与 I3 的显式接线；不认证操作者，不自行授权传输。"""
from __future__ import annotations

import copy
from pathlib import Path

from .contracts import DeliveryError, digest
from tools.wiki_runtime.evidence.cli import _load
from tools.wiki_runtime.evidence.preparation import _fields, _need, _root, _text
from tools.wiki_runtime.evidence.projection import build_learning_projection, _prepare


class PreparationGuard:
    def __init__(self, descriptor):
        self.descriptor = Path(descriptor).absolute()

    def _inputs(self):
        cfg = _load(self.descriptor)
        _fields(cfg, {'schema', 'wikiRoot', 'sourceRoot', 'projectionRoot', 'recognitionRoot',
            'context', 'knowledge', 'brief', 'request', 'recognition', 'review', 'previous',
            'prepare', 'operationReview'}, 'preparation_descriptor_fields')
        _need(cfg['schema'] == 'knowledge-preparation-connection/1', 'preparation_descriptor_schema')

        def path(key):
            _text(cfg[key], 'preparation_descriptor_path')
            return self.descriptor.parent / cfg[key]

        kwargs = {k: _root(path(v)) for k, v in (
            ('wiki_root', 'wikiRoot'), ('source_root', 'sourceRoot'),
            ('projection_root', 'projectionRoot'), ('recognition_root', 'recognitionRoot'))}
        kwargs['prepare_path'] = cfg['prepare']
        for key in ('recognition', 'review', 'previous'):
            kwargs[key] = None if cfg[key] is None else _load(path(key))
        return cfg, kwargs, [_load(path(k)) for k in ('context', 'knowledge', 'brief', 'request')]

    def checked(self, *, include_provenance=False):
        """每次重读描述文件、观察与实际依赖；输出固定上传 bytes。"""
        try:
            cfg, kwargs, args = self._inputs()
            result = build_learning_projection(*args, **kwargs)
            if result['projectionState'] != 'reviewed_for_scope':
                raise DeliveryError('preparation_' + result['projectionState'],
                                    '知识准备未通过或已失效；先核对对应观察', 'conflict')
            _, package, dependencies = _prepare(kwargs['projection_root'], kwargs['prepare_path'])
            _need(dependencies == result['dependencies'] and digest(package.manifest) ==
                  result['prepareRef']['normalizedManifestDigest'], 'preparation_changed_before_send')
            mapping = result['mapping']
            binding = {'schema': 'knowledge-preparation-binding/1',
                'mappingDigest': digest(mapping), 'intent': mapping['intent'],
                'normalizedManifestDigest': mapping['prepareRef']['normalizedManifestDigest'],
                'assurance': 'operator_supplied_no_host_authentication'}
            if include_provenance:
                from .preparation_provenance import verify_provenance
                archive = {'schema':'learning-preparation-provenance/1', 'binding':binding,
                    'mapping':result['mapping'], 'brief':args[2], 'recognition':kwargs['recognition'],
                    'knowledge':args[1], 'projectionReview':kwargs['review'], 'manifest':package.manifest,
                    'existingDocuments':[{key:row[key] for key in
                        ('pageId','locator','byteDigest','bytes','text')} for row in args[0]['documents']],
                    'sourceRetention':'external', 'sourceOriginalsVerified':False,
                    'assurance':'operator_supplied_no_host_authentication'}
                verify_provenance(archive, binding)
                return binding, package, cfg, archive
            return binding, package, cfg
        except DeliveryError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise DeliveryError('preparation_invalid', '知识准备输入或实际依赖无效；未授权发送', 'conflict') from exc

    def review_request(self, operation, activity_id, scope, payload, *, binding=None):
        """准备者用真实待发送参数供独立审阅；不是用户/宿主认证。"""
        if binding is None:
            binding, _, _ = self.checked()
        _need(operation in ('confirm-proposal', 'confirm-spine', 'prepare-quiz', 'publish-quiz', 'author-block', 'complete-authored-book'), 'production_review_operation')
        _need(type(payload) is dict, 'production_review_payload')
        if operation in ('confirm-proposal', 'confirm-spine'):
            key = 'proposal' if operation == 'confirm-proposal' else 'spine'
            _need(type(payload.get(key)) is dict, 'production_review_explicit_payload_required')
        result = {'schema': 'learning-production-review-request/1',
            'operation': operation, 'activityId': activity_id, 'scope': copy.deepcopy(scope),
            'preparationBinding': binding, 'payload': copy.deepcopy(payload)}
        result['requestDigest'] = digest(result)
        return result

    def validate(self, manifest, *, intent=None, expected=None, package=None,
                 operation=None, activity_id=None, scope=None, payload=None, include_review=False):
        binding, actual, cfg = self.checked()
        step_observation = None
        if (digest(manifest) != binding['normalizedManifestDigest']
                or (intent is not None and intent != binding['intent'])
                or (expected is not None and expected != binding)):
            raise DeliveryError('preparation_binding', '实际请求与已审映射绑定不一致', 'conflict')
        if package is not None and (package.manifest != actual.manifest or package.corpus != actual.corpus
                                    or package.inputs != actual.inputs):
            raise DeliveryError('preparation_upload_bytes', '实际上传成员或字节与已审投影不一致', 'conflict')
        if operation in ('confirm-proposal', 'confirm-spine', 'prepare-quiz', 'publish-quiz', 'author-block', 'complete-authored-book'):
            try:
                rr = self.review_request(operation, activity_id, scope, payload, binding=binding)
                _need(cfg['operationReview'] is not None, 'production_review_missing')
                review = _load(self.descriptor.parent / cfg['operationReview'])
                _fields(review, {'schema', 'id', 'requestDigest', 'reviewedBy', 'recordedAt',
                    'decision', 'reason', 'assurance'}, 'production_review_fields')
                for key in ('id', 'reviewedBy', 'recordedAt', 'reason'):
                    _text(review[key], 'production_review_text')
                _need(review['schema'] == 'learning-production-review/1'
                      and review['assurance'] == 'operator_supplied'
                      and review['decision'] == 'reviewed_for_scope'
                      and review['requestDigest'] == rr['requestDigest'], 'production_review_binding')
                step_observation = {'request': rr, 'review': review}
            except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
                raise DeliveryError('production_review_required',
                    '后续生产步骤须审实际非空 payload、目标书及 revision；初始映射不覆盖这些新内容', 'conflict') from exc
        return (binding, step_observation) if include_review else binding
