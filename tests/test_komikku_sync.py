# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from unittest.mock import Mock

import pytest

from komikku.models import KomikkuSyncDAO
from komikku.models import KomikkuSyncError
from komikku.models import SyncedState


def test_login_persists_and_loads_credentials(tmp_path, monkeypatch):
    response = Mock(status_code=200, text='token-value')
    post = Mock(return_value=response)
    monkeypatch.setattr('komikku.models.komikku_sync.requests.post', post)
    path = tmp_path / 'cloud-sync.json'

    dao = KomikkuSyncDAO(path)
    dao.login('localhost:8010/', 'alice', 'Password1!')

    assert dao.configured
    assert dao.server == 'http://localhost:8010'
    assert dao.username == 'alice'
    assert dao.api_token == 'token-value'
    assert path.stat().st_mode & 0o777 == 0o600
    assert KomikkuSyncDAO(path).api_token == 'token-value'
    post.assert_called_once_with(
        'http://localhost:8010/api/login',
        data={'username': 'alice', 'password': 'Password1!'},
        timeout=15,
    )


def test_logout_removes_credentials(tmp_path):
    path = tmp_path / 'cloud-sync.json'
    path.write_text(json.dumps({'server': 'http://localhost:8010', 'username': 'alice', 'api_token': 'token'}))
    dao = KomikkuSyncDAO(path)

    dao.logout()

    assert not dao.configured
    assert not path.exists()


def test_validate_and_binary_state_requests(tmp_path, monkeypatch):
    path = tmp_path / 'cloud-sync.json'
    path.write_text(json.dumps({'server': 'http://localhost:8010', 'username': 'alice', 'api_token': 'token'}))
    dao = KomikkuSyncDAO(path)
    state = SyncedState(())
    get = Mock(side_effect=[Mock(status_code=200), Mock(status_code=200, content=state.encode())])
    post = Mock(return_value=Mock(status_code=200, content=state.encode()))
    monkeypatch.setattr('komikku.models.komikku_sync.requests.get', get)
    monkeypatch.setattr('komikku.models.komikku_sync.requests.post', post)

    assert dao.validate()
    assert dao.pull() == state
    assert dao.push(state) == state
    assert post.call_args.kwargs['headers']['Content-Type'] == SyncedState.CONTENT_TYPE
    assert post.call_args.kwargs['data'] == state.encode()


def test_failed_login_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr('komikku.models.komikku_sync.requests.post', Mock(return_value=Mock(status_code=400, text='invalid')))
    path = tmp_path / 'cloud-sync.json'
    dao = KomikkuSyncDAO(path)

    with pytest.raises(KomikkuSyncError):
        dao.login('localhost:8010', 'alice', 'wrong')

    assert not dao.configured
    assert not path.exists()
