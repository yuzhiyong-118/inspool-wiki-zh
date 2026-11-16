"""W1 统一操作 CLI；JSON 回执，正式副作用仍走既有独立入口。"""
from __future__ import annotations

import argparse
import json
import sys

from .operations import OperationError, describe_input, inspect_task, prepare_next


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    describe = commands.add_parser("describe-input")
    describe.add_argument("--route", required=True,
                          choices=("learning", "knowledge", "knowledge_and_learning"))
    describe.add_argument("--stage-count", type=int)
    inspect = commands.add_parser("inspect-task")
    inspect.add_argument("--order", required=True)
    inspect.add_argument("--work-root", required=True)
    inspect.add_argument("--expected-order-sha256")
    inspect.add_argument("--expected-inputs-sha256")
    prepare = commands.add_parser("prepare-next")
    prepare.add_argument("--order", required=True)
    prepare.add_argument("--work-root", required=True)
    prepare.add_argument("--expected-order-sha256", required=True)
    prepare.add_argument("--expected-inputs-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "describe-input":
            result = describe_input(args.route, args.stage_count)
        elif args.operation == "inspect-task":
            result = inspect_task(args.order, args.work_root, args.expected_order_sha256,
                                  args.expected_inputs_sha256)
        else:
            result = prepare_next(args.order, args.work_root, args.expected_order_sha256,
                                  args.expected_inputs_sha256)
        code = 0 if result["status"] in ("ready", "succeeded") else 2
    except (OperationError, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        error = getattr(exc, "code", None)
        result = {"operation": args.operation, "status": "rejected",
                  "error": error if isinstance(error, str) else "invalid_or_unreadable_input",
                  "artifactRefs": [], "nextActions": ["inspect_input_contract_and_current_dependencies"],
                  "formalWriteAuthorized": False, "coursePublishAuthorized": False}
        code = 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
