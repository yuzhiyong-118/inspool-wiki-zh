"""T5 合成学习工作流与真实 Host 子进程入口。"""
from __future__ import annotations

import json
import sys

from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.runtime import empty_proposal


def confirm_learning(host, task_id):
    rows = host.runtime.store.read(
        "SELECT record_json FROM learning_states WHERE task_id='" + task_id + "'"
    )
    if not rows:
        raise ValueError('学习任务不存在')
    learning = json.loads(rows[0]['record_json'])
    event = {
        'event_id': 'confirm-' + task_id,
        'producer': 'synthetic-learning-workflow',
        'task_id': task_id,
        'type': 'learning_confirmation_ready',
        'payload_digest': digest(learning),
        'payload_ref': None,
        'target_version': learning['knowledge_version'],
        'causation_id': None,
        'receipt_sequence': 1,
        'processing_state': 'pending',
    }
    host.accept_learning_event(event)

    def planner(frozen):
        current = dict(frozen['learning_state'], state='awaiting_confirmation')
        return empty_proposal(
            frozen['task']['revision'], learning_state=current, task_state='running',
        )

    host.plan_learning(planner)
    return learning


def main():
    command, root, state_dir, identity = sys.argv[1:5]
    host = StandaloneHost(root, state_dir, None, offline=True)
    try:
        if command == 'revoke':
            result = host.revoke_pending(identity)
        elif command == 'revoke-learning':
            result = host.revoke_learning_authorization(identity)
        elif command == 'pause':
            result = host.pause_learning(identity)
        else:
            raise ValueError(command)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        host.close()


if __name__ == '__main__':
    main()
