"""One MemForest protocol for record merge, benchmark QA and benchmark judge.

Compression algorithms own their planning/encoding logic. Shared experimental
instructions live here, independent of planner, operator and memory backend.
"""
from hashlib import sha256
import json
import re
from .core import to_data
from .core.values import require
from .prompt_templates import (MEMFOREST_MERGE_PROMPT, MEMFOREST_QA_PROMPT,
                               MEMFOREST_JUDGE_PROMPT, PROMPT_PROVENANCE)

PROTOCOL_ID = 'memforest.shared.v1'


def prompt_hash(text):
    return sha256(text.encode('utf-8')).hexdigest()


def protocol_manifest():
    return {'protocol_id': PROTOCOL_ID,
            'templates': {name:dict(source) for name,source in PROMPT_PROVENANCE.items()},
            'scope': 'builtin record writers and benchmark QA/judge; explicit external plugins have separate bindings',
            'merge': {'message_role': 'user', 'temperature': 0.0},
            'qa': {'message_role': 'system', 'temperature': 0.0, 'decoder_legend': False},
            'judge': {'message_role': 'user', 'temperature': 0.0,
                      'response_format': 'json_object', 'labels': ['CORRECT', 'WRONG']},
            'group_merge_adapter': 'count-and-memory-slots-only.v1'}


def render_merge(members):
    require(bool(members), 'Merge needs at least one memory')
    if len(members) == 2:
        older, newer = members
        return MEMFOREST_MERGE_PROMPT.format(older.text, older.time, newer.text, newer.time)
    # RecordFolder/KMeans can select groups. Preserve that algorithm and perform
    # one group call, changing only cardinality and input slots in MemForest.
    header = MEMFOREST_MERGE_PROMPT.split('Memory 1: {}', 1)[0]
    header = header.replace('following two memory entries', f'following {len(members)} memory entries')
    header = header.replace('two original memories', f'{len(members)} original memories')
    rows = '\n'.join(f'Memory {i}: {member.text}, Timestamp {i}: {member.time}'
                     for i, member in enumerate(members, 1))
    return header + rows + '\n'


def render_qa(question, speaker_memories):
    """Render MemForest's two slots; >2 owners remain attributed in slot two."""
    groups = tuple((str(owner), tuple(memories)) for owner, memories in speaker_memories)
    if not groups:
        groups = (('user', ()), ('assistant', ()))
    if len(groups) == 1:
        groups += (('assistant' if groups[0][0] != 'assistant' else 'user', ()),)
    if len(groups) > 2:
        groups = (groups[0], ('other speakers', tuple(f'[{owner}] {memory}'
                  for owner, memories in groups[1:] for memory in memories)))
    values = {'speaker_1_user_id': groups[0][0].split('_')[0],
              'speaker_2_user_id': groups[1][0].split('_')[0],
              'speaker_1_memories': json.dumps(groups[0][1], indent=4),
              'speaker_2_memories': json.dumps(groups[1][1], indent=4), 'question': question}
    # Substitute the template once; braces inside memory content are data.
    def substitute(match):
        key = match.group(1)
        require(key in values, 'Unknown MemForest QA template variable')
        return values[key]
    return re.sub(r'\{\{\s*(\w+)\s*\}\}', substitute, MEMFOREST_QA_PROMPT)


def public_question_text(question):
    return question_text(question.parts,question.options,question.as_of)


def question_text(parts,options,as_of):
    text = ' '.join(part.text or '' for part in parts)
    if as_of is not None:
        text += '\nQUERY TIME\n' + json.dumps(to_data(as_of), ensure_ascii=False)
    if options:
        text += '\nOPTIONS\n' + json.dumps(to_data(options), ensure_ascii=False)
    return text


def render_judge(question, gold_answer, generated_answer):
    return MEMFOREST_JUDGE_PROMPT.format(question=question, gold_answer=gold_answer,
                                        generated_answer=generated_answer)
