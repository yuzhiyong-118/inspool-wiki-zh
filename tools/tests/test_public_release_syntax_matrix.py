"""链接语法族矩阵：穷举标准写法，验证每一格要么被解析并检查，要么被报告。

覆盖内联链接与图片、引用式链接与图片（含短式、折叠式、可选标题、尖括号与配对括号）、
HTML 链接与图片、以及应当被忽略的写法（代码块、行内代码、注释、自动链接、普通方括号）。

判定口径只有两条：被解析并检查，或被报告；不允许静默放过。
"""
import unittest

from tools.check_public_release import check_tree, link_targets

TREE = {
    'doc.md': '# T\n',
    'other.md': '# 其它\n\n## 标题\n',
    'img.png': 'x\n',
    'dir/a(b)c.md': '# x\n',
}

# (名称, 正文, 期望条目种类, 期望阻断码)
CASES = [
    ('内联-基础', '# T\n\n[x](other.md)\n', {'inline'}, set()),
    ('内联-尖括号', '# T\n\n[x](<other.md>)\n', {'inline'}, set()),
    ('内联-双引号标题', '# T\n\n[x](other.md "ti")\n', {'inline'}, set()),
    ('内联-单引号标题', "# T\n\n[x](other.md 'ti')\n", {'inline'}, set()),
    ('内联-圆括号标题', '# T\n\n[x](other.md (ti))\n', {'inline'}, set()),
    ('内联-两端空格', '# T\n\n[x]( other.md )\n', {'inline'}, set()),
    ('内联-配对括号目标', '# T\n\n[x](dir/a(b)c.md)\n', {'inline'}, set()),
    ('内联-空目标', '# T\n\n[x]()\n', {'inline'}, {'empty-target'}),
    ('内联-纯片段', '# T\n\n## 标题\n\n[x](#标题)\n', {'inline'}, set()),
    ('内联-带片段', '# T\n\n[x](other.md#标题)\n', {'inline'}, set()),
    ('内联-带查询串', '# T\n\n[x](other.md?a=1)\n', {'inline'}, set()),
    ('内联-未闭合', '# T\n\n[x](other.md\n', {'broken'}, {'unparsed-link'}),
    ('内联-指向私人目录', '# T\n\n[x](raw/secret.md)\n', {'inline'},
     {'unpublished-target'}),

    ('图片-基础', '# T\n\n![a](img.png)\n', {'image'}, set()),
    ('图片-尖括号带空格', '# T\n\n![a](<raw/private image.png>)\n', {'image'},
     {'unpublished-target'}),
    ('图片-引用式', '# T\n\n![a][r]\n\n[r]: img.png\n', {'image'}, set()),
    ('图片-引用式指向私人', '# T\n\n![a][r]\n\n[r]: raw/x.png\n', {'image'},
     {'unpublished-target'}),
    ('图片-折叠引用', '# T\n\n![a][]\n\n[a]: img.png\n', {'image'}, set()),

    ('引用-完整', '# T\n\n[x][r]\n\n[r]: other.md\n', {'ref'}, set()),
    ('引用-折叠', '# T\n\n[x][]\n\n[x]: other.md\n', {'ref'}, set()),
    ('引用-短式', '# T\n\n[x]\n\n[x]: other.md\n', {'ref'}, set()),
    ('引用-定义带标题', '# T\n\n[x]\n\n[x]: other.md "ti"\n', {'ref'}, set()),
    ('引用-定义尖括号', '# T\n\n[x]\n\n[x]: <other.md>\n', {'ref'}, set()),
    ('引用-短式指向私人目录', '# T\n\n[x]\n\n[x]: wiki/private.md\n', {'ref'},
     {'unpublished-target'}),
    ('引用-短式定义带标题指向私人目录', '# T\n\n[x]\n\n[x]: wiki/private.md "Title"\n',
     {'ref'}, {'unpublished-target'}),
    ('引用-缺定义', '# T\n\n[x][missing]\n', {'unresolved'}, set()),

    ('html-双引号', '# T\n\n<a href="other.md">文本</a>\n', {'html'}, set()),
    ('html-单引号', "# T\n\n<a href='other.md'>文本</a>\n", {'html'}, set()),
    ('html-无引号', '# T\n\n<a href=other.md>文本</a>\n', {'html'}, set()),
    ('html-大写与额外属性', '# T\n\n<A HREF="other.md" title="x">文本</A>\n', {'html'}, set()),
    ('html-无引号指向私人目录', '# T\n\n<a href=raw/x.md>文本</a>\n', {'html'},
     {'unpublished-target'}),
    ('html-图片指向私人目录', '# T\n\n<img src="raw/x.png" alt="图">\n', {'image'},
     {'unpublished-target'}),
    ('html-图片存在', '# T\n\n<img src="img.png" alt="图">\n', {'image'}, set()),
    ('html-指向私人目录', '# T\n\n<a href="raw/x.md">文本</a>\n', {'html'},
     {'unpublished-target'}),
    ('html-注释内不算活跃', '# T\n\n<!-- <a href="raw/x.md">x</a> -->\n', set(), set()),
    ('html-空标签不阻断', '# T\n\n<a href="other.md"></a>\n', {'html'}, set()),

    ('自动链接不阻断', '# T\n\n<https://example.com/a>\n', set(), set()),
    ('纯文本方括号不阻断', '# T\n\n这是 [注] 这样的普通文字\n', set(), set()),
    ('代码块内链接不阻断', '# T\n\n```\n[x](raw/x.md)\n```\n', set(), set()),
    ('行内代码内链接不阻断', '# T\n\n`[x](raw/x.md)`\n', set(), set()),
    ('wikilink 报告人工审查', '# T\n\n[[meta/graph-schema]]\n', {'wiki'}, set()),
]


class SyntaxMatrixTests(unittest.TestCase):
    def test_each_construct_is_parsed_or_reported(self):
        for name, text, expect_kinds, expect_codes in CASES:
            with self.subTest(case=name):
                files = dict(TREE)
                files['doc.md'] = text
                issues = check_tree(files, set(files))
                kinds = {kind for _l, _b, _t, kind in link_targets(text)}
                self.assertTrue(expect_kinds <= kinds,
                                f'期望条目 {sorted(expect_kinds)}，实际 {sorted(kinds)}')
                blocking = {i['code'] for i in issues if i['severity'] == 'blocking'}
                for code in expect_codes:
                    self.assertIn(code, blocking, f'期望阻断码 {code}，实际 {sorted(blocking)}')
                if not expect_codes:
                    self.assertEqual(blocking, set(),
                                     f'出现非期望阻断 {sorted(blocking)}')

    def test_matrix_covers_every_case(self):
        names = [name for name, *_ in CASES]
        self.assertEqual(len(names), len(set(names)), '用例名称重复')


if __name__ == '__main__':
    unittest.main()
