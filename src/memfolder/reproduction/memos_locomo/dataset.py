"""Official two-turn, per-speaker LoCoMo conversion; gold stays outside memory."""
from datetime import datetime,timezone
from .providers import digest

def batches(dataset):
    result=[]
    for conv_idx,sample in enumerate(dataset):
        conv=sample['conversation']
        for side in ['a','b']:
            uid=f'locomo_{conv_idx}_speaker_{side}'
            own=conv['speaker_'+side]
            for session_idx in range(35):
                session_key=f'session_{session_idx}'
                if session_key not in conv:continue
                # Preserve the exact ISO representation used by official ingestion.
                # Replacing +00:00 with Z changes both model inputs and embeddings.
                date=datetime.strptime(conv[session_key+'_date_time']+' UTC','%I:%M %p on %d %B, %Y %Z').replace(tzinfo=timezone.utc).isoformat()
                messages=[{'role':'user' if turn['speaker']==own else 'assistant','content':turn['speaker']+': '+turn['text'],'chat_time':date} for turn in conv[session_key]]
                for start in range(0,len(messages),2):
                    batch=messages[start:start+2]
                    identity=digest({'kind':'raw_two_turn_native_fast','user_name':uid,'session':session_key,'start':start,'messages':batch})
                    result.append({'conv_idx':conv_idx,'side':side,'uid':uid,'session':session_key,'start':start,'messages':batch,'identity':identity})
    return result

def questions(dataset):
    return [(c,i,q) for c,row in enumerate(dataset) for i,q in enumerate(row["qa"]) if q["category"]!=5]
