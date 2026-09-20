import unittest
from experiment import QUESTIONS, route, stats, validate

class ExperimentTests(unittest.TestCase):
    def answer(self):
        return {'answers':{
            'category':{'type':'choice','choice':'normal','confidence':1.0,'probabilities':{k:float(k=='normal') for k in QUESTIONS['category']['criteria']}},
            'severity':{'type':'score','score':0.0,'confidence':1.0,'probabilities':{'0':1.0,'1':0.0,'2':0.0,'3':0.0}},
            'needs_human_review':{'type':'noul','noul':0.0}}}
    def test_score_uncertainty_prevents_escalation(self):
        r=self.answer(); r['answers']['severity'].update(score=2.8,confidence=0.69)
        self.assertEqual(route(r),'human_review')
    def test_fractional_severity_can_trigger_candidate(self):
        r=self.answer(); r['answers']['severity'].update(score=2.8,confidence=0.9)
        self.assertEqual(route(r),'escalation_candidate')
    def test_noul_is_used_without_confidence(self):
        r=self.answer(); r['answers']['needs_human_review']['noul']=0.5
        self.assertEqual(route(r),'human_review')
    def test_invalid_choice_rejected(self):
        r=self.answer(); r['answers']['category']['choice']='invented'
        with self.assertRaises(ValueError): validate(r,QUESTIONS)
    def test_nan_probability_rejected(self):
        r=self.answer(); r['answers']['needs_human_review']['noul']=float('nan')
        with self.assertRaises(ValueError): validate(r,QUESTIONS)
    def test_p95_is_nearest_rank(self):
        s=stats(list(range(1,51))); self.assertEqual(s['p95_ms'],48); self.assertEqual(s['median_ms'],25.5)

if __name__=='__main__': unittest.main()
