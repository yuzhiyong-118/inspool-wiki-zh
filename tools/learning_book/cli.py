"""学习资料交付 CLI：stdout 始终输出一个 JSON 结果。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .budget import load_budget, process_identity
from .baseline import Baseline
from .contracts import DeliveryError, digest, load_deployment, read_json, validate_package
from .deeptutor import DeepTutor
from .evidence_store import EvidenceStore
from .production import Production
from .handoff import Handoff, verify_handoff


EXIT_CODES = {"succeeded": 0, "invalid": 2, "conflict": 3, "busy": 4,
              "failed": 5, "uncertain": 6, "partial": 7, "prepared": 6, "dispatching": 6, 'needs_review':2}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # 参数错误可能包含私有参数，固定输出，不回显传入值。
        raise DeliveryError("arguments", "参数无效；用 --help 查看调用方式")


def parser():
    root = Parser(description=__doc__)
    commands = root.add_subparsers(dest="operation", required=True, parser_class=Parser)
    validate = commands.add_parser("validate", help="纯本地资料包校验")
    validate.add_argument("--package", required=True)
    validate.add_argument("--package-root")
    process = commands.add_parser("process-identity", help="只读选定 server PID 身份，供受控部署绑定")
    process.add_argument("--pid", type=int, required=True)
    verify = commands.add_parser("verify-handoff", help="离线验证可搬运学习交接包")
    verify.add_argument("--package", required=True)
    continuation = commands.add_parser('revalidate-preparation', help='同活动准备重新核验；只读远端，不生成课程')
    for name in ('state-dir','deployment','activity','continuation-id','knowledge-preparation','reason'):
        continuation.add_argument('--'+name, required=True)
    continuation.add_argument('--expected-revision', required=True, type=int)
    continuation.add_argument('--review-file')
    quiz=commands.add_parser('prepare-quiz',help='向已映射课程传递预审选择题模板')
    for name in ('activity','request-id','deployment','state-dir','page-id','block-id','budget-context'):
        quiz.add_argument('--'+name,required=True)
    inputs = quiz.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--templates')
    inputs.add_argument('--question-preparation')
    quiz.add_argument('--expected-revision',required=True,type=int)
    quiz.add_argument('--retry-of')
    quiz.add_argument('--knowledge-preparation')
    authored = commands.add_parser('publish-quiz', help='无模型发布已审定稿题目')
    for name in ('activity','request-id','deployment','state-dir','page-id','block-id','budget-context','question-preparation'):
        authored.add_argument('--'+name, required=True)
    authored.add_argument('--expected-revision', required=True, type=int)
    authored.add_argument('--retry-of'); authored.add_argument('--knowledge-preparation')
    author_block = commands.add_parser('author-block', help='经准备审阅写入作者正文，不调用模型')
    for name in ('activity','request-id','deployment','state-dir','page-id','budget-context','knowledge-preparation'):
        author_block.add_argument('--'+name, required=True)
    author_block.add_argument('--operation', dest='author_operation', required=True)
    author_block.add_argument('--expected-revision', required=True, type=int)
    author_block.add_argument('--block-id'); author_block.add_argument('--title')
    author_block.add_argument('--position', type=int); author_block.add_argument('--retry-of')
    body = author_block.add_mutually_exclusive_group(required=True)
    body.add_argument('--body'); body.add_argument('--body-file')
    extension = commands.add_parser('append-extension', help='以显式未审模式追加学习扩展，不调用模型')
    for name in ('activity','request-id','deployment','state-dir','page-id','extension-id','blocks',
                 'budget-context','knowledge-preparation','question-preparation','expected-revision'):
        extension.add_argument('--'+name, required=True, type=int if name == 'expected-revision' else str)
    extension.add_argument('--position', type=int); extension.add_argument('--retry-of')
    author_plan = commands.add_parser('author-plan', help='只读生成当前整书交付计划')
    for name in ('activity','deployment','state-dir'):
        author_plan.add_argument('--'+name, required=True)
    complete = commands.add_parser('complete-authored-book', help='按实际页块完成作者整书交付')
    for name in ('activity','request-id','deployment','state-dir','plan','budget-context','knowledge-preparation'):
        complete.add_argument('--'+name, required=True)
    complete.add_argument('--expected-revision', required=True, type=int)
    complete.add_argument('--retry-of')
    export = commands.add_parser("export-results", help="只读导出有限学习记录和公开会话")
    for name in ("activity", "export-id", "deployment", "state-dir"):
        export.add_argument("--" + name, required=True)
    for name in ("snapshot-id", "sessions-file", "collection-declaration", "completion-declaration", "clock-assumption", "limits"):
        export.add_argument("--" + name)
    for name in ("capture-baseline", "check-baseline", "review-baseline"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", required=True)
        command.add_argument("--deployment", required=True)
        command.add_argument("--activity", required=True)
        command.add_argument("--snapshot-id", required=True)
        if name == "capture-baseline":
            command.add_argument("--capture-id", required=True)
            command.add_argument("--purpose", choices=("pre_learning", "retrospective"), required=True)
            command.add_argument("--declaration", help="pre_learning 时必需：actorId/statement JSON")
        elif name == "check-baseline":
            command.add_argument("--check-id", required=True)
        else:
            command.add_argument("--review-id", required=True)
            command.add_argument("--review-file", required=True)
    for name in ("publish-inputs", "recover-inputs", "create", "confirm-proposal", "confirm-spine", "show", "reconcile"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", required=True)
        command.add_argument("--deployment", required=True)
        command.add_argument("--request-id", required=True)
        if name not in ("show", "reconcile"):
            command.add_argument("--budget-context")
            command.add_argument("--retry-of")
            command.add_argument('--knowledge-preparation', help='显式知识准备接线 JSON；受控请求不可省略')
        if name == "publish-inputs":
            command.add_argument("--package", required=True)
            command.add_argument("--package-root")
        elif name == "create":
            command.add_argument("--corpus-receipt", required=True, help="publish-inputs 回传的 corpusReceiptRef（请求 ID）")
            command.add_argument("--activity-id", required=True)
            command.add_argument("--intent", required=True)
            command.add_argument("--replacement-of", help="已有首次基线的旧 activity；创建替代书，不重绑旧答案")
        elif name.startswith("confirm-"):
            command.add_argument("--activity", required=True)
            command.add_argument("--payload", required=True, help="JSON 对象或 null；null 表示确认上游当前产物")
            command.add_argument("--expected-revision", required=True, type=int)
        elif name == "show":
            command.add_argument("--rebuild-index", action="store_true")
        elif name == "reconcile":
            command.add_argument("--candidate-book-id")
    return root


def run(args):
    if args.operation == "validate":
        package = validate_package(args.package, args.package_root)
        return {"operation": "validate", "requestId": None, "status": "succeeded", "receiptRef": None,
                "activityRef": None, "errors": [], "nextAction": "publish_inputs_when_authorized",
                "manifest": package.manifest, "corpusDigest": digest(package.corpus)}
    if args.operation == "process-identity":
        return {"operation": args.operation, "status": "succeeded", "identity": process_identity(args.pid),
                "errors": [], "nextAction": "bind_only_owned_dedicated_server"}
    if args.operation == "verify-handoff":
        return {"operation": "verify-handoff", **verify_handoff(args.package)}
    config = load_deployment(args.deployment)
    store = EvidenceStore(args.state_dir)
    if args.operation == 'revalidate-preparation':
        from .knowledge_preparation import PreparationGuard
        app = Production(store, DeepTutor(config), preparation_guard=PreparationGuard(args.knowledge_preparation))
        return app.revalidate_preparation(args.activity, args.continuation_id, args.expected_revision,
            args.reason, read_json(args.review_file) if args.review_file else None)
    if args.operation == "export-results":
        return Handoff(store, DeepTutor(config)).export_learning_results(args.activity, args.export_id,
            snapshot_id=args.snapshot_id, sessions=read_json(args.sessions_file) if args.sessions_file else None,
            collection_declaration=read_json(args.collection_declaration) if args.collection_declaration else None,
            completion_declaration=read_json(args.completion_declaration) if args.completion_declaration else None,
            clock_assumption=read_json(args.clock_assumption) if args.clock_assumption else None,
            limits=read_json(args.limits) if args.limits else None)
    if args.operation in ("capture-baseline", "check-baseline", "review-baseline"):
        app = Baseline(store, DeepTutor(config))
        if args.operation == "capture-baseline":
            return app.capture_baseline(args.activity, args.capture_id, args.snapshot_id, args.purpose,
                                        read_json(args.declaration) if args.declaration else None)
        if args.operation == "check-baseline":
            return app.check_baseline(args.activity, args.snapshot_id, args.check_id)
        return app.record_baseline_review(args.activity, args.snapshot_id, args.review_id, read_json(args.review_file))
    budget = load_budget(getattr(args, "budget_context", None), config["scope"])
    guard = None
    if getattr(args, 'knowledge_preparation', None):
        from .knowledge_preparation import PreparationGuard
        guard = PreparationGuard(args.knowledge_preparation)
    question_guard = None
    if getattr(args, 'question_preparation', None):
        from .question_preparation import QuestionPreparation
        question_guard = QuestionPreparation(args.question_preparation)
    app = Production(store, DeepTutor(config), budget, preparation_guard=guard, question_guard=question_guard)
    if args.operation == 'append-extension':
        return app.append_extension(args.activity, args.request_id, args.page_id, args.extension_id,
            read_json(args.blocks), args.expected_revision, position=args.position, retry_of=args.retry_of)
    if args.operation == 'author-plan':
        return {'operation': 'author-plan', 'status': 'succeeded',
                'plan': app.author_delivery_plan(args.activity), 'modelCalls': 0}
    if args.operation == 'author-block':
        body = args.body if args.body is not None else Path(args.body_file).read_text(encoding='utf-8')
        return app.author_block(args.activity, args.request_id, args.page_id, args.author_operation, body,
            args.expected_revision, block_id=args.block_id, title=args.title, position=args.position,
            retry_of=args.retry_of)
    if args.operation == 'complete-authored-book':
        return app.complete_authored_book(args.activity, args.request_id, read_json(args.plan),
            args.expected_revision, retry_of=args.retry_of)
    if args.operation == 'publish-quiz':
        return app.publish_quiz(args.activity, args.request_id, args.page_id, args.block_id,
            args.expected_revision, retry_of=args.retry_of)
    if args.operation=='prepare-quiz':
        return app.prepare_quiz(args.activity,args.request_id,args.page_id,args.block_id,
            read_json(args.templates) if args.templates else None,args.expected_revision,retry_of=args.retry_of)
    if args.operation == "publish-inputs":
        if guard is not None:
            _, package, _ = guard.checked()
            cfg, kwargs, _ = guard._inputs()
            if (kwargs['projection_root'] / cfg['prepare']).resolve() != Path(args.package).resolve():
                raise DeliveryError('preparation_package_path', 'CLI package 与接线中的实际资料包不符')
            if args.package_root and Path(args.package_root).resolve() != package.root:
                raise DeliveryError('preparation_package_root', 'CLI package-root 与接线不符')
        else:
            package = validate_package(args.package, args.package_root)
        return app.publish_learning_inputs(package, args.request_id, retry_of=args.retry_of)
    if args.operation == "recover-inputs":
        return app.recover_inputs(args.request_id)
    if args.operation == "create":
        return app.create_activity(args.corpus_receipt, args.request_id, args.activity_id, args.intent,
            retry_of=args.retry_of, replacement_of=args.replacement_of)
    if args.operation.startswith("confirm-"):
        operation = app.confirm_proposal if args.operation == "confirm-proposal" else app.confirm_spine
        return operation(args.activity, args.request_id, read_json(args.payload), args.expected_revision, retry_of=args.retry_of)
    if args.operation == "show":
        return app.inspect_receipt(args.request_id, rebuild_index=args.rebuild_index)
    return app.reconcile_request(args.request_id, candidate_book_id=args.candidate_book_id)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    operation, request_id = None, None
    try:
        args = parser().parse_args(argv)
        operation, request_id = args.operation, getattr(args, "request_id", None)
        result = run(args)
    except DeliveryError as exc:
        result = {"operation": operation, "requestId": request_id, "status": exc.status,
                  "receiptRef": None, "activityRef": None, "errors": [{"code": exc.code, "message": exc.message}],
                  "nextAction": "inspect_configuration_or_receipt"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError):
        result = {"operation": operation, "requestId": request_id, "status": "failed", "receiptRef": None,
                  "activityRef": None, "errors": [{"code": "local_failure", "message": "本地文件／契约处理失败；核对持久回执后再继续"}],
                  "nextAction": "inspect_receipt_before_retrying"}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return EXIT_CODES.get(result["status"], 5)


if __name__ == "__main__":
    sys.exit(main())
