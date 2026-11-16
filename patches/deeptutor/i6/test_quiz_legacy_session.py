"""用已安装 wheel 和独立的真实 HTTP 服务验证首答，固定夹具，无模型。"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--expected-first-status", required=True, type=int, choices=(200, 500))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="i6-quiz-", dir=args.scratch.resolve(strict=True)) as temp:
        runtime = Path(temp)
        allowed = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATH", "PATHEXT"}
        child_env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        child_env.update(DEEPTUTOR_HOME=str(runtime), DEEPTUTOR_VERSION_CHECK_ENABLED="false", PYTHONUTF8="1")
        os.environ.clear()
        os.environ.update(child_env)
        from deeptutor.book.models import Block, Book, Chapter, Page, Spine
        from deeptutor.book.storage import get_book_storage
        from deeptutor.services.llm.usage_ledger import ledger_path

        storage = get_book_storage()
        book_id, page_id, chapter_id, block_id = "bk_i6_fixture", "pg_i6", "ch_i6", "blk_i6"
        storage.save_book(Book(id=book_id, title="I6 fixture", status="ready", page_count=1, chapter_count=1))
        storage.save_spine(Spine(book_id=book_id, chapters=[Chapter(id=chapter_id, page_ids=[page_id])]))
        storage.save_page(Page(id=page_id, book_id=book_id, chapter_id=chapter_id, status="ready", blocks=[
            Block(id=block_id, type="quiz", status="ready", payload={"questions": [{
                "id": "q_i6", "question_type": "choice", "question": "Pick A.",
                "options": {"A": "A", "B": "B"}, "correct_answer": "A",
            }]})
        ]))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        client = build_opener(ProxyHandler({}))

        def request(path, payload=None):
            req = Request(f"http://127.0.0.1:{port}{path}",
                          data=None if payload is None else json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
            try:
                response = client.open(req, timeout=6)
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        with (runtime / "server.log").open("w+b") as log:
            server = subprocess.Popen(
                [sys._base_executable, "-B", "-m", "deeptutor_cli.main", "serve",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=runtime, env={**child_env, "PYTHONPATH": str(Path(sys.prefix) / "Lib/site-packages")},
                stdout=log, stderr=log,
            )
            try:
                for _ in range(80):
                    if server.poll() is not None:
                        raise RuntimeError("隔离服务提前退出")
                    try:
                        if request("/health/ready")[0] == 200:
                            break
                    except URLError:
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError("隔离服务启动超时")
                content_status, content = request(f"/api/books/{book_id}/content")
                state_path = f"/api/books/{book_id}/learning-state"
                before_status, before = request(state_path)
                submitted = {
                    "book_id": book_id, "page_id": page_id, "block_id": block_id,
                    "question_id": "q_i6", "user_answer": "A", "is_correct": True,
                    "submission_id": "i6-fixture-submission",
                }
                first_status, result = request("/api/books/quiz-attempt", submitted)
                after_status, after = request(state_path)
                attempts = after["progress"]["value"]["quiz_attempts"]
                assert content_status == before_status == after_status == 200
                assert content["schema"] == "book-content-read/1"
                assert before["schema"] == "book-learning-state-read/1"
                assert before["progress"]["status"] == "missing"
                assert first_status == args.expected_first_status, first_status
                assert len(attempts) == 1 and attempts[0]["submission_id"] == submitted["submission_id"]
                if first_status == 200:
                    assert result["progress"]["quiz_attempts"] == attempts
                else:
                    assert result["detail"] == "Failed to save Focus-Check evidence"
                assert not ledger_path().exists()
                print(json.dumps({
                    "contentStatus": content_status, "learningStateStatus": before_status,
                    "firstQuizStatus": first_status, "firstQuizDetail": result.get("detail"),
                    "retainedAttempts": len(attempts), "modelLedgerCreated": False,
                }))
            finally:
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=8)


if __name__ == "__main__":
    main()
