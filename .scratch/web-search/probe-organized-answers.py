# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Live diagnostic harness; run from the repository root with PYTHONPATH=. ."""
import asyncio,json,socket,time
from datetime import datetime,timezone
from pathlib import Path
from src.config.schema import Config
from src.llm.llamacpp import ensure_server,shutdown_llama_server
from src.server.voice_session import VoiceTurnSession
from tests.test_voice_session import FakeAvatar,FakeSegmenter

async def main():
 output={'at':datetime.now(timezone.utc).isoformat(),'engines':[],'searches':[],'turns':[]}
 c=Config();c.llm.provider='llamacpp';c.llm.model='gemma-4-E2B_q4_0-it';c.llm.max_tokens=788;c.llm.response_max_chars=200;c.reply_streaming.enabled=True
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 c.llm.llamacpp_port=port;c.llm.base_url=ensure_server(c.llm.model,port=port,ctx=8192)
 c.conversation_snapshot=True;c.profile_id='search_retest';c.profile_rag={'enabled':False,'dataset_ids':[]}
 c.profile_web_search={'enabled':True,'allowed_domains':[]}
 import yaml
 from src.config.schema import AssistantProfileConfig,ReplyRulesConfig
 lib=yaml.safe_load(Path('config/avatar_profiles.yaml').read_text())
 profile=next(p for p in lib['profiles'] if p['id']=='main')
 c.llm.assistant_profile=AssistantProfileConfig(**profile['assistant_profile'])
 c.llm.reply_rules=ReplyRulesConfig(**profile['reply_rules'])
 for i,question in enumerate(['周杰倫的生日是什麼時候？','周杰倫的生日','台積電哪一年成立？','請查台積電總部在哪裡','請查玉山的高度是多少？','Python最新的完整版本號','請上網簡短比較USB-C和USB-A的差別','請查國立臺灣歷史博物館在哪裡','周杰倫現在幾歲','你好','什麼是光合作用？']):
  avatar=FakeAvatar();avatar.config=c;avatar.sessionid=920000+i
  voice=VoiceTurnSession(avatar.sessionid,c,avatar);voice._segmenter=FakeSegmenter()
  events=[];voice.attach_event_sink(lambda raw:events.append(json.loads(raw)))
  selection=[]
  original_web_inputs=voice._web_inputs
  async def observed_inputs(*args, **kwargs):
   value=await original_web_inputs(*args, **kwargs)
   if value is not None: selection.append(value.web_selection)
   return value
  voice._web_inputs=observed_inputs
  try:
   start=time.monotonic();await voice.start_text_turn(question);await voice._turn_task
   record={'selection':selection,'question':question,'seconds':round(time.monotonic()-start,3),
    'sources':[e for e in events if e['type']=='web_search_result'],
    'responses':[e.get('text_delta') for e in events if e['type']=='assistant_response_delta'], 'queued_speech':[message[0] for message in avatar.messages],
    'board':[e for e in events if e['type'] in ('assistant_board','board_item')], 'errors':[e for e in events if e.get('state')=='error']}
   output['turns'].append(record);Path('.scratch/web-search/organized-matrix.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n');print('turn',json.dumps(record,ensure_ascii=False),flush=True)
  finally:await voice.close()
 Path('.scratch/web-search/organized-matrix.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
try:asyncio.run(main())
finally:shutdown_llama_server()
