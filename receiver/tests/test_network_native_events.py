import json
from unittest.mock import Mock
import pytest
from network_native_events import normalize, capture, query

AP='00:11:22:33:44:55'
SW='00:11:22:33:44:66'


def event(at=1000, mac=AP, identity='native-1'):
    return {'id': identity, 'timestamp': at*1000, 'category': 'UNIFI_DEVICES',
            'event': 'LINK_CHANGED', 'message_raw': '{DEVICE} changed link',
            'parameters': {'DEVICE': {'id': mac, 'name': 'Test AP', 'password': 'secret'}},
            'secret': 'secret'}


def test_native_normalization_timestamp_message_and_allowlist():
    row=normalize(event(), 1100)
    assert row['at']==1000 and row['timestamp_ms']==1000000
    assert row['message']=='Test AP changed link'
    assert row['device_macs']==[AP]
    assert 'secret' not in json.dumps(row)
    assert normalize({**event(),'timestamp':float('nan')},1100) is None
    assert normalize({**event(),'category':'SECURITY'},1100) is None
    assert normalize(event(at=2000),1100) is None


def state():
    return {'incidents':[{'mac':AP,'detected_at':1000,'closed_at':1100,
                         'before':[{'parent':{'mac':SW}}],'samples':[]}]}


def test_native_events_correlate_to_ap_and_parent_but_not_outside_window():
    data=state()
    fetch=Mock(return_value=([event(950),event(1050,SW,'parent'),event(1500,AP,'late')],False))
    capture(None,data,1600,fetch)
    assert [r['id'] for r in data['incidents'][0]['native_events']]==['native-1','parent']
    capture(None,data,1660,Mock(side_effect=ConnectionError()))
    assert data['native']['status']=='unavailable'
    assert len(data['incidents'][0]['native_events'])==2


def test_overlap_deduplication_and_explicit_partial_coverage():
    data=state()
    fetch=Mock(return_value=([event()],True))
    capture(None,data,1100,fetch)
    assert data['native']['status']=='partial'
    capture(None,data,1160,fetch)
    assert fetch.call_args.args[1]==500
    assert len(data['native']['events'])==1


def test_query_has_bounded_pages_and_read_only_endpoint():
    response=Mock()
    response.iter_content.side_effect=lambda size:iter([json.dumps({'data':[event()],'total_page_count':3}).encode()])
    client=Mock(host='https://controller',site='default',_controller_type='unifi_os')
    client._get_session.return_value.post.return_value=response
    rows,truncated=query(client,100,200)
    assert truncated and len(rows)==2
    calls=client._get_session.return_value.post.call_args_list
    assert len(calls)==2
    assert calls[0].args[0].endswith('/system-log/all')
    assert calls[0].kwargs['json']['pageSize']==100
    assert calls[1].kwargs['json']['pageNumber']==1


def test_oversized_response_is_rejected_and_closed():
    response=Mock()
    response.iter_content.return_value=iter([b'x'*(1024*1024+1)])
    client=Mock(host='https://controller',site='default',_controller_type='unifi_os')
    client._get_session.return_value.post.return_value=response
    with pytest.raises(ValueError):query(client,100,200)
    response.close.assert_called_once()


def test_polling_native_failure_does_not_stop_link_capture(tmp_path,monkeypatch):
    import network_links
    client=Mock(enabled=True)
    client._get.return_value={'data':[{'type':'usw','mac':SW,'name':'Test switch','state':1,'last_seen':1000,'uplink':{}}]}
    monkeypatch.setattr('network_native_events.query',Mock(side_effect=ConnectionError()))
    # capture receives an explicit failing fetch to exercise independence.
    original=network_links.capture
    monkeypatch.setattr(network_links,'capture',lambda c,s,n:original(c,s,n,Mock(side_effect=ConnectionError())))
    result=network_links.poll(client,tmp_path,1000)
    assert result['generated']==1000 and result['native']['status']=='unavailable'
