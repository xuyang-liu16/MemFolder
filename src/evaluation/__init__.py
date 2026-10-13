from .qa_reader import RetrievalReader, ContextBuilder, ChatAnswerer, ReaderContext
from .retrieval import (
    LexicalRetriever,
    DenseRetriever,
    GraphExpansion,
    TimeDecayRetriever,
    visible,
    QdrantRetriever,
    M3NativeRetriever,
    SDKRetriever,
)
from .metrics import (
    ExactMatch,
    TokenF1,
    ChoiceAccuracy,
    EvidenceRecall,
    LoCoMoF1,
    ChatJudge,
    MetricEvaluator,
    ProtocolEvaluator,
    aggregate,
    PersonaMemAccuracy,
)
from .qa_reader import QAPrompt, ContextFolderPrompt
from . import metrics as _compat_metrics, qa_reader as _compat_qa_reader, retrieval as _compat_retrieval
from ..component_runtime import install_module_aliases as _install_aliases
import sys as _sys
_install_aliases(_sys.modules[__name__], {
    'native': _compat_retrieval,
    'reader': _compat_qa_reader,
    'prompts': _compat_qa_reader,
    'official': _compat_metrics,
    'evaluator': _compat_metrics,
})
