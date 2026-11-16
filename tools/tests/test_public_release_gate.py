"""公开发布门禁的反例测试：覆盖方案 §8.2 列出的必测场景。

全部在临时 Git 仓库中构造暂存树，检查只读索引，不依赖网络或模型。
"""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.check_public_release import check, check_tree, path_error


def build_repo(root, files, allowlist=None, exceptions=None):
    """在 root 建临时 Git 仓库，把 files 写入并暂存。"""
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    names = allowlist if allowlist is not None else list(files)
    manifest = {'schema': 1, 'description': 'test', 'files': sorted(set(names) | {'public-files.json'})}
    if exceptions is not None:
        manifest['exceptions'] = exceptions
    (root / 'public-files.json').write_text(
        json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True, capture_output=True)
    return root


def codes(issues):
    return [issue['code'] for issue in issues]


class GateLinkTests(unittest.TestCase):
    def test_untracked_target_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[缺失](docs/missing.md)\n'})
            (root / 'docs').mkdir()
            (root / 'docs' / 'missing.md').write_text('# x\n', encoding='utf-8')
            count, issues = check(root)
            self.assertIn('unpublished-target', codes(issues))
            self.assertTrue(any('工作区存在但未跟踪' in i['message'] for i in issues))

    def test_index_is_checked_not_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[缺失](docs/missing.md)\n'})
            (root / 'doc.md').write_text('# T\n\n[正常](docs/ok.md)\n', encoding='utf-8')
            (root / 'docs').mkdir()
            (root / 'docs' / 'ok.md').write_text('# ok\n', encoding='utf-8')
            count, issues = check(root)
            self.assertIn('unpublished-target', codes(issues))

    def test_path_with_space_and_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {
                '设计 说明.md': '# 标题\n\n[链接](<设计 说明.md>)\n',
                '其他.md': '# 标题\n\n[链接](其他.md)\n',
            })
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['code'] in
                              ('unpublished-target', 'escape', 'path')], [])

    def test_path_escape_is_blocked(self):
        files = {'doc.md': '# T\n\n[越界](../../outside.md)\n'}
        issues = check_tree(files, set(files))
        self.assertIn('escape', codes(issues))

    def test_directory_link_requires_tracked_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {
                'doc.md': '# T\n\n[目录](docs)\n',
                'docs/a.md': '# a\n',
            })
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['code'] == 'unpublished-target'], [])
            # 目标目录不在暂存树时必须报错
            issues2 = check_tree({'doc.md': '# T\n\n[目录](docs)\n'}, {'doc.md'})
            self.assertIn('unpublished-target', codes(issues2))

    def test_missing_anchor_is_blocked(self):
        files = {
            'doc.md': '# T\n\n[锚点](other.md#不存在)\n',
            'other.md': '# 其它\n\n## 真实标题\n',
        }
        issues = check_tree(files, set(files))
        self.assertIn('anchor', codes(issues))

    def test_code_block_example_is_not_active_link(self):
        files = {'doc.md': '# T\n\n```markdown\n[示例](docs/missing.md)\n```\n'}
        issues = check_tree(files, set(files))
        self.assertEqual([i for i in issues if i['code'] == 'unpublished-target'], [])

    def test_reference_link_resolution(self):
        files = {'doc.md': '# T\n\n[定义][a]\n\n[a]: docs/other.md\n',
                 'docs/other.md': '# 其它\n'}
        issues = check_tree(files, set(files))
        self.assertEqual([i for i in issues if i['code'] == 'unpublished-target'], [])
        missing = {'doc.md': '# T\n\n[未定义][a]\n'}
        issues2 = check_tree(missing, set(missing))
        self.assertIn('ref', codes(issues2))
        self.assertEqual([i for i in issues2 if i['severity'] == 'blocking'], [])

    def test_missing_title_and_unclosed_frontmatter(self):
        files = {'doc.md': '---\n\n# 标题\n'}
        issues = check_tree(files, set(files))
        self.assertIn('frontmatter', codes(issues))
        files2 = {'doc.md': '正文没有标题\n'}
        issues2 = check_tree(files2, set(files2))
        self.assertIn('title', codes(issues2))


class GatePathTests(unittest.TestCase):
    def test_forced_private_paths_are_denied(self):
        for name in ('raw/unprocessed/secret.md', 'wiki/index.md',
                     'docs/design/evidence/output.json', 'references/upstream/x.md'):
            with self.subTest(name=name):
                self.assertIsNotNone(path_error(name, {name}))

    def test_missing_allowlist_entry_is_denied(self):
        self.assertIsNotNone(path_error('docs/new.md', {'docs/old.md'}))


class GateLinkSyntaxTests(unittest.TestCase):
    def test_short_reference_link_is_checked(self):
        files = {'doc.md': '# T\n\n[hidden]\n\n[hidden]: wiki/private.md\n'}
        issues = check_tree(files, set(files))
        self.assertIn('unpublished-target', codes(issues))

    def test_reference_image_is_checked(self):
        files = {'doc.md': '# T\n\n![image][hidden]\n\n[hidden]: raw/private.png\n'}
        issues = check_tree(files, set(files))
        self.assertIn('unpublished-target', codes(issues))

    def test_angle_bracket_image_target_with_space_is_checked(self):
        files = {'doc.md': '# T\n\n![image](<raw/private image.png>)\n'}
        issues = check_tree(files, set(files))
        self.assertIn('unpublished-target', codes(issues))

    def test_html_link_uses_visible_text_as_label(self):
        files = {'doc.md': '# T\n\n<a href="doc.md">正常</a>\n'}
        issues = check_tree(files, set(files))
        self.assertEqual([i for i in issues if i['code'] == 'empty-label'], [])
        self.assertEqual([i for i in issues if i['severity'] == 'blocking'], [])

    def test_html_comment_is_not_active_link(self):
        files = {'doc.md': '# T\n\n<!-- [x](raw/secret.md) -->\n'}
        issues = check_tree(files, set(files))
        self.assertEqual([i for i in issues if i['code'] == 'unpublished-target'], [])


class GateAnchorTests(unittest.TestCase):
    def test_heading_inside_code_block_is_not_an_anchor(self):
        files = {
            'doc.md': '# T\n\n```markdown\n## Fake\n```\n\n[链接](other.md#fake)\n',
            'other.md': '# 其它\n\n```markdown\n## Fake\n```\n',
        }
        issues = check_tree(files, set(files))
        self.assertIn('anchor', codes(issues))

    def test_duplicate_headings_get_numbered_anchors(self):
        files = {
            'doc.md': '# T\n\n[一](other.md#same)\n\n[二](other.md#same-1)\n',
            'other.md': '# 其它\n\n## Same\n\n## Same\n',
        }
        issues = check_tree(files, set(files))
        self.assertEqual([i for i in issues if i['code'] == 'anchor'], [])


class GateSyntaxRegressionTests(unittest.TestCase):
    """复审暴露的语法与锚点缺口，全部走真实暂存树路径。"""

    def test_reference_definition_with_title_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[hidden]\n\n[hidden]: wiki/private.md "Title"\n'})
            count, issues = check(root)
            self.assertIn('unpublished-target', codes(issues))

    def test_inline_target_with_balanced_parentheses_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[secret](wiki/private(copy).md)\n'})
            count, issues = check(root)
            self.assertIn('unpublished-target', codes(issues))

    def test_inline_link_with_title_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[x](other.md "Title")\n',
                              'other.md': '# 其它\n'})
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['severity'] == 'blocking'], [])

    def test_unparsable_link_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[broken](unclosed\n'})
            count, issues = check(root)
            self.assertIn('unparsed-link', codes(issues))

    def test_heading_with_inline_code_keeps_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[链接](other.md#使用-check-命令)\n',
                              'other.md': '# 其它\n\n## 使用 `check` 命令\n'})
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['code'] == 'anchor'], [])

    def test_percent_encoded_fragment_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[链接](other.md#%E4%B8%AD%E6%96%87)\n',
                              'other.md': '# 其它\n\n## 中文\n'})
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['code'] == 'anchor'], [])

    def test_percent_encoded_pure_fragment_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n## 中文\n\n[链接](#%E4%B8%AD%E6%96%87)\n'})
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['code'] == 'anchor'], [])

    def test_generated_anchor_collision_is_globally_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root, {'doc.md': '# T\n\n[链接](other.md#same-1-1)\n',
                              'other.md': '# 其它\n\n## Same\n\n## Same\n\n## Same-1\n'})
            count, issues = check(root)
            self.assertEqual([i for i in issues if i['code'] == 'anchor'], [])


class GateExceptionTests(unittest.TestCase):
    def test_precise_exception_downgrades_and_stale_one_blocks(self):
        content = '# T\n\n示例 key: sk-' + 'a' * 30 + '\n'
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        files = {'doc.md': content}
        good = check_tree(files, set(files), exceptions=[
            {'path': 'doc.md', 'code': 'secret', 'line': 3, 'digest': digest,
             'reason': '测试用假凭据'},
        ])
        self.assertEqual([i for i in good if i['code'] == 'secret' and
                          i['severity'] == 'blocking'], [])
        stale = check_tree(files, set(files), exceptions=[
            {'path': 'doc.md', 'code': 'secret', 'line': 3, 'digest': '0' * 64,
             'reason': '摘要已过期'},
        ])
        self.assertIn('exception-stale', codes(stale))
        self.assertTrue([i for i in stale if i['code'] == 'exception-stale'
                         and i['severity'] == 'blocking'])


if __name__ == '__main__':
    unittest.main()
