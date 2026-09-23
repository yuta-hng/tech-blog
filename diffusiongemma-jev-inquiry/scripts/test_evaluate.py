"""Offline checks for result parsing and label leakage, not model accuracy tests."""
import unittest
from evaluate import payload, decode, summarize


class EvaluationTests(unittest.TestCase):
    def example(self):
        return {'answers': {
            'department': {'choice': 'account', 'probabilities': {'account': .6, 'other': .4}},
            'severity': {'score': .93, 'probabilities': {'0': .45, '1': .17, '2': .38}},
            'needsHuman': {'noul': .4},
        }}

    def test_argmax_is_not_rounded_score(self):
        result = decode(self.example(), ['account', 'other'])
        self.assertEqual(result['prediction']['severity'], 0)
        self.assertEqual(round(result['severity_expected_score']), 1)
        self.assertFalse(result['prediction']['needsHuman'])

    def test_wire_request_excludes_answer_metadata(self):
        questions = {'needsHuman': {'type': 'boolean', 'instructions': 'Help needed?'}}
        body = payload(questions, 'sample text')
        self.assertEqual(body['state'], 'sample text')
        self.assertEqual(body['questions']['needsHuman']['type'], 'noul')
        self.assertEqual(questions['needsHuman']['type'], 'boolean')
        self.assertFalse({'id', 'labels', 'note', 'tricky'} & set(body))

    def test_invalid_probability_rejected(self):
        body = self.example()
        body['answers']['needsHuman']['noul'] = float('nan')
        with self.assertRaises(ValueError):
            decode(body, ['account', 'other'])

    def test_missing_class_rejected(self):
        body = self.example()
        del body['answers']['severity']['probabilities']['2']
        with self.assertRaises(ValueError):
            decode(body, ['account', 'other'])

    def test_failures_count_against_all_attempted(self):
        gold = {'department': 'account', 'severity': 2, 'needsHuman': True}
        ok = {'id': 'one', 'valid': True, 'gold': gold, 'prediction': gold,
              'tricky': False, 'severity_expected_score': 2, 'client_ms': 10}
        failed = {'id': 'two', 'valid': False, 'gold': gold, 'tricky': False}
        s = summarize([ok, failed], 2, 1, ['account', 'other'])
        self.assertEqual(s['accuracy']['department']['of_all_attempted'], .5)
        self.assertEqual(s['accuracy']['department']['of_valid_responses'], 1)
        self.assertEqual(s['urgent_recall_including_failed'], .5)


if __name__ == '__main__':
    unittest.main()
