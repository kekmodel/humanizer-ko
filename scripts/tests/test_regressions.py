"""Run: python3 -B -m unittest discover -s scripts/tests -v"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelity_check import check, render
from tell_scan import strip_frame

class RegressionTests(unittest.TestCase):
    def test_negation_change_needs_review(self):
        self.assertIn('부정', check('이 정책은 효과가 있다.', '이 정책은 효과가 없다.')['semantic_cue_changes'])

    def test_short_quotes_need_review(self):
        for left, right in [('"', '"'), ('“', '”'), ('‘', '’'), ("'", "'")]:
            with self.subTest(left=left):
                r = check(f'그는 {left}동의{right}라고 말했다.', f'그는 {left}반대{right}라고 말했다.')
                self.assertEqual(r['quotes_broken'], ['동의'])
                self.assertNotEqual(r['verdict'], 'PASS')

    def test_quote_multiplicity_and_unquoted_occurrence(self):
        r = check('그는 "동의"라고 말했다. 동의라는 말이다.', '그는 "반대"라고 말했다. 동의라는 말이다.')
        self.assertEqual(r['quotes_broken'], ['동의'])
        self.assertEqual(check('"동의"와 "동의"', '"동의"')['quotes_broken'], ['동의'])

    def test_korean_quantity_loss(self):
        for quantity in ['세 가지', '두 명', '절반', '세 가지가', '두 명은', '십 년간']:
            with self.subTest(quantity=quantity):
                r = check(f'대상은 {quantity} 정도다.', '대상은 정도다.')
                self.assertTrue(r['korean_quantities_missing'])

    def test_obligation_change(self):
        r = check('기업은 모델을 구축해야 한다.', '기업은 모델을 구축한다.')
        self.assertIn('당위', r['semantic_cue_changes'])

    def test_unchanged_text(self):
        text = '이 정책은 효과가 없다. 대상은 세 가지다. 그는 "동의"라고 말했다.'
        r = check(text, text)
        self.assertEqual(r['verdict'], 'PASS')
        self.assertIn('의미 보존은 별도 대조 필요', render(r))

    def test_high_edit_rate_alone_is_not_abort(self):
        r = check('봄에는 꽃이 핀다.', '꽃이 피는 계절은 봄이다.')
        self.assertGreaterEqual(r['change_rate_pct'], 30)
        self.assertEqual(r['verdict'], 'WARN')

    def test_number_loss_still_aborts(self):
        self.assertEqual(check('회원국의 67%가 참여했다.', '회원국이 참여했다.')['verdict'], 'ABORT')

    def test_preserve_ordinary_opening_and_closing(self):
        for text in ['이번 안내는 최종본입니다!\n\n신청은 금요일까지 받습니다.',
                     '신청 안내입니다.\n\n추가 질문은 월요일까지 제출해 주세요.',
                     '  본문입니다.\n\n  마지막 문단입니다.\n',
                     '물론입니다! 신청은 금요일까지입니다.\n\n자세한 안내입니다.']:
            self.assertEqual(strip_frame(text), text)

    def test_remove_only_standalone_greetings(self):
        self.assertEqual(strip_frame('물론입니다!\n\n본문입니다.\n\n도움이 되셨길 바랍니다!'), '본문입니다.')
        self.assertEqual(strip_frame('물론입니다!'), '물론입니다!')

if __name__ == '__main__':
    unittest.main()
