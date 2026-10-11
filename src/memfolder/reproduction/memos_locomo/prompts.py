"""Literal prompts from the pinned Apache-2.0 MemOS evaluator."""
import json
from .runtime import PACKAGE

def prompts():return json.loads((PACKAGE/'prompts.json').read_text(encoding='utf-8'))

def judge_messages(question,gold,answer):
    values=prompts()
    fields={'question':question,'gold_answer':gold,'response':answer}
    parts=json.loads((PACKAGE/'judge_parts.json').read_text(encoding='utf-8'))
    user=''.join(str(fields[part['field']]) if 'field' in part else part['literal'] for part in parts)
    return [{'role':'system','content':values['JUDGE_SYSTEM']},{'role':'user','content':user}]
