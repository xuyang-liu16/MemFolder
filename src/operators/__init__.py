"""Interchangeable text writers and contract-checked action execution."""
from .contracts import (
    Chat,
    ChatRequest,
    Tokenizer,
    Cl100kTokenizer,
    Member,
    Fact,
    EncodingRound,
    TextWriteResult,
    MemberResolver,
    TextWriter,
    RecordBuilder,
    FactExtractor,
    TriagePolicy,
    Compiler,
    Verifier,
    FeedbackBuilder,
    RoundSelector,
)
from .record_operations import (
    TextOperator,
    RuleOperator,
    NativeSummaryWriter,
    ConcatWriter,
    ConservativeRecordBuilder,
    ChronologicalMembers,
    MemForestPairWriter,
    TomePairWriter,
    TomeEmbeddingBuilder,
)
from .action_dispatch import DispatchOperator
from .contextfolder import (
    ContextFolderWriter,
    FactPlanner,
    FactTriage,
    ContextCompiler,
    BlindFactVerifier,
    RepairFeedback,
    ShortestCleanRound,
)
__all__=[name for name in globals() if not name.startswith('_') and name[0].isupper()]

from .. import services as _compat_services
from . import action_dispatch as _compat_action_dispatch
from . import contextfolder as _compat_contextfolder
from . import contracts as _compat_contracts
from . import record_operations as _compat_record_operations
from ..component_runtime import install_module_aliases as _install_aliases
import sys as _sys
_install_aliases(_sys.modules[__name__], {
    'types': _compat_contracts,
    'protocols': _compat_contracts,
    'text': _compat_record_operations,
    'memforest': _compat_record_operations,
    'tome': _compat_record_operations,
    'dispatch': _compat_action_dispatch,
    'contextfolder_prompts': _compat_contextfolder,
    'metering': _compat_services,
})
