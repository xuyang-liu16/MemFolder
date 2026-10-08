"""Ported from the user-designated standard release; see docs/METHOD_PROVENANCE.json."""
MERGE_PROMPT = """
You are an intelligent memory summarization assistant. Please extract the core information from the following {n} memory entries and their timestamps, and generate a concise and coherent summary paragraph. If the memories contain relative time expressions (e.g., “last June,” “two months ago”), convert them into specific dates based on the corresponding timestamps (for example, if a memory mentions “last June” and the timestamp is February 2023, the actual time should be June 2022). The summary length should be kept within the combined length of the original memories as much as possible. Output only the final summarized result, without any explanations, analysis, reasoning steps, or additional content.
{lines}
"""
