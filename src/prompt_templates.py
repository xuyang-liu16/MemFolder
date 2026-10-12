"""Verbatim MemForest literals; rendered by prompt_protocol, never baseline-owned."""

MEMFOREST_MERGE_PROMPT = """
You are an intelligent memory summarization assistant. Please extract the core information from the following two memory entries and their timestamps, and generate a concise and coherent summary paragraph. If the memories contain relative time expressions (e.g., “last June,” “two months ago”), convert them into specific dates based on the corresponding timestamps (for example, if a memory mentions “last June” and the timestamp is February 2023, the actual time should be June 2022). The summary length should be kept within the combined length of the two original memories as much as possible. Output only the final summarized result, without any explanations, analysis, reasoning steps, or additional content.
Memory 1: {}, Timestamp 1: {}
Memory 2: {}, Timestamp 2: {}
"""

MEMFOREST_QA_PROMPT = """
    You are an intelligent memory assistant tasked with retrieving accurate information from conversation memories.

    # CONTEXT:
    You have access to memories from two speakers in a conversation. These memories contain\x20
    timestamped information that may be relevant to answering the question.

    # INSTRUCTIONS:
    1. Carefully analyze all provided memories from both speakers
    2. Pay special attention to the timestamps to determine the answer
    3. If the question asks about a specific event or fact, look for direct evidence in the memories
    4. If the memories contain contradictory information, prioritize the most recent memory
    5. If there is a question about time references (like "last year", "two months ago", etc.),\x20
       calculate the actual date based on the memory timestamp. For example, if a memory from\x20
       4 May 2022 mentions "went to India last year," then the trip occurred in 2021.
    6. Always convert relative time references to specific dates, months, or years. For example,\x20
       convert "last year" to "2022" or "two months ago" to "March 2023" based on the memory\x20
       timestamp. Ignore the reference while answering the question.
    7. Focus only on the content of the memories from both speakers. Do not confuse character\x20
       names mentioned in memories with the actual users who created those memories.
    8. The answer should be less than 5-6 words.

    # APPROACH (Think step by step):
    1. First, examine all memories that contain information related to the question
    2. Examine the timestamps and content of these memories carefully
    3. Look for explicit mentions of dates, times, locations, or events that answer the question
    4. If the answer requires calculation (e.g., converting relative time references), show your work
    5. Formulate a precise, concise answer based solely on the evidence in the memories
    6. Double-check that your answer directly addresses the question asked
    7. Ensure your final answer is specific and avoids vague time references

    Memories for user {{speaker_1_user_id}}:

    {{speaker_1_memories}}

    Memories for user {{speaker_2_user_id}}:

    {{speaker_2_memories}}

    Question: {{question}}

    Answer:
    """

MEMFOREST_JUDGE_PROMPT = """
Your task is to label an answer to a question as ’CORRECT’ or ’WRONG’. You will be given the following data:
    (1) a question (posed by one user to another user),\x20
    (2) a ’gold’ (ground truth) answer,\x20
    (3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic, for example:
Question: Do you remember what I got the last time I went to Hawaii?
Gold answer: A shell necklace
The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.\x20

For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

Now it's time for the real question:
Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}

First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.\x20
Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""

PROMPT_PROVENANCE = {'MEMFOREST_MERGE_PROMPT': {'symbol': 'PROMPT_TEMPLATE', 'source_sha256': '181b0d937a2371f196ebdd5da5924195fcb2ba12ca37398f59e05404123120f1', 'prompt_sha256': '9e24917dbd537d43afeeffa0e6a506199108bcdbbe0820bee51de6ddff109a4c'}, 'MEMFOREST_QA_PROMPT': {'symbol': 'ANSWER_PROMPT', 'source_sha256': '407bea1c1453dc6832c234bb1ed936d401d796fabcc0b28337a47ba63517d3ba', 'prompt_sha256': 'f3c786104816bba61d03b7f41c2be45009e6c8c296a04d9712ab1a59e4ae2399'}, 'MEMFOREST_JUDGE_PROMPT': {'symbol': 'ACCURACY_PROMPT', 'source_sha256': '5643455db1d7355b599a2225120c0209d0248550629ff31a71469276302c48f4', 'prompt_sha256': '62395dd312a631dfd9355026a0b69cc936018274c3198b6365b5c2a5c9bca9e0'}}
