"""Composable planners and individual stages. NumPy is loaded on first vector operation."""
from .contracts import (
    Group,
    AnchorSelection,
    FeatureProvider,
    AnchorSelector,
    GroupAssigner,
    Partitioner,
    GroupRouter,
    BudgetAllocator,
    PairRouter,
    GraphClassifier,
    GraphCoverageSelector,
    GraphImportanceSelector,
)
from .plan_helpers import component_nodes, selection_required
from .recordfolder import (
    RecordFolderPlanner,
    ContextFolderPlanner,
    DensityPeakAnchors,
    NearestAnchorAssignment,
    TemporalCandidates,
    FusedAffinity,
    AnchorGate,
    ChainMatcher,
    ChainHosting,
)
from .record_selection import (
    PrunePlanner,
    PartitionPlanner,
    RandomSelector,
    RandomGroups,
    DartSelector,
    KmeansClusters,
    ClusterRepresentatives,
)
from .tome import TomeRoundPlanner, TomePooledGroups, TemporalTomePlanner
from .memforest import (
    AverageLinkageGroups,
    MemForestPlanner,
    JointClusters,
    CapacityAllocator,
    LegacyClusterCeil,
    MstPairRouter,
    resolve_memforest_budget,
)
from .streammeco import StreamMeCoPlanner, MediaConnectivity, SphericalCoverage, ImportanceDiversity
from .feature_extraction import (
    StoredEmbeddings,
    GroundingFeatures,
    EventTimeFeatures,
    SemanticEmbeddingFeatures,
    CurrentEmbeddings,
)

__all__=[name for name in globals() if not name.startswith('_') and name[0].isupper()]
__all__.extend(('resolve_memforest_budget','component_nodes','selection_required'))

from . import record_selection as _selection
_selection.TomePooledGroups = TomePooledGroups
_selection.TomeRoundPlanner = TomeRoundPlanner
_selection.AverageLinkageGroups = AverageLinkageGroups

from . import contracts as _compat_contracts
from . import feature_extraction as _compat_feature_extraction
from . import memforest as _compat_memforest
from . import plan_helpers as _compat_plan_helpers
from . import record_selection as _compat_record_selection
from . import recordfolder as _compat_recordfolder
from . import streammeco as _compat_streammeco
from . import tome as _compat_tome
from ..component_runtime import install_module_aliases as _install_aliases
import sys as _sys
_install_aliases(_sys.modules[__name__], {
    'common': _compat_plan_helpers,
    'baselines': _compat_record_selection,
    'features': _compat_feature_extraction,
    'grounding': _compat_feature_extraction,
    'protocols': _compat_contracts,
    'rewrite': _compat_record_selection,
    'temporal_tome': _compat_tome,
    '_density': _compat_recordfolder,
    '_memforest': _compat_memforest,
    '_streammeco': _compat_streammeco,
})
