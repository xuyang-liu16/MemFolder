"""Generate documented configurations; no provider calls or original data copies."""
from copy import deepcopy
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
directory=ROOT/'examples/experiments'
base=json.loads((directory/'offline-demo.json').read_text(encoding='utf-8'))
def save(name,config):
    (directory/name).write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

space={'provider':'caller-declared','model':'REPLACE_EMBEDDING_MODEL','revision':'REPLACE_MODEL_REVISION','dimension':1536}
def http(model):return {'plugin':'compatible-http','parameters':{'base_url':'https://api.example.invalid/v1','model':model,'api_key_env':'MEMFOLDER_PROVIDER_KEY','revision':'REPLACE_MODEL_REVISION'}}
for method in ('recordfolder','contextfolder'):
    cfg=deepcopy(base)
    cfg['compression']['planner']={'plugin':method,'parameters':{'candidates':{'plugin':'temporal-candidates','parameters':{'temporal_feature':'temporal'}}}}
    cfg['compression']['operator']={'plugin':method+'-operator'}
    cfg['compression']['features']=[{'plugin':'semantic-encoder','parameters':{'space':space}},{'plugin':'chat-grounding'},{'plugin':'event-time-features'}]
    cfg['reader']['parameters']['answerer']={'plugin':'chat-answerer','parameters':{'prompt_builder':{'plugin':'contextfolder-qa-prompt' if method=='contextfolder' else 'qa-prompt'}}}
    cfg['services']={'chat':http('REPLACE_CHAT_MODEL'),'grounding':http('REPLACE_GROUNDING_MODEL'),'embeddings':{'plugin':'cached-service','parameters':{'path':'../../build/caches/embeddings.sqlite','namespace':'example.embedding.v1','provider':http('REPLACE_EMBEDDING_MODEL')}},'tokenizer':{'plugin':'tiktoken-counter'}}
    cfg['evaluator']={'plugin':'metric-evaluator','parameters':{'metrics':[{'plugin':'locomo-f1'},{'plugin':'evidence-recall'}]}}
    cfg['output_dir']='../../build/experiments/'+method+'-001'
    save(method+'-template.json',cfg)
prune=deepcopy(base['compression']);prune.update(planner={'plugin':'random-prune'},operator={'plugin':'rule-operator'})
save('offline-matrix.json',{'experiment':base,'output_dir':'../../build/experiments/offline-matrix',
    'axes':[{'path':'compression','values':[base['compression'],prune]}],'seeds':[7,11],'max_runs':4})
save('dataset-components.json',{
    'locomo':{'plugin':'locomo-dataset','parameters':{'path':'data/locomo.json','utc_offset_minutes':0}},
    'longmemeval':{'plugin':'longmemeval-dataset','parameters':{'path':'data/longmemeval.json','utc_offset_minutes':0}},
    'personamem-v1':{'plugin':'personamem-dataset','parameters':{'path':'data/questions.csv','contexts_path':'data/contexts.jsonl'}},
    'm3-robot':{'plugin':'m3-dataset','parameters':{'path':'data/robot.json','variant':'robot','sample_ids':['video-id'],'memory_loaders':{'video-id':{'plugin':'m3','parameters':{'path':'data/video-id.pkl'}}}}},
    'm3-web':{'plugin':'m3-dataset','parameters':{'path':'data/web.json','variant':'web','sample_ids':['video-id'],'memory_loaders':{'video-id':{'plugin':'m3','parameters':{'path':'data/video-id.pkl'}}}}}})
print(json.dumps({'status':'written','configs':6,'model_calls':0}))
