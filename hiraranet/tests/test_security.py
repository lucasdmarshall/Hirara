import pytest
from hiraranet.scan import scan_ports
from hiraranet.enum_svc import enum_services
from hiraranet.lookup import lookup_dns


@pytest.mark.asyncio
async def test_private_scan_is_blocked_before_connect():
    async def connect(*args): pytest.fail('private target reached connector')
    result = await scan_ports('127.0.0.1', ports=[80], connector=connect)
    assert result.error and 'blocked' in result.error


def test_private_nameserver_requires_operator_permission():
    result = lookup_dns('example.com', nameserver='127.0.0.1')
    assert result.error and 'blocked' in result.error
