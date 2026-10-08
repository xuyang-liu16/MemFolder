"""Instrument live service calls without exporting credentials or source payloads."""
from dataclasses import dataclass
from ..core import fingerprint
from ..planning.common import emit
import inspect


class MeteredServices:
    def __init__(self,services,context,*,capture_prompts=False):
        self.services=services;self.context=context;self.capture_prompts=capture_prompts;self.calls=0;self._proxies={}
    def require(self,name):
        provider=self.services.require(name)
        if not callable(getattr(provider,'complete',None)):return provider
        if name not in self._proxies:self._proxies[name]=_ChatProxy(provider,self)
        return self._proxies[name]


class _ChatProxy:
    def __init__(self,provider,meter):self._provider=provider;self._meter=meter
    def __getattr__(self,name):return getattr(self._provider,name)
    def complete(self,request):
        m=self._meter;m.calls+=1
        data={'role':request.role,'call_index':m.calls,'prompt_hash':fingerprint(request.prompt),
              'max_tokens':request.max_tokens,'temperature':request.temperature}
        if m.capture_prompts:data['prompt']=request.prompt
        try:
            response=self._provider.complete(request)
        except Exception:
            emit(m.context,'memfolder.services.chat','memfolder.service.chat_call',**data,status='failed')
            raise
        def finished(value):
            data['response_hash']=fingerprint(value)
            if m.capture_prompts:data['response']=value
            emit(m.context,'memfolder.services.chat','memfolder.service.chat_call',**data,status='completed')
            return value
        if inspect.isawaitable(response):
            async def finish_async():
                try:return finished(await response)
                except Exception:
                    emit(m.context,'memfolder.services.chat','memfolder.service.chat_call',**data,status='failed')
                    raise
            return finish_async()
        return finished(response)
