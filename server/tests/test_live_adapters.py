import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from radar_server.analysis_models import AnalysisInput, CapturedMessage, InterestProfile, validate_output
from radar_server.delivery_channels import DigestLinks
from radar_server.openai_provider import OpenAIProvider, strict_schema
from radar_server.providers import ExtractiveProvider, ProviderFailure
from radar_server.telegram_channel import TelegramChannel, format_message, utf16_length
from radar_server.topics import prepare_topics


def batch():
    message = CapturedMessage(str(uuid4()), 'Synthetic semiconductor release information.', 1000, 1000, (), 'structured')
    return AnalysisInput(prepare_topics([message]), InterestProfile(interests=['semiconductor']), 1)


def provider_response(value, **changes):
    return {'status': 'completed', 'model': 'gpt-4.1-mini-2025-04-14',
            'usage': {'input_tokens': 100, 'output_tokens': 200},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}], **changes}


def test_openai_citation_validation_and_actual_charge():
    value = batch()
    def respond(request):
        body = json.loads(request.content)
        assert request.url == 'https://api.openai.com/v1/responses'
        assert body['store'] is False and 'tools' not in body
        assert body['text']['format']['strict'] is True
        return httpx.Response(200, json=provider_response(ExtractiveProvider.render(value)))
    provider = OpenAIProvider('sk-synthetic-only', httpx.MockTransport(respond))
    limit, result = provider.maximum_charge(value), provider.generate(value)
    assert len(validate_output(result.output, value).topics) == 1
    assert result.usage.measured and result.usage.cost_microusd == 360
    assert result.usage.tokens <= limit.tokens and result.usage.cost_microusd <= limit.cost_microusd


def test_schema_requires_defaulted_fields_and_no_extra_fields():
    schema = strict_schema()
    topic = schema['$defs']['SummaryTopic']
    assert 'source_urls' in topic['required']
    assert topic['additionalProperties'] is False


def test_uncertain_input_cannot_request_uncaveated_output():
    message = CapturedMessage(str(uuid4()),'Synthetic information',None,1000,(),'fallback_no_message_time')
    value = AnalysisInput(prepare_topics([message]),InterestProfile(interests=['information']),1)
    schema = OpenAIProvider.request(value)['text']['format']['schema']
    properties = schema['$defs']['SummaryTopic']['properties']
    assert 'none' not in properties['uncertainty']['enum']
    assert 'topic_id' not in properties
    assert schema['properties']['topics']['required'] == [value.topics[0].topic_id]


def test_keyed_provider_output_preserves_every_topic():
    value=batch()
    item=ExtractiveProvider.render(value)['topics'][0]
    identifier=item.pop('topic_id')
    provider=OpenAIProvider('sk-synthetic-only',httpx.MockTransport(lambda _:httpx.Response(200,json=provider_response({'topics':{identifier:item}}))))
    result=provider.generate(value)
    assert validate_output(result.output,value).topics[0].topic_id==identifier


def test_provider_schema_scopes_evidence_to_each_topic():
    first=CapturedMessage(str(uuid4()),'Synthetic semiconductor release',1000,1000,(),'structured')
    second=CapturedMessage(str(uuid4()),'A different housing event',1000000,1000000,(),'structured')
    value=AnalysisInput(prepare_topics([first,second]),InterestProfile(interests=['semiconductor']),1)
    schema=OpenAIProvider.request(value)['text']['format']['schema']
    for topic in value.topics:
        shape=schema['properties']['topics']['properties'][topic.topic_id]
        assert shape['properties']['points']['items']['properties']['evidence_ids']['items']['enum']==[topic.messages[0].event_id]
        assert shape['properties']['source_urls']['maxItems']==0


def test_visible_laughter_is_context_only_when_requested():
    first = CapturedMessage(str(uuid4()),'합성 재미있는 회사 행사 정보',1000,1000,(),'structured')
    laughter = CapturedMessage(str(uuid4()),'ㅋㅋㅋㅋ',1001,1001,(),'structured')
    assert len(prepare_topics([first,laughter])[0].messages)==1
    assert len(prepare_topics([first,laughter],preserve_reactions=True)[0].messages)==2


def test_telegram_can_run_without_public_digest_url(monkeypatch):
    monkeypatch.setenv('RADAR_TELEGRAM_BOT_TOKEN',TOKEN)
    monkeypatch.setenv('RADAR_TELEGRAM_CHAT_ID',CHAT)
    monkeypatch.setenv('RADAR_DIGEST_LINK_SECRET','synthetic-'+'s'*40)
    monkeypatch.delenv('RADAR_PUBLIC_URL',raising=False)
    assert not TelegramChannel.from_env().links.enabled


@pytest.mark.parametrize('status,code,permanent', [(401,'provider_auth',True), (403,'provider_auth',True),
    (429,'provider_rate_limited',False), (503,'provider_unavailable',False), (400,'provider_request_rejected',True)])
def test_openai_errors_are_sanitized(status, code, permanent):
    provider = OpenAIProvider('sk-synthetic-only', httpx.MockTransport(lambda _: httpx.Response(status, text='private response')))
    with pytest.raises(ProviderFailure) as error:
        provider.generate(batch())
    assert error.value.code == code and error.value.permanent == permanent
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('changes', [{'status':'incomplete'}, {'output':[]},
    {'usage':{'input_tokens':True,'output_tokens':1}}, {'model':'unexpected-model'}])
def test_openai_invalid_or_incomplete_results_rejected(changes):
    response = provider_response({'topics':[]}, **changes)
    provider = OpenAIProvider('sk-synthetic-only', httpx.MockTransport(lambda _: httpx.Response(200,json=response)))
    with pytest.raises(ProviderFailure):
        provider.generate(batch())


def claim():
    return SimpleNamespace(delivery_id=uuid4(), payload={'title':'Synthetic digest', 'message':'Plain <text> & no markup'})


TOKEN = '123456:synthetic-' + 'x' * 30
CHAT = '123456789'


def test_telegram_plain_text_and_scoped_link():
    def respond(request):
        data = json.loads(request.content)
        assert data['chat_id'] == CHAT and 'parse_mode' not in data
        assert data['entities'][0]['type']=='bold'
        assert data['link_preview_options']['is_disabled'] is True
        assert '#key=' in data['reply_markup']['inline_keyboard'][0][0]['url']
        return httpx.Response(200,json={'ok':True,'result':{'message_id':42,'chat':{'id':int(CHAT)}}})
    channel = TelegramChannel(TOKEN, CHAT, DigestLinks('https://example.com', 'synthetic-' + 's'*32), httpx.MockTransport(respond))
    result = channel.publish(claim())
    assert result.outcome == 'accepted' and result.message_id == '42'


def test_telegram_includes_corrections_beyond_first_point():
    item=claim()
    item.payload['topics']=[{'payload':{'title':'합성 일정 변경','points':[{'text':'처음 월요일이라고 공유됨'},{'text':'이후 화요일로 정정됨'}],'uncertainty':'conflicting_messages'}}]
    def respond(request):
        data=json.loads(request.content)
        assert '이후 화요일로 정정됨' in data['text']
        assert '미확인' in data['text']
        return httpx.Response(200,json={'ok':True,'result':{'message_id':42,'chat':{'id':int(CHAT)}}})
    assert TelegramChannel(TOKEN,CHAT,transport=httpx.MockTransport(respond)).publish(item).outcome=='accepted'


def test_telegram_bold_entities_use_utf16_offsets_and_never_parse_source_markup():
    literal='<b>원문</b> & **대사** 😀'
    payload={'title':'합성 😀 제목','topics':[{'payload':{'title':'중요한 😀 소식','importance':95,
        'points':[{'text':'핵심 공지 😀 변경'}],'uncertainty':'none','quotes':[{'text':literal,'truncated':False}]}}]}
    text,entities=format_message(payload)
    assert literal in text and '🔥' in text and '💬' in text
    encoded=text.encode('utf-16-le')
    bold=[encoded[e['offset']*2:(e['offset']+e['length'])*2].decode('utf-16-le') for e in entities]
    assert any('중요한 😀 소식' in part for part in bold)
    assert any('핵심 공지 😀 변경' in part for part in bold)
    assert all(e['type']=='bold' for e in entities)


@pytest.mark.parametrize('count',[3,5,10])
def test_all_topics_fit_with_quotes_and_long_non_bmp_text(count):
    payload={'title':'합성 테스트','topics':[{'source_from':1789734600000,'source_through':1789734660000,
        'payload':{'title':'😀'*90,'importance':95,'points':[{'text':'😀'*300}]*3,
                   'uncertainty':'limited_context','quotes':[{'text':'😀'*80,'truncated':True,'observed_at':1789734600000}]*2}} for _ in range(count)]}
    text,entities=format_message(payload)
    assert utf16_length(text)<=4000
    assert text.count('📌')+text.count('🔥')==count
    assert all(e['offset']+e['length']<=utf16_length(text) for e in entities)


def test_telegram_preserves_exact_quote_text():
    item=claim()
    quote='합성 원문: 화요일로 바뀌었어요!'
    item.payload['topics']=[{'payload':{'title':'합성 일정','points':[{'text':'일정이 변경됨'}],
        'uncertainty':'limited_context','quotes':[{'text':quote,'truncated':False}]}}]
    def respond(request):
        text=json.loads(request.content)['text']
        assert '원문 인용: “'+quote+'”' in text
        return httpx.Response(200,json={'ok':True,'result':{'message_id':42,'chat':{'id':int(CHAT)}}})
    assert TelegramChannel(TOKEN,CHAT,transport=httpx.MockTransport(respond)).publish(item).outcome=='accepted'


def test_quote_collection_time_is_shown_in_korean_time():
    from datetime import datetime,timezone
    item=claim()
    stamp=int(datetime(2026,9,17,13,38,tzinfo=timezone.utc).timestamp()*1000)
    item.payload['topics']=[{'payload':{'title':'합성 이전 대화','points':[{'text':'합성 요약'}],
        'uncertainty':'limited_context','quotes':[{'text':'합성 실제 대사','truncated':False,'observed_at':stamp}]}}]
    def respond(request):
        assert '09/17 22:38 수집' in json.loads(request.content)['text']
        return httpx.Response(200,json={'ok':True,'result':{'message_id':42,'chat':{'id':int(CHAT)}}})
    assert TelegramChannel(TOKEN,CHAT,transport=httpx.MockTransport(respond)).publish(item).outcome=='accepted'


@pytest.mark.parametrize('status,data,outcome,code', [
    (403,{},'failed','channel_auth'), (400,{},'failed','channel_rejected'),
    (503,{},'uncertain','channel_unavailable'),
    (429,{'parameters':{'retry_after':900000}},'retry','rate_limited'),
    (200,{'ok':True,'result':{'message_id':1,'chat':{'id':999}}},'uncertain','invalid_response'),
    (200,{'ok':True,'result':{'message_id':True,'chat':{'id':int(CHAT)}}},'uncertain','invalid_response')])
def test_telegram_failure_and_wrong_destination(status, data, outcome, code):
    channel = TelegramChannel(TOKEN, CHAT, transport=httpx.MockTransport(lambda _:httpx.Response(status,json=data)))
    result = channel.publish(claim())
    assert (result.outcome,result.code) == (outcome,code)
    if status == 429:
        assert result.retry_after == 86400


def test_telegram_unknown_outcome_never_automatically_retries():
    def respond(request):
        raise httpx.ReadTimeout('response could contain private data',request=request)
    result = TelegramChannel(TOKEN,CHAT,transport=httpx.MockTransport(respond)).publish(claim())
    assert (result.outcome,result.code) == ('uncertain','response_lost')
