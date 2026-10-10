"""Composable planners and individual stages. NumPy is loaded on first vector operation."""
from .common import Group,AnchorSelection,component_nodes,selection_required
from .recordfolder import (RecordFolderPlanner,ContextFolderPlanner,DensityPeakAnchors,NearestAnchorAssignment,
    TemporalCandidates,FusedAffinity,AnchorGate,ChainMatcher,ChainHosting)
from .baselines import (PrunePlanner,PartitionPlanner,RandomSelector,RandomGroups,DartSelector,
    KmeansClusters,ClusterRepresentatives,TomeRoundPlanner,TomePooledGroups,AverageLinkageGroups)
from .memforest import MemForestPlanner,JointClusters,CapacityAllocator,LegacyClusterCeil,MstPairRouter,resolve_memforest_budget
from .streammeco import StreamMeCoPlanner,MediaConnectivity,SphericalCoverage,ImportanceDiversity
from .features import StoredEmbeddings,GroundingFeatures,EventTimeFeatures,SemanticEmbeddingFeatures
from .features import CurrentEmbeddings
from .temporal_tome import TemporalTomePlanner
from .protocols import (FeatureProvider,AnchorSelector,GroupAssigner,Partitioner,GroupRouter,
    BudgetAllocator,PairRouter,GraphClassifier,GraphCoverageSelector,GraphImportanceSelector)

__all__=[name for name in globals() if not name.startswith('_') and name[0].isupper()]
__all__.extend(('resolve_memforest_budget','component_nodes','selection_required'))
