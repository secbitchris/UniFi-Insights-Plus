import json
from unittest.mock import Mock
import pytest
from network_evidence import annotate, device_records, port_errors
from network_inventory import assess


def switch(errors, uptime=1000):
    return {'type':'usw','name':'Switch','mac':'aa:bb:cc:dd:ee:ff','state':1,'uptime':uptime,
            'port_table':[{'port_idx':7,'up':True,'rx_errors':errors,'tx_errors':0}]}


def test_lifetime_totals_are_not_new_faults_and_growth_is_detected():
    first, state = port_errors([switch(100000)], {}, 100)
    assert first['severity'] == 'unknown'
    stable, _ = port_errors([switch(100000, 1300)], state, 400)
    assert stable['severity'] == 'info'
    assert stable['ports'][0]['new_errors'] == 0
    rising, _ = port_errors([switch(100010, 1300)], state, 400)
    assert rising['severity'] == 'warning'
    assert rising['ports'][0]['new_errors'] == 10
    assert rising['ports'][0]['errors_per_minute'] == 2


@pytest.mark.parametrize('device,now',[ (switch(2,10),400), (switch(100010,10),400), (switch(100010,1300),1101)])
def test_reset_or_long_gap_cannot_produce_rate(device,now):
    _, state = port_errors([switch(100000)], {}, 100)
    result,_ = port_errors([device],state,now)
    assert result['severity'] == 'unknown'
    assert result['ports'][0]['new_errors'] is None


def test_retired_inventory_remains_visible_and_defaults_to_expected():
    devices=[switch(0),{'type':'uap','name':'AP','mac':'11:22:33:44:55:66','state':0,'last_seen':50}]
    rows=device_records(devices,{'aa:bb:cc:dd:ee:ff':{'status':'retired'}},'https://controller','default',100)
    assert rows[0]['policy']=='retired'
    assert rows[1]['policy']=='expected' and rows[1]['last_seen_age_seconds']==50
    assert rows[1]['unifi_url']=='https://controller/network/default/devices'


def test_warning_since_and_clear_transitions():
    check=[{'title':'Channel plan','severity':'warning','detail':'AP drift'}]
    state,events=annotate(check,[],{},100)
    assert events==[] and check[0]['status_since']==100
    state,events=annotate(check,[],state,400)
    assert events==[] and check[0]['status_since']==100
    check[0]['severity']='ok'
    state,events=annotate(check,[],state,700)
    assert events==[{'at':700,'title':'Channel plan','from':'warning','to':'ok'}]
    assert check[0]['last_clear']==700


@pytest.mark.parametrize('mode,channel,severity',[('disabled',None,'info'),('auto',None,'unknown'),('auto',36,'warning')])
def test_disabled_and_unreported_channels_are_not_drift(tmp_path, mode, channel, severity):
    ap={'type':'uap','name':'AP','mac':'11:22:33:44:55:66','state':1,
        'radio_table':[{'radio':'na','tx_power_mode':mode}],
        'radio_table_stats':[{'radio':'na','channel':channel}]}
    checks=assess([ap],[],[],{'AP':{'na':132}},str(tmp_path))
    check=next(c for c in checks if c['title']=='Channel plan')
    assert check['severity']==severity
    if mode=='disabled': assert 'disabled in UniFi' in check['items'][0]


def test_retired_device_excluded_only_from_offline_alert(tmp_path):
    device=switch(0);device['state']=0
    checks=assess([device],[],[],{},str(tmp_path),{device['mac']:{'status':'retired'}})
    assert next(c for c in checks if c['title']=='Devices online')['severity']=='ok'


def test_policy_endpoint_only_changes_local_monitor_file(tmp_path,monkeypatch):
    import routes.network_health as route
    monkeypatch.setattr(route,'ROOT',tmp_path)
    monkeypatch.setattr(route,'read_snapshot',lambda:{'devices':[{'mac':'aa:bb:cc:dd:ee:ff'}]})
    result=route.set_device_policy('AA:BB:CC:DD:EE:FF',route.DevicePolicy(status='retired',reason='removed'))
    assert result['saved']['status']=='retired'
    assert json.loads((tmp_path/'device-policy.json').read_text())['aa:bb:cc:dd:ee:ff']['reason']=='removed'
    with pytest.raises(Exception): route.set_device_policy('../bad',route.DevicePolicy(status='retired'))


def test_intentionally_offline_excluded_without_retirement(tmp_path):
    device=switch(0); device['state']=0
    policies={device['mac']:{'status':'intentionally_offline','reason':'Off by design'}}
    rows=device_records([device],policies,'https://controller','default',100)
    assert rows[0]['policy']=='intentionally_offline'
    checks=assess([device],[],[],{},str(tmp_path),policies)
    online=next(c for c in checks if c['title']=='Devices online')
    assert online['severity']=='ok'
    assert '1 intentionally offline' in online['detail']
    assert '0 retired' in online['detail']


def test_status_only_update_preserves_expected_speed(tmp_path,monkeypatch):
    import routes.network_health as route
    monkeypatch.setattr(route,'ROOT',tmp_path)
    monkeypatch.setattr(route,'read_snapshot',lambda:{'devices':[{'mac':'aa:bb:cc:dd:ee:ff'}]})
    route.set_device_policy('aa:bb:cc:dd:ee:ff',route.DevicePolicy(status='expected',expected_speed_mbps=100))
    route.set_device_policy('aa:bb:cc:dd:ee:ff',route.DevicePolicy(status='intentionally_offline'))
    entry=json.loads((tmp_path/'device-policy.json').read_text())['aa:bb:cc:dd:ee:ff']
    assert entry['status']=='intentionally_offline' and entry['expected_speed_mbps']==100
    device={'type':'usw','name':'Flex','mac':'aa:bb:cc:dd:ee:ff','state':1,'uplink':{'uplink_mac':'parent','uplink_remote_port':3}}
    parent={'mac':'parent','port_table':[{'port_idx':3,'up':True,'speed':100}]}
    row=device_records([device,parent],{device['mac']:entry},'https://controller','default',100)[0]
    assert row['expected_speed_mbps']==100 and row['uplink_speed_mbps']==100


def test_fresher_device_uplink_wins_over_stale_parent():
    device={'type':'usw','name':'Flex','mac':'aa','state':1,'last_seen':200,
            'uplink':{'uplink_mac':'parent','uplink_remote_port':3,'up':True,'speed':100}}
    parent={'mac':'parent','last_seen':100,'port_table':[{'port_idx':3,'up':False,'speed':0}]}
    row=device_records([device,parent],{'aa':{'status':'expected','expected_speed_mbps':100}},'https://controller','default',210)[0]
    assert row['uplink_up'] is True and row['uplink_speed_mbps']==100
    assert row['uplink_observation_source']=='device' and row['uplink_observed_at']==200
