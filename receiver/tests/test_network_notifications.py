import json
from unittest.mock import Mock
from network_notifications import deliver, public_status

def configure(root, enabled=True):
    (root/'notification-config.json').write_text(json.dumps({'enabled':enabled,'kind':'ntfy','url':'https://example.test/topic'}))

def incident(at=101, identity='new'):
    return {'id':identity,'detected_at':at,'name':'Test AP','trigger_speed_mbps':100,'expected_mbps':1000}

def test_new_incident_sends_once_across_restart(tmp_path):
    configure(tmp_path)
    sender=Mock()
    deliver(tmp_path,{'incidents':[incident(90,'old')]},100,sender)
    assert not sender.called
    report={'incidents':[incident(90,'old'),incident()]}
    deliver(tmp_path,report,102,sender)
    deliver(tmp_path,report,162,sender)
    assert sender.call_count==1
    assert public_status(tmp_path)['sent']==1

def test_failed_delivery_retries_without_losing_evidence(tmp_path):
    configure(tmp_path)
    sender=Mock(side_effect=[TimeoutError(),None])
    deliver(tmp_path,{'incidents':[]},100,sender)
    report={'incidents':[incident()]}
    deliver(tmp_path,report,102,sender)
    deliver(tmp_path,report,103,sender)
    assert sender.call_count==1
    deliver(tmp_path,report,162,sender)
    assert sender.call_count==2
    assert public_status(tmp_path)['sent']==1

def test_reenable_does_not_replay_disabled_period(tmp_path):
    configure(tmp_path,False)
    sender=Mock()
    deliver(tmp_path,{'incidents':[]},100,sender)
    configure(tmp_path)
    deliver(tmp_path,{'incidents':[incident(101)]},200,sender)
    assert not sender.called
    deliver(tmp_path,{'incidents':[incident(201,'second')]},202,sender)
    assert sender.call_count==1

def test_failure_is_bounded(tmp_path):
    configure(tmp_path)
    sender=Mock(side_effect=ConnectionError())
    deliver(tmp_path,{'incidents':[]},100,sender)
    for now in [102,1000,2000,4000,8000,16000]:
        deliver(tmp_path,{'incidents':[incident()]},now,sender)
    assert sender.call_count==5
    assert public_status(tmp_path)['failed']==1
