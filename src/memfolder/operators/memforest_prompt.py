"""Original local MemForest pair summary prompt."""
PROMPT_TEMPLATE = """
You are an intelligent memory summarization assistant. Please extract the core information from the following two memory entries and their timestamps, and generate a concise and coherent summary paragraph. If the memories contain relative time expressions (e.g., “last June,” “two months ago”), convert them into specific dates based on the corresponding timestamps (for example, if a memory mentions “last June” and the timestamp is February 2023, the actual time should be June 2022). The summary length should be kept within the combined length of the two original memories as much as possible. Output only the final summarized result, without any explanations, analysis, reasoning steps, or additional content.
Memory 1: {}, Timestamp 1: {}
Memory 2: {}, Timestamp 2: {}
"""
