"""``tools/check_instance_markers.py`` 的判据测试。

这些用例固定住批次 J 实际踩到的形态：表格单元格里的账本金额、括号内嵌的金额、
以及不该被误报的授权额度。
"""
import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location(
    'check_instance_markers',
    pathlib.Path(__file__).resolve().parents[1] / 'check_instance_markers.py')
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class InstanceMarkerPatterns(unittest.TestCase):
    def names(self, text):
        return {hit[0] for hit in MOD.scan_text(text)}

    def test_instance_control_identity(self):
        self.assertIn('实例控制身份', self.names('当前实例为 architecture-cumulative-x1'))

    def test_trial_address(self):
        self.assertIn('试学地址', self.names('见 http://127.0.0.1:8080/s/course/1'))

    def test_course_activity_ids(self):
        self.assertIn('课程活动标识', self.names('活动 geo-flow-agent-20261110'))

    def test_private_project_name(self):
        self.assertIn('私有课程项目名', self.names('仓库 geo_flow 与 GeoFlow 均已改名'))

    def test_object_ids(self):
        self.assertIn('对象标识', self.names('对象 bk_0123abcd 与 pg_99ff0011'))

    def test_personal_choice(self):
        self.assertIn('个人选择', self.names('用户选择不备份任何一次运行'))

    def test_run_labels_and_instance_dirs(self):
        self.assertIn('实例运行标签', self.names('标签 prepared-quiz-001'))
        self.assertIn('实例运行标签', self.names('阶段 quiz_regeneration_interrupted'))
        self.assertIn('实例目录名', self.names('目录 runtime-i2'))

    def test_local_ports(self):
        self.assertIn('本机端口（散文）', self.names('网页 3836 已关闭'))
        self.assertIn('本机端口（成对）', self.names('端口 8246/3846 已关闭'))

    def test_ledger_amount_in_table_cell(self):
        """批次 J 实际漏掉的形态：金额在表格单元格里。"""
        text = '| I6 阶段基线 | 62 次调用／**200,821** tokens／输入 175,577 |'
        self.assertIn('实例账本金额', self.names(text))

    def test_ledger_amount_in_parentheses(self):
        """形态：金额在括号内嵌，前文是账本类关键词。"""
        text = '日常账本 567,049、80 万暂停／100 万上限保留。'
        self.assertIn('实例账本金额', self.names(text))

    def test_ledger_amount_after_merge_view(self):
        text = '原Q3新增9,095仍未归并，合并视角567,049；'
        self.assertIn('实例账本金额', self.names(text))

    def test_authorized_quota_is_not_a_hit(self):
        """授权额度与暂停线是设计参数，刻意保留，不该命中。"""
        for text in ('本轮 I2 文本模型调用累计输入＋输出 **1,000,000 原始 tokens**',
                     '用户另批 30,000、24,000 暂停，续测计量见本机账本',
                     '现有授权记录为累计 1,000,000、800,000 暂停，已记账量（见本机账本）',
                     '用户首轮授权 300,000 原始 tokens，200,000 暂停',
                     '总额 100 万／暂停线 80 万'):
            self.assertNotIn('实例账本金额', self.names(text), text)

    def test_call_counts_are_not_hits(self):
        self.assertNotIn('实例账本金额', self.names('独立 162＋13＋3＝178 项不同检查全过'))

    def test_ratios_are_not_hits(self):
        self.assertNotIn('实例账本金额', self.names('cache_read 占比 54.72%'))

    def test_url_port_pair_is_not_a_false_positive(self):
        """论文 URL 里的 2011/2011 不是本机端口。"""
        self.assertNotIn('本机端口（成对）', self.names(
            'https://example.org/downloads/2011/2011_paper.pdf'))

    def test_catches_the_actual_pre_rewrite_sentences(self):
        """用改写前真实存在的句子做回归：这几句曾经留在公开文档里。"""
        actual = [
            '| I6 终值 | 67 次调用／**217,743** tokens = 215,933 实报 ＋ 1,810 估算 ＋ 0 缺失 |',
            '日常仍为 Q3，账本 567,049、80 万暂停／100 万上限及原学习记录保留。',
            '原Q3新增9,095仍未归并，合并视角567,049；',
            '增强固定场景通过2/2、普通0/2，实报8,161；另保留发送前失败估算934，合计新增9,095。',
            '| 业务累计 | **262,517** tokens；总额 100 万／暂停线 80 万 |',
        ]
        for text in actual:
            self.assertIn('实例账本金额', self.names(text), text)

    def test_authorized_quota_in_real_sentences_is_not_a_hit(self):
        """同样是真实句子：授权额度不该被误报。"""
        actual = [
            '用户另批 30,000、24,000 暂停，续测计量见本机账本（实报＋估算分列）。',
            '用户首轮授权 300,000 原始 tokens，200,000 暂停，随后用户将累计总额提高到 1,000,000。',
            '现有授权记录为累计 1,000,000、800,000 暂停，已记账量（见本机账本）。',
        ]
        for text in actual:
            self.assertNotIn('实例账本金额', self.names(text), text)


if __name__ == '__main__':
    unittest.main()
